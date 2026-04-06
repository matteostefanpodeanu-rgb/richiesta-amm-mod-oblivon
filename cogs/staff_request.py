"""
cogs/staff_request.py — Comando /richiesta-staff (solo Amministrazione)
"""

import asyncio
import discord
from discord.ext import commands
from discord import app_commands
import logging
from datetime import datetime

import config
import database as db

log = logging.getLogger("OblivionBot.StaffRequest")


# ─────────────────────────────────────────
#  MODAL
# ─────────────────────────────────────────

class StaffRequestModal(discord.ui.Modal, title="⚜️  Richiesta Amministrazione"):
    def __init__(self):
        super().__init__(timeout=config.MODAL_TIMEOUT)

    priorita = discord.ui.TextInput(
        label="Priorità",
        placeholder="urgente / alta / media / bassa",
        max_length=10,
        required=True,
        style=discord.TextStyle.short,
    )
    motivo = discord.ui.TextInput(
        label="Motivo della richiesta",
        placeholder="Descrivi chiaramente il motivo per cui chiami l'Amministrazione...",
        max_length=500,
        required=True,
        style=discord.TextStyle.paragraph,
    )
    note = discord.ui.TextInput(
        label="Note aggiuntive (opzionale)",
        placeholder="Qualsiasi informazione extra utile all'Amministrazione...",
        max_length=300,
        required=False,
        style=discord.TextStyle.paragraph,
    )

    async def on_submit(self, interaction: discord.Interaction):
        priorita_raw = self.priorita.value.strip().lower()
        valide = ["urgente", "alta", "media", "bassa"]
        priorita = priorita_raw if priorita_raw in valide else "media"
        motivo = self.motivo.value.strip()
        note = self.note.value.strip() or None

        await interaction.response.defer(ephemeral=True)

        # Salva nel DB
        request = db.new_request(
            team="amministrazione",
            priority=priorita,
            reason=motivo,
            notes=note or "Nessuna nota aggiuntiva.",
            requester_id=interaction.user.id,
            channel_id=interaction.channel.id,
            guild_id=interaction.guild.id,
        )

        stats = db.get_stats()

        # Embed nel canale ticket
        embed = build_request_embed(
            request=request,
            requester=interaction.user,
            channel=interaction.channel,
            stats=stats,
        )

        view = ResolveView(req_id=request["id"])
        msg = await interaction.channel.send(embed=embed, view=view)
        db.update_message_id(request["id"], msg.id)

        await interaction.followup.send(
            f"✅ Richiesta `{request['id']}` inviata! L'Amministrazione è stata notificata in DM.",
            ephemeral=True,
        )

        # DM ai membri dell'amministrazione (subito)
        await send_dms(
            guild=interaction.guild,
            request=request,
            requester=interaction.user,
            channel=interaction.channel,
        )

        # Ping ruolo → eliminato immediatamente in background
        role = interaction.guild.get_role(config.ROLE_AMMINISTRAZIONE)
        if role:
            async def ping_and_delete():
                try:
                    ping_msg = await interaction.channel.send(
                        f"{role.mention}",
                        allowed_mentions=discord.AllowedMentions(roles=True),
                    )
                    await asyncio.sleep(0)
                    await ping_msg.delete()
                except Exception:
                    pass
            asyncio.create_task(ping_and_delete())

        # Log su canale dedicato
        await send_log(
            bot=interaction.client,
            guild=interaction.guild,
            request=request,
            requester=interaction.user,
            channel=interaction.channel,
        )

    async def on_error(self, interaction: discord.Interaction, error: Exception):
        log.error(f"Errore nel modal: {error}", exc_info=True)
        if not interaction.response.is_done():
            await interaction.response.send_message(
                "❌ Si è verificato un errore. Riprova.", ephemeral=True
            )


# ─────────────────────────────────────────
#  VIEW — Bottoni risolvi / annulla
# ─────────────────────────────────────────

