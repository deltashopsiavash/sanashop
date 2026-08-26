#!/usr/bin/env python3
import logging
import os

from telegram.ext import Application, CallbackQueryHandler, CommandHandler, MessageHandler, filters

import bot


logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")


def build_application(token: str) -> Application:
    proxy_url = (os.environ.get("TELEGRAM_PROXY_URL") or "").strip()
    builder = Application.builder().token(token)

    if proxy_url:
        # PTB uses a separate HTTPXRequest for normal Bot API calls and getUpdates.
        # Configure both explicitly so polling and send/upload requests go through
        # the foreign proxy even when the host itself cannot reach Telegram.
        builder = builder.proxy(proxy_url).get_updates_proxy(proxy_url)
        logging.info("Telegram proxy is enabled")
    else:
        logging.warning("TELEGRAM_PROXY_URL is empty; Telegram will be contacted directly")

    return builder.build()


def run():
    token = os.environ.get("TELEGRAM_BOT_TOKEN")
    if not token:
        raise SystemExit("TELEGRAM_BOT_TOKEN is required")

    app = build_application(token)
    app.add_handler(CommandHandler("start", bot.start))
    app.add_handler(CommandHandler("skip", bot.skip))
    app.add_handler(CallbackQueryHandler(bot.callback))
    app.add_handler(MessageHandler(filters.PHOTO, bot.photo))
    app.add_handler(MessageHandler(filters.Document.ALL, bot.document))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, bot.message))
    app.run_polling(drop_pending_updates=True)


if __name__ == "__main__":
    run()
