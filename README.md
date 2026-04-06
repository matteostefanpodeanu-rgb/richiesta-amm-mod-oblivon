# Oblivion Network — Staff Request Bot

Bot Discord per la gestione delle richieste staff nei ticket.

---

## Installazione

### 1. Requisiti
- Python 3.10 o superiore
- pip

### 2. Installa le dipendenze

```bash
pip install -r requirements.txt
```

### 3. Configura il bot

**A) Crea il bot su Discord Developer Portal**
1. Vai su https://discord.com/developers/applications
2. Crea una nuova applicazione
3. Vai su **Bot** → abilita questi intents:
   - `SERVER MEMBERS INTENT`
   - `MESSAGE CONTENT INTENT`
4. Copia il **Token**

**B) Crea il file `.env`**

Apri `.env` e incolla il token:
```
DISCORD_TOKEN=il_tuo_token_qui
```

**C) Configura `config.py`**

Apri `config.py` e imposta:
- `ROLE_MODERAZIONE` — ID del ruolo Moderazione
- `ROLE_AMMINISTRAZIONE` — ID del ruolo Amministrazione
- `ALLOWED_ROLES` — ID dei ruoli che possono usare `/richiesta-staff`
- `LOG_CHANNEL_ID` — ID del canale log (opzionale, metti `0` per disabilitare)
- `TICKET_PREFIXES` — Prefissi dei nomi dei canali ticket (default: `ticket`, `supporto`, ecc.)

**Come copiare un ID Discord:**
Attiva la **Modalità Sviluppatore** in Impostazioni → Avanzate → Modalità sviluppatore.
Poi tasto destro su qualsiasi ruolo/canale/utente → Copia ID.

### 4. Invita il bot nel server

Genera il link di invito dal Developer Portal con questi permessi:
- `Send Messages`
- `Embed Links`
- `Mention @everyone, @here and All Roles`
- `Use Slash Commands`
- `Read Message History`
- `Manage Messages` (per eliminare i ping automatici)

### 5. Avvia il bot

```bash
python bot.py
```

---

## Comandi disponibili

| Comando | Descrizione | Permesso richiesto |
|---|---|---|
| `/richiesta-staff` | Apre il pannello per chiamare Mod o Admin | Ruoli in `ALLOWED_ROLES` |
| `/richieste-aperte` | Lista tutte le richieste ancora aperte | Gestione messaggi |
| `/statistiche-staff` | Statistiche generali del sistema | Gestione messaggi |

---

## Funzionamento

1. Lo staff usa `/richiesta-staff` all'interno di un canale ticket
2. Seleziona il team (**Moderazione** o **Amministrazione**) dal menu
3. Compila il modal: **priorità**, **motivo**, **note aggiuntive**
4. Nel ticket appare l'embed permanente con:
   - Tutti i dati della richiesta
   - Statistiche in tempo reale (tempo medio risposta, richieste aperte, risolte oggi)
   - Bottoni **Segna come risolto** e **Annulla richiesta**
5. Il ruolo viene **pingato nel canale** (il ping si auto-elimina dopo 10 secondi)
6. Ogni membro del team riceve un **DM** con link diretto al ticket
7. Tutto viene **loggato** nel canale dedicato

---

## Struttura file

```
oblivion_bot/
├── bot.py              ← Entrypoint principale
├── config.py           ← Configurazione (ID ruoli, colori, ecc.)
├── database.py         ← Gestione dati (JSON)
├── requirements.txt
├── .env                ← Token bot (NON condividere!)
├── cogs/
│   ├── staff_request.py  ← Logica principale
│   └── stats.py          ← Comando statistiche
└── data/
    └── requests.json     ← Creato automaticamente
```

---

## Note

- Il file `data/requests.json` viene creato automaticamente al primo avvio
- I log del bot vengono salvati in `bot.log`
- I bottoni sull'embed sono persistenti (funzionano anche dopo un riavvio del bot)
