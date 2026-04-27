"""
Простое JSON-хранилище избранных стихов.
Формат файла favorites.json:
{
  "123456789": ["Иоанна 3:16", "Римлянам 8:28"]
}
"""

from __future__ import annotations

import json
import os
from tempfile import NamedTemporaryFile
from typing import Dict, List

FAVORITES_FILE = os.getenv("FAVORITES_FILE", "favorites.json")
MAX_FAVORITES_PER_CHAT = 50


def _load_data() -> Dict[str, List[str]]:
    if not os.path.exists(FAVORITES_FILE):
        return {}

    try:
        with open(FAVORITES_FILE, "r", encoding="utf-8") as f:
            data = json.load(f)
        if isinstance(data, dict):
            normalized = {}
            for key, value in data.items():
                if isinstance(value, list):
                    normalized[str(key)] = [str(v) for v in value]
            return normalized
    except (json.JSONDecodeError, OSError, ValueError):
        return {}

    return {}


def _atomic_save(data: Dict[str, List[str]]) -> None:
    directory = os.path.dirname(os.path.abspath(FAVORITES_FILE)) or "."
    os.makedirs(directory, exist_ok=True)

    with NamedTemporaryFile("w", encoding="utf-8", delete=False, dir=directory) as tmp:
        json.dump(data, tmp, ensure_ascii=False, indent=2)
        tmp.flush()
        os.fsync(tmp.fileno())
        tmp_name = tmp.name

    os.replace(tmp_name, FAVORITES_FILE)


def add_favorite(chat_id: int, verse_ref: str) -> bool:
    data = _load_data()
    key = str(chat_id)
    favorites = data.get(key, [])

    if verse_ref in favorites:
        return False

    favorites.append(verse_ref)
    data[key] = favorites[-MAX_FAVORITES_PER_CHAT:]
    _atomic_save(data)
    return True


def get_favorites(chat_id: int) -> List[str]:
    data = _load_data()
    return data.get(str(chat_id), [])


def remove_favorite(chat_id: int, verse_ref: str) -> bool:
    data = _load_data()
    key = str(chat_id)
    favorites = data.get(key, [])

    if verse_ref not in favorites:
        return False

    favorites.remove(verse_ref)
    data[key] = favorites
    _atomic_save(data)
    return True
