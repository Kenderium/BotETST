
import asyncio
import json
import os
import random
import sys
import time
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Optional
from urllib.parse import quote

import discord
from discord.ext import commands


def _load_dotenv_if_present() -> None:
	"""Loads a local .env file if python-dotenv is installed."""
	try:
		from dotenv import load_dotenv  # type: ignore

		load_dotenv()
	except Exception:
		# Keep env-only configuration working even without python-dotenv.
		return


@dataclass(frozen=True)
class Settings:
	token: str
	prefix: str = "!"


def load_settings() -> Settings:
	token = os.getenv("DISCORD_TOKEN", "").strip()
	prefix = os.getenv("COMMAND_PREFIX", "!").strip() or "!"

	if not token:
		raise RuntimeError(
			"DISCORD_TOKEN is missing. Put it in your environment or in a .env file."
		)

	return Settings(token=token, prefix=prefix)


def _split_host_port(raw: str, default_port: int) -> tuple[str, int]:
	raw = raw.strip()
	if not raw:
		raise ValueError("Empty host.")
	if ":" in raw:
		host, port_s = raw.rsplit(":", 1)
		return host.strip(), int(port_s.strip())
	return raw, default_port


def _split_platform_identifier(raw: str, default_platform: str) -> tuple[str, str]:
	raw = raw.strip()
	if not raw:
		raise ValueError("Empty identifier.")
	if ":" in raw:
		platform, identifier = raw.split(":", 1)
		platform = platform.strip().lower()
		identifier = identifier.strip()
		if platform and identifier:
			return platform, identifier
	return default_platform.strip().lower() or "steam", raw


def _looks_like_trn_app_id(value: str) -> bool:
	# TRN docs show an app id formatted as a UUID.
	v = value.strip()
	if len(v) != 36:
		return False
	parts = v.split("-")
	return [len(p) for p in parts] == [8, 4, 4, 4, 12]


class TrnHttpError(RuntimeError):
	def __init__(self, status: int, payload: object):
		super().__init__(f"TRN HTTP {status}")
		self.status = status
		self.payload = payload


class RapidApiHttpError(RuntimeError):
	def __init__(self, status: int, url: str, payload: object):
		super().__init__(f"RapidAPI HTTP {status}")
		self.status = status
		self.url = url
		self.payload = payload


async def _trn_get_profile(
	*,
	api_key: str,
	game_slug: str,
	platform: str,
	identifier: str,
) -> dict:
	import aiohttp

	url = (
		f"https://public-api.tracker.gg/v2/{game_slug}/standard/profile/"
		f"{platform}/{quote(identifier, safe='')}"
	)
	headers = {"TRN-Api-Key": api_key}

	async with aiohttp.ClientSession() as session:
		async with session.get(url, headers=headers, timeout=aiohttp.ClientTimeout(total=10)) as resp:
			data = await resp.json(content_type=None)
			if resp.status >= 400:
				raise TrnHttpError(resp.status, data)
			return data


def _trn_build_embed(*, title: str, payload: dict, profile_url: str) -> discord.Embed:
	data = payload.get("data") or {}
	platform_info = data.get("platformInfo") or {}
	segments = data.get("segments") or []

	player_name = platform_info.get("platformUserHandle") or platform_info.get("platformUserIdentifier") or "Unknown"
	platform_name = platform_info.get("platformSlug") or platform_info.get("platformName") or ""

	embed = discord.Embed(
		title=title,
		description=f"Profil: **{player_name}** {f'({platform_name})' if platform_name else ''}\n{profile_url}",
		color=discord.Color.blurple(),
	)

	chosen = None
	for seg in segments:
		seg_type = (seg.get("type") or "").lower()
		if seg_type in {"overview", "lifetime"}:
			chosen = seg
			break
	if chosen is None and segments:
		chosen = segments[0]

	stats = (chosen or {}).get("stats") or {}
	preferred = [
		"rank",
		"rating",
		"mmr",
		"tier",
		"wins",
		"losses",
		"matchesPlayed",
		"winPercentage",
		"kd",
		"kda",
	]

	added = 0
	for key in preferred:
		v = stats.get(key)
		if not isinstance(v, dict):
			continue
		name = v.get("displayName") or key
		value = v.get("displayValue") or v.get("value")
		if value is None:
			continue
		embed.add_field(name=str(name), value=str(value), inline=True)
		added += 1
		if added >= 6:
			break

	if added == 0 and isinstance(stats, dict):
		for k in list(stats.keys())[:6]:
			v = stats.get(k)
			if isinstance(v, dict):
				name = v.get("displayName") or k
				value = v.get("displayValue") or v.get("value")
				if value is not None:
					embed.add_field(name=str(name), value=str(value), inline=True)

	return embed


class _TtlCache:
	def __init__(self) -> None:
		self._store: dict[str, tuple[float, object]] = {}
		self._locks: dict[str, "asyncio.Lock"] = {}

	def get(self, key: str) -> object | None:
		now = time.monotonic()
		item = self._store.get(key)
		if item is None:
			return None
		expires_at, value = item
		if expires_at <= now:
			self._store.pop(key, None)
			return None
		return value

	def set(self, key: str, value: object, ttl_seconds: float) -> None:
		self._store[key] = (time.monotonic() + ttl_seconds, value)

	async def get_or_set(self, *, key: str, ttl_seconds: float, factory):
		import asyncio

		cached = self.get(key)
		if cached is not None:
			print(f"[Cache HIT] {key}", flush=True)
			return cached

		lock = self._locks.get(key)
		if lock is None:
			lock = asyncio.Lock()
			self._locks[key] = lock

		async with lock:
			cached2 = self.get(key)
			if cached2 is not None:
				print(f"[Cache HIT] {key}", flush=True)
				return cached2
			print(f"[Cache MISS] {key} - calling API", flush=True)
			value = await factory()
			self.set(key, value, ttl_seconds)
			return value


