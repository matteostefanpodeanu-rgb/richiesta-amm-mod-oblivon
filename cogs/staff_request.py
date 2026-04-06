"""
cogs/staff_request.py — Comando /richiesta-staff
"""

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

class StaffRequestModal(discord.ui.Modal):
    def __init__(self, team: str):
        label = config.TEAM_LABEL[team]
        super().__init__(title=f"Richiesta {label}", timeout=config.MODAL_TIMEOUT)
        self.team = team

        self.priorita = discord.ui.TextInput(
            label="Priorità",
            placeholder="urgente / alta / media / bassa",
            max_length=10,
            required=True,
            style=discord.TextStyle.short,
        )
        self.motivo = discord.ui.TextInput(
            label="Motivo della richiesta",
            placeholder="Descrivi il motivo per cui chiami questo team...",
            max_length=500,
            required=True,
            style=discord.TextStyle.paragraph,
        )
        self.note = discord.ui.TextInput(
            label="Note aggiuntive (opzionale)",
            placeholder="Qualsiasi informazione extra utile al team...",
            max_length=300,
            required=False,
            style=discord.TextStyle.paragraph,
        )
        self.add_item(self.priorita)
        self.add_item(self.motivo)
        self.add_item(self.note)

    async def on_submit(self, interaction: discord.Interaction):
        priorita_raw = self.priorita.value.strip().lower()
        valide = ["urgente", "alta", "media", "bassa"]
        priorita = priorita_raw if priorita_raw in valide else "media"
        motivo = self.motivo.value.strip()
        note = self.note.value.strip() or "Nessuna nota aggiuntiva."

        await interaction.response.defer(ephemeral=True)

        # Salva nel DB
        request = db.new_request(
            team=self.team,
            priority=priorita,
            reason=motivo,
            notes=note,
            requester_id=interaction.user.id,
            channel_id=interaction.channel.id,
            guild_id=interaction.guild.id,
        )

        stats = db.get_stats()

        # Build embed principale
        embed = build_request_embed(
            request=request,
            requester=interaction.user,
            channel=interaction.channel,
            stats=stats,
        )

        # View con bottone "Segna come risolto"
        view = ResolveView(req_id=request["id"])

        msg = await interaction.channel.send(embed=embed, view=view)
        db.update_message_id(request["id"], msg.id)

        await interaction.followup.send(
            f"✅ Richiesta `{request['id']}` inviata con successo!",
            ephemeral=True
        )

        # Ping ruolo nel canale
        role_id = (
            config.ROLE_MODERAZIONE
            if self.team == "moderazione"
            else config.ROLE_AMMINISTRAZIONE
        )
        role = interaction.guild.get_role(role_id)
        if role:
            ping_msg = await interaction.channel.send(
                f"{role.mention} — <@{interaction.user.id}> ha aperto una richiesta `{config.PRIORITY_EMOJI[priorita]} {priorita.upper()}`.",
                allowed_mentions=discord.AllowedMentions(roles=True),
            )
            # Elimina il ping dopo 10s per non spammare
            await asyncio.sleep(10)
            try:
                await ping_msg.delete()
            except Exception:
                pass

        # DM ai membri del team
        await send_dms(
            guild=interaction.guild,
            role_id=role_id,
            request=request,
            requester=interaction.user,
            channel=interaction.channel,
        )

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
#  VIEW — Bottone "Segna come risolto"
# ─────────────────────────────────────────

