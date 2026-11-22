"""Клавиатуры бота: Inline и Reply клавиатуры."""

from aiogram.types import (
    InlineKeyboardButton,
    InlineKeyboardMarkup,
    KeyboardButton,
    ReplyKeyboardMarkup,
    WebAppInfo,
)


def get_start_keyboard(webapp_url: str | None = None) -> InlineKeyboardMarkup:
    """Главная inline-клавиатура приветствия."""
    buttons = [
        [
            InlineKeyboardButton(
                text="📋 Оставить заявку / Получить прайс",
                callback_data="start_survey",
            )
        ]
    ]

    # Если настроен Web App URL, добавляем кнопку мини-приложения с тулбаром Liquid Glass
    if webapp_url:
        buttons.append(
            [
                InlineKeyboardButton(
                    text="🌐 Открыть каталог (Web App)",
                    web_app=WebAppInfo(url=webapp_url),
                )
            ]
        )

    return InlineKeyboardMarkup(inline_keyboard=buttons)


def get_cancel_inline_keyboard() -> InlineKeyboardMarkup:
    """Inline-кнопка для отмены заполнения анкеты."""
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(
                    text="❌ Отменить заполнение",
                    callback_data="cancel_survey",
                )
            ]
        ]
    )


def get_site_keyboard() -> InlineKeyboardMarkup:
    """Inline-клавиатура для шага ввода сайта / соцсетей."""
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(
                    text="🌐 Нет сайта",
                    callback_data="site_none",
                )
            ],
            [
                InlineKeyboardButton(
                    text="❌ Отменить заполнение",
                    callback_data="cancel_survey",
                )
            ],
        ]
    )


def get_phone_reply_keyboard() -> ReplyKeyboardMarkup:
    """Reply-клавиатура с кнопкой отправки контакта и отменой."""
    return ReplyKeyboardMarkup(
        keyboard=[
            [
                KeyboardButton(
                    text="📱 Отправить мой номер",
                    request_contact=True,
                )
            ],
            [
                KeyboardButton(text="❌ Отмена"),
            ],
        ],
        resize_keyboard=True,
        one_time_keyboard=True,
    )


def get_admin_keyboard(is_collector_running: bool = False) -> InlineKeyboardMarkup:
    """Inline-клавиатура панели администратора."""
    parser_btn_text = "⏳ Сбор выполняется..." if is_collector_running else "🌐 Запустить сбор"

    return InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(
                    text=parser_btn_text,
                    callback_data="admin_start_parser",
                )
            ],
            [
                InlineKeyboardButton(
                    text="📊 Скачать базу в Excel",
                    callback_data="admin_export_excel",
                )
            ],
            [
                InlineKeyboardButton(
                    text="📈 Статистика",
                    callback_data="admin_stats",
                )
            ],
            [
                InlineKeyboardButton(
                    text="🔄 Обновить",
                    callback_data="admin_refresh",
                )
            ],
        ]
    )


def get_back_to_admin_keyboard() -> InlineKeyboardMarkup:
    """Кнопка возврата в главное меню админки."""
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(
                    text="⬅️ Назад в админ-панель",
                    callback_data="admin_refresh",
                )
            ]
        ]
    )
