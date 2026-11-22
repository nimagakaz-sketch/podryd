"""Обработчики команд администратора, парсера, выбора регионов и выгрузки базы."""

import asyncio
import logging
import os
from aiogram import Bot, F, Router
from aiogram.exceptions import TelegramBadRequest
from aiogram.filters import Command
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.types import CallbackQuery, FSInputFile, Message

import config
import database
import excel_export
import keyboards
from web_parser import collector

logger = logging.getLogger(__name__)

router = Router(name="admin_router")


class AdminStates(StatesGroup):
    """FSM-состояния для админ-панели."""
    waiting_for_custom_regions = State()


def is_admin(user_id: int) -> bool:
    """Проверяет, является ли пользователь администратором."""
    return user_id in config.ADMIN_IDS


async def _run_parser_task(bot: Bot, admin_id: int, target_regions: list[str] | None = None) -> None:
    """Фоновая задача выполнения веб-парсера с развернутым отчетом администратору."""
    try:
        result = await collector.run(regions=target_regions)
        added = result.get("added", 0)
        added_with_phone = result.get("added_with_phone", 0)
        updated = result.get("updated", 0)
        sites_crawled = result.get("sites_crawled", 0)
        search_links = result.get("search_links_found", 0)
        queries_count = result.get("queries_count", 0)
        duration = result.get("duration_seconds", 0)
        search_mode = result.get("search_mode", "Поиск + Резервные каталоги")
        warnings = result.get("warnings", [])

        stats = await database.get_stats()
        selected_regions = await database.get_selected_region_names()

        # Форматируем список регионов для отчета
        regions_used = result.get("regions", target_regions or selected_regions)
        if len(regions_used) > 5:
            regions_summary = ", ".join(regions_used[:5]) + f" (+ ещё {len(regions_used) - 5})"
        else:
            regions_summary = ", ".join(regions_used) if regions_used else "Все базовые регионы"

        # Формируем блок замечаний/предупреждений (если были)
        warnings_text = ""
        if warnings:
            warnings_items = "\n".join([f"  • {w}" for w in warnings[:3]])
            warnings_text = f"\n⚠️ <b>Предупреждения:</b>\n{warnings_items}\n"

        text = (
            "✅ <b>Веб-парсер успешно завершил сбор!</b>\n\n"
            f"📍 <b>Регионы сбора:</b> {regions_summary}\n"
            f"⚙️ <b>Источник поиска:</b> {search_mode}\n"
            f"⏱ <b>Время работы:</b> {duration:.1f} сек.\n"
            f"🔍 <b>Запросов выполнено:</b> {queries_count}\n"
            f"🔗 <b>Ссылок найдено в поиске:</b> {search_links}\n"
            f"🌐 <b>Сайтов исследовано:</b> {sites_crawled}\n\n"
            f"📥 <b>Новых записей добавлено:</b> {added} (с телефоном: <b>{added_with_phone}</b>)\n"
            f"🔄 <b>Существующих обновлено:</b> {updated}\n\n"
            "📊 <b>ИТОГО В БАЗЕ ДАННЫХ:</b>\n"
            f"👥 Всего подрядчиков: <b>{stats['total_count']}</b>\n"
            f"📞 С номерами телефонов: <b>{stats['with_phone']}</b>\n"
            f"🌐 С сайтами/ссылками: <b>{stats['with_website']}</b>\n"
            f"⏳ За последние 24 часа: <b>{stats['last_24h_count']}</b>\n"
            f"{warnings_text}\n"
            "Нажмите <b>«📊 Скачать базу в Excel»</b> в /admin, чтобы выгрузить обновленную базу с делением по 6 листам!"
        )
        await bot.send_message(
            chat_id=admin_id,
            text=text,
            reply_markup=keyboards.get_admin_keyboard(
                is_collector_running=False,
                selected_regions_count=len(selected_regions),
            ),
        )
    except Exception as e:
        logger.error("Ошибка в фоновой задаче парсера: %s", e, exc_info=True)
        try:
            await bot.send_message(
                chat_id=admin_id,
                text=f"⚠️ Произошла ошибка при выполнении парсера: {e}",
            )
        except Exception:
            pass