class _PersistentTtlCache:
	"""A TTL cache persisted to a JSON file so values survive restarts.

	Stores expiration using wall-clock seconds (`time.time()`), not monotonic,
	to be compatible across process lifetimes.
	"""
	def __init__(self, file_path: str) -> None:
		self._file_path = file_path
		self._lock = None
		# In-memory store: key -> (expires_at_epoch_seconds, value)
		self._store: dict[str, tuple[float, object]] | None = None
		self._locks: dict[str, "asyncio.Lock"] = {}

	async def _get_lock(self):
		import asyncio

		if self._lock is None:
			self._lock = asyncio.Lock()
		return self._lock

	def _ensure_loaded(self) -> dict[str, tuple[float, object]]:
		if self._store is not None:
			return self._store
		try:
			with open(self._file_path, "r", encoding="utf-8") as f:
				obj = json.load(f)
			if isinstance(obj, dict):
				store: dict[str, tuple[float, object]] = {}
				now = time.time()
				for k, v in obj.items():
					if not isinstance(k, str) or not isinstance(v, dict):
						continue
					exp = v.get("expires_at")
					val = v.get("value")
					if isinstance(exp, (int, float)):
						if exp > now:
							store[k] = (float(exp), val)
				self._store = store
			else:
				self._store = {}
		except FileNotFoundError:
			self._store = {}
		except Exception:
			# Corrupt file: start fresh (and keep the old file as-is).
			self._store = {}
		return self._store

	def _atomic_save(self, data: dict[str, tuple[float, object]]) -> None:
		os.makedirs(os.path.dirname(self._file_path), exist_ok=True)
		tmp = f"{self._file_path}.tmp"
		serializable: dict[str, dict[str, object]] = {
			k: {"expires_at": exp, "value": val} for k, (exp, val) in data.items()
		}
		with open(tmp, "w", encoding="utf-8") as f:
			json.dump(serializable, f, ensure_ascii=False, indent=2)
		os.replace(tmp, self._file_path)

	def get(self, key: str) -> object | None:
		now = time.time()
		data = self._ensure_loaded()
		item = data.get(key)
		if item is None:
			return None
		expires_at, value = item
		if expires_at <= now:
			# Expired: drop and persist
			data.pop(key, None)
			try:
				self._atomic_save(data)
			except Exception:
				pass
			return None
		return value

	def set(self, key: str, value: object, ttl_seconds: float) -> None:
		data = self._ensure_loaded()
		data[key] = (time.time() + float(ttl_seconds), value)
		try:
			self._atomic_save(data)
		except Exception:
			pass

	async def get_or_set(self, *, key: str, ttl_seconds: float, factory):
		import asyncio

		cached = self.get(key)
		if cached is not None:
			print(f"[Cache HIT] {key}", flush=True)
			return cached

		lock = self._locks.get(key)
		if lock is None:
			lock = asyncio.Lock()
			self._locks[key] = lock

		async with lock:
			cached2 = self.get(key)
			if cached2 is not None:
				print(f"[Cache HIT] {key}", flush=True)
				return cached2
			print(f"[Cache MISS] {key} - calling API", flush=True)
			value = await factory()
			self.set(key, value, ttl_seconds)
			return value


class _UserIdStore:
	def __init__(self, file_path: str) -> None:
		self._file_path = file_path
		self._lock = None
		self._data: dict[str, dict[str, str]] | None = None

	async def _get_lock(self):
		import asyncio

		if self._lock is None:
			self._lock = asyncio.Lock()
		return self._lock

	def _ensure_loaded(self) -> dict[str, dict[str, str]]:
		if self._data is not None:
			return self._data
		try:
			with open(self._file_path, "r", encoding="utf-8") as f:
				obj = json.load(f)
			if isinstance(obj, dict):
				# expected: {"<discord_user_id>": {"steam": "...", "epic": "..."}}
				self._data = {
					str(k): (v if isinstance(v, dict) else {})  # type: ignore[dict-item]
					for k, v in obj.items()
				}
			else:
				self._data = {}
		except FileNotFoundError:
			self._data = {}
		except Exception:
			# Corrupt file: start fresh (and keep the old file as-is).
			self._data = {}
		return self._data

	def _atomic_save(self, data: dict[str, dict[str, str]]) -> None:
		os.makedirs(os.path.dirname(self._file_path), exist_ok=True)
		tmp = f"{self._file_path}.tmp"
		with open(tmp, "w", encoding="utf-8") as f:
			json.dump(data, f, ensure_ascii=False, indent=2)
		os.replace(tmp, self._file_path)

	async def get(self, user_id: int) -> dict[str, str]:
		lock = await self._get_lock()
		async with lock:
			data = self._ensure_loaded()
			return dict(data.get(str(user_id), {}))

	async def set_value(self, user_id: int, key: str, value: str) -> None:
		key = key.strip().lower()
		if key not in {"steam", "epic"}:
			raise ValueError("Invalid key")
		value = value.strip()
		lock = await self._get_lock()
		async with lock:
			data = self._ensure_loaded()
			entry = data.get(str(user_id))
			if not isinstance(entry, dict):
				entry = {}
			data[str(user_id)] = entry
			entry[key] = value
			self._atomic_save(data)

	async def clear(self, user_id: int, which: str) -> None:
		which = which.strip().lower() or "all"
		if which not in {"steam", "epic", "all"}:
			raise ValueError("Invalid clear option")
		lock = await self._get_lock()
		async with lock:
			data = self._ensure_loaded()
			uid = str(user_id)
			if uid not in data:
				return
			if which == "all":
				data.pop(uid, None)
			else:
				entry = data.get(uid, {})
				if isinstance(entry, dict):
					entry.pop(which, None)
					if not entry:
						data.pop(uid, None)
			self._atomic_save(data)


