"""Асинхронная работа с базой данных: PostgreSQL (через asyncpg) или SQLite (через aiosqlite)."""

import asyncio
from datetime import datetime
import logging
import re
from typing import Any

import aiosqlite

import config

logger = logging.getLogger(__name__)

# Пул подключений PostgreSQL (если задан DATABASE_URL)
_pg_pool = None

# Базовый список целевых регионов РФ по умолчанию для админки и парсера
DEFAULT_ADMIN_REGIONS = [
    "Москва и МО",
    "Санкт-Петербург и ЛО",
    "Кемеровская область",
    "Новосибирская область",
    "Свердловская область",
    "Краснодарский край",
    "Татарстан",
    "Красноярский край",
    "Тюменская область",
    "Челябинская область",
    "Самарская область",
    "Нижегородская область",
    "Ростовская область",
    "Башкортостан",
    "Пермский край",
    "Иркутская область",
    "Омская область",
    "Воронежская область",
    "Алтайский край",
]


async def get_pg_pool():
    """Возвращает или создает пул соединений PostgreSQL."""
    global _pg_pool
    if _pg_pool is None:
        import asyncpg
        logger.info("Подключение к PostgreSQL через asyncpg...")
        _pg_pool = await asyncpg.create_pool(
            dsn=config.DATABASE_URL,
            min_size=1,
            max_size=10,
            command_timeout=60,
        )
    return _pg_pool


async def close_db() -> None:
    """Закрытие соединений с базой данных при завершении работы бота."""
    global _pg_pool
    if _pg_pool is not None:
        await _pg_pool.close()
        _pg_pool = None
        logger.info("Пул соединений PostgreSQL закрыт.")


_sqlite_lock = asyncio.Lock()


def get_sqlite_connection() -> aiosqlite.Connection:
    """Возвращает объект подключения SQLite с увеличенным таймаутом ожидания блокировки."""
    return aiosqlite.connect(config.DB_PATH, timeout=30.0)


def normalize_website(url: str | None) -> str:
    """Нормализует домен/ссылку для аккуратной дедупликации."""
    if not url:
        return ""
    u = url.strip().lower()
    if u in ("не указан", "нет сайта", "none", "-", ""):
        return ""
    u = re.sub(r"^https?://", "", u)
    u = re.sub(r"^www\.", "", u)
    u = u.split("/")[0].split("?")[0].split("#")[0].strip()
    return u


def normalize_phone_match(phone: str | None) -> str:
    """Нормализует номер телефона (последние 10 цифр) для поиска дублей."""
    if not phone:
        return ""
    p = phone.strip().lower()
    if p in ("не указан", "none", "-", ""):
        return ""
    digits = re.sub(r"\D", "", phone)
    if len(digits) >= 10:
        return digits[-10:]
    return digits


def merge_tags(old_tags: str, new_tags: str) -> str:
    """Объединяет теги категорий без повторений."""
    all_tags = []
    seen = set()
    for s in (old_tags, new_tags):
        for tag in s.split(","):
            t = tag.strip()
            if t and t not in seen:
                seen.add(t)
                all_tags.append(t)
    return ", ".join(all_tags)