@router.message(Command("admin"))
async def cmd_admin(message: Message, state: FSMContext) -> None:
    """Обработчик команды /admin."""
    if not is_admin(message.from_user.id):
        await message.answer("⛔ <b>Доступ запрещен.</b> Эта команда только для администраторов.")
        return

    await state.clear()
    stats = await database.get_stats()
    selected_regions = await database.get_selected_region_names()

    text = (
        "👑 <b>Панель администратора</b>\n\n"
        "Управление базой B2B-подрядчиков по благоустройству, детским площадкам, заборам и МАФам.\n\n"
        f"📊 <b>Всего записей в базе:</b> {stats['total_count']}\n"
        f"📞 <b>С номерами телефонов:</b> {stats['with_phone']}\n"
        f"🌐 <b>С сайтами/ссылками:</b> {stats['with_website']}\n"
        f"⏳ <b>Добавлено за 24 часа:</b> {stats['last_24h_count']}\n"
        f"📍 <b>Выбрано регионов для сбора:</b> {len(selected_regions)} шт.\n\n"
        "Выберите действие:"
    )
    await message.answer(
        text=text,
        reply_markup=keyboards.get_admin_keyboard(
            is_collector_running=collector.is_running,
            selected_regions_count=len(selected_regions),
        ),
    )


@router.callback_query(F.data == "admin_refresh")
async def callback_admin_refresh(callback: CallbackQuery, state: FSMContext) -> None:
    """Обновление главного экрана админки с защитой от message is not modified."""
    if not is_admin(callback.from_user.id):
        await callback.answer("⛔ Доступ запрещен", show_alert=True)
        return

    await state.clear()
    stats = await database.get_stats()
    selected_regions = await database.get_selected_region_names()

    text = (
        "👑 <b>Панель администратора</b>\n\n"
        "Управление базой B2B-подрядчиков по благоустройству, детским площадкам, заборам и МАФам.\n\n"
        f"📊 <b>Всего записей в базе:</b> {stats['total_count']}\n"
        f"📞 <b>С номерами телефонов:</b> {stats['with_phone']}\n"
        f"🌐 <b>С сайтами/ссылками:</b> {stats['with_website']}\n"
        f"⏳ <b>Добавлено за 24 часа:</b> {stats['last_24h_count']}\n"
        f"📍 <b>Выбрано регионов для сбора:</b> {len(selected_regions)} шт.\n\n"
        "Выберите действие:"
    )
    if callback.message:
        try:
            await callback.message.edit_text(
                text=text,
                reply_markup=keyboards.get_admin_keyboard(
                    is_collector_running=collector.is_running,
                    selected_regions_count=len(selected_regions),
                ),
            )
            await callback.answer("Данные обновлены")
        except TelegramBadRequest as e:
            if "message is not modified" in str(e).lower():
                await callback.answer("Данные пока не изменились")
            else:
                logger.warning("Ошибка обновления сообщения: %s", e)
                await callback.answer()


# ==================== ИНТЕРАКТИВНЫЙ ВЫБОР РЕГИОНОВ ====================