async def _rapidapi_get_json(*, url: str, api_key: str, api_host: str) -> dict:
	import json

	import aiohttp

	headers = {
		"X-RapidAPI-Key": api_key,
		"X-RapidAPI-Host": api_host,
		"User-Agent": "RapidAPI Playground",
		"Accept-Encoding": "identity",
	}
	async with aiohttp.ClientSession() as session:
		async with session.get(url, headers=headers, timeout=aiohttp.ClientTimeout(total=15)) as resp:
			# RapidAPI providers are not always consistent with content-types.
			try:
				data: object = await resp.json(content_type=None)
			except Exception:
				text = await resp.text()
				try:
					data = json.loads(text)
				except Exception:
					data = {"raw": text}

			if resp.status >= 400:
				raise RapidApiHttpError(resp.status, url, data)
		# Check if payload contains error structure even with 200 status
		if isinstance(data, dict):
			if "error" in data and "statusCode" in data:
				# RapidAPI error in payload
				status_code = data.get("statusCode", 500)
				raise RapidApiHttpError(status_code if isinstance(status_code, int) else 500, url, data)
			# Avoid returning and caching empty objects
			if not data:
				raise RapidApiHttpError(502, url, {"message": "Empty JSON object"})
			return data
		raise RuntimeError(f"RapidAPI returned non-object JSON for {url}: {type(data).__name__}")


def _pick_scalar_stats(payload: object, limit: int = 6) -> list[tuple[str, str]]:
	# Very generic extractor for unknown API shapes.
	interesting = {
		"rank",
		"mmr",
		"rating",
		"wins",
		"losses",
		"matches",
		"match",
		"win",
		"loss",
		"goal",
		"goals",
		"assist",
		"assists",
		"save",
		"saves",
		"shot",
		"shots",
		"mvps",
		"mvp",
		# Extra tokens commonly found in Rocket League APIs
		"tier",
		"division",
		"playlist",
		"league",
		"season",
		"rankpoints",
		"rank_points",
	}

	items: list[tuple[str, str]] = []

	def walk(obj: object, prefix: str = "", depth: int = 0, only_interesting: bool = True) -> None:
		nonlocal items
		if len(items) >= limit or depth > 4:
			return
		if isinstance(obj, dict):
			for k, v in obj.items():
				key = str(k)
				path = f"{prefix}.{key}" if prefix else key
				walk(v, path, depth + 1, only_interesting)
				if len(items) >= limit:
					return
			return
		if isinstance(obj, list):
			for i, v in enumerate(obj[:10]):
				walk(v, f"{prefix}[{i}]" if prefix else f"[{i}]", depth + 1, only_interesting)
				if len(items) >= limit:
					return
			return

		# Scalars
		if isinstance(obj, (str, int, float, bool)) and prefix:
			leaf = prefix.rsplit(".", 1)[-1].lower()
			if (not only_interesting) or any(token in leaf for token in interesting):
				val = str(obj)
				if isinstance(obj, str) and len(val) > 120:
					return
				items.append((prefix, val))

	# First pass: collect only interesting tokens
	walk(payload, "", 0, True)
	# Fallback: if nothing matched, collect any scalar leaves
	if len(items) == 0:
		walk(payload, "", 0, False)
	return items


