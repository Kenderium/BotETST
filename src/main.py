
import os
import random
import sys
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
				raise RuntimeError(f"TRN HTTP {resp.status}: {data}")
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

	@bot.event
	async def on_ready() -> None:
		if bot.user is None:
			return
		print(f"ETST connected as {bot.user} (id={bot.user.id})")

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
		print(f"Command error: {type(error).__name__}: {error}")
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
		embed.add_field(name=f"{p}DJ", value="Citation DJ.", inline=True)
		embed.add_field(name=f"{p}Nicoow", value="Citation Nicoow.", inline=True)
		embed.add_field(name=f"{p}Lucas", value="Citation Lucas.", inline=True)
		embed.add_field(name=f"{p}Grimdal", value="Invoque Grimdal.", inline=True)
		embed.add_field(name=f"{p}Kenderium", value="Invoque Kenderium.", inline=True)
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
			value="(À brancher) Stats Smite 2.",
			inline=False,
		)
		embed.add_field(
			name=f"{p}stats rocketleague <pseudo>",
			value="(À brancher) Stats Rocket League.",
			inline=False,
		)
		embed.set_footer(text="Eternal Storm — Smite, Overwatch 2, Rocket League, Ark, Minecraft, Fortnite, etc.")
		await ctx.send(embed=embed)

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

	@bot.command(name="DJ")
	async def dj(ctx: commands.Context) -> None:
		await ctx.send("My vengance is going to be huge")

	def _simple_callout(name: str, default_text: str):
		@bot.command(name=name)
		async def _cmd(ctx: commands.Context) -> None:
			await ctx.send(default_text)

		return _cmd

	_simple_callout("Nicoow", "My vengance is going to hurt you ☠")
	_simple_callout("Lucas", "Lucas.")
	_simple_callout("Grimdal", "Grimdal a été invoqué.")
	_simple_callout("Kenderium", "Kenderium a été invoqué.")

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
		from mcstatus import JavaServer  # type: ignore
		import asyncio

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
				await ctx.send(await _mc_status_text())
			except Exception as e:
				await ctx.send(
					"Impossible de récupérer le status Minecraft. "
					"Vérifie `MINECRAFT_SERVER` (souvent `:25565`). "
					"Attention: `8123` est fréquemment le port Dynmap (web), pas le port Minecraft."
				)
				print(f"Minecraft status error: {type(e).__name__}: {e}")
			return

		if game_key in {"ark"}:
			try:
				await ctx.send(await _ark_status_text_etst1())
			except Exception as e:
				await ctx.send(
					"Impossible de récupérer le status ARK. "
					"Vérifie `ARK_ETST1_SERVER` (IP:port du port *query* Steam/A2S)."
				)
				print(f"ARK status error: {type(e).__name__}: {e}")
			return

		if not pseudo.strip():
			await ctx.send(f"Usage: `{settings.prefix}stats <jeu> <pseudo>`")
			return

		if game_key in {"smite2", "smite 2", "smite_2"}:
			api_key = os.getenv("TRN_API_KEY", "").strip()
			if not api_key:
				await ctx.send("TRN_API_KEY manquant: ajoute-le dans ton `.env` pour activer `!stats smite2`.")
				return
			platform_default = os.getenv("TRN_SMITE2_PLATFORM", "steam").strip() or "steam"
			platform, identifier = _split_platform_identifier(pseudo, platform_default)
			try:
				payload = await _trn_get_profile(
					api_key=api_key,
					game_slug="smite2",
					platform=platform,
					identifier=identifier,
				)
				embed = _trn_build_embed(
					title="TRN — Smite 2",
					payload=payload,
					profile_url=f"https://tracker.gg/smite2/profile/{platform}/{quote(identifier, safe='')}"
				)
				await ctx.send(embed=embed)
			except Exception as e:
				print(f"TRN Smite2 error: {type(e).__name__}: {e}")
				await ctx.send(
					"Impossible de récupérer les stats Smite 2 (TRN). "
					"Vérifie `TRN_API_KEY` et le pseudo (tu peux faire `steam:Pseudo`)."
				)
			return

		if game_key in {"smite1", "smite 1", "smite_1", "smite"}:
			api_key = os.getenv("TRN_API_KEY", "").strip()
			if not api_key:
				await ctx.send("TRN_API_KEY manquant: ajoute-le dans ton `.env` pour activer `!stats smite1`.")
				return
			platform_default = os.getenv("TRN_SMITE1_PLATFORM", "steam").strip() or "steam"
			platform, identifier = _split_platform_identifier(pseudo, platform_default)
			try:
				payload = await _trn_get_profile(
					api_key=api_key,
					game_slug="smite",
					platform=platform,
					identifier=identifier,
				)
				embed = _trn_build_embed(
					title="TRN — Smite",
					payload=payload,
					profile_url=f"https://tracker.gg/smite/profile/{platform}/{quote(identifier, safe='')}"
				)
				await ctx.send(embed=embed)
			except Exception as e:
				print(f"TRN Smite error: {type(e).__name__}: {e}")
				await ctx.send(
					"Impossible de récupérer les stats Smite (TRN). "
					"Vérifie `TRN_API_KEY` et le pseudo (tu peux faire `steam:Pseudo`)."
				)
			return

		if game_key in {"rocketleague", "rocket", "rl"}:
			api_key = os.getenv("TRN_API_KEY", "").strip()
			if not api_key:
				await ctx.send("TRN_API_KEY manquant: ajoute-le dans ton `.env` pour activer `!stats rocketleague`.")
				return
			platform_default = os.getenv("TRN_RL_PLATFORM", "steam").strip() or "steam"
			platform, identifier = _split_platform_identifier(pseudo, platform_default)
			try:
				payload = await _trn_get_profile(
					api_key=api_key,
					game_slug="rocket-league",
					platform=platform,
					identifier=identifier,
				)
				embed = _trn_build_embed(
					title="TRN — Rocket League",
					payload=payload,
					profile_url=f"https://tracker.gg/rocket-league/profile/{platform}/{quote(identifier, safe='')}"
				)
				await ctx.send(embed=embed)
			except Exception as e:
				print(f"TRN RocketLeague error: {type(e).__name__}: {e}")
				await ctx.send(
					"Impossible de récupérer les stats Rocket League (TRN). "
					"Vérifie `TRN_API_KEY` et le pseudo (tu peux faire `steam:Pseudo` ou `epic:Pseudo`)."
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