class ResolveView(discord.ui.View):
    def __init__(self, req_id: str):
        super().__init__(timeout=None)
        self.req_id = req_id

    @discord.ui.button(
        label="✅  Segna come risolto",
        style=discord.ButtonStyle.success,
        custom_id="resolve_request",
    )
    async def resolve_btn(self, interaction: discord.Interaction, button: discord.ui.Button):
        request = db.get_request(self.req_id)
        if not request:
            await interaction.response.send_message("❌ Richiesta non trovata.", ephemeral=True)
            return
        if request["status"] == "resolved":
            await interaction.response.send_message("⚠️ Questa richiesta è già stata risolta.", ephemeral=True)
            return

        resolved = db.resolve_request(self.req_id, interaction.user.id)
        if not resolved:
            await interaction.response.send_message("❌ Impossibile risolvere la richiesta.", ephemeral=True)
            return

        stats = db.get_stats()
        requester = interaction.guild.get_member(resolved["requester_id"])

        embed = build_resolved_embed(
            request=resolved,
            requester=requester,
            resolver=interaction.user,
            channel=interaction.channel,
            stats=stats,
        )

        for child in self.children:
            child.disabled = True
        button.label = "✅  Risolta"

        await interaction.message.edit(embed=embed, view=self)
        await interaction.response.send_message(
            f"✅ Richiesta `{self.req_id}` risolta da {interaction.user.mention}."
        )

        await send_log(
            bot=interaction.client,
            guild=interaction.guild,
            request=resolved,
            requester=requester,
            channel=interaction.channel,
            resolved_by=interaction.user,
        )

    @discord.ui.button(
        label="❌  Annulla richiesta",
        style=discord.ButtonStyle.danger,
        custom_id="cancel_request",
    )
    async def cancel_btn(self, interaction: discord.Interaction, button: discord.ui.Button):
        request = db.get_request(self.req_id)
        if not request:
            await interaction.response.send_message("❌ Richiesta non trovata.", ephemeral=True)
            return

        is_requester = interaction.user.id == request["requester_id"]
        is_admin = interaction.user.guild_permissions.administrator

        if not (is_requester or is_admin):
            await interaction.response.send_message(
                "❌ Solo il richiedente o un amministratore può annullare questa richiesta.",
                ephemeral=True,
            )
            return
        if request["status"] == "resolved":
            await interaction.response.send_message("⚠️ La richiesta è già stata risolta.", ephemeral=True)
            return

        db.resolve_request(self.req_id, interaction.user.id)

        for child in self.children:
            child.disabled = True

        embed = interaction.message.embeds[0] if interaction.message.embeds else None
        if embed:
            embed.color = discord.Color.greyple()
            embed.set_footer(text=f"{embed.footer.text} • ANNULLATA")

        await interaction.message.edit(embed=embed, view=self)
        await interaction.response.send_message(
            f"🗑️ Richiesta `{self.req_id}` annullata da {interaction.user.mention}."
        )


# ─────────────────────────────────────────
#  HELPER — Embed richiesta aperta
# ─────────────────────────────────────────

def build_request_embed(
    request: dict,
    requester: discord.Member,
    channel: discord.TextChannel,
    stats: dict,
) -> discord.Embed:
    priorita = request["priority"]
    p_emoji = config.PRIORITY_EMOJI.get(priorita, "⚪")
    colore = config.COLORS.get(priorita, config.COLORS["default"])
    avg = f"{stats['avg_response_min']} min" if stats["avg_response_min"] > 0 else "N/D"

    embed = discord.Embed(
        title=f"⚜️  Richiesta al Team Amministrazione",
        description=(
            f"{requester.mention} ha aperto una richiesta urgente al team di **Amministrazione**.\n"
            f"Il team è stato notificato e raggiungerà il ticket il prima possibile."
        ),
        color=colore,
        timestamp=datetime.utcnow(),
    )
    embed.set_author(name="Oblivion Network — Richiesta Staff")
    embed.set_thumbnail(url=requester.display_avatar.url if requester.display_avatar else None)

    embed.add_field(name=f"{p_emoji}  Priorità", value=f"**{priorita.upper()}**", inline=True)
    embed.add_field(name="⚜️  Team", value="Amministrazione", inline=True)
    embed.add_field(name="🕐  Orario", value=datetime.utcnow().strftime("%d/%m/%Y %H:%M"), inline=True)

    embed.add_field(name="👤  Richiedente", value=requester.mention, inline=True)
    embed.add_field(name="🎫  Ticket", value=channel.mention, inline=True)
    embed.add_field(name="🆔  ID Richiesta", value=f"`{request['id']}`", inline=True)

    embed.add_field(
        name="📋  Motivo della richiesta",
        value=f"> {request['reason']}",
        inline=False,
    )
    if request.get("notes") and request["notes"] != "Nessuna nota aggiuntiva.":
        embed.add_field(
            name="📝  Note aggiuntive",
            value=f"> {request['notes']}",
            inline=False,
        )

    embed.add_field(
        name="📊  Statistiche sistema",
        value=(
            f"⏱️ Tempo medio risposta: **{avg}**  •  "
            f"🟡 Richieste aperte: **{stats['open']}**  •  "
            f"✅ Risolte oggi: **{stats['resolved_today']}**"
        ),
        inline=False,
    )
    embed.set_footer(text=f"Oblivion Network  •  {request['id']}  •  In attesa di risposta")
    return embed


