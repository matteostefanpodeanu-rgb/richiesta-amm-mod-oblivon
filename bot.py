"""
Oblivion Network — Staff Request Bot
Avvia il bot: python bot.py
"""

import discord
from discord.ext import commands
from discord import app_commands
import asyncio
import logging
import os
from dotenv import load_dotenv

load_dotenv()

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    handlers=[
        logging.FileHandler("bot.log", encoding="utf-8"),
        logging.StreamHandler()
    ]
)
log = logging.getLogger("OblivionBot")

intents = discord.Intents.default()
intents.members = True
intents.message_content = True
intents.guilds = True


class OblivionBot(commands.Bot):
    def __init__(self):
        super().__init__(
            command_prefix="!",
            intents=intents,
            help_command=None
        )

    async def setup_hook(self):
        await self.load_extension("cogs.staff_request")
        log.info("Cogs caricati.")

    async def on_ready(self):
        log.info(f"Bot online come {self.user} (ID: {self.user.id})")
        await self.change_presence(
            activity=discord.Activity(
                type=discord.ActivityType.watching,
                name="i ticket di Oblivion Network"
            )
        )
        try:
            synced = await self.tree.sync()
            log.info(f"Sincronizzati {len(synced)} slash command.")
        except Exception as e:
            log.error(f"Errore sync comandi: {e}")


def main():
    token = os.getenv("DISCORD_TOKEN")
    if not token:
        log.critical("DISCORD_TOKEN non trovato nel file .env!")
        return
    bot = OblivionBot()
    bot.run(token, log_handler=None)


if __name__ == "__main__":
    main()
