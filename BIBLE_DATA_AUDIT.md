# Проверка `VERSE_THEMES` и `POPULAR_VERSES` (3 минуты)

Этот мини-аудит нужен, чтобы не ловить ошибки вида:
- тема выбрана, а стих не находится;
- в теме ссылка `Ин. 3:16`, а в базе ключ `Иоанна 3:16`.

## Что важно

Ключи в `VERSE_THEMES` должны совпадать с ключами в `POPULAR_VERSES` **символ в символ**.

Пример:
- ✅ `"Иоанна 3:16"` есть в `POPULAR_VERSES`
- ❌ `"Ин. 3:16"`, если в базе хранится `"Иоанна 3:16"`

## Быстрая проверка скриптом

Сохрани этот код как `check_themes.py` рядом с `bible_data.py` и запусти `python check_themes.py`.

```python
from bible_data import POPULAR_VERSES, VERSE_THEMES

all_refs = set(POPULAR_VERSES.keys())
missing = []

for theme, refs in VERSE_THEMES.items():
    for ref in refs:
        if ref not in all_refs:
            missing.append((theme, ref))

if not missing:
    print("OK: все ссылки из VERSE_THEMES существуют в POPULAR_VERSES")
else:
    print("Найдены несовпадения:")
    for theme, ref in missing:
        print(f"- {theme}: {ref}")
```

## Что делать, если есть несовпадения

1. Открой `bible_data.py`.
2. Найди проблемный референс из отчёта.
3. Приведи формат к тому, как он хранится в `POPULAR_VERSES`.
4. Повтори запуск проверки.

## Рекомендуемый единый формат

Чтобы не путаться, выбери один стиль и используй везде:
- полные названия книг: `Иоанна 3:16`, `Римлянам 8:28`;
- одинаковые разделители глав/стихов (`:`);
- одинаковые префиксы для 1/2/3 посланий.
