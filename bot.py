"""Главный файл запуска Telegram-бота."""

import asyncio
import logging
import os
import sys
from aiohttp import web
from aiogram import Bot, Dispatcher
from aiogram.client.default import DefaultBotProperties
from aiogram.enums import ParseMode
from aiogram.fsm.storage.memory import MemoryStorage
from aiogram.types import BotCommand, BotCommandScopeDefault

import config
import database
from handlers import admin, user
import webapp_server

# Настройка логирования
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - [%(levelname)s] - %(name)s - %(message)s",
    handlers=[
        logging.StreamHandler(sys.stdout),
    ],
)
logger = logging.getLogger("podryd_bot")


async def set_bot_commands(bot: Bot) -> None:
    """Установка команд бота в меню Telegram."""
    commands = [
        BotCommand(command="start", description="🚀 Запустить бота / Получить прайс"),
        BotCommand(command="cancel", description="❌ Отменить текущее действие"),
        BotCommand(command="admin", description="👑 Панель администратора"),
    ]
    await bot.set_my_commands(commands=commands, scope=BotCommandScopeDefault())


async def main() -> None:
    """Точка входа: инициализация и запуск polling."""
    logger.info("Запуск бота...")

    # Инициализация базы данных (PostgreSQL или SQLite)
    await database.init_db()
    if config.DATABASE_URL:
        logger.info("База данных PostgreSQL успешно инициализирована.")
    else:
        logger.info("База данных SQLite успешно инициализирована: %s", config.DB_PATH)

    # Инициализация бота с HTML-разметкой по умолчанию
    bot = Bot(
        token=config.BOT_TOKEN,
        default=DefaultBotProperties(parse_mode=ParseMode.HTML),
    )

    dp = Dispatcher(storage=MemoryStorage())

    # Регистрация роутеров (админский первым, чтобы перехватывать админские команды)
    dp.include_router(admin.router)
    dp.include_router(user.router)

    # Настройка команд в меню
    await set_bot_commands(bot)

    # Получаем информацию о боте
    bot_info = await bot.get_me()
    logger.info("Бот @%s (ID: %s) успешно авторизован!", bot_info.username, bot_info.id)
    logger.info("Список ID администраторов: %s", config.ADMIN_IDS)

    # Запуск встроенного веб-сервера для Render Web Service и Telegram Mini App
    http_runner = None
    port_env = os.getenv("PORT", "8000").strip()
    port = int(port_env) if port_env.isdigit() else 8000
    try:
        http_runner = await webapp_server.start_webapp_server(port)
        logger.info("Mini App & Web сервер успешно запущен на порту %d", port)
    except Exception as e:
        logger.error("Ошибка при запуске Mini App веб-сервера на порту %d: %s", port, e)
        http_runner = None

    # Запуск polling
    try:
        await bot.delete_webhook(drop_pending_updates=True)
        await dp.start_polling(bot)
    finally:
        if http_runner:
            await http_runner.cleanup()
            logger.info("Mini App HTTP сервер остановлен.")
        await database.close_db()
        await bot.session.close()
        logger.info("Сессия бота и соединение с БД закрыты.")


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except (KeyboardInterrupt, SystemExit):
        logger.info("Бот остановлен пользователем.")
