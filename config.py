"""
config.py — Configurazione del bot Oblivion Network
Modifica questi valori con gli ID del tuo server.
"""

# ─────────────────────────────────────────
#  ID RUOLI (copia da Discord: tasto destro sul ruolo → Copia ID)
# ─────────────────────────────────────────
ROLE_MODERAZIONE = 1490702856888647781   # ID ruolo Moderazione
ROLE_AMMINISTRAZIONE = 1490702923146072147   # ID ruolo Amministrazione

# Ruoli che possono usare /richiesta-staff
ALLOWED_ROLES = [
    1490703252528959498,  # Staff
    # Aggiungi altri ruoli staff
]

# ─────────────────────────────────────────
#  CANALE LOG (opzionale — metti 0 per disabilitare)
# ─────────────────────────────────────────
LOG_CHANNEL_ID = 1490705146899075174   # ID del canale dove loggare le richieste

# ─────────────────────────────────────────
#  PREFISSO NOME CANALI TICKET
#  Il bot controlla che il canale inizi con uno di questi prefissi
# ─────────────────────────────────────────
TICKET_PREFIXES = ["ticket", "supporto", "aiuto", "help"]

# ─────────────────────────────────────────
#  COLORI EMBED (formato 0xRRGGBB)
# ─────────────────────────────────────────
COLORS = {
    "urgente": 0xe53935,
    "alta":    0xfb8c00,
    "media":   0xfdd835,
    "bassa":   0x43a047,
    "default": 0x7c3ec4,
    "resolved":0x5865f2,
    "log":     0x7c3ec4,
}

# ─────────────────────────────────────────
#  EMOJI
# ─────────────────────────────────────────
PRIORITY_EMOJI = {
    "urgente": "🔴",
    "alta":    "🟠",
    "media":   "🟡",
    "bassa":   "🟢",
}

TEAM_EMOJI = {
    "moderazione":    "🛡️",
    "amministrazione": "⚜️",
}

TEAM_LABEL = {
    "moderazione":    "Moderazione",
    "amministrazione": "Amministrazione",
}

# ─────────────────────────────────────────
#  TIMEOUT modal (secondi)
# ─────────────────────────────────────────
MODAL_TIMEOUT = 180
