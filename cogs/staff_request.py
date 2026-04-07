"""
cogs/staff_request.py
Oblivion Network — Sistema Richieste Amministrazione
"""

import asyncio
import logging
from datetime import datetime, timezone

import discord
from discord import app_commands
from discord.ext import commands

import config
import database as db

log = logging.getLogger("OblivionBot.StaffRequest")

SEP = "┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄"


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _fmt_elapsed(minutes: float) -> str:
    if minutes < 1:
        return "< 1 min"
    if minutes < 60:
        return f"{int(minutes)} min"
    h = int(minutes // 60)
    m = int(minutes % 60)
    return f"{h}h {m}m" if m else f"{h}h"


def _priority_bar(priority: str) -> str:
    bars = {
        "urgente": "█████  URGENTE",
        "alta":    "████░  ALTA",
        "media":   "███░░  MEDIA",
        "bassa":   "██░░░  BASSA",
    }
    return bars.get(priority, "███░░  MEDIA")


# ══════════════════════════════════════════════════════════════════════════════
#  MODAL
# ══════════════════════════════════════════════════════════════════════════════

class StaffRequestModal(discord.ui.Modal, title="⚜️  Richiesta Amministrazione"):
    def __init__(self):
        super().__init__(timeout=config.MODAL_TIMEOUT)

    priorita = discord.ui.TextInput(
        label="Livello di priorità",
        placeholder="urgente  /  alta  /  media  /  bassa",
        max_length=10,
        required=True,
        style=discord.TextStyle.short,
    )
    motivo = discord.ui.TextInput(
        label="Motivo della richiesta",
        placeholder="Descrivi in modo chiaro e completo il motivo per cui è necessario l'intervento dell'Amministrazione.",
        max_length=500,
        required=True,
        style=discord.TextStyle.paragraph,
    )
    note = discord.ui.TextInput(
        label="Contesto aggiuntivo  (opzionale)",
        placeholder="Cronologia eventi, tentativi già effettuati, link rilevanti, nomi coinvolti...",
        max_length=400,
        required=False,
        style=discord.TextStyle.paragraph,
    )

    async def on_submit(self, interaction: discord.Interaction):
        await interaction.response.defer(ephemeral=True)

        raw = self.priorita.value.strip().lower()
        priorita = raw if raw in ("urgente", "alta", "media", "bassa") else "media"
        motivo = self.motivo.value.strip()
        note = self.note.value.strip() or None

        request = db.new_request(
            team="amministrazione",
            priority=priorita,
            reason=motivo,
            notes=note or "—",
            requester_id=interaction.user.id,
            channel_id=interaction.channel.id,
            guild_id=interaction.guild.id,
        )

        stats = db.get_stats()
        embed = _build_open_embed(request, interaction.user, interaction.channel, stats)
        view = RequestView(req_id=request["id"])
        msg = await interaction.channel.send(embed=embed, view=view)
        db.update_message_id(request["id"], msg.id)

        await interaction.followup.send(
            f"✅  Richiesta **{request['id']}** inviata.\n"
            f"L'Amministrazione è stata avvisata via DM e verrà al più presto.",
            ephemeral=True,
        )

        role = interaction.guild.get_role(config.ROLE_AMMINISTRAZIONE)
        if role:
            async def _silent_ping():
                try:
                    pm = await interaction.channel.send(
                        f"{role.mention}",
                        allowed_mentions=discord.AllowedMentions(roles=True),
                    )
                    await asyncio.sleep(0)
                    await pm.delete()
                except Exception:
                    pass
            asyncio.create_task(_silent_ping())

        await _send_dms(interaction.guild, request, interaction.user, interaction.channel)
        await _send_log(interaction.client, interaction.guild, request,
                        interaction.user, interaction.channel)

    async def on_error(self, interaction: discord.Interaction, error: Exception):
        log.error("Errore modal StaffRequest", exc_info=True)
        msg = "❌ Si è verificato un errore imprevisto. Riprova o contatta un amministratore."
        if interaction.response.is_done():
            await interaction.followup.send(msg, ephemeral=True)
        else:
            await interaction.response.send_message(msg, ephemeral=True)


# ══════════════════════════════════════════════════════════════════════════════
#  VIEW
# ══════════════════════════════════════════════════════════════════════════════

class RequestView(discord.ui.View):
    def __init__(self, req_id: str):
        super().__init__(timeout=None)
        self.req_id = req_id

    @discord.ui.button(
        label="Segna come risolta",
        emoji="✅",
        style=discord.ButtonStyle.success,
        custom_id="oblivion:resolve",
        row=0,
    )
    async def btn_resolve(self, interaction: discord.Interaction, button: discord.ui.Button):
        request = db.get_request(self.req_id)
        if not request:
            return await interaction.response.send_message("❌ Richiesta non trovata.", ephemeral=True)
        if request["status"] != "open":
            return await interaction.response.send_message("⚠️  Questa richiesta non è più aperta.", ephemeral=True)

        resolved = db.resolve_request(self.req_id, interaction.user.id)
        if not resolved:
            return await interaction.response.send_message("❌ Impossibile aggiornare la richiesta.", ephemeral=True)

        stats = db.get_stats()
        requester = interaction.guild.get_member(resolved["requester_id"])
        embed = _build_resolved_embed(resolved, requester, interaction.user, interaction.channel, stats)

        _disable_all(self)
        button.label = "Risolta"
        await interaction.message.edit(embed=embed, view=self)
        await interaction.response.send_message(
            f"✅  Richiesta **{self.req_id}** segnata come risolta da {interaction.user.mention}.",
        )
        await _send_log(interaction.client, interaction.guild, resolved,
                        requester, interaction.channel, resolved_by=interaction.user)

    @discord.ui.button(
        label="Prendi in carico",
        emoji="🔰",
        style=discord.ButtonStyle.primary,
        custom_id="oblivion:claim",
        row=0,
    )
    async def btn_claim(self, interaction: discord.Interaction, button: discord.ui.Button):
        request = db.get_request(self.req_id)
        if not request:
            return await interaction.response.send_message("❌ Richiesta non trovata.", ephemeral=True)
        if request["status"] != "open":
            return await interaction.response.send_message("⚠️  Questa richiesta non è più aperta.", ephemeral=True)

        user_role_ids = [r.id for r in interaction.user.roles]
        if (config.ROLE_AMMINISTRAZIONE not in user_role_ids
                and not interaction.user.guild_permissions.administrator):
            return await interaction.response.send_message(
                "❌ Solo i membri dell'Amministrazione possono prendere in carico le richieste.",
                ephemeral=True,
            )

        embed = interaction.message.embeds[0]
        embed = _patch_embed_claimed(embed, interaction.user)
        button.disabled = True
        button.label = f"In carico: {interaction.user.display_name}"
        await interaction.message.edit(embed=embed, view=self)
        await interaction.response.send_message(
            f"🔰  {interaction.user.mention} ha preso in carico la richiesta **{self.req_id}**.",
        )

    @discord.ui.button(
        label="Annulla",
        emoji="🗑️",
        style=discord.ButtonStyle.danger,
        custom_id="oblivion:cancel",
        row=0,
    )
    async def btn_cancel(self, interaction: discord.Interaction, button: discord.ui.Button):
        request = db.get_request(self.req_id)
        if not request:
            return await interaction.response.send_message("❌ Richiesta non trovata.", ephemeral=True)
        if request["status"] != "open":
            return await interaction.response.send_message("⚠️  Questa richiesta non è più aperta.", ephemeral=True)

        is_requester = interaction.user.id == request["requester_id"]
        is_admin = interaction.user.guild_permissions.administrator
        if not (is_requester or is_admin):
            return await interaction.response.send_message(
                "❌ Solo il richiedente o un amministratore può annullare la richiesta.",
                ephemeral=True,
            )

        db.resolve_request(self.req_id, interaction.user.id)
        embed = interaction.message.embeds[0]
        embed = _patch_embed_cancelled(embed, interaction.user)
        _disable_all(self)
        await interaction.message.edit(embed=embed, view=self)
        await interaction.response.send_message(
            f"🗑️  Richiesta **{self.req_id}** annullata da {interaction.user.mention}.",
        )


def _disable_all(view: discord.ui.View):
    for child in view.children:
        child.disabled = True


# ══════════════════════════════════════════════════════════════════════════════
#  EMBED BUILDERS
# ══════════════════════════════════════════════════════════════════════════════

def _build_open_embed(request, requester, channel, stats) -> discord.Embed:
    priorita = request["priority"]
    p_emoji = config.PRIORITY_EMOJI.get(priorita, "⚪")
    colore = config.COLORS.get(priorita, config.COLORS["default"])
    avg = _fmt_elapsed(stats["avg_response_min"]) if stats["avg_response_min"] > 0 else "N/D"
    now_str = _now().strftime("%d/%m/%Y  %H:%M UTC")

    embed = discord.Embed(color=colore, timestamp=_now())
    embed.set_author(
        name="OBLIVION NETWORK  ·  Sistema Richieste Staff",
        icon_url=channel.guild.icon.url if channel.guild.icon else None,
    )
    embed.add_field(
        name="⚜️  RICHIESTA AMMINISTRAZIONE",
        value=(
            f"{requester.mention} ha aperto una richiesta all'Amministrazione.\n"
            f"Il team è stato avvisato e raggiungerà il ticket a breve.\n"
            f"{SEP}"
        ),
        inline=False,
    )
    embed.add_field(
        name="LIVELLO DI PRIORITÀ",
        value=f"{p_emoji}  `{_priority_bar(priorita)}`",
        inline=False,
    )
    embed.add_field(name="👤  Richiedente", value=requester.mention, inline=True)
    embed.add_field(name="🎫  Ticket", value=channel.mention, inline=True)
    embed.add_field(name="🆔  ID Richiesta", value=f"`{request['id']}`", inline=True)
    embed.add_field(name="🕐  Aperta il", value=now_str, inline=True)
    embed.add_field(name="📌  Stato", value="🟡  In attesa", inline=True)
    embed.add_field(name="🔰  In carico a", value="—", inline=True)
    embed.add_field(name=SEP, value="", inline=False)
    embed.add_field(
        name="📋  MOTIVO DELLA RICHIESTA",
        value=f"```{request['reason'][:450]}```",
        inline=False,
    )
    if request.get("notes") and request["notes"] != "—":
        embed.add_field(
            name="📝  CONTESTO AGGIUNTIVO",
            value=f"```{request['notes'][:350]}```",
            inline=False,
        )
    embed.add_field(name=SEP, value="", inline=False)
    embed.add_field(
        name="📊  STATISTICHE SISTEMA",
        value=(
            f"⏱️  Tempo medio risposta  **{avg}**\n"
            f"🟡  Richieste aperte  **{stats['open']}**\n"
            f"✅  Risolte oggi  **{stats['resolved_today']}**\n"
            f"📬  Totale storico  **{stats['total']}**"
        ),
        inline=False,
    )
    embed.set_thumbnail(url=requester.display_avatar.url if requester.display_avatar else None)
    embed.set_footer(text=f"Oblivion Network  ·  {request['id']}  ·  In attesa di risposta")
    return embed


def _build_resolved_embed(request, requester, resolver, channel, stats) -> discord.Embed:
    priorita = request["priority"]
    p_emoji = config.PRIORITY_EMOJI.get(priorita, "⚪")
    avg = _fmt_elapsed(stats["avg_response_min"]) if stats["avg_response_min"] > 0 else "N/D"

    resolved_at = datetime.fromisoformat(request["resolved_at"]) if request.get("resolved_at") else _now()
    created_at = datetime.fromisoformat(request["created_at"])
    elapsed = _fmt_elapsed((resolved_at - created_at).total_seconds() / 60)
    resolved_str = resolved_at.strftime("%d/%m/%Y  %H:%M UTC")

    embed = discord.Embed(color=config.COLORS["resolved"], timestamp=resolved_at)
    embed.set_author(
        name="OBLIVION NETWORK  ·  Sistema Richieste Staff",
        icon_url=channel.guild.icon.url if channel.guild.icon else None,
    )
    embed.add_field(
        name="✅  RICHIESTA RISOLTA — AMMINISTRAZIONE",
        value=(
            f"La richiesta è stata gestita da {resolver.mention}.\n"
            f"Tempo di risposta:  **{elapsed}**\n"
            f"{SEP}"
        ),
        inline=False,
    )
    embed.add_field(name=f"{p_emoji}  Priorità", value=f"**{priorita.upper()}**", inline=True)
    embed.add_field(name="✅  Gestita da", value=resolver.mention, inline=True)
    embed.add_field(name="🕐  Risolta il", value=resolved_str, inline=True)
    embed.add_field(name="👤  Richiedente", value=requester.mention if requester else "Sconosciuto", inline=True)
    embed.add_field(name="🎫  Ticket", value=channel.mention, inline=True)
    embed.add_field(name="🆔  ID", value=f"`{request['id']}`", inline=True)
    embed.add_field(name=SEP, value="", inline=False)
    embed.add_field(
        name="📋  MOTIVO ORIGINALE",
        value=f"```{request['reason'][:450]}```",
        inline=False,
    )
    embed.add_field(name=SEP, value="", inline=False)
    embed.add_field(
        name="📊  STATISTICHE SISTEMA",
        value=(
            f"⏱️  Tempo medio risposta  **{avg}**\n"
            f"✅  Risolte oggi  **{stats['resolved_today']}**\n"
            f"📬  Totale storico  **{stats['total']}**"
        ),
        inline=False,
    )
    embed.set_footer(text=f"Oblivion Network  ·  {request['id']}  ·  RISOLTA")
    return embed


def _patch_embed_claimed(embed: discord.Embed, claimer: discord.Member) -> discord.Embed:
    for i, field in enumerate(embed.fields):
        if "In carico a" in field.name:
            embed.set_field_at(i, name=field.name, value=claimer.mention, inline=field.inline)
        if "Stato" in field.name:
            embed.set_field_at(i, name=field.name, value="🔵  In gestione", inline=field.inline)
    return embed


def _patch_embed_cancelled(embed: discord.Embed, canceller: discord.Member) -> discord.Embed:
    embed.color = discord.Color.from_rgb(90, 90, 100)
    for i, field in enumerate(embed.fields):
        if "Stato" in field.name:
            embed.set_field_at(i, name=field.name, value="⛔  Annullata", inline=field.inline)
    old = embed.footer.text or ""
    embed.set_footer(text=old.replace("In attesa di risposta", "ANNULLATA"))
    return embed


# ══════════════════════════════════════════════════════════════════════════════
#  DM
# ══════════════════════════════════════════════════════════════════════════════

async def _send_dms(guild, request, requester, channel):
    role = guild.get_role(config.ROLE_AMMINISTRAZIONE)
    if not role:
        log.warning(f"Ruolo Amministrazione (ID {config.ROLE_AMMINISTRAZIONE}) non trovato.")
        return

    priorita = request["priority"]
    p_emoji = config.PRIORITY_EMOJI.get(priorita, "⚪")
    colore = config.COLORS.get(priorita, config.COLORS["default"])
    ticket_url = f"https://discord.com/channels/{guild.id}/{channel.id}"
    now_str = _now().strftime("%d/%m/%Y  %H:%M UTC")

    embed = discord.Embed(color=colore, timestamp=_now())
    embed.set_author(
        name="OBLIVION NETWORK  ·  Richiesta Staff",
        icon_url=guild.icon.url if guild.icon else None,
    )
    embed.add_field(
        name="📬  SEI STATO CHIAMATO IN UN TICKET",
        value=(
            f"Un membro dello staff richiede la presenza dell'**Amministrazione**.\n"
            f"Server: **{guild.name}**  ·  Canale: **#{channel.name}**\n"
            f"{SEP}"
        ),
        inline=False,
    )
    embed.add_field(
        name="PRIORITÀ",
        value=f"{p_emoji}  `{_priority_bar(priorita)}`",
        inline=False,
    )
    embed.add_field(name="👤  Richiedente", value=requester.display_name, inline=True)
    embed.add_field(name="🕐  Orario", value=now_str, inline=True)
    embed.add_field(name="🆔  ID", value=f"`{request['id']}`", inline=True)
    embed.add_field(name=SEP, value="", inline=False)
    embed.add_field(
        name="📋  MOTIVO",
        value=f"```{request['reason'][:400]}```",
        inline=False,
    )
    if request.get("notes") and request["notes"] != "—":
        embed.add_field(
            name="📝  CONTESTO",
            value=f"```{request['notes'][:300]}```",
            inline=False,
        )
    embed.add_field(
        name="🔗  ACCEDI AL TICKET",
        value=f"[**→ Apri il ticket su Discord**]({ticket_url})",
        inline=False,
    )
    embed.set_thumbnail(url=requester.display_avatar.url if requester.display_avatar else None)
    embed.set_footer(text=f"Oblivion Network  ·  {request['id']}  ·  Messaggio automatico")

    view = discord.ui.View()
    view.add_item(discord.ui.Button(
        label="Vai al ticket",
        emoji="🔗",
        style=discord.ButtonStyle.link,
        url=ticket_url,
    ))

    sent, failed = 0, 0
    for member in role.members:
        if member.bot:
            continue
        try:
            await member.send(embed=embed, view=view)
            sent += 1
        except discord.Forbidden:
            failed += 1
        except Exception as e:
            log.warning(f"DM fallito per {member}: {e}")
            failed += 1

    log.info(f"DM Amministrazione — {sent} inviati, {failed} falliti.")


# ══════════════════════════════════════════════════════════════════════════════
#  LOG
# ══════════════════════════════════════════════════════════════════════════════

async def _send_log(bot, guild, request, requester, channel, resolved_by=None):
    if not config.LOG_CHANNEL_ID:
        return
    log_ch = guild.get_channel(config.LOG_CHANNEL_ID)
    if not log_ch:
        return

    priorita = request["priority"]
    p_emoji = config.PRIORITY_EMOJI.get(priorita, "⚪")
    is_resolved = request["status"] == "resolved"
    status_str = "✅  Risolta" if is_resolved else "🟡  Aperta"
    colore = config.COLORS["resolved"] if is_resolved else config.COLORS.get(priorita, config.COLORS["default"])

    embed = discord.Embed(
        title=f"📋  Log Richiesta  ·  {request['id']}",
        color=colore,
        timestamp=_now(),
    )
    embed.set_author(
        name="OBLIVION NETWORK  ·  Staff Request Log",
        icon_url=guild.icon.url if guild.icon else None,
    )
    embed.add_field(name="Stato", value=status_str, inline=True)
    embed.add_field(name="Priorità", value=f"{p_emoji}  {priorita.upper()}", inline=True)
    embed.add_field(
        name="Richiedente",
        value=requester.mention if requester else f"`{request['requester_id']}`",
        inline=True,
    )
    embed.add_field(name="Ticket", value=channel.mention, inline=True)
    if resolved_by:
        embed.add_field(name="Gestita da", value=resolved_by.mention, inline=True)
    if request.get("resolved_at") and request.get("created_at"):
        elapsed = _fmt_elapsed(
            (datetime.fromisoformat(request["resolved_at"])
             - datetime.fromisoformat(request["created_at"])).total_seconds() / 60
        )
        embed.add_field(name="⏱️  Tempo risposta", value=elapsed, inline=True)
    embed.add_field(
        name="Motivo",
        value=f"```{request['reason'][:400]}```",
        inline=False,
    )
    embed.set_footer(text="Oblivion Network  ·  Staff Request Log")
    try:
        await log_ch.send(embed=embed)
    except Exception as e:
        log.warning(f"Impossibile inviare al canale log: {e}")


# ══════════════════════════════════════════════════════════════════════════════
#  COG
# ══════════════════════════════════════════════════════════════════════════════

class StaffRequestCog(commands.Cog):
    def __init__(self, bot: commands.Bot):
        self.bot = bot

    @app_commands.command(
        name="richiesta-staff",
        description="Apri una richiesta al team Amministrazione nel ticket corrente",
    )
    async def richiesta_staff(self, interaction: discord.Interaction):
        if not any(interaction.channel.name.lower().startswith(p)
                   for p in config.TICKET_PREFIXES):
            return await interaction.response.send_message(
                "❌  Questo comando è disponibile **solo nei canali ticket**.",
                ephemeral=True,
            )
        user_role_ids = {r.id for r in interaction.user.roles}
        if (not user_role_ids.intersection(config.ALLOWED_ROLES)
                and not interaction.user.guild_permissions.administrator):
            return await interaction.response.send_message(
                "❌  Non hai i permessi necessari per usare questo comando.",
                ephemeral=True,
            )
        await interaction.response.send_modal(StaffRequestModal())

    @app_commands.command(
        name="richieste-aperte",
        description="Visualizza tutte le richieste Amministrazione ancora aperte",
    )
    @app_commands.default_permissions(manage_messages=True)
    async def richieste_aperte(self, interaction: discord.Interaction):
        open_reqs = db.get_open_requests()
        if not open_reqs:
            return await interaction.response.send_message(
                "✅  Nessuna richiesta aperta al momento.", ephemeral=True
            )

        priority_order = {"urgente": 0, "alta": 1, "media": 2, "bassa": 3}
        open_reqs.sort(key=lambda r: priority_order.get(r["priority"], 9))

        embed = discord.Embed(
            title="📋  Richieste Amministrazione — In Attesa",
            color=config.COLORS["default"],
            timestamp=_now(),
        )
        embed.set_author(
            name="OBLIVION NETWORK  ·  Pannello Staff",
            icon_url=interaction.guild.icon.url if interaction.guild.icon else None,
        )
        for req in open_reqs[:10]:
            p_emoji = config.PRIORITY_EMOJI.get(req["priority"], "⚪")
            ch = interaction.guild.get_channel(req["channel_id"])
            ch_str = ch.mention if ch else f"`#{req['channel_id']}`"
            created = datetime.fromisoformat(req["created_at"])
            elapsed = _fmt_elapsed((_now() - created).total_seconds() / 60)
            short_reason = req["reason"][:90] + ("…" if len(req["reason"]) > 90 else "")
            embed.add_field(
                name=f"{p_emoji}  {req['id']}  ·  {req['priority'].upper()}",
                value=(
                    f"**Ticket:** {ch_str}\n"
                    f"**Motivo:** {short_reason}\n"
                    f"**Aperta da:** {elapsed}"
                ),
                inline=False,
            )
        if len(open_reqs) > 10:
            embed.add_field(name="", value=f"*... e altre {len(open_reqs) - 10} richieste.*", inline=False)
        embed.set_footer(text=f"Oblivion Network  ·  {len(open_reqs)} richieste aperte")
        await interaction.response.send_message(embed=embed, ephemeral=True)

    @app_commands.command(
        name="statistiche-staff",
        description="Statistiche complete del sistema richieste staff",
    )
    @app_commands.default_permissions(manage_messages=True)
    async def statistiche_staff(self, interaction: discord.Interaction):
        stats = db.get_stats()
        avg = _fmt_elapsed(stats["avg_response_min"]) if stats["avg_response_min"] > 0 else "N/D"

        embed = discord.Embed(
            title="📊  Statistiche — Sistema Richieste Staff",
            color=config.COLORS["default"],
            timestamp=_now(),
        )
        embed.set_author(
            name="OBLIVION NETWORK  ·  Pannello Admin",
            icon_url=interaction.guild.icon.url if interaction.guild.icon else None,
        )
        embed.set_thumbnail(url=interaction.guild.icon.url if interaction.guild.icon else None)
        embed.add_field(name="🟡  Aperte ora", value=f"**{stats['open']}**", inline=True)
        embed.add_field(name="✅  Risolte oggi", value=f"**{stats['resolved_today']}**", inline=True)
        embed.add_field(name="📬  Totale storico", value=f"**{stats['total']}**", inline=True)
        embed.add_field(name="⏱️  Tempo medio risposta", value=f"**{avg}**", inline=True)
        embed.set_footer(text="Oblivion Network  ·  Staff Request Stats")
        await interaction.response.send_message(embed=embed)


async def setup(bot: commands.Bot):
    await bot.add_cog(StaffRequestCog(bot))
    log.info("StaffRequestCog caricato.")
