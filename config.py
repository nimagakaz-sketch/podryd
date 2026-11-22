"""Модуль конфигурации бота и настроек веб-парсера."""

import os
from pathlib import Path
from dotenv import load_dotenv

# Загружаем переменные окружения из .env
BASE_DIR = Path(__file__).resolve().parent
load_dotenv(BASE_DIR / ".env")

BOT_TOKEN = os.getenv("BOT_TOKEN", "").strip()
if not BOT_TOKEN:
    raise ValueError("Переменная окружения BOT_TOKEN не установлена! Проверьте файл .env")

# Парсинг ADMIN_IDS (список целых чисел)
_admin_ids_raw = os.getenv("ADMIN_IDS", "").strip()
ADMIN_IDS: list[int] = []
if _admin_ids_raw:
    for item in _admin_ids_raw.split(","):
        cleaned = item.strip()
        if cleaned.isdigit():
            ADMIN_IDS.append(int(cleaned))

# ==================== БАЗА ДАННЫХ ====================
# Если задан DATABASE_URL (PostgreSQL), бот подключается к нему через asyncpg.
# Если не задан — fallback на локальный SQLite через aiosqlite.
DATABASE_URL = os.getenv("DATABASE_URL", "").strip()
if DATABASE_URL.startswith("postgres://"):
    # Render, Heroku и некоторые провайдеры передают postgres://, заменяем на postgresql:// для asyncpg
    DATABASE_URL = DATABASE_URL.replace("postgres://", "postgresql://", 1)

DB_PATH = BASE_DIR / os.getenv("DB_PATH", "data/contractors.db")
CATALOG_PDF_PATH = BASE_DIR / os.getenv("CATALOG_PDF_PATH", "assets/price_catalog.pdf")
EXPORTS_DIR = BASE_DIR / "exports"

# WebApp URL (опционально)
WEBAPP_URL = os.getenv("WEBAPP_URL", "").strip() or None

# Поисковый API ключ (опционально, для Serper.dev или Google Custom Search)
# Serper.dev дает 2,500 бесплатных поисков Google без блокировок дата-центров
SEARCH_API_KEY = os.getenv("SEARCH_API_KEY", "").strip() or None
GOOGLE_CSE_ID = os.getenv("GOOGLE_CSE_ID", "").strip() or None


# ==================== НАСТРОЙКИ ВЕБ-ПАРСЕРА ====================
def _parse_list(raw: str, default: list[str]) -> list[str]:
    if not raw:
        return default
    delimiter = ";" if ";" in raw else ","
    items = [item.strip() for item in raw.split(delimiter) if item.strip()]
    return items if items else default


DEFAULT_QUERIES = [
    "благоустройство детские площадки",
    "установка детских городков маф",
    "производство заборов ограждений",
    "подрядчики благоустройство территорий",
    "поставка мафов для парков",
    "ограждения детских садов и школ",
]

DEFAULT_REGIONS = [
    "Москва и МО",
    "Санкт-Петербург",
    "Краснодарский край",
    "Екатеринбург",
    "Казань",
    "Новосибирск",
    "Нижний Новгород",
    "Ростов-на-Дону",
]

DEFAULT_SEEDS = [
    "https://rostov-gorod.ru",
    "https://parki-rossii.ru",
    "https://blagoustroystvo.info",
]

SEARCH_QUERIES = _parse_list(os.getenv("SEARCH_QUERIES", ""), DEFAULT_QUERIES)
TARGET_REGIONS = _parse_list(os.getenv("TARGET_REGIONS", ""), DEFAULT_REGIONS)
SEED_URLS = _parse_list(os.getenv("SEED_URLS", ""), DEFAULT_SEEDS)

PARSER_DELAY = float(os.getenv("PARSER_DELAY", "1.5"))
PARSER_MAX_PER_QUERY = int(os.getenv("PARSER_MAX_PER_QUERY", "15"))

# Создаем необходимые локальные директории
DB_PATH.parent.mkdir(parents=True, exist_ok=True)
CATALOG_PDF_PATH.parent.mkdir(parents=True, exist_ok=True)
EXPORTS_DIR.mkdir(parents=True, exist_ok=True)
