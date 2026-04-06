"""
database.py — Gestione persistente delle statistiche e richieste
Usa JSON come storage leggero. Sostituibile con SQLite/PostgreSQL.
"""

import json
import os
import asyncio
from datetime import datetime, date
from typing import Optional

DB_PATH = "data/requests.json"


def _load() -> dict:
    os.makedirs("data", exist_ok=True)
    if not os.path.exists(DB_PATH):
        return {
            "counter": 0,
            "requests": {},
            "stats": {
                "total": 0,
                "resolved_today": 0,
                "last_reset": str(date.today()),
                "response_times": []
            }
        }
    with open(DB_PATH, "r", encoding="utf-8") as f:
        return json.load(f)


def _save(data: dict):
    os.makedirs("data", exist_ok=True)
    with open(DB_PATH, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=2, ensure_ascii=False)


def _check_daily_reset(data: dict) -> dict:
    """Resetta i contatori giornalieri se è un nuovo giorno."""
    today = str(date.today())
    if data["stats"].get("last_reset") != today:
        data["stats"]["resolved_today"] = 0
        data["stats"]["last_reset"] = today
    return data


def new_request(team: str, priority: str, reason: str, notes: str,
                requester_id: int, channel_id: int, guild_id: int) -> dict:
    """Crea una nuova richiesta e restituisce i dati salvati."""
    data = _load()
    data = _check_daily_reset(data)
    data["counter"] += 1
    data["stats"]["total"] += 1

    req_id = f"REQ-{data['counter']:04d}"
    request = {
        "id": req_id,
        "team": team,
        "priority": priority,
        "reason": reason,
        "notes": notes,
        "requester_id": requester_id,
        "channel_id": channel_id,
        "guild_id": guild_id,
        "created_at": datetime.utcnow().isoformat(),
        "resolved_at": None,
        "resolved_by": None,
        "status": "open",
        "message_id": None,
    }
    data["requests"][req_id] = request
    _save(data)
    return request


def update_message_id(req_id: str, message_id: int):
    data = _load()
    if req_id in data["requests"]:
        data["requests"][req_id]["message_id"] = message_id
        _save(data)


def resolve_request(req_id: str, resolved_by_id: int) -> Optional[dict]:
    data = _load()
    data = _check_daily_reset(data)
    if req_id not in data["requests"]:
        return None
    req = data["requests"][req_id]
    if req["status"] == "resolved":
        return None

    created = datetime.fromisoformat(req["created_at"])
    now = datetime.utcnow()
    elapsed = (now - created).total_seconds() / 60  # minuti

    req["resolved_at"] = now.isoformat()
    req["resolved_by"] = resolved_by_id
    req["status"] = "resolved"
    data["stats"]["resolved_today"] += 1
    data["stats"]["response_times"].append(round(elapsed, 1))
    # Mantieni solo ultimi 50 tempi per la media
    data["stats"]["response_times"] = data["stats"]["response_times"][-50:]
    _save(data)
    return req


def get_stats() -> dict:
    data = _load()
    data = _check_daily_reset(data)
    times = data["stats"]["response_times"]
    avg_time = round(sum(times) / len(times), 1) if times else 0

    open_requests = sum(
        1 for r in data["requests"].values() if r["status"] == "open"
    )
    return {
        "total": data["stats"]["total"],
        "resolved_today": data["stats"]["resolved_today"],
        "open": open_requests,
        "avg_response_min": avg_time,
        "counter": data["counter"],
    }


def get_request(req_id: str) -> Optional[dict]:
    data = _load()
    return data["requests"].get(req_id)


def get_open_requests() -> list:
    data = _load()
    return [r for r in data["requests"].values() if r["status"] == "open"]
