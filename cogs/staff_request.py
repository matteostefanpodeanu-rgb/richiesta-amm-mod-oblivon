"""
cogs/staff_request.py — Sistema richieste Amministrazione
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

        # Legge i ruoli admin dal DB
        admin_role_ids = db.get_admin_roles()
        if not admin_role_ids:
            await interaction.followup.send(
                "❌ Nessun ruolo Amministrazione configurato.\n"
                "Un amministratore deve usare `/set-ruoli-amministrazione` prima.",
                ephemeral=True,
            )
            return

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

        # DM a tutti i membri dei ruoli admin
        await send_dms(
            guild=interaction.guild,
            admin_role_ids=admin_role_ids,
            request=request,
            requester=interaction.user,
            channel=interaction.channel,
        )

        # Ping tutti i ruoli admin → eliminato subito in background
        async def ping_and_delete():
            try:
                mentions = " ".join(
                    interaction.guild.get_role(rid).mention
                    for rid in admin_role_ids
                    if interaction.guild.get_role(rid)
                )
                if mentions:
                    ping_msg = await interaction.channel.send(
                        mentions,
                        allowed_mentions=discord.AllowedMentions(roles=True),
                    )
                    await asyncio.sleep(0)
                    await ping_msg.delete()
            except Exception:
                pass
        asyncio.create_task(ping_and_delete())

        # Log su canale dedicato
        await send_log(
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
            await interaction.response.send_message("⚠️ Già risolta.", ephemeral=True)
            return

        resolved = db.resolve_request(self.req_id, interaction.user.id)
        if not resolved:
            await interaction.response.send_message("❌ Impossibile risolvere.", ephemeral=True)
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
                "❌ Solo il richiedente o un amministratore può annullare.", ephemeral=True
            )
            return
        if request["status"] == "resolved":
            await interaction.response.send_message("⚠️ Già risolta.", ephemeral=True)
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
#  EMBED — Richiesta aperta
# ─────────────────────────────────────────

def build_request_embed(request, requester, channel, stats) -> discord.Embed:
    priorita = request["priority"]
    p_emoji = config.PRIORITY_EMOJI.get(priorita, "⚪")
    colore = config.COLORS.get(priorita, config.COLORS["default"])
    avg = f"{stats['avg_response_min']} min" if stats["avg_response_min"] > 0 else "N/D"

    embed = discord.Embed(
        title="⚜️  Richiesta al Team Amministrazione",
        description=(
            f"{requester.mention} ha aperto una richiesta al team di **Amministrazione**.\n"
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

    embed.add_field(name="📋  Motivo", value=f"> {request['reason']}", inline=False)
    if request.get("notes") and request["notes"] != "Nessuna nota aggiuntiva.":
        embed.add_field(name="📝  Note", value=f"> {request['notes']}", inline=False)

    embed.add_field(
        name="📊  Statistiche sistema",
        value=(
            f"⏱️ Tempo medio risposta: **{avg}**  •  "
            f"🟡 Aperte: **{stats['open']}**  •  "
            f"✅ Risolte oggi: **{stats['resolved_today']}**"
        ),
        inline=False,
    )
    embed.set_footer(text=f"Oblivion Network  •  {request['id']}  •  In attesa di risposta")
    return embed


# ─────────────────────────────────────────
#  EMBED — Richiesta risolta
# ─────────────────────────────────────────

def build_resolved_embed(request, requester, resolver, channel, stats) -> discord.Embed:
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
        value=f"⏱️ Tempo medio risposta: **{avg}**  •  ✅ Risolte oggi: **{stats['resolved_today']}**",
        inline=False,
    )
    embed.set_footer(text=f"Oblivion Network  •  {request['id']}  •  RISOLTA")
    return embed


# ─────────────────────────────────────────
#  DM a tutti i membri dei ruoli admin
# ─────────────────────────────────────────

async def send_dms(guild, admin_role_ids, request, requester, channel):
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
    dm_embed.set_footer(text=f"Oblivion Network  •  {request['id']}  •  Messaggio automatico")

    # Raccoglie tutti i membri unici da tutti i ruoli admin
    members_to_notify = set()
    for role_id in admin_role_ids:
        role = guild.get_role(role_id)
        if not role:
            log.warning(f"Ruolo admin ID {role_id} non trovato nel server.")
            continue
        for member in role.members:
            if not member.bot:
                members_to_notify.add(member)

    sent = 0
    failed = 0
    for member in members_to_notify:
        try:
            await member.send(embed=dm_embed)
            sent += 1
            log.info(f"DM inviato a {member.name}")
        except discord.Forbidden:
            log.warning(f"DM bloccato da {member.name} (privacy attiva)")
            failed += 1
        except Exception as e:
            log.warning(f"Impossibile inviare DM a {member.name}: {e}")
            failed += 1

    log.info(f"DM Amministrazione: {sent} inviati, {failed} falliti.")


# ─────────────────────────────────────────
#  LOG su canale dedicato
# ─────────────────────────────────────────

async def send_log(guild, request, requester, channel, resolved_by=None):
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
#  HELPER — embed configurazione
# ─────────────────────────────────────────

def build_config_embed(title, description, guild, current_roles, max_roles=10) -> discord.Embed:
    embed = discord.Embed(
        title=title,
        description=description,
        color=config.COLORS["default"],
        timestamp=datetime.utcnow(),
    )
    embed.add_field(name="📋  Ruoli configurati", value=f"{len(current_roles)}/{max_roles}", inline=True)
    embed.set_footer(text="Oblivion Network — Configurazione")
    return embed


# ─────────────────────────────────────────
#  COG
# ─────────────────────────────────────────

class StaffRequestCog(commands.Cog):
    def __init__(self, bot: commands.Bot):
        self.bot = bot

    # ── /richiesta-amministrazione ──────────────────────────
    @app_commands.command(
        name="richiesta-amministrazione",
        description="Chiama il team Amministrazione nel ticket"
    )
    async def richiesta_amministrazione(self, interaction: discord.Interaction):
        channel_name = interaction.channel.name.lower()
        is_ticket = any(channel_name.startswith(p) for p in config.TICKET_PREFIXES)
        if not is_ticket:
            await interaction.response.send_message(
                "❌ Questo comando può essere usato **solo nei canali ticket**.",
                ephemeral=True,
            )
            return

        allowed = db.get_allowed_roles()
        user_roles = [r.id for r in interaction.user.roles]
        is_allowed = (
            any(r in user_roles for r in allowed)
            or interaction.user.guild_permissions.administrator
        )
        if not is_allowed:
            await interaction.response.send_message(
                "❌ Non hai i permessi per usare questo comando.",
                ephemeral=True,
            )
            return

        modal = StaffRequestModal()
        await interaction.response.send_modal(modal)

    # ── /set-ruoli-amministrazione ───────────────────────────
    @app_commands.command(
        name="set-ruoli-amministrazione",
        description="[ADMIN] Gestisci i ruoli Amministrazione che ricevono le notifiche (max 10)"
    )
    @app_commands.default_permissions(administrator=True)
    @app_commands.describe(
        azione="aggiungi, rimuovi o visualizza i ruoli",
        ruolo="Il ruolo da aggiungere o rimuovere"
    )
    @app_commands.choices(azione=[
        app_commands.Choice(name="➕ Aggiungi ruolo", value="add"),
        app_commands.Choice(name="➖ Rimuovi ruolo", value="remove"),
        app_commands.Choice(name="📋 Visualizza lista", value="list"),
    ])
    async def set_ruoli_amministrazione(
        self,
        interaction: discord.Interaction,
        azione: str,
        ruolo: discord.Role = None,
    ):
        current = db.get_admin_roles()

        if azione == "list":
            if not current:
                desc = "Nessun ruolo configurato. Usa **➕ Aggiungi ruolo** per aggiungerne."
            else:
                desc = "\n".join(
                    f"• {interaction.guild.get_role(r).mention if interaction.guild.get_role(r) else f'`{r}` (eliminato)'}"
                    for r in current
                )
            embed = build_config_embed(
                title=f"⚜️  Ruoli Amministrazione ({len(current)}/10)",
                description=desc,
                guild=interaction.guild,
                current_roles=current,
            )
            await interaction.response.send_message(embed=embed, ephemeral=True)
            return

        if ruolo is None:
            await interaction.response.send_message("❌ Specifica un ruolo.", ephemeral=True)
            return

        if azione == "add":
            if len(current) >= 10:
                await interaction.response.send_message(
                    "❌ Hai raggiunto il limite di **10 ruoli**. Rimuovine uno prima.",
                    ephemeral=True,
                )
                return
            ok = db.add_admin_role(ruolo.id)
            if not ok:
                await interaction.response.send_message(
                    f"⚠️ {ruolo.mention} è già nella lista.", ephemeral=True
                )
                return
            current = db.get_admin_roles()
            membri = len([m for m in ruolo.members if not m.bot])
            embed = build_config_embed(
                title="✅  Ruolo Amministrazione aggiunto",
                description=f"{ruolo.mention} riceverà ora le notifiche DM delle richieste.\n👥 Membri notificati: **{membri}**",
                guild=interaction.guild,
                current_roles=current,
            )
            await interaction.response.send_message(embed=embed, ephemeral=True)
            log.info(f"Admin role aggiunto: {ruolo.name} ({ruolo.id})")

        elif azione == "remove":
            ok = db.remove_admin_role(ruolo.id)
            if not ok:
                await interaction.response.send_message(
                    f"⚠️ {ruolo.mention} non è nella lista.", ephemeral=True
                )
                return
            current = db.get_admin_roles()
            embed = build_config_embed(
                title="🗑️  Ruolo Amministrazione rimosso",
                description=f"{ruolo.mention} non riceverà più le notifiche DM.",
                guild=interaction.guild,
                current_roles=current,
            )
            await interaction.response.send_message(embed=embed, ephemeral=True)
            log.info(f"Admin role rimosso: {ruolo.name} ({ruolo.id})")

    # ── /set-ruoli-autorizzati ───────────────────────────────
    @app_commands.command(
        name="set-ruoli-autorizzati",
        description="[ADMIN] Gestisci i ruoli che possono usare /richiesta-amministrazione (max 10)"
    )
    @app_commands.default_permissions(administrator=True)
    @app_commands.describe(
        azione="aggiungi, rimuovi o visualizza i ruoli",
        ruolo="Il ruolo da aggiungere o rimuovere"
    )
    @app_commands.choices(azione=[
        app_commands.Choice(name="➕ Aggiungi ruolo", value="add"),
        app_commands.Choice(name="➖ Rimuovi ruolo", value="remove"),
        app_commands.Choice(name="📋 Visualizza lista", value="list"),
    ])
    async def set_ruoli_autorizzati(
        self,
        interaction: discord.Interaction,
        azione: str,
        ruolo: discord.Role = None,
    ):
        current = db.get_allowed_roles()

        if azione == "list":
            if not current:
                desc = "Nessun ruolo autorizzato. Usa **➕ Aggiungi ruolo** per aggiungerne."
            else:
                desc = "\n".join(
                    f"• {interaction.guild.get_role(r).mention if interaction.guild.get_role(r) else f'`{r}` (eliminato)'}"
                    for r in current
                )
            embed = build_config_embed(
                title=f"🛡️  Ruoli autorizzati ({len(current)}/10)",
                description=desc,
                guild=interaction.guild,
                current_roles=current,
            )
            await interaction.response.send_message(embed=embed, ephemeral=True)
            return

        if ruolo is None:
            await interaction.response.send_message("❌ Specifica un ruolo.", ephemeral=True)
            return

        if azione == "add":
            if len(current) >= 10:
                await interaction.response.send_message(
                    "❌ Hai raggiunto il limite di **10 ruoli**. Rimuovine uno prima.",
                    ephemeral=True,
                )
                return
            ok = db.add_allowed_role(ruolo.id)
            if not ok:
                await interaction.response.send_message(
                    f"⚠️ {ruolo.mention} è già nella lista.", ephemeral=True
                )
                return
            current = db.get_allowed_roles()
            embed = build_config_embed(
                title="✅  Ruolo autorizzato aggiunto",
                description=f"{ruolo.mention} può ora usare `/richiesta-amministrazione`.",
                guild=interaction.guild,
                current_roles=current,
            )
            await interaction.response.send_message(embed=embed, ephemeral=True)

        elif azione == "remove":
            ok = db.remove_allowed_role(ruolo.id)
            if not ok:
                await interaction.response.send_message(
                    f"⚠️ {ruolo.mention} non è nella lista.", ephemeral=True
                )
                return
            current = db.get_allowed_roles()
            embed = build_config_embed(
                title="🗑️  Ruolo autorizzato rimosso",
                description=f"{ruolo.mention} non può più usare `/richiesta-amministrazione`.",
                guild=interaction.guild,
                current_roles=current,
            )
            await interaction.response.send_message(embed=embed, ephemeral=True)

    # ── /richieste-aperte ────────────────────────────────────
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

    # ── /statistiche-staff ───────────────────────────────────
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