async def _render_regions_menu(
    callback: CallbackQuery, page: int = 1, notice: str | None = None
) -> None:
    """Отрисовка интерактивного списка регионов с галочками и пагинацией."""
    regions = await database.get_admin_regions()
    selected_count = sum(1 for r in regions if r["is_selected"])
    total_regions = len(regions)
    page_size = 8
    total_pages = max(1, (total_regions + page_size - 1) // page_size)
    page = max(1, min(page, total_pages))

    notice_line = f"💡 <i>{notice}</i>\n\n" if notice else ""
    text = (
        "📍 <b>Выбор регионов для сбора подрядчиков</b>\n\n"
        f"{notice_line}"
        "Нажимайте на кнопки с названиями, чтобы отмечать нужные регионы (<b>✅</b>) "
        "или снимать выбор (<b>⬜</b>).\n\n"
        f"📌 <b>Выбрано:</b> {selected_count} из {total_regions}\n"
        f"📄 <b>Страница {page} из {total_pages}</b>:"
    )

    if callback.message:
        try:
            await callback.message.edit_text(
                text=text,
                reply_markup=keyboards.get_regions_keyboard(regions, page=page, page_size=page_size),
            )
        except TelegramBadRequest as e:
            if "message is not modified" not in str(e).lower():
                logger.warning("Ошибка рендера меню регионов: %s", e)


@router.callback_query(F.data.startswith("admin_regions:"))
async def callback_admin_regions(callback: CallbackQuery, state: FSMContext) -> None:
    """Открытие меню выбора регионов."""
    if not is_admin(callback.from_user.id):
        await callback.answer("⛔ Доступ запрещен", show_alert=True)
        return

    await state.clear()
    page = 1
    parts = callback.data.split(":")
    if len(parts) > 1 and parts[1].isdigit():
        page = int(parts[1])

    await _render_regions_menu(callback, page=page)
    await callback.answer()


@router.callback_query(F.data.startswith("reg_page:"))
async def callback_reg_page(callback: CallbackQuery) -> None:
    """Переключение страницы списка регионов."""
    if not is_admin(callback.from_user.id):
        await callback.answer("⛔ Доступ запрещен", show_alert=True)
        return

    page = 1
    parts = callback.data.split(":")
    if len(parts) > 1 and parts[1].isdigit():
        page = int(parts[1])

    await _render_regions_menu(callback, page=page)
    await callback.answer()


@router.callback_query(F.data.startswith("reg_tog:"))
async def callback_reg_toggle(callback: CallbackQuery) -> None:
    """Переключение галочки региона (✅ <-> ⬜)."""
    if not is_admin(callback.from_user.id):
        await callback.answer("⛔ Доступ запрещен", show_alert=True)
        return

    parts = callback.data.split(":")
    if len(parts) >= 3 and parts[1].isdigit() and parts[2].isdigit():
        reg_id = int(parts[1])
        page = int(parts[2])
        new_status = await database.toggle_admin_region(reg_id)
        status_text = "включен ✅" if new_status else "выключен ⬜"
        await _render_regions_menu(callback, page=page)
        await callback.answer(f"Регион {status_text}")
    else:
        await callback.answer()


@router.callback_query(F.data.startswith("reg_all:"))
async def callback_reg_all(callback: CallbackQuery) -> None:
    """Выбрать все регионы."""
    if not is_admin(callback.from_user.id):
        await callback.answer("⛔ Доступ запрещен", show_alert=True)
        return

    page = 1
    parts = callback.data.split(":")
    if len(parts) > 1 and parts[1].isdigit():
        page = int(parts[1])

    await database.select_all_admin_regions(select_all=True)
    await _render_regions_menu(callback, page=page, notice="Все регионы успешно выбраны!")
    await callback.answer("Все регионы отмечены ✅")


@router.callback_query(F.data.startswith("reg_reset:"))
async def callback_reg_reset(callback: CallbackQuery) -> None:
    """Сбросить выбор регионов."""
    if not is_admin(callback.from_user.id):
        await callback.answer("⛔ Доступ запрещен", show_alert=True)
        return

    page = 1
    parts = callback.data.split(":")
    if len(parts) > 1 and parts[1].isdigit():
        page = int(parts[1])

    await database.select_all_admin_regions(select_all=False)
    await _render_regions_menu(callback, page=page, notice="Выбор сброшен. Отметьте нужные регионы.")
    await callback.answer("Выбор сброшен ⬜")


@router.callback_query(F.data == "reg_noop")
async def callback_reg_noop(callback: CallbackQuery) -> None:
    """Заглушка для информационных кнопок пагинатора."""
    await callback.answer()


@router.callback_query(F.data == "reg_add_custom")
async def callback_reg_add_custom(callback: CallbackQuery, state: FSMContext) -> None:
    """Запрос ввода своего региона от администратора."""
    if not is_admin(callback.from_user.id):
        await callback.answer("⛔ Доступ запрещен", show_alert=True)
        return

    await state.set_state(AdminStates.waiting_for_custom_regions)
    text = (
        "✍️ <b>Добавление своего региона или города</b>\n\n"
        "Отправьте в чат название одного или нескольких регионов/городов через запятую.\n\n"
        "<i>Пример:</i>\n"
        "<code>Калининградская область, Хабаровский край, Владивосток</code>\n\n"
        "Они будут добавлены в базу и автоматически отмечены для сбора."
    )
    if callback.message:
        try:
            await callback.message.edit_text(
                text=text,
                reply_markup=keyboards.get_cancel_custom_region_keyboard(),
            )
        except TelegramBadRequest:
            pass
    await callback.answer()


@router.message(AdminStates.waiting_for_custom_regions)
async def process_custom_regions_input(message: Message, state: FSMContext) -> None:
    """Обработка текстового ввода названий регионов."""
    if not is_admin(message.from_user.id):
        await message.answer("⛔ Доступ запрещен.")
        return

    raw_text = (message.text or "").strip()
    if not raw_text:
        await message.answer(
            "⚠️ Пожалуйста, введите текстовое название хотя бы одного региона.",
            reply_markup=keyboards.get_cancel_custom_region_keyboard(),
        )
        return

    # Разделяем по запятым, точкам с запятой или переводам строк
    delimiters = [",", ";", "\n"]
    cleaned_input = raw_text
    for d in delimiters[1:]:
        cleaned_input = cleaned_input.replace(d, ",")

    raw_names = [item.strip() for item in cleaned_input.split(",") if item.strip()]
    if not raw_names:
        await message.answer(
            "⚠️ Не удалось распознать названия. Введите их через запятую:",
            reply_markup=keyboards.get_cancel_custom_region_keyboard(),
        )
        return

    added = await database.add_custom_admin_regions(raw_names)
    await state.clear()

    regions = await database.get_admin_regions()
    added_str = ", ".join(added) if added else raw_names[0]
    await message.answer(
        f"✅ <b>Успешно добавлены и выбраны регионы:</b>\n{added_str}\n\n"
        "Вы можете сразу запустить сбор или продолжить настройку списка:",
        reply_markup=keyboards.get_regions_keyboard(regions, page=1, page_size=8),
    )


# ==================== ЗАПУСК ПАРСЕРА ====================

@router.callback_query(F.data == "admin_start_parser")
async def callback_admin_start_parser(callback: CallbackQuery) -> None:
    """Запуск асинхронного веб-парсера по выбранным регионам."""
    if not is_admin(callback.from_user.id):
        await callback.answer("⛔ Доступ запрещен", show_alert=True)
        return

    if collector.is_running:
        await callback.answer("⚠️ Сборщик уже запущен и собирает данные!", show_alert=True)
        return

    selected_regions = await database.get_selected_region_names()
    if not selected_regions:
        await callback.answer(
            "⚠️ Не выбрано ни одного региона! Нажмите «📍 Выбрать регионы» и отметьте хотя бы один.",
            show_alert=True,
        )
        return

    await callback.answer(f"Запускаю сбор по {len(selected_regions)} регионам...")

    # Запускаем фоновую задачу с передачей выбранных регионов
    asyncio.create_task(
        _run_parser_task(callback.bot, callback.from_user.id, target_regions=selected_regions)
    )

    regs_preview = ", ".join(selected_regions[:5])
    if len(selected_regions) > 5:
        regs_preview += f" (+ ещё {len(selected_regions) - 5})"

    if callback.message:
        try:
            await callback.message.edit_text(
                "🚀 <b>Сборщик подрядчиков успешно запущен в фоне!</b>\n\n"
                f"📍 <b>Выбранные регионы ({len(selected_regions)}):</b> {regs_preview}\n\n"
                "Парсер формирует целевые поисковые запросы по благоустройству, детским площадкам, "
                "заборам, паркам и МАФам, глубоко исследует сайты, каталоги и контактные страницы, "
                "дожимает телефонные номера и сразу сохраняет всё в базу данных.\n\n"
                "⏳ <i>Бот остаётся полностью доступным — по окончании сбора вам придет подробный отчет со статистикой.</i>",
                reply_markup=keyboards.get_admin_keyboard(
                    is_collector_running=True,
                    selected_regions_count=len(selected_regions),
                ),
            )
        except TelegramBadRequest as e:
            if "message is not modified" in str(e).lower():
                await callback.answer("Сбор уже запущен")
            else:
                logger.warning("Ошибка UI при старте парсера: %s", e)


# ==================== СТАТИСТИКА И ЭКСПОРТ ====================

@router.callback_query(F.data == "admin_stats")
async def callback_admin_stats(callback: CallbackQuery) -> None:
    """Показ подробной статистики с защитой от message is not modified."""
    if not is_admin(callback.from_user.id):
        await callback.answer("⛔ Доступ запрещен", show_alert=True)
        return

    stats = await database.get_stats()
    selected_regions = await database.get_selected_region_names()
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
        f"⏱ <b>Добавлено за 24 часа:</b> {stats['last_24h_count']}\n"
        f"📍 <b>Активных регионов для сбора:</b> {len(selected_regions)}\n\n"
        "<b>Источники поступления:</b>\n"
        f"  • 📋 Анкета Telegram-бота: <b>{form_count}</b>\n"
        f"  • 🌐 Автоматический веб-парсер: <b>{web_count}</b>\n\n"
        "<b>По ключевым направлениям:</b>\n"
        f"{cats_text}\n"
    )
    if callback.message:
        try:
            await callback.message.edit_text(
                text=text,
                reply_markup=keyboards.get_back_to_admin_keyboard(),
            )
            await callback.answer()
        except TelegramBadRequest as e:
            if "message is not modified" in str(e).lower():
                await callback.answer("Данные пока не изменились")
            else:
                logger.warning("Ошибка UI при показе статистики: %s", e)
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
        logger.error("Ошибка при генерации/отправке Excel: %s", e, exc_info=True)
        if callback.message:
            await callback.message.answer(f"❌ Произошла ошибка при экспорте: {e}")
    finally:
        if excel_path and os.path.exists(excel_path):
            try:
                os.remove(excel_path)
                logger.info("Временный файл экспорта %s успешно удален", excel_path)
            except OSError as err:
                logger.warning("Не удалось удалить временный файл %s: %s", excel_path, err)