async def init_db() -> None:
    """Инициализация базы данных: PostgreSQL или SQLite в зависимости от конфигурации."""
    if config.DATABASE_URL:
        # ==================== POSTGRESQL ====================
        pool = await get_pg_pool()
        async with pool.acquire() as conn:
            await conn.execute(
                """
                CREATE TABLE IF NOT EXISTS contractors (
                    id SERIAL PRIMARY KEY,
                    source VARCHAR(64) NOT NULL DEFAULT 'form',
                    region VARCHAR(255) NOT NULL DEFAULT 'Не указан',
                    phone VARCHAR(255) NOT NULL DEFAULT 'Не указан',
                    website VARCHAR(255) NOT NULL DEFAULT 'Не указан',
                    company_name VARCHAR(255) NOT NULL DEFAULT 'Не указано',
                    category_tags TEXT NOT NULL DEFAULT '',
                    has_phone SMALLINT NOT NULL DEFAULT 0,
                    has_website SMALLINT NOT NULL DEFAULT 0,
                    snippet TEXT NOT NULL DEFAULT '',
                    tg_username VARCHAR(255) DEFAULT '',
                    tg_user_id BIGINT DEFAULT NULL,
                    created_at TIMESTAMP WITHOUT TIME ZONE DEFAULT CURRENT_TIMESTAMP
                );
                CREATE INDEX IF NOT EXISTS idx_contractors_source ON contractors(source);
                CREATE INDEX IF NOT EXISTS idx_contractors_has_phone ON contractors(has_phone);
                CREATE INDEX IF NOT EXISTS idx_contractors_has_website ON contractors(has_website);
                CREATE INDEX IF NOT EXISTS idx_contractors_created_at ON contractors(created_at);

                CREATE TABLE IF NOT EXISTS admin_regions (
                    id SERIAL PRIMARY KEY,
                    name VARCHAR(255) NOT NULL UNIQUE,
                    is_selected SMALLINT NOT NULL DEFAULT 1,
                    is_custom SMALLINT NOT NULL DEFAULT 0,
                    created_at TIMESTAMP WITHOUT TIME ZONE DEFAULT CURRENT_TIMESTAMP
                );
                CREATE INDEX IF NOT EXISTS idx_admin_regions_selected ON admin_regions(is_selected);
                """
            )

            # Проверяем и заполняем дефолтные регионы, если таблица пуста
            reg_count = await conn.fetchval("SELECT COUNT(*) FROM admin_regions")
            if reg_count == 0:
                for reg in DEFAULT_ADMIN_REGIONS:
                    await conn.execute(
                        "INSERT INTO admin_regions (name, is_selected, is_custom) VALUES ($1, 1, 0) ON CONFLICT (name) DO NOTHING",
                        reg,
                    )
                logger.info("Инициализировано %d базовых регионов РФ в PostgreSQL.", len(DEFAULT_ADMIN_REGIONS))
        logger.info("Таблицы и индексы PostgreSQL успешно проверены.")
    else:
        # ==================== SQLITE ====================
        async with get_sqlite_connection() as db:
            db.row_factory = aiosqlite.Row

            async with db.execute(
                "SELECT name FROM sqlite_master WHERE type='table' AND name='contractors'"
            ) as cur:
                table_exists = await cur.fetchone() is not None

            if not table_exists:
                await db.execute(
                    """
                    CREATE TABLE contractors (
                        id INTEGER PRIMARY KEY AUTOINCREMENT,
                        source TEXT NOT NULL DEFAULT 'form',
                        region TEXT NOT NULL DEFAULT 'Не указан',
                        phone TEXT NOT NULL DEFAULT 'Не указан',
                        website TEXT NOT NULL DEFAULT 'Не указан',
                        company_name TEXT NOT NULL DEFAULT 'Не указано',
                        category_tags TEXT NOT NULL DEFAULT '',
                        has_phone INTEGER NOT NULL DEFAULT 0,
                        has_website INTEGER NOT NULL DEFAULT 0,
                        snippet TEXT NOT NULL DEFAULT '',
                        tg_username TEXT DEFAULT '',
                        tg_user_id INTEGER DEFAULT NULL,
                        created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                    )
                    """
                )
            else:
                # Проверяем структуру колонок
                async with db.execute("PRAGMA table_info(contractors)") as cur:
                    cols_info = {row["name"]: row for row in await cur.fetchall()}

                user_id_col = cols_info.get("user_id")
                if user_id_col and user_id_col["notnull"] == 1:
                    await db.execute(
                        """
                        CREATE TABLE contractors_migrated (
                            id INTEGER PRIMARY KEY AUTOINCREMENT,
                            source TEXT NOT NULL DEFAULT 'form',
                            region TEXT NOT NULL DEFAULT 'Не указан',
                            phone TEXT NOT NULL DEFAULT 'Не указан',
                            website TEXT NOT NULL DEFAULT 'Не указан',
                            company_name TEXT NOT NULL DEFAULT 'Не указано',
                            category_tags TEXT NOT NULL DEFAULT '',
                            has_phone INTEGER NOT NULL DEFAULT 0,
                            has_website INTEGER NOT NULL DEFAULT 0,
                            snippet TEXT NOT NULL DEFAULT '',
                            tg_username TEXT DEFAULT '',
                            tg_user_id INTEGER DEFAULT NULL,
                            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                        )
                        """
                    )
                    await db.execute(
                        """
                        INSERT INTO contractors_migrated (
                            id, source, region, phone, website, company_name,
                            category_tags, has_phone, has_website, snippet,
                            tg_username, tg_user_id, created_at
                        )
                        SELECT 
                            id,
                            COALESCE(source, 'form'),
                            COALESCE(region, 'Не указан'),
                            COALESCE(phone, 'Не указан'),
                            COALESCE(website, COALESCE(site, 'Не указан')),
                            COALESCE(company_name, 'Не указано'),
                            COALESCE(category_tags, ''),
                            COALESCE(has_phone, 1),
                            COALESCE(has_website, 1),
                            COALESCE(snippet, ''),
                            COALESCE(username, ''),
                            user_id,
                            created_at
                        FROM contractors
                        """
                    )
                    await db.execute("DROP TABLE contractors")
                    await db.execute("ALTER TABLE contractors_migrated RENAME TO contractors")

            await db.execute("CREATE INDEX IF NOT EXISTS idx_contractors_source ON contractors(source)")
            await db.execute("CREATE INDEX IF NOT EXISTS idx_contractors_has_phone ON contractors(has_phone)")
            await db.execute("CREATE INDEX IF NOT EXISTS idx_contractors_has_website ON contractors(has_website)")
            await db.execute("CREATE INDEX IF NOT EXISTS idx_contractors_created_at ON contractors(created_at)")

            # Таблица регионов для админки и парсера
            await db.execute(
                """
                CREATE TABLE IF NOT EXISTS admin_regions (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    name TEXT NOT NULL UNIQUE,
                    is_selected INTEGER NOT NULL DEFAULT 1,
                    is_custom INTEGER NOT NULL DEFAULT 0,
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                )
                """
            )
            await db.execute("CREATE INDEX IF NOT EXISTS idx_admin_regions_selected ON admin_regions(is_selected)")

            # Заполняем дефолтные регионы, если таблица пуста
            async with db.execute("SELECT COUNT(*) FROM admin_regions") as cur:
                row = await cur.fetchone()
                reg_count = row[0] if row else 0

            if reg_count == 0:
                for reg in DEFAULT_ADMIN_REGIONS:
                    await db.execute(
                        "INSERT OR IGNORE INTO admin_regions (name, is_selected, is_custom) VALUES (?, 1, 0)",
                        (reg,),
                    )
                logger.info("Инициализировано %d базовых регионов РФ в SQLite.", len(DEFAULT_ADMIN_REGIONS))

            await db.commit()
        logger.info("Таблицы и индексы SQLite успешно проверены.")