# ─────────────────────────────────────────
#  HELPER — Embed richiesta risolta
# ─────────────────────────────────────────

def build_resolved_embed(
    request: dict,
    requester,
    resolver: discord.Member,
    channel: discord.TextChannel,
    stats: dict,
) -> discord.Embed:
    priorita = request["priority"]
    p_emoji = config.PRIORITY_EMOJI.get(priorita, "⚪")
    avg = f"{stats['avg_response_min']} min" if stats["avg_response_min"] > 0 else "N/D"

    resolved_at = datetime.fromisoformat(request["resolved_at"]) if request.get("resolved_at") else datetime.utcnow()
    created_at = datetime.fromisoformat(request["created_at"])
    elapsed = round((resolved_at - created_at).total_seconds() / 60, 1)

    embed = discord.Embed(
        title="✅  Richiesta Risolta — Amministrazione",
        description=(
            f"La richiesta è stata gestita da {resolver.mention}.\n"
            f"⏱️ Tempo di risposta: **{elapsed} minuti**"
        ),
        color=config.COLORS["resolved"],
        timestamp=resolved_at,
    )
    embed.set_author(name="Oblivion Network — Richiesta Staff")

    embed.add_field(name=f"{p_emoji}  Priorità", value=f"**{priorita.upper()}**", inline=True)
    embed.add_field(name="✅  Gestita da", value=resolver.mention, inline=True)
    embed.add_field(name="🕐  Risolta il", value=resolved_at.strftime("%d/%m/%Y %H:%M"), inline=True)

    embed.add_field(name="👤  Richiedente", value=requester.mention if requester else "Sconosciuto", inline=True)
    embed.add_field(name="🎫  Ticket", value=channel.mention, inline=True)
    embed.add_field(name="🆔  ID", value=f"`{request['id']}`", inline=True)

    embed.add_field(name="📋  Motivo originale", value=f"> {request['reason']}", inline=False)
    embed.add_field(
        name="📊  Statistiche",
        value=(
            f"⏱️ Tempo medio risposta: **{avg}**  •  "
            f"✅ Risolte oggi: **{stats['resolved_today']}**"
        ),
        inline=False,
    )
    embed.set_footer(text=f"Oblivion Network  •  {request['id']}  •  RISOLTA")
    return embed


# ─────────────────────────────────────────
#  HELPER — DM ai membri dell'Amministrazione
# ─────────────────────────────────────────

