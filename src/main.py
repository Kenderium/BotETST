
import os
import random
import sys
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Optional

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
			title="Help on BOT",
			description="Some useful commands",
			color=discord.Color.blurple(),
		)
		embed.add_field(name="!hello", value="Greets the user", inline=True)
		embed.add_field(name="!users", value="Prints number of users", inline=True)
		embed.add_field(name="!damn", value="You can damn people", inline=True)
		embed.add_field(name="!DJ", value="My vengance is going to be huge", inline=True)
		embed.add_field(name="!Nicoow", value="My vengance is going to hurt you ☠", inline=True)
		embed.add_field(name="!Lucas", value="Lucas.", inline=True)
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
		if ":" in raw:
			host, port_s = raw.rsplit(":", 1)
			return host.strip(), int(port_s.strip())
		return raw, 25565

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
				"Usage: `!stats <jeu> <pseudo>`\n"
				"Exemples: `!stats smite2 MonPseudo`, `!stats rocketleague MonPseudo`, `!stats minecraft`"
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

		if not pseudo.strip():
			await ctx.send("Usage: `!stats <jeu> <pseudo>`")
			return

		if game_key in {"smite2", "smite 2", "smite_2"}:
			await ctx.send(
				"Smite 2: il me faut la méthode/API que tu veux utiliser (officielle/tiers) + les clefs."
			)
			return

		if game_key in {"rocketleague", "rocket", "rl"}:
			await ctx.send(
				"Rocket League: pas d’API officielle simple. Si tu as un token Tracker Network (TRN) ou autre, je peux l’intégrer."
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

