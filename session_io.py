"""Speichern und Laden von Sitzungsdaten (Profile + Produkte)."""

from __future__ import annotations

import dataclasses
import json
import os
from datetime import datetime

from engine import Profil

DATA_DIR = "data"


def save_session(
    name: str,
    profil1: Profil,
    profil2: Profil | None,
    veranlagung: str,
    produkte: list[dict],
) -> str:
    os.makedirs(DATA_DIR, exist_ok=True)
    safe = "".join(c for c in name if c.isalnum() or c in "-_")
    path = os.path.join(DATA_DIR, f"save_{safe}.json")
    payload = {
        "saved_at": datetime.now().isoformat(timespec="minutes"),
        "profil1": dataclasses.asdict(profil1),
        "profil2": dataclasses.asdict(profil2) if profil2 else None,
        "veranlagung": veranlagung,
        "produkte": produkte,
    }
    with open(path, "w", encoding="utf-8") as f:
        json.dump(payload, f, ensure_ascii=False, indent=2)
    return path


def load_session(path: str) -> dict:
    with open(path, encoding="utf-8") as f:
        data = json.load(f)
    data["profil1"] = Profil(**data["profil1"])
    if data.get("profil2"):
        data["profil2"] = Profil(**data["profil2"])
    return data


def list_saves() -> list[tuple[str, str]]:
    """Gibt [(Anzeigename, Dateipfad), ...] zurück, neueste zuerst."""
    if not os.path.exists(DATA_DIR):
        return []
    result = []
    for fname in sorted(os.listdir(DATA_DIR), reverse=True):
        if fname.startswith("save_") and fname.endswith(".json"):
            display = fname[5:-5]
            result.append((display, os.path.join(DATA_DIR, fname)))
    return result