class ResolveView(discord.ui.View):
    def __init__(self, req_id: str):
        super().__init__(timeout=None)  # Persistente al riavvio
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

        # Aggiorna embed
        stats = db.get_stats()
        requester = interaction.guild.get_member(resolved["requester_id"])
        channel = interaction.channel

        embed = build_resolved_embed(
            request=resolved,
            requester=requester,
            resolver=interaction.user,
            channel=channel,
            stats=stats,
        )

        button.disabled = True
        button.label = "✅  Risolto"
        await interaction.message.edit(embed=embed, view=self)
        await interaction.response.send_message(
            f"✅ Richiesta `{self.req_id}` segnata come risolta da {interaction.user.mention}.",
        )

        # Log
        await send_log(
            bot=interaction.client,
            guild=interaction.guild,
            request=resolved,
            requester=requester,
            channel=channel,
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

        # Solo il richiedente o un admin può annullare
        is_requester = interaction.user.id == request["requester_id"]
        is_admin = interaction.user.guild_permissions.administrator

        if not (is_requester or is_admin):
            await interaction.response.send_message(
                "❌ Solo il richiedente o un amministratore può annullare questa richiesta.",
                ephemeral=True
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
#  VIEW — Selezione team (ephemeral)
# ─────────────────────────────────────────

class TeamSelectView(discord.ui.View):
    def __init__(self):
        super().__init__(timeout=60)

    @discord.ui.select(
        cls=discord.ui.Select,
        placeholder="Seleziona il team da chiamare...",
        options=[
            discord.SelectOption(
                label="Team Moderazione",
                description="Chiama i moderatori del server",
                value="moderazione",
                emoji="🛡️",
            ),
            discord.SelectOption(
                label="Team Amministrazione",
                description="Chiama gli amministratori del server",
                value="amministrazione",
                emoji="⚜️",
            ),
        ],
    )
    async def select_team(self, interaction: discord.Interaction, select: discord.ui.Select):
        team = select.values[0]
        modal = StaffRequestModal(team=team)
        await interaction.response.send_modal(modal)
        self.stop()

    async def on_timeout(self):
        for child in self.children:
            child.disabled = True


# ─────────────────────────────────────────
#  HELPER — Build embed richiesta aperta
# ─────────────────────────────────────────

def build_request_embed(
    request: dict,
    requester: discord.Member,
    channel: discord.TextChannel,
    stats: dict,
) -> discord.Embed:
    team = request["team"]
    priorita = request["priority"]
    p_emoji = config.PRIORITY_EMOJI.get(priorita, "⚪")
    t_emoji = config.TEAM_EMOJI.get(team, "👥")
    colore = config.COLORS.get(priorita, config.COLORS["default"])
    label = config.TEAM_LABEL[team]

    avg = f"{stats['avg_response_min']} min" if stats['avg_response_min'] > 0 else "N/D"

    embed = discord.Embed(
        title=f"{t_emoji}  Richiesta al Team {label}",
        description=(
            f"{requester.mention} ha inviato una richiesta al team di **{label}**.\n"
            f"Il team è stato notificato. Attendere la risposta nel ticket."
        ),
        color=colore,
        timestamp=datetime.utcnow(),
    )
    embed.set_author(name="Richiesta Staff — Oblivion Network")
    embed.add_field(name=f"{p_emoji}  Priorità", value=f"**{priorita.upper()}**", inline=True)
    embed.add_field(name=f"{t_emoji}  Team chiamato", value=label, inline=True)
    embed.add_field(name="👤  Richiedente", value=requester.mention, inline=True)
    embed.add_field(name="🎫  Ticket", value=channel.mention, inline=True)
    embed.add_field(name="📋  Motivo della richiesta", value=request["reason"], inline=False)
    embed.add_field(name="📝  Note aggiuntive", value=request["notes"], inline=False)
    embed.add_field(
        name="📊  Statistiche",
        value=(
            f"🟢 Tempo medio risposta: **{avg}**  •  "
            f"🟡 Richieste aperte: **{stats['open']}**  •  "
            f"✅ Risolte oggi: **{stats['resolved_today']}**"
        ),
        inline=False,
    )
    embed.set_footer(text=f"Oblivion Network  •  {request['id']}")
    if requester.display_avatar:
        embed.set_thumbnail(url=requester.display_avatar.url)
    return embed


# ─────────────────────────────────────────
#  HELPER — Build embed richiesta risolta
# ─────────────────────────────────────────

def build_resolved_embed(
    request: dict,
    requester,
    resolver: discord.Member,
    channel: discord.TextChannel,
    stats: dict,
) -> discord.Embed:
    team = request["team"]
    priorita = request["priority"]
    p_emoji = config.PRIORITY_EMOJI.get(priorita, "⚪")
    t_emoji = config.TEAM_EMOJI.get(team, "👥")
    label = config.TEAM_LABEL[team]
    avg = f"{stats['avg_response_min']} min" if stats['avg_response_min'] > 0 else "N/D"

    resolved_at = datetime.fromisoformat(request["resolved_at"]) if request.get("resolved_at") else datetime.utcnow()
    created_at = datetime.fromisoformat(request["created_at"])
    elapsed = round((resolved_at - created_at).total_seconds() / 60, 1)

    embed = discord.Embed(
        title=f"✅  Richiesta Risolta — {label}",
        description=(
            f"La richiesta è stata gestita da {resolver.mention}.\n"
            f"Tempo di risposta: **{elapsed} minuti**"
        ),
        color=config.COLORS["resolved"],
        timestamp=resolved_at,
    )
    embed.set_author(name="Richiesta Staff — Oblivion Network")
    embed.add_field(name=f"{p_emoji}  Priorità", value=f"**{priorita.upper()}**", inline=True)
    embed.add_field(name=f"{t_emoji}  Team", value=label, inline=True)
    embed.add_field(name="👤  Richiedente", value=requester.mention if requester else "Sconosciuto", inline=True)
    embed.add_field(name="✅  Gestito da", value=resolver.mention, inline=True)
    embed.add_field(name="📋  Motivo originale", value=request["reason"], inline=False)
    embed.add_field(
        name="📊  Statistiche",
        value=(
            f"🟢 Tempo medio risposta: **{avg}**  •  "
            f"✅ Risolte oggi: **{stats['resolved_today']}**"
        ),
        inline=False,
    )
    embed.set_footer(text=f"Oblivion Network  •  {request['id']}  •  RISOLTA")
    return embed


# ─────────────────────────────────────────
#  HELPER — Invia DM ai membri del team
# ─────────────────────────────────────────

async def send_dms(
    guild: discord.Guild,
    role_id: int,
    request: dict,
    requester: discord.Member,
    channel: discord.TextChannel,
):
    role = guild.get_role(role_id)
    if not role:
        log.warning(f"Ruolo {role_id} non trovato.")
        return

    priorita = request["priority"]
    p_emoji = config.PRIORITY_EMOJI.get(priorita, "⚪")
    team_label = config.TEAM_LABEL[request["team"]]
    colore = config.COLORS.get(priorita, config.COLORS["default"])
    ticket_url = f"https://discord.com/channels/{guild.id}/{channel.id}"

    dm_embed = discord.Embed(
        title="📬  Sei stato chiamato in un ticket",
        description=(
            f"Uno staff member richiede la tua presenza nel ticket **{channel.name}**"
            f" del server **{guild.name}**.\n\n"
            f"**{p_emoji} Priorità:** {priorita.upper()}\n"
            f"**Richiedente:** {requester.display_name}\n"
            f"**Motivo:** {request['reason'][:200]}{'...' if len(request['reason']) > 200 else ''}"
        ),
        color=colore,
        timestamp=datetime.utcnow(),
    )
    dm_embed.add_field(name="🔗  Link al ticket", value=f"[Clicca qui per andare al ticket]({ticket_url})", inline=False)
    dm_embed.set_footer(text=f"Oblivion Network  •  {request['id']}")
    dm_embed.set_thumbnail(url=guild.icon.url if guild.icon else None)

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

    log.info(f"DM inviati: {sent} successo, {failed} falliti per {team_label}.")


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
    status = "🟢 Risolta" if request["status"] == "resolved" else "🟡 Aperta"

    embed = discord.Embed(
        title=f"📋  Log Richiesta Staff  •  {request['id']}",
        color=config.COLORS["log"],
        timestamp=datetime.utcnow(),
    )
    embed.add_field(name="Team", value=config.TEAM_LABEL[request["team"]], inline=True)
    embed.add_field(name="Priorità", value=f"{p_emoji} {priorita.upper()}", inline=True)
    embed.add_field(name="Stato", value=status, inline=True)
    embed.add_field(name="Richiedente", value=requester.mention if requester else str(request["requester_id"]), inline=True)
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

import asyncio


class StaffRequestCog(commands.Cog):
    def __init__(self, bot: commands.Bot):
        self.bot = bot

    @app_commands.command(
        name="richiesta-staff",
        description="Chiama il team di moderazione o amministrazione nel ticket"
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

        # Controlla che l'utente abbia un ruolo autorizzato
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

        view = TeamSelectView()
        await interaction.response.send_message(
            "Seleziona il team che vuoi chiamare:",
            view=view,
            ephemeral=True,
        )

    @app_commands.command(
        name="richieste-aperte",
        description="Mostra tutte le richieste staff ancora aperte"
    )
    @app_commands.default_permissions(manage_messages=True)
    async def richieste_aperte(self, interaction: discord.Interaction):
        open_reqs = db.get_open_requests()
        if not open_reqs:
            await interaction.response.send_message("✅ Nessuna richiesta aperta al momento.", ephemeral=True)
            return

        embed = discord.Embed(
            title="📋  Richieste Staff Aperte",
            color=config.COLORS["default"],
            timestamp=datetime.utcnow(),
        )
        for req in open_reqs[:10]:  # Max 10
            p_emoji = config.PRIORITY_EMOJI.get(req["priority"], "⚪")
            t_emoji = config.TEAM_EMOJI.get(req["team"], "👥")
            channel = interaction.guild.get_channel(req["channel_id"])
            ch_mention = channel.mention if channel else f"#{req['channel_id']}"
            created = datetime.fromisoformat(req["created_at"])
            elapsed = round((datetime.utcnow() - created).total_seconds() / 60, 1)
            embed.add_field(
                name=f"{p_emoji} {req['id']}  —  {t_emoji} {config.TEAM_LABEL[req['team']]}",
                value=f"{ch_mention}  •  {req['reason'][:80]}...\n⏱️ Aperta da **{elapsed} min**",
                inline=False,
            )
        embed.set_footer(text=f"Oblivion Network  •  {len(open_reqs)} richieste aperte")
        await interaction.response.send_message(embed=embed, ephemeral=True)


async def setup(bot: commands.Bot):
    await bot.add_cog(StaffRequestCog(bot))
    log.info("StaffRequestCog caricato.")