def format_dt(dt: Optional[datetime]) -> str:
	if not dt:
		return "N/A"
	if dt.tzinfo is None:
		dt = dt.replace(tzinfo=timezone.utc)
	return dt.astimezone(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")


async def build_bot(settings: Settings) -> commands.Bot:
	intents = discord.Intents.default()
	# Required for prefix commands in discord.py v2+.
	intents.message_content = True
	intents.members = True

	bot = commands.Bot(
		command_prefix=settings.prefix,
		intents=intents,
		help_command=None,
	)

	# Persist API cache to disk so it survives restarts
	api_cache_path = os.path.join(os.getcwd(), "data", "api_cache.json")
	os.makedirs(os.path.dirname(api_cache_path), exist_ok=True)
	api_cache = _PersistentTtlCache(api_cache_path)
	TTL_MINECRAFT_SECONDS = 30.0
	TTL_ARK_SECONDS = 30.0
	TTL_TRN_SECONDS = 120.0
	TTL_RL_SECONDS = 86400.0  # 24 hours for RapidAPI caching

	user_ids_path = os.path.join(os.getcwd(), "data", "user_ids.json")
	user_ids = _UserIdStore(user_ids_path)

	@bot.event
	async def on_ready() -> None:
		if bot.user is None:
			return
		print(f"ETST connected as {bot.user} (id={bot.user.id})", flush=True)

	@bot.event
	async def on_command_error(ctx: commands.Context, error: Exception) -> None:
		if isinstance(error, commands.CommandNotFound):
			return
		if isinstance(error, commands.MissingRequiredArgument):
			await ctx.send(f"Argument manquant. Essaye: `{settings.prefix}help {ctx.command}`")
			return
		if isinstance(error, commands.BadArgument):
			await ctx.send("Argument invalide.")
			return

		# Log unexpected errors server-side.
		print(f"Command error: {type(error).__name__}: {error}", flush=True)
		await ctx.send("Oups, une erreur est survenue côté bot.")

	@bot.command(name="help")
	async def help_cmd(ctx: commands.Context) -> None:
		embed = discord.Embed(
			title="Aide — Bot Eternal Storm",
			description=(
				"Commandes disponibles (préfixe: "
				f"`{settings.prefix}`)"
			),
			color=discord.Color.blurple(),
		)
		p = settings.prefix
		embed.add_field(name=f"{p}hello", value="Dit bonjour.", inline=True)
		embed.add_field(name=f"{p}users", value="Nombre de membres sur le serveur.", inline=True)
		embed.add_field(name=f"{p}damn [@membre]", value="Damn quelqu'un (ou juste 'Damn.').", inline=True)
		embed.add_field(name=f"{p}hi [XXX]", value="Invoque quelqu'un (DJ, Nicoow, Lucas, Grimdal, Kenderium, etc.) ou toi si rien n'est spécifié.", inline=True)
		embed.add_field(
			name=f"{p}id",
			value=(
				"Enregistre/affiche tes IDs Steam/Epic. "
				"Ex: `!id steam MonSteam` • `!id epic MonEpic` • `!id clear all`"
			),
			inline=False,
		)
		embed.add_field(
			name=f"{p}stats minecraft",
			value="Status du serveur Minecraft (joueurs en ligne).",
			inline=False,
		)
		embed.add_field(
			name=f"{p}stats ark",
			value="Joueurs en ligne sur le serveur ARK ETST1 (Fjordur / VAC).",
			inline=False,
		)
		embed.add_field(
			name=f"{p}stats smite2 <pseudo>",
			value="Stats profil Smite 2 (via TRN). Ex: `!stats smite2 steam:Pseudo`",
			inline=False,
		)
		embed.add_field(
			name=f"{p}stats rocketleague <pseudo>",
			value=(
				"Stats Rocket League (RapidAPI). Exemples:\n"
				f"• `{settings.prefix}stats rocketleague epic:TonPseudo`\n"
				f"• `{settings.prefix}stats rocketleague TonDisplayNameEpic`"
			),
			inline=False,
		)
		embed.add_field(
			name=f"{p}stats rl tournaments",
			value="Tournois Rocket League en Europe",
			inline=False,
		)
		embed.add_field(
			name=f"{p}stats rl shop",
			value="Shop Rocket League (featured items)",
			inline=False,
		)
		embed.add_field(
			name=f"{p}stats smite1 <pseudo>",
			value="Stats profil Smite 1 (via TRN). Ex: `!stats smite1 steam:Pseudo`",
			inline=False,
		)
		embed.add_field(
			name="Astuce",
			value=(
				"Tu peux enregistrer tes pseudos une fois pour toutes :\n"
				"• `!id steam <ton_steam>`\n"
				"• `!id epic <ton_epic>`\n"
				"Puis utiliser `!stats smite1` / `!stats smite2` / `!stats rocketleague` sans préciser le pseudo.\n"
				"Pour Rocket League (rocket-league1), préfère `epic:<ton_pseudo>` (la plateforme `steam:` est ignorée)."
			),
			inline=False,
		)
		embed.set_footer(text="Eternal Storm — Smite, Overwatch 2, Rocket League, Ark, Minecraft, Fortnite, etc.")
		await ctx.send(embed=embed)

	@bot.command(name="id")
	async def id_cmd(ctx: commands.Context, action: str = "show", kind: str = "", *, value: str = "") -> None:
		"""Gère les identifiants enregistrés par utilisateur.

		Usages:
		- !id                      -> show
		- !id show                 -> show
		- !id steam <value>        -> set steam
		- !id epic <value>         -> set epic
		- !id set steam <value>    -> set steam
		- !id clear [steam|epic|all]
		"""
		try:
			action_l = (action or "").strip().lower()
			kind_l = (kind or "").strip().lower()

			# Shorthand: !id steam <value> / !id epic <value>
			if action_l in {"steam", "epic"}:
				kind_l = action_l
				action_l = "set"
				# value is already in `kind`+`value`? In this shorthand form, `kind` is the first word after action.
				# With signature (action, kind, *, value), shorthand gives action=steam, kind=<first token of value>.
				if kind and value:
					value = f"{kind} {value}".strip()
				else:
					value = kind
				kind_l = kind_l
				kind = ""

			if action_l in {"", "show", "get"}:
				entry = await user_ids.get(ctx.author.id)
				steam = entry.get("steam")
				epic = entry.get("epic")
				lines = []
				lines.append(f"Steam: {steam if steam else '(non défini)'}")
				lines.append(f"Epic: {epic if epic else '(non défini)'}")
				lines.append("\nPour définir : `!id steam <valeur>` ou `!id epic <valeur>`")
				lines.append("Pour effacer : `!id clear steam|epic|all`")
				await ctx.send("\n".join(lines))
				return

			if action_l == "set":
				if kind_l not in {"steam", "epic"}:
					await ctx.send("Usage: `!id steam <valeur>` ou `!id epic <valeur>`")
					return
				if not value.strip():
					await ctx.send(f"Usage: `!id {kind_l} <valeur>`")
					return
				await user_ids.set_value(ctx.author.id, kind_l, value)
				await ctx.send(f"OK, {kind_l} enregistré.")
				return

			if action_l == "clear":
				which = kind_l or "all"
				if which not in {"steam", "epic", "all"}:
					await ctx.send("Usage: `!id clear steam|epic|all`")
					return
				await user_ids.clear(ctx.author.id, which)
				await ctx.send("OK, identifiant(s) effacé(s).")
				return

			await ctx.send("Usage: `!id` (voir), `!id steam <valeur>`, `!id epic <valeur>`, `!id clear steam|epic|all`")
		except Exception as e:
			print(f"[id_cmd] error: {e}", flush=True)
			await ctx.send("Erreur interne lors de la gestion des IDs.")

	@bot.command(name="hello")
	async def hello(ctx: commands.Context) -> None:
		await ctx.send(f"Hello {ctx.author.mention}!")

	@bot.command(name="users")
	async def users(ctx: commands.Context) -> None:
		if ctx.guild is None:
			await ctx.send("No guild context.")
			return
		await ctx.send(str(ctx.guild.member_count or 0))

	@bot.command(name="damn")
	async def damn(ctx: commands.Context, member: Optional[discord.Member] = None) -> None:
		if member is None:
			await ctx.send("Damn.")
			return
		await ctx.send(f"Damn {member.mention}.")

	_callouts = {
		"DJ": "My vengance is going to be huge",
		"Nicoow": "My vengance is going to hurt you ☠",
		"Lucas": "Lucas.",
		"Grimdal": "Grimdal a été invoqué.",
		"Kenderium": "Kenderium a été invoqué.",
	}

	@bot.command(name="hi")
	async def hi(ctx: commands.Context, *, target: str = "") -> None:
		target = target.strip() if target else ""
		if not target:
			target = ctx.author.name
		if target in _callouts:
			await ctx.send(_callouts[target])
		else:
			await ctx.send(f"Invoque {target}.")

	def _get_mc_target() -> tuple[str, int]:
		raw = os.getenv("MINECRAFT_SERVER", "").strip()
		if not raw:
			raise RuntimeError("MINECRAFT_SERVER is missing (example: play.example.com:25565)")
		return _split_host_port(raw, 25565)

	def _get_ark_target_etst1() -> tuple[str, int]:
		raw = os.getenv("ARK_ETST1_SERVER", "").strip()
		if not raw:
			raise RuntimeError(
				"ARK_ETST1_SERVER is missing (example: etst.duckdns.org:27015). "
				"Note: this should be the Steam query port (A2S)."
			)
		return _split_host_port(raw, 27015)

	async def _ark_status_text_etst1() -> str:
		import asyncio

		import a2s  # type: ignore

		host, port = _get_ark_target_etst1()

		def _probe() -> str:
			info_fn = getattr(a2s, "info", None)
			if info_fn is None:
				raise RuntimeError(
					"A2S library mismatch: expected `a2s.info()` but it is missing. "
					"Fix: `pip uninstall a2s` then `pip install -r requirements.txt` (installs `python-a2s`)."
				)
			info = info_fn((host, port), timeout=5.0)
			online = getattr(info, "player_count", None)
			max_p = getattr(info, "max_players", None)
			map_name = getattr(info, "map_name", None)
			vac = getattr(info, "vac", False)
			name = getattr(info, "server_name", None) or "ETST1"

			online_s = str(online) if online is not None else "?"
			max_s = str(max_p) if max_p is not None else "?"
			map_s = f" — map `{map_name}`" if map_name else ""
			vac_s = "VAC ON" if vac else "VAC OFF"
			return f"ARK `{name}`: {online_s}/{max_s} joueurs{map_s} — {vac_s}"

		return await asyncio.to_thread(_probe)

	async def _mc_status_text() -> str:
		import asyncio

		from mcstatus import JavaServer  # type: ignore

		host, port = _get_mc_target()

		def _probe() -> str:
			server = JavaServer(host, port)
			status = server.status()
			online = getattr(status.players, "online", 0)
			max_p = getattr(status.players, "max", 0)
			latency = getattr(status, "latency", None)
			ms = f"{int(latency)}ms" if latency is not None else "N/A"
			return f"Minecraft server `{host}:{port}`: {online}/{max_p} players (ping {ms})"

		return await asyncio.to_thread(_probe)

	@bot.command(name="stats")
	async def stats(ctx: commands.Context, game: Optional[str] = None, *, pseudo: str = "") -> None:
		if not game:
			await ctx.send(
				f"Usage: `{settings.prefix}stats <jeu> [pseudo]`\n"
				f"Exemples: `{settings.prefix}stats minecraft`, `{settings.prefix}stats ark`, "
				f"`{settings.prefix}stats smite2 MonPseudo`, `{settings.prefix}stats rocketleague MonPseudo`"
			)
			return

		game_key = game.strip().lower()

		if game_key in {"minecraft", "mc"}:
			try:
				text = await api_cache.get_or_set(
					key="minecraft_status",
					ttl_seconds=TTL_MINECRAFT_SECONDS,
					factory=_mc_status_text,
				)
				await ctx.send(text)
			except Exception as e:
				await ctx.send(
					"Impossible de récupérer le status Minecraft. "
					"Vérifie `MINECRAFT_SERVER` (souvent `:25565`). "
					"Attention: `8123` est fréquemment le port Dynmap (web), pas le port Minecraft."
				)
				print(f"Minecraft status error: {type(e).__name__}: {e}", flush=True)
			return

		if game_key in {"ark"}:
			try:
				text = await api_cache.get_or_set(
					key="ark_etst1_status",
					ttl_seconds=TTL_ARK_SECONDS,
					factory=_ark_status_text_etst1,
				)
				await ctx.send(text)
			except Exception as e:
				await ctx.send(
					"Impossible de récupérer le status ARK. "
					"Vérifie `ARK_ETST1_SERVER` (IP:port du port *query* Steam/A2S)."
				)
				print(f"ARK status error: {type(e).__name__}: {e}", flush=True)
			return

		if game_key in {"smite2", "smite 2", "smite_2"}:
			api_key = os.getenv("TRN_API_KEY", "").strip()
			if not api_key:
				await ctx.send("TRN_API_KEY manquant: ajoute-le dans ton `.env` pour activer `!stats smite2`.")
				return
			if not _looks_like_trn_app_id(api_key):
				await ctx.send(
					"TRN_API_KEY ne ressemble pas à un App ID TRN (UUID). "
					"Dans la doc TRN, la valeur attendue est l’App ID (format `xxxxxxxx-xxxx-xxxx-xxxx-xxxxxxxxxxxx`)."
				)
			platform_default = os.getenv("TRN_SMITE2_PLATFORM", "steam").strip() or "steam"
			pseudo_effective = pseudo.strip()
			if not pseudo_effective:
				entry = await user_ids.get(ctx.author.id)
				pseudo_effective = (entry.get("steam") or "").strip()
				if not pseudo_effective:
					await ctx.send(
						"Pseudo Steam manquant. Enregistre-le avec `!id steam <ton_steam>` "
						"ou passe-le en argument : `!stats smite2 <steam>`."
					)
					return
			platform, identifier = _split_platform_identifier(pseudo_effective, platform_default)
			try:
				cache_key = f"trn:smite2:{platform}:{identifier}".lower()
				payload = await api_cache.get_or_set(
					key=cache_key,
					ttl_seconds=TTL_TRN_SECONDS,
					factory=lambda: _trn_get_profile(
						api_key=api_key,
						game_slug="smite2",
						platform=platform,
						identifier=identifier,
					),
				)
				embed = _trn_build_embed(
					title="TRN — Smite 2",
					payload=payload,  # type: ignore[arg-type]
					profile_url=f"https://tracker.gg/smite2/profile/{platform}/{quote(identifier, safe='')}"
				)
				await ctx.send(embed=embed)
			except TrnHttpError as e:
				print(f"TRN Smite2 HTTP {e.status}: {e.payload}", flush=True)
				if e.status in {401, 403}:
					await ctx.send("TRN refuse l’accès (401/403). Vérifie `TRN_API_KEY` (App ID TRN) et les permissions/quota.")
				elif e.status == 404:
					await ctx.send("Profil introuvable sur TRN. Essaie `steam:Pseudo` ou une autre plateforme.")
				elif e.status == 429:
					await ctx.send("Rate limit TRN (429). Réessaye dans quelques secondes.")
				else:
					await ctx.send("Erreur TRN inattendue. Check les logs du bot.")
			except Exception as e:
				print(f"TRN Smite2 error: {type(e).__name__}: {e}", flush=True)
				await ctx.send("Impossible de récupérer les stats Smite 2 (TRN). Check les logs du bot.")
			return

		if game_key in {"smite1", "smite 1", "smite_1", "smite"}:
			api_key = os.getenv("TRN_API_KEY", "").strip()
			if not api_key:
				await ctx.send("TRN_API_KEY manquant: ajoute-le dans ton `.env` pour activer `!stats smite1`.")
				return
			if not _looks_like_trn_app_id(api_key):
				await ctx.send(
					"TRN_API_KEY ne ressemble pas à un App ID TRN (UUID). "
					"Dans la doc TRN, la valeur attendue est l’App ID."
				)
			platform_default = os.getenv("TRN_SMITE1_PLATFORM", "steam").strip() or "steam"
			pseudo_effective = pseudo.strip()
			if not pseudo_effective:
				entry = await user_ids.get(ctx.author.id)
				pseudo_effective = (entry.get("steam") or "").strip()
				if not pseudo_effective:
					await ctx.send(
						"Pseudo Steam manquant. Enregistre-le avec `!id steam <ton_steam>` "
						"ou passe-le en argument : `!stats smite1 <steam>`."
					)
					return
			platform, identifier = _split_platform_identifier(pseudo_effective, platform_default)
			try:
				cache_key = f"trn:smite:{platform}:{identifier}".lower()
				payload = await api_cache.get_or_set(
					key=cache_key,
					ttl_seconds=TTL_TRN_SECONDS,
					factory=lambda: _trn_get_profile(
						api_key=api_key,
						game_slug="smite",
						platform=platform,
						identifier=identifier,
					),
				)
				embed = _trn_build_embed(
					title="TRN — Smite",
					payload=payload,  # type: ignore[arg-type]
					profile_url=f"https://tracker.gg/smite/profile/{platform}/{quote(identifier, safe='')}"
				)
				await ctx.send(embed=embed)
			except TrnHttpError as e:
				print(f"TRN Smite HTTP {e.status}: {e.payload}", flush=True)
				if e.status in {401, 403}:
					await ctx.send("TRN refuse l’accès (401/403). Vérifie `TRN_API_KEY` (App ID TRN) et les permissions/quota.")
				elif e.status == 404:
					await ctx.send("Profil introuvable sur TRN. Essaie `steam:Pseudo` ou une autre plateforme.")
				elif e.status == 429:
					await ctx.send("Rate limit TRN (429). Réessaye dans quelques secondes.")
				else:
					await ctx.send("Erreur TRN inattendue. Check les logs du bot.")
			except Exception as e:
				print(f"TRN Smite error: {type(e).__name__}: {e}", flush=True)
				await ctx.send("Impossible de récupérer les stats Smite (TRN). Check les logs du bot.")
			return

		if game_key in {"rocketleague", "rocket", "rl"}:
			rapid_key = os.getenv("RAPIDAPI_KEY", "").strip()
			rapid_host = os.getenv("RL_RAPIDAPI_HOST", "").strip()
			
			if not rapid_key or not rapid_host:
				await ctx.send(
					"Rocket League est configuré via RapidAPI. Il manque une variable d'env: "
					"`RAPIDAPI_KEY` ou `RL_RAPIDAPI_HOST`. "
					"Voir README/.env.example."
				)
				return
			
			# Check for special commands: tournaments or shop
			pseudo_lower = pseudo.strip().lower()
			
			# Tournaments command
			if pseudo_lower == "tournaments":
				try:
					url = f"https://{rapid_host}/tournaments/europe"
					print(f"RapidAPI RL Tournaments GET {url}", flush=True)
					cache_key = f"rapidapi:rl:tournaments:europe".lower()
					payload = await api_cache.get_or_set(
						key=cache_key,
						ttl_seconds=TTL_RL_SECONDS,
						factory=lambda: _rapidapi_get_json(url=url, api_key=rapid_key, api_host=rapid_host),
					)
					print(f"RapidAPI RL Tournaments payload keys: {list(payload.keys()) if isinstance(payload, dict) else type(payload).__name__}", flush=True)
					embed = discord.Embed(
						title="Rocket League — Tournois Europe",
						color=discord.Color.blurple(),
					)
					
					# Parse tournaments array
					if isinstance(payload, dict):
						tournaments = payload.get("tournaments", [])
						if isinstance(tournaments, list) and len(tournaments) > 0:
							for i, tournament in enumerate(tournaments[:12]):  # Show up to 12 tournaments
								if isinstance(tournament, dict):
									# Parse fields: players, starts (ISO timestamp), mode
									players = tournament.get("players", "?")
									starts_iso = tournament.get("starts", "")
									mode = tournament.get("mode", "Standard")
									
									# Format the start time from ISO timestamp
									try:
										dt = datetime.fromisoformat(starts_iso.replace("Z", "+00:00"))
										# Show date and time in a readable format
										date_str = dt.strftime("%d/%m/%Y %H:%M UTC")
									except Exception:
										date_str = starts_iso or "Date inconnue"
									
									embed.add_field(
										name=f"🏆 Tournoi {i+1}",
										value=f"**Mode:** {mode}\n**Joueurs:** {players}v{players}\n**Début:** {date_str}",
										inline=True
									)
						else:
							embed.description = "Aucun tournoi disponible."
						
						if len(embed.fields) == 0:
							# Fallback: show raw data
							embed.description = f"Réponse reçue. Structure: {list(payload.keys())[:10]}"
							for k, v in _pick_scalar_stats(payload, limit=10):
								leaf = k.rsplit(".", 1)[-1]
								embed.add_field(name=leaf, value=str(v)[:100], inline=True)
								
					await ctx.send(embed=embed)
				except RapidApiHttpError as e:
					print(f"RapidAPI RL Tournaments HTTP {e.status} for {e.url}: {e.payload}", flush=True)
					if e.status in {401, 403}:
						await ctx.send("RapidAPI refuse l'accès (401/403). Vérifie `RAPIDAPI_KEY`.")
					elif e.status == 404:
						await ctx.send("Endpoint tournaments introuvable (404).")
					elif e.status == 429 or (isinstance(e.payload, dict) and "quota" in str(e.payload).lower()):
						await ctx.send("Quota journalier RapidAPI dépassé. Réessaye demain. (Les données sont en cache 24h.)")
					else:
						await ctx.send(f"Erreur RapidAPI HTTP {e.status}. Check les logs du bot.")
				except Exception as e:
					print(f"RapidAPI RL Tournaments error: {type(e).__name__}: {e}", flush=True)
					await ctx.send("Impossible de récupérer les tournois Rocket League.")
				return
			
			# Shop command
			if pseudo_lower == "shop":
				try:
					url = f"https://{rapid_host}/shops/featured"
					print(f"RapidAPI RL Shop GET {url}", flush=True)
					cache_key = f"rapidapi:rl:shop:featured".lower()
					payload = await api_cache.get_or_set(
						key=cache_key,
						ttl_seconds=TTL_RL_SECONDS,
						factory=lambda: _rapidapi_get_json(url=url, api_key=rapid_key, api_host=rapid_host),
					)
					print(f"RapidAPI RL Shop payload keys: {list(payload.keys()) if isinstance(payload, dict) else type(payload).__name__}", flush=True)
					embed = discord.Embed(
						title="Rocket League — Shop Featured",
						color=discord.Color.blurple(),
					)
					# Try to extract shop items from payload
					if isinstance(payload, dict):
						items = payload.get("items") or payload.get("featured") or payload.get("data") or payload
						if isinstance(items, list):
							for i, item in enumerate(items[:15]):  # Limit to 15 items
								if isinstance(item, dict):
									name = item.get("name") or item.get("title") or f"Item {i+1}"
									price = item.get("price") or item.get("cost") or "?"
									rarity = item.get("rarity") or ""
									value_text = f"Prix: {price}"
									if rarity:
										value_text += f" • {rarity}"
									embed.add_field(name=name, value=value_text, inline=True)
						if len(embed.fields) == 0:
							# Fallback: show raw data
							embed.description = f"Réponse reçue. Structure: {list(payload.keys())[:10]}"
							for k, v in _pick_scalar_stats(payload, limit=10):
								leaf = k.rsplit(".", 1)[-1]
								embed.add_field(name=leaf, value=str(v)[:100], inline=True)
								
					await ctx.send(embed=embed)
				except RapidApiHttpError as e:
					print(f"RapidAPI RL Shop HTTP {e.status} for {e.url}: {e.payload}", flush=True)
					if e.status in {401, 403}:
						await ctx.send("RapidAPI refuse l'accès (401/403). Vérifie `RAPIDAPI_KEY`.")
					elif e.status == 404:
						await ctx.send("Endpoint shop introuvable (404).")
					elif e.status == 429 or (isinstance(e.payload, dict) and "quota" in str(e.payload).lower()):
						await ctx.send("Quota journalier RapidAPI dépassé. Réessaye demain. (Les données sont en cache 24h.)")
					elif e.status == 500:
						await ctx.send("Erreur serveur RapidAPI (500). L'API du shop peut être temporairement indisponible.")
					else:
						await ctx.send(f"Erreur RapidAPI HTTP {e.status}. Check les logs du bot.")
				except Exception as e:
					print(f"RapidAPI RL Shop error: {type(e).__name__}: {e}", flush=True)
					await ctx.send("Impossible de récupérer le shop Rocket League.")
				return
			
			# Normal player stats lookup
			url_tmpl = os.getenv("RL_RAPIDAPI_URL_TEMPLATE", "").strip()
			if not url_tmpl:
				await ctx.send(
					"Il manque `RL_RAPIDAPI_URL_TEMPLATE` pour les stats de joueur. "
					"Voir README/.env.example."
				)
				return

			platform_default = os.getenv("RL_PLATFORM", "steam").strip() or "steam"
			pseudo_effective = pseudo.strip()
			if not pseudo_effective:
				entry = await user_ids.get(ctx.author.id)
				pseudo_effective = (entry.get("epic") or "").strip()
				if not pseudo_effective:
					await ctx.send(
						"Pseudo Epic manquant. Enregistre-le avec `!id epic <ton_epic>` "
						"ou passe-le en argument : `!stats rocketleague <epic>`."
					)
					return
			platform, identifier = _split_platform_identifier(pseudo_effective, platform_default)
			# Normalize identifier case for providers that expect lowercase display names
			identifier_norm = identifier.strip()
			if rapid_host == "rocket-league1.p.rapidapi.com":
				identifier_norm = identifier_norm.lower()

			url_path_or_full = url_tmpl.format(
				platform=quote(platform, safe=""),
				identifier=quote(identifier_norm, safe=""),
				player=quote(identifier_norm, safe=""),
			)
			url = (
				f"https://{rapid_host}{url_path_or_full}"
				if url_path_or_full.startswith("/")
				else url_path_or_full
			)

			try:
				print(f"RapidAPI RL GET {url}", flush=True)
				cache_key = f"rapidapi:rl:{rapid_host}:{url}".lower()
				payload = await api_cache.get_or_set(
					key=cache_key,
					ttl_seconds=TTL_RL_SECONDS,
					factory=lambda: _rapidapi_get_json(url=url, api_key=rapid_key, api_host=rapid_host),
				)
				embed = discord.Embed(
					title="Rocket League — RapidAPI",
					description=f"Joueur: `{identifier_norm}`",
					color=discord.Color.blurple(),
				)
				if rapid_host == "rocket-league1.p.rapidapi.com" and platform not in {"epic", "egs"}:
					embed.add_field(
						name="Note",
						value=(
							"Cette API attend un Epic account id ou display name. "
							"La plateforme `steam:` est ignorée. Astuce: utilise `epic:<ton_pseudo>`"
						),
						inline=False,
					)
				# Prefer Rocket League-specific parsing when available
				parsed = False
				if isinstance(payload, dict):
					ranks = payload.get("ranks")
					if isinstance(ranks, list) and ranks:
						for item in ranks[:6]:
							if isinstance(item, dict):
								playlist = item.get("playlist") or "Unknown"
								rank_name = item.get("rank") or "?"
								division = item.get("division")
								mmr = item.get("mmr")
								streak = item.get("streak")
								value_text = f"{rank_name}"
								if division is not None:
									value_text += f" • Div {division}"
								if mmr is not None:
									value_text += f" • MMR {mmr}"
								if streak is not None:
									value_text += f" • Streak {streak}"
								embed.add_field(name=str(playlist), value=value_text, inline=True)
						parsed = parsed or (len(embed.fields) > 0)
					reward = payload.get("reward")
					if isinstance(reward, dict):
						level = reward.get("level")
						progress = reward.get("progress")
						embed.add_field(name="Reward", value=f"Level: {level or '?'} • Progress: {progress if progress is not None else '?'}", inline=False)
						parsed = True

				# Fallback: generic scalar stats when format is unknown
				if not parsed:
					for k, v in _pick_scalar_stats(payload, limit=6):
						leaf = k.rsplit(".", 1)[-1]
						embed.add_field(name=leaf, value=v, inline=True)
					if len(embed.fields) == 0:
						embed.add_field(name="Info", value="Réponse reçue, mais format inconnu (voir logs).", inline=False)
				print(f"RapidAPI RL payload keys: {list(payload.keys()) if isinstance(payload, dict) else type(payload).__name__}", flush=True)
				await ctx.send(embed=embed)
			except RapidApiHttpError as e:
				print(f"RapidAPI RocketLeague HTTP {e.status} for {e.url}: {e.payload}", flush=True)
				if e.status in {401, 403}:
					await ctx.send(
						"RapidAPI refuse l’accès (401/403). Vérifie `RAPIDAPI_KEY` et que l’API est bien active sur ton compte."
					)
				elif e.status == 404:
					await ctx.send(
						"Endpoint introuvable (404). Vérifie `RL_RAPIDAPI_URL_TEMPLATE` (pour rocket-league1: `/ranks/{identifier}`)."
					)
				elif e.status == 429 or (isinstance(e.payload, dict) and "quota" in str(e.payload).lower()):
					await ctx.send("Quota journalier RapidAPI dépassé. Réessaye demain. (Les stats sont en cache 24h si déjà demandées.)")
				elif e.status == 502 and isinstance(e.payload, dict) and "empty json" in str(e.payload.get("message", "")).lower():
					await ctx.send("Joueur introuvable sur l’API Rocket League (RapidAPI). Vérifie le display name/id Epic ou essaye une autre graphie.")
				else:
					await ctx.send(f"Erreur RapidAPI HTTP {e.status}. Check les logs du bot.")
			except Exception as e:
				print(f"RapidAPI RocketLeague error: {type(e).__name__}: {e}", flush=True)
				await ctx.send(
					"Impossible de récupérer les stats Rocket League (RapidAPI). "
					"Check les logs du bot (journalctl) pour le détail."
				)
			return

		await ctx.send("Jeu non supporté pour l’instant. Priorités actuelles: smite2, minecraft, rocketleague.")

	return bot


def main() -> int:
	_load_dotenv_if_present()
	settings = load_settings()

	bot = asyncio_run(build_bot(settings))
	bot.run(settings.token)
	return 0


def asyncio_run(coro):
	try:
		import asyncio

		return asyncio.run(coro)
	except RuntimeError:
		# Fallback for environments where an event loop is already running.
		import asyncio

		loop = asyncio.get_event_loop()
		return loop.run_until_complete(coro)


if __name__ == "__main__":
	raise SystemExit(main())

