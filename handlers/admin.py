"""Обработчики команд администратора, парсера и выгрузки базы."""

import asyncio
import logging
import os
from aiogram import Bot, F, Router
from aiogram.filters import Command
from aiogram.types import CallbackQuery, FSInputFile, Message

import config
import database
import excel_export
import keyboards
from web_parser import collector

logger = logging.getLogger(__name__)

router = Router(name="admin_router")


def is_admin(user_id: int) -> bool:
    """Проверяет, является ли пользователь администратором."""
    return user_id in config.ADMIN_IDS


async def _run_parser_task(bot: Bot, admin_id: int) -> None:
    """Фоновая задача выполнения веб-парсера с уведомлением администратора."""
    try:
        result = await collector.run()
        added = result.get("added", 0)
        updated = result.get("updated", 0)
        total_p = result.get("total_processed", 0)

        stats = await database.get_stats()
        text = (
            "✅ <b>Веб-парсер успешно завершил сбор!</b>\n\n"
            f"📥 <b>Новых записей добавлено:</b> {added}\n"
            f"🔄 <b>Существующих обновлено:</b> {updated}\n"
            f"🌐 <b>Обработано доменов/сайтов:</b> {total_p}\n\n"
            f"📊 <b>Всего записей в базе:</b> {stats['total_count']}\n"
            f"📞 <b>С номерами телефонов:</b> {stats['with_phone']}\n"
            f"🌐 <b>С сайтами:</b> {stats['with_website']}\n\n"
            "Нажмите <b>«📊 Скачать базу в Excel»</b> в /admin, чтобы выгрузить обновленную базу с делением по листам!"
        )
        await bot.send_message(
            chat_id=admin_id,
            text=text,
            reply_markup=keyboards.get_admin_keyboard(is_collector_running=False),
        )
    except Exception as e:
        logger.error("Ошибка в фоновой задаче парсера: %s", e)
        try:
            await bot.send_message(
                chat_id=admin_id,
                text=f"⚠️ Произошла ошибка при выполнении парсера: {e}",
            )
        except Exception:
            pass


@router.message(Command("admin"))
async def cmd_admin(message: Message) -> None:
    """Обработчик команды /admin."""
    if not is_admin(message.from_user.id):
        await message.answer("⛔ <b>Доступ запрещен.</b> Эта команда только для администраторов.")
        return

    stats = await database.get_stats()
    text = (
        "👑 <b>Панель администратора</b>\n\n"
        "Управление базой B2B-подрядчиков по благоустройству, детским площадкам, заборам и МАФам.\n\n"
        f"📊 <b>Всего записей в базе:</b> {stats['total_count']}\n"
        f"📞 <b>С номерами телефонов:</b> {stats['with_phone']}\n"
        f"🌐 <b>С сайтами/ссылками:</b> {stats['with_website']}\n"
        f"⏳ <b>Добавлено за последние 24 часа:</b> {stats['last_24h_count']}\n\n"
        "Выберите действие:"
    )
    await message.answer(
        text=text,
        reply_markup=keyboards.get_admin_keyboard(is_collector_running=collector.is_running),
    )


@router.callback_query(F.data == "admin_refresh")
async def callback_admin_refresh(callback: CallbackQuery) -> None:
    """Обновление главного экрана админки."""
    if not is_admin(callback.from_user.id):
        await callback.answer("⛔ Доступ запрещен", show_alert=True)
        return

    stats = await database.get_stats()
    text = (
        "👑 <b>Панель администратора</b>\n\n"
        "Управление базой B2B-подрядчиков по благоустройству, детским площадкам, заборам и МАФам.\n\n"
        f"📊 <b>Всего записей в базе:</b> {stats['total_count']}\n"
        f"📞 <b>С номерами телефонов:</b> {stats['with_phone']}\n"
        f"🌐 <b>С сайтами/ссылками:</b> {stats['with_website']}\n"
        f"⏳ <b>Добавлено за последние 24 часа:</b> {stats['last_24h_count']}\n\n"
        "Выберите действие:"
    )
    if callback.message:
        await callback.message.edit_text(
            text=text,
            reply_markup=keyboards.get_admin_keyboard(is_collector_running=collector.is_running),
        )
    await callback.answer("Данные обновлены")