async def send_dms(
    guild: discord.Guild,
    request: dict,
    requester: discord.Member,
    channel: discord.TextChannel,
):
    role = guild.get_role(config.ROLE_AMMINISTRAZIONE)
    if not role:
        log.warning(f"Ruolo Amministrazione ({config.ROLE_AMMINISTRAZIONE}) non trovato.")
        return

    priorita = request["priority"]
    p_emoji = config.PRIORITY_EMOJI.get(priorita, "⚪")
    colore = config.COLORS.get(priorita, config.COLORS["default"])
    ticket_url = f"https://discord.com/channels/{guild.id}/{channel.id}"
    created_at = datetime.fromisoformat(request["created_at"])
    timestamp_str = created_at.strftime("%d/%m/%Y alle %H:%M")

    dm_embed = discord.Embed(
        title=f"{p_emoji}  Richiesta {priorita.upper()} — ⚜️ Amministrazione",
        description=(
            f"Sei stato chiamato nel ticket **#{channel.name}** sul server **{guild.name}**.\n"
            f"Un membro dello staff richiede la presenza dell'Amministrazione.\n\n"
            f"━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
        ),
        color=colore,
        timestamp=datetime.utcnow(),
    )
    dm_embed.set_author(
        name="Oblivion Network — Richiesta Staff",
        icon_url=guild.icon.url if guild.icon else None,
    )
    dm_embed.set_thumbnail(url=requester.display_avatar.url if requester.display_avatar else None)

    dm_embed.add_field(name=f"{p_emoji}  Priorità", value=f"**{priorita.upper()}**", inline=True)
    dm_embed.add_field(name="⚜️  Team", value="**Amministrazione**", inline=True)
    dm_embed.add_field(name="🕐  Orario richiesta", value=timestamp_str, inline=True)

    dm_embed.add_field(
        name="👤  Richiedente",
        value=f"{requester.display_name} (`{requester.name}`)",
        inline=True,
    )
    dm_embed.add_field(name="🎫  Canale ticket", value=f"#{channel.name}", inline=True)
    dm_embed.add_field(name="🆔  ID Richiesta", value=f"`{request['id']}`", inline=True)

    dm_embed.add_field(
        name="📋  Motivo della richiesta",
        value=f"> {request['reason'][:300]}{'...' if len(request['reason']) > 300 else ''}",
        inline=False,
    )
    if request.get("notes") and request["notes"] != "Nessuna nota aggiuntiva.":
        dm_embed.add_field(
            name="📝  Note aggiuntive",
            value=f"> {request['notes'][:200]}{'...' if len(request['notes']) > 200 else ''}",
            inline=False,
        )

    dm_embed.add_field(
        name="🔗  Accedi al ticket",
        value=f"[**→ Clicca qui per aprire il ticket**]({ticket_url})\n`{ticket_url}`",
        inline=False,
    )
    dm_embed.set_footer(
        text=f"Oblivion Network  •  {request['id']}  •  Messaggio automatico"
    )

    sent = 0
    failed = 0
    for member in role.members:
        if member.bot:
            continue
        try:
            await member.send(embed=dm_embed)
            sent += 1
        except discord.Forbidden:
            failed += 1
        except Exception as e:
            log.warning(f"Impossibile inviare DM a {member}: {e}")
            failed += 1

    log.info(f"DM Amministrazione: {sent} inviati, {failed} falliti.")


# ─────────────────────────────────────────
#  HELPER — Log su canale dedicato
# ─────────────────────────────────────────

async def send_log(
    bot: commands.Bot,
    guild: discord.Guild,
    request: dict,
    requester,
    channel: discord.TextChannel,
    resolved_by: discord.Member = None,
):
    if not config.LOG_CHANNEL_ID:
        return
    log_channel = guild.get_channel(config.LOG_CHANNEL_ID)
    if not log_channel:
        return

    priorita = request["priority"]
    p_emoji = config.PRIORITY_EMOJI.get(priorita, "⚪")
    status = "✅ Risolta" if request["status"] == "resolved" else "🟡 Aperta"

    embed = discord.Embed(
        title=f"📋  Log Richiesta  •  {request['id']}",
        color=config.COLORS["log"],
        timestamp=datetime.utcnow(),
    )
    embed.add_field(name="Team", value="⚜️ Amministrazione", inline=True)
    embed.add_field(name="Priorità", value=f"{p_emoji} {priorita.upper()}", inline=True)
    embed.add_field(name="Stato", value=status, inline=True)
    embed.add_field(
        name="Richiedente",
        value=requester.mention if requester else str(request["requester_id"]),
        inline=True,
    )
    embed.add_field(name="Ticket", value=channel.mention, inline=True)
    if resolved_by:
        embed.add_field(name="Gestita da", value=resolved_by.mention, inline=True)
    embed.add_field(name="Motivo", value=request["reason"][:500], inline=False)
    embed.set_footer(text="Oblivion Network — Staff Request Log")

    try:
        await log_channel.send(embed=embed)
    except Exception as e:
        log.warning(f"Impossibile inviare log: {e}")


