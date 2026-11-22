"""Обработчики пользовательской части и FSM анкеты."""

import logging
import re
from aiogram import F, Router
from aiogram.filters import Command, CommandStart, StateFilter
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.types import (
    CallbackQuery,
    FSInputFile,
    Message,
    ReplyKeyboardRemove,
)

import config
import database
import keyboards

logger = logging.getLogger(__name__)

router = Router(name="user_router")


class ContractorForm(StatesGroup):
    """Состояния FSM для анкеты подрядчика."""

    waiting_for_region = State()
    waiting_for_site = State()
    waiting_for_phone = State()


# Текст приветствия и оффера
START_MESSAGE = (
    "👋 <b>Здравствуйте!</b>\n\n"
    "🏭 <b>Поставки детских игровых площадок, МАФов и ограждений</b> "
    "для объектов благоустройства (парки, скверы, ЖК, детсады, городская среда).\n\n"
    "📦 <i>В нашем каталоге:</i> качалки-балансиры, качели, карусели, "
    "зимние и всесезонные горки, воркаут-комплексы, турники, рукоходы, "
    "детские скамейки и ограждения.\n"
    "🚚 <b>Доставка осуществляется за счет поставщика!</b>\n\n"
    "Оставьте контакты вашей компании, чтобы мгновенно получить оптовый прайс и каталог."
)


@router.message(CommandStart())
async def cmd_start(message: Message, state: FSMContext) -> None:
    """Обработчик команды /start."""
    await state.clear()
    await message.answer(
        text=START_MESSAGE,
        reply_markup=keyboards.get_start_keyboard(webapp_url=config.WEBAPP_URL),
    )


@router.message(Command("cancel"))
@router.message(F.text.casefold().in_(["отмена", "❌ отмена", "/cancel"]))
async def cmd_cancel(message: Message, state: FSMContext) -> None:
    """Отмена текущего заполнения анкеты через команду или текст."""
    current_state = await state.get_state()
    if current_state is None:
        await message.answer(
            "Нет активных действий для отмены.",
            reply_markup=ReplyKeyboardRemove(),
        )
        return

    await state.clear()
    await message.answer(
        "❌ Заполнение анкеты отменено.\n"
        "Когда будете готовы, нажмите /start чтобы начать заново.",
        reply_markup=ReplyKeyboardRemove(),
    )


@router.callback_query(F.data == "cancel_survey")
async def callback_cancel_survey(callback: CallbackQuery, state: FSMContext) -> None:
    """Отмена заполнения анкеты через inline-кнопку."""
    await state.clear()
    await callback.answer("Заполнение отменено")
    if callback.message:
        await callback.message.edit_text(
            "❌ <b>Заполнение анкеты отменено.</b>\n\n"
            "Вы можете вернуться к заполнению в любой момент, нажав /start.",
        )


@router.callback_query(F.data == "start_survey")
async def callback_start_survey(callback: CallbackQuery, state: FSMContext) -> None:
    """Старт пошаговой анкеты по кнопке."""
    await state.set_state(ContractorForm.waiting_for_region)
    await callback.answer()
    if callback.message:
        await callback.message.answer(
            "📍 <b>Шаг 1 из 3: Регион / Город работы</b>\n\n"
            "Укажите ваш регион или город, в котором реализуете объекты благоустройства "
            "<i>(например: Москва и МО, Екатеринбург, Краснодарский край)</i>:",
            reply_markup=keyboards.get_cancel_inline_keyboard(),
        )


# ==================== ШАГ 1: РЕГИОН ====================


@router.message(StateFilter(ContractorForm.waiting_for_region), F.text)
async def process_region(message: Message, state: FSMContext) -> None:
    """Обработка ввода региона."""
    region = message.text.strip()
    if len(region) < 2:
        await message.answer(
            "⚠️ Пожалуйста, укажите корректное название региона или города (не менее 2 символов):",
            reply_markup=keyboards.get_cancel_inline_keyboard(),
        )
        return

    await state.update_data(region=region)
    await state.set_state(ContractorForm.waiting_for_site)

    await message.answer(
        f"✅ Регион: <b>{region}</b>\n\n"
        "🌐 <b>Шаг 2 из 3: Сайт или соцсети компании</b>\n\n"
        "Укажите ссылку на сайт, группу ВК или соцсеть вашей организации.\n"
        "Если у компании нет сайта — просто нажмите кнопку <b>«Нет сайта»</b> ниже:",
        reply_markup=keyboards.get_site_keyboard(),
    )


# ==================== ШАГ 2: САЙТ / СОЦСЕТИ ====================


@router.callback_query(
    StateFilter(ContractorForm.waiting_for_site), F.data == "site_none"
)
async def callback_site_none(callback: CallbackQuery, state: FSMContext) -> None:
    """Обработка нажатия кнопки 'Нет сайта'."""
    await state.update_data(site="Нет сайта")
    await state.set_state(ContractorForm.waiting_for_phone)
    await callback.answer()

    if callback.message:
        await callback.message.answer(
            "📱 <b>Шаг 3 из 3: Номер телефона для связи</b>\n\n"
            "Нажмите кнопку <b>«📱 Отправить мой номер»</b> на клавиатуре ниже "
            "или введите номер вручную текстом <i>(например: +7 999 123-45-67)</i>:",
            reply_markup=keyboards.get_phone_reply_keyboard(),
        )