async def save_lead(
    source: str = "web_parser",
    region: str = "Не указан",
    phone: str = "Не указан",
    website: str = "Не указан",
    company_name: str = "Не указано",
    category_tags: str = "",
    snippet: str = "",
    tg_username: str | None = None,
    tg_user_id: int | None = None,
) -> tuple[int, bool]:
    """
    Сохраняет подрядчика с аккуратной дедупликацией (PostgreSQL или SQLite).
    Возвращает (lead_id, is_new: bool).
    """
    region = (region or "").strip() or "Не указан"
    phone = (phone or "").strip() or "Не указан"
    website = (website or "").strip() or "Не указан"
    company_name = (company_name or "").strip() or "Не указано"
    category_tags = (category_tags or "").strip()
    snippet = (snippet or "").strip()
    tg_username = (tg_username or "").strip()

    norm_web = normalize_website(website)
    norm_phone = normalize_phone_match(phone)

    has_phone = 1 if norm_phone else 0
    has_website = 1 if norm_web else 0

    # ==================== ВЕТКА POSTGRESQL ====================
    if config.DATABASE_URL:
        pool = await get_pg_pool()
        async with pool.acquire() as conn:
            existing_row = None

            if norm_web:
                existing_row = await conn.fetchrow(
                    "SELECT * FROM contractors WHERE website ILIKE $1 LIMIT 1",
                    f"%{norm_web}%",
                )

            if not existing_row and norm_phone:
                existing_row = await conn.fetchrow(
                    "SELECT * FROM contractors WHERE phone LIKE $1 LIMIT 1",
                    f"%{norm_phone}%",
                )

            if not existing_row and company_name != "Не указано" and region != "Не указан":
                existing_row = await conn.fetchrow(
                    "SELECT * FROM contractors WHERE company_name = $1 AND region = $2 LIMIT 1",
                    company_name,
                    region,
                )

            if existing_row:
                existing_id = existing_row["id"]
                combined_tags = merge_tags(existing_row["category_tags"] or "", category_tags)

                updated_phone = existing_row["phone"]
                if (not updated_phone or updated_phone == "Не указан") and phone != "Не указан":
                    updated_phone = phone

                updated_web = existing_row["website"]
                if (not updated_web or updated_web == "Не указан") and website != "Не указан":
                    updated_web = website

                updated_region = existing_row["region"]
                if (not updated_region or updated_region == "Не указан") and region != "Не указан":
                    updated_region = region

                updated_snippet = existing_row["snippet"] or ""
                if len(snippet) > len(updated_snippet):
                    updated_snippet = snippet

                cur_has_phone = 1 if normalize_phone_match(updated_phone) else 0
                cur_has_web = 1 if normalize_website(updated_web) else 0

                await conn.execute(
                    """
                    UPDATE contractors
                    SET category_tags = $1,
                        phone = $2,
                        website = $3,
                        region = $4,
                        snippet = $5,
                        has_phone = $6,
                        has_website = $7
                    WHERE id = $8
                    """,
                    combined_tags,
                    updated_phone,
                    updated_web,
                    updated_region,
                    updated_snippet,
                    cur_has_phone,
                    cur_has_web,
                    existing_id,
                )
                return existing_id, False

            # Вставка новой записи в Postgres
            row = await conn.fetchrow(
                """
                INSERT INTO contractors (
                    source, region, phone, website, company_name,
                    category_tags, has_phone, has_website, snippet,
                    tg_username, tg_user_id
                )
                VALUES ($1, $2, $3, $4, $5, $6, $7, $8, $9, $10, $11)
                RETURNING id
                """,
                source,
                region,
                phone,
                website,
                company_name,
                category_tags,
                has_phone,
                has_website,
                snippet,
                tg_username,
                tg_user_id,
            )
            return row["id"], True

    # ==================== ВЕТКА SQLITE ====================
    async with _sqlite_lock:
        async with get_sqlite_connection() as db:
            db.row_factory = aiosqlite.Row

            existing_row = None

            if norm_web:
                async with db.execute(
                    "SELECT * FROM contractors WHERE website LIKE ? LIMIT 1",
                    (f"%{norm_web}%",),
                ) as cur:
                    existing_row = await cur.fetchone()

            if not existing_row and norm_phone:
                async with db.execute(
                    "SELECT * FROM contractors WHERE phone LIKE ? LIMIT 1",
                    (f"%{norm_phone}%",),
                ) as cur:
                    existing_row = await cur.fetchone()

            if not existing_row and company_name != "Не указано" and region != "Не указан":
                async with db.execute(
                    "SELECT * FROM contractors WHERE company_name = ? AND region = ? LIMIT 1",
                    (company_name, region),
                ) as cur:
                    existing_row = await cur.fetchone()

            if existing_row:
                existing_id = existing_row["id"]
                combined_tags = merge_tags(existing_row["category_tags"] or "", category_tags)

                updated_phone = existing_row["phone"]
                if (not updated_phone or updated_phone == "Не указан") and phone != "Не указан":
                    updated_phone = phone

                updated_web = existing_row["website"]
                if (not updated_web or updated_web == "Не указан") and website != "Не указан":
                    updated_web = website

                updated_region = existing_row["region"]
                if (not updated_region or updated_region == "Не указан") and region != "Не указан":
                    updated_region = region

                updated_snippet = existing_row["snippet"] or ""
                if len(snippet) > len(updated_snippet):
                    updated_snippet = snippet

                cur_has_phone = 1 if normalize_phone_match(updated_phone) else 0
                cur_has_web = 1 if normalize_website(updated_web) else 0

                await db.execute(
                    """
                    UPDATE contractors
                    SET category_tags = ?,
                        phone = ?,
                        website = ?,
                        region = ?,
                        snippet = ?,
                        has_phone = ?,
                        has_website = ?
                    WHERE id = ?
                    """,
                    (
                        combined_tags,
                        updated_phone,
                        updated_web,
                        updated_region,
                        updated_snippet,
                        cur_has_phone,
                        cur_has_web,
                        existing_id,
                    ),
                )
                await db.commit()
                return existing_id, False

            now_str = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
            cursor = await db.execute(
                """
                INSERT INTO contractors (
                    source, region, phone, website, company_name,
                    category_tags, has_phone, has_website, snippet,
                    tg_username, tg_user_id, created_at
                )
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    source,
                    region,
                    phone,
                    website,
                    company_name,
                    category_tags,
                    has_phone,
                    has_website,
                    snippet,
                    tg_username,
                    tg_user_id,
                    now_str,
                ),
            )
            await db.commit()
            return cursor.lastrowid or 0, True


async def add_contractor(
    user_id: int,
    username: str | None,
    region: str,
    site: str,
    phone: str,
) -> int:
    """Сохранение лида из анкеты Telegram-бота."""
    tags = "Анкета бота, Детские площадки, МАФы, Заборы и ограждения"
    lead_id, _ = await save_lead(
        source="form",
        region=region,
        phone=phone,
        website=site,
        company_name=f"Подрядчик (@{username})" if username else f"Подрядчик (ID {user_id})",
        category_tags=tags,
        snippet="Заявка через Telegram-бота на получение прайс-листа и каталога",
        tg_username=username,
        tg_user_id=user_id,
    )
    return lead_id


async def get_all_contractors() -> list[dict[str, Any]]:
    """Получает все записи из базы данных, отсортированные от новых к старым."""
    query = """
        SELECT id, source, region, phone, website, company_name,
               category_tags, has_phone, has_website, snippet,
               tg_username, tg_user_id, created_at
        FROM contractors
        ORDER BY id DESC
    """

    if config.DATABASE_URL:
        pool = await get_pg_pool()
        async with pool.acquire() as conn:
            rows = await conn.fetch(query)
            result = []
            for r in rows:
                item = dict(r)
                if item.get("created_at") and hasattr(item["created_at"], "strftime"):
                    item["created_at"] = item["created_at"].strftime("%Y-%m-%d %H:%M:%S")
                result.append(item)
            return result
    else:
        async with get_sqlite_connection() as db:
            db.row_factory = aiosqlite.Row
            async with db.execute(query) as cursor:
                rows = await cursor.fetchall()
                return [dict(row) for row in rows]


async def get_stats() -> dict[str, Any]:
    """Возвращает подробную статистику базы данных."""
    target_tags = [
        "Детские площадки",
        "Заборы и ограждения",
        "Парки и скверы",
        "Детсады и школы",
        "Дворы и ЖК",
        "МАФы",
    ]

    if config.DATABASE_URL:
        pool = await get_pg_pool()
        async with pool.acquire() as conn:
            total_count = await conn.fetchval("SELECT COUNT(*) FROM contractors") or 0
            with_phone = await conn.fetchval("SELECT COUNT(*) FROM contractors WHERE has_phone = 1") or 0
            with_website = await conn.fetchval("SELECT COUNT(*) FROM contractors WHERE has_website = 1") or 0
            last_24h_count = await conn.fetchval(
                "SELECT COUNT(*) FROM contractors WHERE created_at >= NOW() - INTERVAL '1 day'"
            ) or 0

            source_rows = await conn.fetch(
                "SELECT source, COUNT(*) as cnt FROM contractors GROUP BY source"
            )
            sources = {r["source"]: r["cnt"] for r in source_rows}

            categories_count = {}
            for tag in target_tags:
                cnt = await conn.fetchval(
                    "SELECT COUNT(*) FROM contractors WHERE category_tags ILIKE $1",
                    f"%{tag}%",
                ) or 0
                categories_count[tag] = cnt

            return {
                "total_count": total_count,
                "with_phone": with_phone,
                "with_website": with_website,
                "last_24h_count": last_24h_count,
                "sources": sources,
                "categories": categories_count,
            }
    else:
        async with get_sqlite_connection() as db:
            db.row_factory = aiosqlite.Row

            async with db.execute("SELECT COUNT(*) FROM contractors") as cur:
                row = await cur.fetchone()
                total_count = row[0] if row else 0

            async with db.execute("SELECT COUNT(*) FROM contractors WHERE has_phone = 1") as cur:
                row = await cur.fetchone()
                with_phone = row[0] if row else 0

            async with db.execute("SELECT COUNT(*) FROM contractors WHERE has_website = 1") as cur:
                row = await cur.fetchone()
                with_website = row[0] if row else 0

            async with db.execute(
                """
                SELECT COUNT(*) FROM contractors
                WHERE created_at >= datetime('now', '-1 day', 'localtime')
                   OR created_at >= datetime('now', '-1 day')
                """
            ) as cur:
                row = await cur.fetchone()
                last_24h_count = row[0] if row else 0

            async with db.execute(
                "SELECT source, COUNT(*) as cnt FROM contractors GROUP BY source"
            ) as cur:
                source_rows = await cur.fetchall()
                sources = {r["source"]: r["cnt"] for r in source_rows}

            categories_count = {}
            for tag in target_tags:
                async with db.execute(
                    "SELECT COUNT(*) FROM contractors WHERE category_tags LIKE ?",
                    (f"%{tag}%",),
                ) as cur:
                    r = await cur.fetchone()
                    categories_count[tag] = r[0] if r else 0

            return {
                "total_count": total_count,
                "with_phone": with_phone,
                "with_website": with_website,
                "last_24h_count": last_24h_count,
                "sources": sources,
                "categories": categories_count,
            }


# ==================== УПРАВЛЕНИЕ РЕГИОНАМИ ДЛЯ ПАРСИНГА ====================

async def get_admin_regions() -> list[dict[str, Any]]:
    """Возвращает список всех регионов с их статусом выбора."""
    query = "SELECT id, name, is_selected, is_custom FROM admin_regions ORDER BY is_custom ASC, id ASC"
    if config.DATABASE_URL:
        pool = await get_pg_pool()
        async with pool.acquire() as conn:
            rows = await conn.fetch(query)
            return [
                {
                    "id": r["id"],
                    "name": r["name"],
                    "is_selected": bool(r["is_selected"]),
                    "is_custom": bool(r["is_custom"]),
                }
                for r in rows
            ]
    else:
        async with get_sqlite_connection() as db:
            db.row_factory = aiosqlite.Row
            async with db.execute(query) as cur:
                rows = await cur.fetchall()
                return [
                    {
                        "id": r["id"],
                        "name": r["name"],
                        "is_selected": bool(r["is_selected"]),
                        "is_custom": bool(r["is_custom"]),
                    }
                    for r in rows
                ]


async def toggle_admin_region(region_id: int) -> bool:
    """Переключает статус выбора региона (0 <-> 1). Возвращает новый статус."""
    if config.DATABASE_URL:
        pool = await get_pg_pool()
        async with pool.acquire() as conn:
            row = await conn.fetchrow("SELECT is_selected FROM admin_regions WHERE id = $1", region_id)
            if not row:
                return False
            new_val = 0 if row["is_selected"] else 1
            await conn.execute("UPDATE admin_regions SET is_selected = $1 WHERE id = $2", new_val, region_id)
            return bool(new_val)
    else:
        async with get_sqlite_connection() as db:
            db.row_factory = aiosqlite.Row
            async with db.execute("SELECT is_selected FROM admin_regions WHERE id = ?", (region_id,)) as cur:
                row = await cur.fetchone()
                if not row:
                    return False
                new_val = 0 if row["is_selected"] else 1
            await db.execute("UPDATE admin_regions SET is_selected = ? WHERE id = ?", (new_val, region_id))
            await db.commit()
            return bool(new_val)


async def select_all_admin_regions(select_all: bool = True) -> None:
    """Выбирает все регионы (1) или сбрасывает все (0)."""
    val = 1 if select_all else 0
    if config.DATABASE_URL:
        pool = await get_pg_pool()
        async with pool.acquire() as conn:
            await conn.execute("UPDATE admin_regions SET is_selected = $1", val)
    else:
        async with get_sqlite_connection() as db:
            await db.execute("UPDATE admin_regions SET is_selected = ?", (val,))
            await db.commit()


async def add_custom_admin_regions(names: list[str]) -> list[str]:
    """Добавляет пользовательские регионы, сразу помечая их выбранными."""
    added = []
    if config.DATABASE_URL:
        pool = await get_pg_pool()
        async with pool.acquire() as conn:
            for raw_name in names:
                name = raw_name.strip()
                if len(name) < 2:
                    continue
                await conn.execute(
                    """
                    INSERT INTO admin_regions (name, is_selected, is_custom)
                    VALUES ($1, 1, 1)
                    ON CONFLICT (name) DO UPDATE SET is_selected = 1
                    """,
                    name,
                )
                added.append(name)
    else:
        async with get_sqlite_connection() as db:
            for raw_name in names:
                name = raw_name.strip()
                if len(name) < 2:
                    continue
                await db.execute(
                    """
                    INSERT INTO admin_regions (name, is_selected, is_custom)
                    VALUES (?, 1, 1)
                    ON CONFLICT(name) DO UPDATE SET is_selected = 1
                    """,
                    (name,),
                )
                added.append(name)
            await db.commit()
    return added


async def get_selected_region_names() -> list[str]:
    """Возвращает список названий всех отмеченных администратором регионов."""
    query = "SELECT name FROM admin_regions WHERE is_selected = 1 ORDER BY is_custom ASC, id ASC"
    if config.DATABASE_URL:
        pool = await get_pg_pool()
        async with pool.acquire() as conn:
            rows = await conn.fetch(query)
            return [r["name"] for r in rows]
    else:
        async with get_sqlite_connection() as db:
            db.row_factory = aiosqlite.Row
            async with db.execute(query) as cur:
                rows = await cur.fetchall()
                return [r["name"] for r in rows]
