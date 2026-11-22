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


def get_admin_keyboard(
    is_collector_running: bool = False, selected_regions_count: int = 0
) -> InlineKeyboardMarkup:
    """Inline-клавиатура панели администратора с кнопкой выбора регионов."""
    parser_btn_text = "⏳ Сбор выполняется..." if is_collector_running else "🌐 Запустить сбор"
    reg_btn_text = f"📍 Выбрать регионы ({selected_regions_count})" if selected_regions_count > 0 else "📍 Выбрать регионы"

    return InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(
                    text=reg_btn_text,
                    callback_data="admin_regions:1",
                )
            ],
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


def get_regions_keyboard(
    regions: list[dict], page: int = 1, page_size: int = 8
) -> InlineKeyboardMarkup:
    """
    Интерактивная клавиатура выбора регионов с мультиселектом (галочки),
    пагинацией и кнопками управления.
    """
    total_regions = len(regions)
    total_pages = max(1, (total_regions + page_size - 1) // page_size)
    page = max(1, min(page, total_pages))

    start_idx = (page - 1) * page_size
    end_idx = start_idx + page_size
    page_regions = regions[start_idx:end_idx]

    keyboard = []

    # Кнопки регионов по 2 в ряд
    row = []
    for reg in page_regions:
        mark = "✅" if reg["is_selected"] else "⬜"
        name = reg["name"]
        btn_text = f"{mark} {name}"
        row.append(
            InlineKeyboardButton(
                text=btn_text,
                callback_data=f"reg_tog:{reg['id']}:{page}",
            )
        )
        if len(row) == 2:
            keyboard.append(row)
            row = []
    if row:
        keyboard.append(row)

    # Навигационная строка пагинации
    if total_pages > 1:
        nav_row = []
        if page > 1:
            nav_row.append(
                InlineKeyboardButton(
                    text="◀️ Назад",
                    callback_data=f"reg_page:{page - 1}",
                )
            )
        else:
            nav_row.append(
                InlineKeyboardButton(
                    text="·",
                    callback_data="reg_noop",
                )
            )

        nav_row.append(
            InlineKeyboardButton(
                text=f"{page}/{total_pages}",
                callback_data="reg_noop",
            )
        )

        if page < total_pages:
            nav_row.append(
                InlineKeyboardButton(
                    text="Вперед ▶️",
                    callback_data=f"reg_page:{page + 1}",
                )
            )
        else:
            nav_row.append(
                InlineKeyboardButton(
                    text="·",
                    callback_data="reg_noop",
                )
            )
        keyboard.append(nav_row)

    # Строка быстрых действий выбора
    keyboard.append([
        InlineKeyboardButton(
            text="✅ Выбрать все",
            callback_data=f"reg_all:{page}",
        ),
        InlineKeyboardButton(
            text="🧹 Сбросить",
            callback_data=f"reg_reset:{page}",
        ),
    ])

    # Добавление своего региона
    keyboard.append([
        InlineKeyboardButton(
            text="✍️ Добавить свой регион/город",
            callback_data="reg_add_custom",
        )
    ])

    # Запуск парсера по отмеченным
    keyboard.append([
        InlineKeyboardButton(
            text="🚀 Запустить сбор по выбранным",
            callback_data="admin_start_parser",
        )
    ])

    # Возврат в админку
    keyboard.append([
        InlineKeyboardButton(
            text="⬅️ Назад в админ-панель",
            callback_data="admin_refresh",
        )
    ])

    return InlineKeyboardMarkup(inline_keyboard=keyboard)


def get_cancel_custom_region_keyboard() -> InlineKeyboardMarkup:
    """Кнопка отмены ввода пользовательского региона."""
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(
                    text="❌ Отмена",
                    callback_data="admin_regions:1",
                )
            ]
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
