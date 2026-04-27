import json
import os
import threading
from datetime import datetime

DATA_FILE = "favorites.json"
lock = threading.Lock()

def load_data():
    if not os.path.exists(DATA_FILE):
        return {}
    try:
        with open(DATA_FILE, 'r', encoding='utf-8') as f:
            return json.load(f)
    except (json.JSONDecodeError, IOError):
        return {}

def save_data(data):
    # Атомарная запись через временный файл
    temp_file = f"{DATA_FILE}.tmp"
    with open(temp_file, 'w', encoding='utf-8') as f:
        json.dump(data, f, ensure_ascii=False, indent=2)
    os.replace(temp_file, DATA_FILE)

def add_favorite(user_id: int, verse_text: str, reference: str):
    with lock:
        data = load_data()
        if str(user_id) not in data:
            data[str(user_id)] = []
        
        # Проверка на дубликат
        for item in data[str(user_id)]:
            if item['reference'] == reference:
                return False # Уже есть
        
        entry = {
            "reference": reference,
            "text": verse_text,
            "added_at": datetime.now().isoformat()
        }
        data[str(user_id)].append(entry)
        save_data(data)
        return True

def get_favorites(user_id: int):
    with lock:
        data = load_data()
        return data.get(str(user_id), [])

def remove_favorite(user_id: int, reference: str):
    with lock:
        data = load_data()
        if str(user_id) not in data:
            return False
        
        initial_len = len(data[str(user_id)])
        data[str(user_id)] = [
            item for item in data[str(user_id)] if item['reference'] != reference
        ]
        
        if len(data[str(user_id)]) < initial_len:
            save_data(data)
            return True
        return False