@router.callback_query(F.data == "admin_start_parser")
async def callback_admin_start_parser(callback: CallbackQuery) -> None:
    """Запуск асинхронного веб-парсера."""
    if not is_admin(callback.from_user.id):
        await callback.answer("⛔ Доступ запрещен", show_alert=True)
        return

    if collector.is_running:
        await callback.answer("⚠️ Сборщик уже запущен и работает!", show_alert=True)
        return

    await callback.answer("Запускаю сборщик...")

    # Запускаем фоновую задачу
    asyncio.create_task(_run_parser_task(callback.bot, callback.from_user.id))

    if callback.message:
        await callback.message.edit_text(
            "🚀 <b>Сборщик подрядчиков успешно запущен в фоне!</b>\n\n"
            "Парсер обходит поисковые запросы по благоустройству, паркам, детским площадкам, "
            "заборам и МАФам по всем целевым регионам, извлекает контакты, телефоны и тегирует организации.\n\n"
            "⏳ <i>Вы можете продолжить пользоваться ботом — по окончании сбора вам придет уведомление.</i>",
            reply_markup=keyboards.get_admin_keyboard(is_collector_running=True),
        )


@router.callback_query(F.data == "admin_stats")
async def callback_admin_stats(callback: CallbackQuery) -> None:
    """Показ подробной статистики."""
    if not is_admin(callback.from_user.id):
        await callback.answer("⛔ Доступ запрещен", show_alert=True)
        return

    stats = await database.get_stats()
    sources = stats.get("sources", {})
    categories = stats.get("categories", {})

    form_count = sources.get("form", 0)
    web_count = sources.get("web_parser", 0)

    cats_text = "\n".join([f"  • {k}: <b>{v}</b>" for k, v in categories.items()])

    text = (
        "📈 <b>Подробная статистика собранной базы:</b>\n\n"
        f"👥 <b>Всего записей в базе:</b> {stats['total_count']}\n"
        f"📞 <b>С номерами телефонов:</b> {stats['with_phone']}\n"
        f"🌐 <b>С сайтами / ссылками:</b> {stats['with_website']}\n"
        f"⏱ <b>Добавлено за 24 часа:</b> {stats['last_24h_count']}\n\n"
        "<b>Источники поступления:</b>\n"
        f"  • 📋 Анкета Telegram-бота: <b>{form_count}</b>\n"
        f"  • 🌐 Автоматический веб-парсер: <b>{web_count}</b>\n\n"
        "<b>По ключевым направлениям:</b>\n"
        f"{cats_text}\n"
    )
    if callback.message:
        await callback.message.edit_text(
            text=text,
            reply_markup=keyboards.get_back_to_admin_keyboard(),
        )
    await callback.answer()


@router.callback_query(F.data == "admin_export_excel")
async def callback_admin_export_excel(callback: CallbackQuery) -> None:
    """Генерация многолистового Excel-файла с базой и отправка администратору."""
    if not is_admin(callback.from_user.id):
        await callback.answer("⛔ Доступ запрещен", show_alert=True)
        return

    await callback.answer("Формирую отчет по листам...")

    contractors = await database.get_all_contractors()
    if not contractors:
        if callback.message:
            await callback.message.answer(
                "ℹ️ <b>База пока пуста.</b> Запустите «🌐 Запустить сбор» или дождитесь заявок из анкеты.",
                reply_markup=keyboards.get_back_to_admin_keyboard(),
            )
        return

    excel_path = None
    try:
        # Генерируем многолистовой Excel-файл
        excel_path = excel_export.export_contractors_to_excel(contractors)

        doc = FSInputFile(
            path=excel_path,
            filename=f"База_Подрядчики_Благоустройство_{len(contractors)}_записей.xlsx",
        )
        if callback.message:
            caption_text = (
                f"📊 <b>Умная выгрузка базы B2B-подрядчиков</b>\n\n"
                f"Всего записей: <b>{len(contractors)}</b> шт.\n\n"
                "📁 <b>Файл разделен по 6 листам:</b>\n"
                "1. 📑 <b>Все данные</b> — полная выгрузка без отсева\n"
                "2. 📞 <b>С телефоном</b> — база с контактами для обзвона\n"
                "3. 🌐 <b>С сайтом</b> — компании с веб-ресурсами\n"
                "4. 🎠 <b>Площадки и парки</b> — детские городки, парки, детсады\n"
                "5. 🛡️ <b>Заборы и МАФ</b> — ограждения, скамейки, урны\n"
                "6. 📋 <b>Анкета бота</b> — прямые заявки из Telegram-бота"
            )
            await callback.message.answer_document(
                document=doc,
                caption=caption_text,
            )
    except Exception as e:
        logger.error("Ошибка при генерации/отправке Excel: %s", e)
        if callback.message:
            await callback.message.answer(f"❌ Произошла ошибка при экспорте: {e}")
    finally:
        # Удаляем временный файл с диска
        if excel_path and os.path.exists(excel_path):
            try:
                os.remove(excel_path)
                logger.info("Временный файл экспорта %s успешно удален", excel_path)
            except OSError as err:
                logger.warning("Не удалось удалить временный файл %s: %s", excel_path, err)
