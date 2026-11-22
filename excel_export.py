"""Умный многолистовой экспорт базы подрядчиков в Excel (.xlsx)."""

from datetime import datetime
from pathlib import Path
from typing import Any
import openpyxl
from openpyxl.styles import Alignment, Border, Font, PatternFill, Side
from openpyxl.utils import get_column_letter

import config

# Заголовки таблицы (единый набор колонок для всех листов)
HEADERS = [
    "ID",
    "Источник",
    "Направления / Теги",
    "Регион",
    "Телефон",
    "Сайт",
    "Компания / Название",
    "Фрагмент / Описание",
    "Telegram Username",
    "Telegram ID",
    "Дата и время",
]

# Цветовые темы шапки для каждого листа
SHEET_COLORS = {
    "Все данные": "1F4E79",          # Темно-синий
    "С телефоном": "1E7E34",         # Изумрудно-зеленый
    "С сайтом": "117A8B",            # Морская волна
    "Площадки и парки": "D35400",    # Насыщенный терракотовый
    "Заборы и МАФ": "5B2C6F",        # Глубокий фиолетовый
    "Анкета бота": "2874A6",         # Лазурный
}


def _matches_sheet(sheet_name: str, item: dict[str, Any]) -> bool:
    """Проверяет принадлежность записи к конкретному листу."""
    tags = item.get("category_tags", "") or ""
    source = item.get("source", "") or ""
    has_phone = item.get("has_phone", 0)
    has_website = item.get("has_website", 0)

    if sheet_name == "Все данные":
        return True
    elif sheet_name == "С телефоном":
        return has_phone == 1
    elif sheet_name == "С сайтом":
        return has_website == 1
    elif sheet_name == "Площадки и парки":
        return any(
            t in tags for t in ["Детские площадки", "Парки и скверы", "Детсады и школы"]
        )
    elif sheet_name == "Заборы и МАФ":
        return any(t in tags for t in ["Заборы и ограждения", "МАФы"])
    elif sheet_name == "Анкета бота":
        return source == "form"
    return False


def _populate_sheet(
    ws: openpyxl.worksheet.worksheet.Worksheet,
    title: str,
    contractors: list[dict[str, Any]],
    header_color: str,
) -> None:
    """Заполняет и стилизует отдельный лист книги Excel."""
    ws.title = title
    ws.views.sheetView[0].showGridLines = True
    ws.freeze_panes = "A2"  # Закрепляем шапку при прокрутке

    # 1. Шапка
    ws.append(HEADERS)
    ws.row_dimensions[1].height = 28

    header_fill = PatternFill(
        start_color=header_color, end_color=header_color, fill_type="solid"
    )
    header_font = Font(name="Arial", size=11, bold=True, color="FFFFFF")
    center_align = Alignment(horizontal="center", vertical="center", wrap_text=True)
    left_align = Alignment(horizontal="left", vertical="center")
    left_wrap_align = Alignment(horizontal="left", vertical="center", wrap_text=True)

    thin_border_side = Side(border_style="thin", color="D0D5DD")
    border = Border(
        left=thin_border_side,
        right=thin_border_side,
        top=thin_border_side,
        bottom=thin_border_side,
    )

    for col_idx in range(1, len(HEADERS) + 1):
        cell = ws.cell(row=1, column=col_idx)
        cell.fill = header_fill
        cell.font = header_font
        cell.alignment = center_align
        cell.border = border

    # 2. Фильтрация данных для листа
    filtered = [item for item in contractors if _matches_sheet(title, item)]

    if not filtered:
        # Если записей нет, выводим уведомление
        ws.append(["—", "Нет данных в этой выборке", "", "", "", "", "", "", "", "", ""])
        ws.row_dimensions[2].height = 24
        empty_cell = ws.cell(row=2, column=2)
        empty_cell.font = Font(name="Arial", size=10, italic=True, color="888888")
        return

    # 3. Данные
    row_alt_fill = PatternFill(
        start_color="F8FAFC", end_color="F8FAFC", fill_type="solid"
    )
    data_font = Font(name="Arial", size=10)

    for row_idx, item in enumerate(filtered, start=2):
        username = item.get("tg_username") or ""
        username_formatted = f"@{username}" if username else "—"
        tg_id_formatted = item.get("tg_user_id") or "—"

        source_display = "Бот (анкета)" if item.get("source") == "form" else "Веб-парсер"

        row_data = [
            item.get("id"),
            source_display,
            item.get("category_tags") or "Благоустройство",
            item.get("region") or "Не указан",
            str(item.get("phone") or "Не указан"),
            item.get("website") or "Не указан",
            item.get("company_name") or "Не указано",
            item.get("snippet") or "",
            username_formatted,
            tg_id_formatted,
            item.get("created_at") or "",
        ]
        ws.append(row_data)
        ws.row_dimensions[row_idx].height = 22

        is_alt = row_idx % 2 == 1
        for col_idx in range(1, len(HEADERS) + 1):
            cell = ws.cell(row=row_idx, column=col_idx)
            cell.font = data_font
            cell.border = border
            if is_alt:
                cell.fill = row_alt_fill

            # Форматирование и выравнивание
            if col_idx in (1, 2, 4, 9, 10, 11):  # ID, Источник, Регион, TG, Дата
                cell.alignment = center_align
            elif col_idx == 5:  # Телефон (текстовый формат)
                cell.alignment = center_align
                cell.number_format = "@"
            elif col_idx == 8:  # Фрагмент / Описание
                cell.alignment = left_wrap_align
            else:
                cell.alignment = left_align

    # 4. Автоподбор ширины колонок
    for col in ws.columns:
        col_letter = get_column_letter(col[0].column)
        max_len = 0
        for cell in col:
            val = str(cell.value or "")
            if len(val) > 70:
                max_len = max(max_len, 45)  # Ограничение для длинных сниппетов
            else:
                max_len = max(max_len, len(val))
        ws.column_dimensions[col_letter].width = min(max(max_len + 4, 12), 48)


def export_contractors_to_excel(contractors: list[dict[str, Any]]) -> Path:
    """
    Генерирует многолистовой Excel-файл (.xlsx) с разбивкой по категориям:
    - Все данные
    - С телефоном
    - С сайтом
    - Площадки и парки
    - Заборы и МАФ
    - Анкета бота
    """
    wb = openpyxl.Workbook()
    # Удаляем дефолтный пустой лист
    wb.remove(wb.active)

    sheet_names = [
        "Все данные",
        "С телефоном",
        "С сайтом",
        "Площадки и парки",
        "Заборы и МАФ",
        "Анкета бота",
    ]

    for s_name in sheet_names:
        ws = wb.create_sheet(title=s_name)
        color = SHEET_COLORS.get(s_name, "1F4E79")
        _populate_sheet(ws, s_name, contractors, color)

    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    file_path = config.EXPORTS_DIR / f"contractors_b2b_{timestamp}.xlsx"
    wb.save(file_path)

    return file_path
