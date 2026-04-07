"""
cogs/stats.py — Comando /statistiche-staff
"""

import discord
from discord.ext import commands
from discord import app_commands
import logging
from datetime import datetime

import config
import database as db

log = logging.getLogger("OblivionBot.Stats")


class StatsCog(commands.Cog):
    def __init__(self, bot: commands.Bot):
        self.bot = bot

    @app_commands.command(
        name="statistiche-staff",
        description="Mostra le statistiche del sistema richieste staff"
    )
    @app_commands.default_permissions(manage_messages=True)
    async def statistiche_staff(self, interaction: discord.Interaction):
        stats = db.get_stats()
        avg = f"{stats['avg_response_min']} min" if stats['avg_response_min'] > 0 else "Nessun dato"

        embed = discord.Embed(
            title="📊  Statistiche Richieste Staff",
            color=config.COLORS["default"],
            timestamp=datetime.utcnow(),
        )
        embed.add_field(name="📬  Richieste totali", value=f"**{stats['total']}**", inline=True)
        embed.add_field(name="✅  Risolte oggi", value=f"**{stats['resolved_today']}**", inline=True)
        embed.add_field(name="🟡  Aperte ora", value=f"**{stats['open']}**", inline=True)
        embed.add_field(name="⏱️  Tempo medio risposta", value=f"**{avg}**", inline=True)
        embed.set_footer(text="Oblivion Network — Statistiche Staff")
        embed.set_thumbnail(url=interaction.guild.icon.url if interaction.guild.icon else None)

        await interaction.response.send_message(embed=embed, ephemeral=False)


async def setup(bot: commands.Bot):
    await bot.add_cog(StatsCog(bot))
    log.info("StatsCog caricato.")