# ─────────────────────────────────────────
#  COG
# ─────────────────────────────────────────

class StaffRequestCog(commands.Cog):
    def __init__(self, bot: commands.Bot):
        self.bot = bot

    @app_commands.command(
        name="richiesta-staff",
        description="Chiama il team Amministrazione nel ticket"
    )
    async def richiesta_staff(self, interaction: discord.Interaction):
        # Controlla che il canale sia un ticket
        channel_name = interaction.channel.name.lower()
        is_ticket = any(channel_name.startswith(p) for p in config.TICKET_PREFIXES)
        if not is_ticket:
            await interaction.response.send_message(
                "❌ Questo comando può essere usato **solo nei canali ticket**.",
                ephemeral=True,
            )
            return

        # Controlla permessi
        user_roles = [r.id for r in interaction.user.roles]
        is_allowed = (
            any(r in user_roles for r in config.ALLOWED_ROLES)
            or interaction.user.guild_permissions.administrator
        )
        if not is_allowed:
            await interaction.response.send_message(
                "❌ Non hai i permessi per usare questo comando.",
                ephemeral=True,
            )
            return

        # Apre direttamente il modal, senza menu di selezione
        modal = StaffRequestModal()
        await interaction.response.send_modal(modal)

    @app_commands.command(
        name="richieste-aperte",
        description="Mostra tutte le richieste Amministrazione ancora aperte"
    )
    @app_commands.default_permissions(manage_messages=True)
    async def richieste_aperte(self, interaction: discord.Interaction):
        open_reqs = db.get_open_requests()
        if not open_reqs:
            await interaction.response.send_message(
                "✅ Nessuna richiesta aperta al momento.", ephemeral=True
            )
            return

        embed = discord.Embed(
            title="📋  Richieste Amministrazione Aperte",
            color=config.COLORS["default"],
            timestamp=datetime.utcnow(),
        )
        for req in open_reqs[:10]:
            p_emoji = config.PRIORITY_EMOJI.get(req["priority"], "⚪")
            ch = interaction.guild.get_channel(req["channel_id"])
            ch_mention = ch.mention if ch else f"#{req['channel_id']}"
            created = datetime.fromisoformat(req["created_at"])
            elapsed = round((datetime.utcnow() - created).total_seconds() / 60, 1)
            embed.add_field(
                name=f"{p_emoji} {req['id']}",
                value=f"{ch_mention}  •  {req['reason'][:80]}...\n⏱️ Aperta da **{elapsed} min**",
                inline=False,
            )
        embed.set_footer(text=f"Oblivion Network  •  {len(open_reqs)} richieste aperte")
        await interaction.response.send_message(embed=embed, ephemeral=True)

    @app_commands.command(
        name="statistiche-staff",
        description="Statistiche generali del sistema richieste"
    )
    @app_commands.default_permissions(manage_messages=True)
    async def statistiche_staff(self, interaction: discord.Interaction):
        stats = db.get_stats()
        avg = f"{stats['avg_response_min']} min" if stats["avg_response_min"] > 0 else "N/D"

        embed = discord.Embed(
            title="📊  Statistiche — Sistema Richieste Staff",
            color=config.COLORS["default"],
            timestamp=datetime.utcnow(),
        )
        embed.add_field(name="🟡  Richieste aperte", value=f"**{stats['open']}**", inline=True)
        embed.add_field(name="✅  Risolte oggi", value=f"**{stats['resolved_today']}**", inline=True)
        embed.add_field(name="⏱️  Tempo medio risposta", value=f"**{avg}**", inline=True)
        embed.set_footer(text="Oblivion Network — Staff Request Stats")
        await interaction.response.send_message(embed=embed, ephemeral=True)


async def setup(bot: commands.Bot):
    await bot.add_cog(StaffRequestCog(bot))
    log.info("StaffRequestCog caricato.")