@router.message(StateFilter(ContractorForm.waiting_for_site), F.text)
async def process_site_text(message: Message, state: FSMContext) -> None:
    """Обработка ручного ввода сайта или соцсетей."""
    site = message.text.strip()
    await state.update_data(site=site)
    await state.set_state(ContractorForm.waiting_for_phone)

    await message.answer(
        f"✅ Сайт/соцсети: <b>{site}</b>\n\n"
        "📱 <b>Шаг 3 из 3: Номер телефона для связи</b>\n\n"
        "Нажмите кнопку <b>«📱 Отправить мой номер»</b> на клавиатуре ниже "
        "или введите номер вручную текстом <i>(например: +7 999 123-45-67)</i>:",
        reply_markup=keyboards.get_phone_reply_keyboard(),
    )


# ==================== ШАГ 3: НОМЕР ТЕЛЕФОНА ====================


def _extract_and_validate_phone(raw_phone: str) -> str | None:
    """
    Валидация номера телефона:
    - Проверяет наличие минимум 10 цифр.
    - Возвращает нормализованный номер с плюсом или цифрами.
    """
    digits = re.sub(r"\D", "", raw_phone)
    if len(digits) < 10:
        return None

    # Если номер начинается с 8 или 7 и состоит из 11 цифр, форматируем в +7...
    if len(digits) == 11 and digits.startswith(("7", "8")):
        return f"+7{digits[1:]}"
    elif raw_phone.strip().startswith("+"):
        return f"+{digits}"
    return f"+{digits}"


@router.message(
    StateFilter(ContractorForm.waiting_for_phone),
    F.contact | F.text,
)
async def process_phone(message: Message, state: FSMContext) -> None:
    """Обработка отправленного контакта или номера текстом."""
    phone_clean: str | None = None

    if message.contact:
        raw_phone = message.contact.phone_number
        phone_clean = _extract_and_validate_phone(raw_phone)
    elif message.text:
        # Проверка на отмену текстом
        if message.text.strip().casefold() in ["отмена", "❌ отмена"]:
            await cmd_cancel(message, state)
            return
        phone_clean = _extract_and_validate_phone(message.text)

    if not phone_clean:
        await message.answer(
            "⚠️ <b>Некорректный номер телефона!</b>\n\n"
            "Пожалуйста, введите номер, содержащий не менее 10 цифр "
            "<i>(например, +7 999 123-45-67)</i> "
            "или нажмите кнопку <b>«📱 Отправить мой номер»</b> внизу экрана:",
            reply_markup=keyboards.get_phone_reply_keyboard(),
        )
        return

    # Извлекаем собранные данные из FSM
    data = await state.get_data()
    region = data.get("region", "Не указан")
    site = data.get("site", "Нет сайта")
    user_id = message.from_user.id
    username = message.from_user.username

    # Сохраняем в базу данных SQLite
    lead_id = await database.add_contractor(
        user_id=user_id,
        username=username,
        region=region,
        site=site,
        phone=phone_clean,
    )

    # Завершаем FSM
    await state.clear()

    # Убираем Reply-клавиатуру
    await message.answer(
        "🎉 <b>Спасибо! Ваша заявка успешно принята!</b>\n\n"
        "Ваши контакты внесены в базу подрядчиков. "
        "Ниже направляем вам оптовый прайс-лист с техническими характеристиками "
        "и габаритами оборудования.\n\n"
        "🚚 <i>Напоминание: доставка осуществляется за счет поставщика!</i>\n"
        "Наш менеджер свяжется с вами в ближайшее время для обсуждения объектов.",
        reply_markup=ReplyKeyboardRemove(),
    )

    # Отправляем PDF каталог/прайс-лист
    if config.CATALOG_PDF_PATH.exists():
        try:
            pdf_document = FSInputFile(
                path=config.CATALOG_PDF_PATH,
                filename="Прайс-лист_МАФ_и_Ограждения.pdf",
            )
            await message.answer_document(
                document=pdf_document,
                caption=(
                    "📄 <b>Оптовый прайс-лист: Детские площадки, МАФы и спортивные комплексы</b>\n"
                    "Все размеры, цены и характеристики указаны внутри."
                ),
            )
        except Exception as e:
            logger.error("Ошибка при отправке PDF каталога: %s", e)
    else:
        logger.warning("PDF каталог по пути %s не найден", config.CATALOG_PDF_PATH)

    # Уведомляем администраторов о новой заявке
    username_display = f"@{username}" if username else "Не указан"
    admin_notification = (
        "🔔 <b>Новая заявка от B2B-подрядчика!</b>\n\n"
        f"🆔 <b>Номер заявки:</b> #{lead_id}\n"
        f"📍 <b>Регион:</b> {region}\n"
        f"🌐 <b>Сайт / Соцсети:</b> {site}\n"
        f"📱 <b>Телефон:</b> <code>{phone_clean}</code>\n"
        f"👤 <b>Telegram:</b> {username_display} (ID: <code>{user_id}</code>)\n"
    )

    for admin_id in config.ADMIN_IDS:
        try:
            await message.bot.send_message(
                chat_id=admin_id,
                text=admin_notification,
            )
        except Exception as e:
            logger.error("Не удалось отправить уведомление админу %s: %s", admin_id, e)
