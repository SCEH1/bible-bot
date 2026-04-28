                reply_markup=get_verse_actions_keyboard()
            )
        except Exception as e:
            logger.error(f"Ошибка edit: {e}")

    elif call.data == "fav_save":
        verse = last_verse.get(chat_id)
        verse_ref = extract_verse_ref(verse)

        if not verse_ref:
            bot.send_message(chat_id, "❌ Не удалось определить стих для сохранения.")
            return

        if add_favorite(chat_id, verse_ref):
            bot.send_message(chat_id, f"⭐ Стих сохранён: <b>{verse_ref}</b>", parse_mode='HTML')
        else:
            bot.send_message(chat_id, f"ℹ️ Уже в избранном: <b>{verse_ref}</b>", parse_mode='HTML')

    elif call.data == "choose_theme":
        if not VERSE_THEMES:
            bot.send_message(chat_id, "⚠️ Темы пока не настроены в bible_data.py", reply_markup=get_main_keyboard())
            return
        bot.send_message(
            chat_id,
            "📚 <b>Выбери тему:</b>",
            parse_mode='HTML',
            reply_markup=get_theme_keyboard()
        )

    elif call.data.startswith("theme:"):
        try:
            idx = int(call.data.split(":", 1)[1]) - 1
        except ValueError:
            bot.send_message(chat_id, "❌ Не удалось определить тему")
            return

        theme_name = get_theme_name_by_idx(idx)
        if not theme_name:
            bot.send_message(chat_id, "❌ Тема не найдена")
            return

        verse = get_random_verse_from_theme(theme_name)
        if not verse:
            bot.send_message(chat_id, f"⚠️ В теме «{theme_name}» нет валидных стихов", reply_markup=get_main_keyboard())
            return

        last_verse[chat_id] = verse
        markup = types.InlineKeyboardMarkup()
        markup.row(types.InlineKeyboardButton("🔍 Разобрать", callback_data="parse"))
        markup.row(types.InlineKeyboardButton("⭐ Сохранить стих", callback_data="fav_save"))
        markup.row(types.InlineKeyboardButton("🎲 Ещё стих", callback_data=f"theme:{idx + 1}"))
        markup.row(types.InlineKeyboardButton("📚 Выбрать тему", callback_data="choose_theme"))

        bot.send_message(
            chat_id,
            f"📚 <b>{html.escape(theme_name)}</b>\n\n{format_verse_card(verse, icon='📖')}",
            parse_mode='HTML',
            reply_markup=markup
        )

    elif call.data == "parse":
        if chat_id in last_verse:
            on_cooldown, remaining = is_on_cooldown(chat_id)
            if on_cooldown:
                bot.send_message(
                    chat_id,
                    f"⏳ Подожди {remaining} сек. перед следующим разбором.",
                    reply_markup=get_main_keyboard()
                )
                return

            mark_request(chat_id)
            threading.Thread(target=parse_in_background, args=(chat_id, last_verse[chat_id]), daemon=True).start()
        else:
            bot.send_message(chat_id, "❌ Стих не найден. Нажми <b>📖 Стих дня</b>", parse_mode='HTML')

    elif call.data.startswith("fav_parse:"):
        try:
            idx = int(call.data.split(":", 1)[1]) - 1
        except ValueError:
            bot.send_message(chat_id, "❌ Неверный номер избранного стиха.")
            return

        favorites = get_favorites(chat_id)
        if idx < 0 or idx >= len(favorites):
            bot.send_message(chat_id, "❌ Избранный стих не найден.")
            return

        verse_ref = favorites[idx]
        verse_text = POPULAR_VERSES.get(verse_ref)
        if not verse_text:
            bot.send_message(chat_id, f"⚠️ В базе нет текста для <b>{verse_ref}</b>.", parse_mode='HTML')
            return

        last_verse[chat_id] = f"{verse_ref}\n\n{verse_text}"
        on_cooldown, remaining = is_on_cooldown(chat_id)
        if on_cooldown:
            bot.send_message(chat_id, f"⏳ Подожди {remaining} сек. перед следующим разбором.")
            return

        mark_request(chat_id)
        threading.Thread(target=parse_in_background, args=(chat_id, last_verse[chat_id]), daemon=True).start()

    elif call.data.startswith("fav_del:"):
        try:
            idx = int(call.data.split(":", 1)[1]) - 1
        except ValueError:
            bot.send_message(chat_id, "❌ Неверный номер избранного стиха.")
            return

        favorites = get_favorites(chat_id)
        if idx < 0 or idx >= len(favorites):
            bot.send_message(chat_id, "❌ Избранный стих не найден.")
            return

        verse_ref = favorites[idx]
        removed = remove_favorite(chat_id, verse_ref)
        if removed:
            bot.send_message(chat_id, f"🗑 Удалено из избранного: <b>{verse_ref}</b>", parse_mode='HTML')
        else:
            bot.send_message(chat_id, "ℹ️ Этот стих уже удалён.")

        send_favorites_list(chat_id)


# ================= FLASK WEBHOOK =================

if __name__ == "__main__":
    app = Flask(__name__)

    @app.route("/" + TG_TOKEN, methods=["POST"])
    def webhook():
        try:
            json_str = request.get_data().decode("UTF-8")
            update = telebot.types.Update.de_json(json_str)

            if update.update_id in processed_updates:
                return "", 200

            processed_updates.append(update.update_id)
            bot.process_new_updates([update])
            return "", 200

        except Exception as e:
            logger.error(f"Webhook error: {e}")
            return "", 500

    @app.route("/")
    def index():
        return "🕊 Bible Bot v2.0 - Ready!", 200

    bot.remove_webhook()
    WEBHOOK_URL = f"https://bible-bot-ssx4.onrender.com/{TG_TOKEN}"
    bot.set_webhook(url=WEBHOOK_URL)
    logger.info(f"🚀 Webhook: {WEBHOOK_URL}")
    logger.info(f"📚 База: {len(POPULAR_VERSES)} стихов | Тем: {len(VERSE_THEMES)}")

    app.run(host="0.0.0.0", port=int(os.environ.get("PORT", 8080)))
storage.py
