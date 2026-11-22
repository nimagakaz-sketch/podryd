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

# Настройка логирования
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - [%(levelname)s] - %(name)s - %(message)s",
    handlers=[
        logging.StreamHandler(sys.stdout),
    ],
)
logger = logging.getLogger("podryd_bot")


async def _health_handler(request: web.Request) -> web.Response:
    """Ответ на health check для Render Web Service."""
    return web.Response(text="OK - Podryd Bot is running", status=200)


async def start_health_server(port: int) -> web.AppRunner:
    """Запуск встроенного HTTP-сервера для бесплатного тарифа Render Web Service."""
    app = web.Application()
    app.router.add_get("/", _health_handler)
    app.router.add_get("/health", _health_handler)
    runner = web.AppRunner(app)
    await runner.setup()
    site = web.TCPSite(runner, "0.0.0.0", port)
    await site.start()
    logger.info("Health-check HTTP сервер успешно запущен на 0.0.0.0:%d (Render Web Service)", port)
    return runner


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

    # Запуск встроенного веб-сервера для Render Web Service (если передан PORT)
    http_runner = None
    port_env = os.getenv("PORT", "").strip()
    if port_env and port_env.isdigit():
        http_runner = await start_health_server(int(port_env))

    # Запуск polling
    try:
        await bot.delete_webhook(drop_pending_updates=True)
        await dp.start_polling(bot)
    finally:
        if http_runner:
            await http_runner.cleanup()
            logger.info("Health-check HTTP сервер остановлен.")
        await database.close_db()
        await bot.session.close()
        logger.info("Сессия бота и соединение с БД закрыты.")


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except (KeyboardInterrupt, SystemExit):
        logger.info("Бот остановлен пользователем.")
