"""
config.py — Configurazione del bot Oblivion Network
Modifica questi valori con gli ID del tuo server.
"""

# ─────────────────────────────────────────
#  ID RUOLI (copia da Discord: tasto destro sul ruolo → Copia ID)
# ─────────────────────────────────────────
ROLE_AMMINISTRAZIONE = 000000000000000000   # ID ruolo Amministrazione

# Ruoli che possono usare /richiesta-staff
ALLOWED_ROLES = [
    000000000000000000,  # Helper
    000000000000000000,  # Supporto
    000000000000000000,  # Moderatore
    # Aggiungi altri ruoli staff
]

# ─────────────────────────────────────────
#  CANALE LOG (opzionale — metti 0 per disabilitare)
# ─────────────────────────────────────────
LOG_CHANNEL_ID = 0   # ID del canale dove loggare le richieste

# ─────────────────────────────────────────
#  PREFISSO NOME CANALI TICKET
#  Il bot controlla che il canale inizi con uno di questi prefissi
# ─────────────────────────────────────────
TICKET_PREFIXES = ["ticket", "supporto", "aiuto", "help"]

# ─────────────────────────────────────────
#  COLORI EMBED — tonalità viola per priorità
# ─────────────────────────────────────────
COLORS = {
    "urgente": 0x4a0080,   # viola intenso/scuro
    "alta":    0x6b21a8,   # viola medio-scuro
    "media":   0x7c3ec4,   # viola standard
    "bassa":   0xa78bca,   # viola tenue/chiaro
    "default": 0x7c3ec4,
    "resolved":0x7c3ec4,
    "log":     0x6b21a8,
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
    "amministrazione": "⚜️",
}

TEAM_LABEL = {
    "amministrazione": "Amministrazione",
}

# ─────────────────────────────────────────
#  TIMEOUT modal (secondi)
# ─────────────────────────────────────────
MODAL_TIMEOUT = 180
