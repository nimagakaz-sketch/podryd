"""HTTP-сервер и API для Telegram Mini App (Web App) базы B2B-подрядчиков."""

import hashlib
import hmac
import json
import logging
import os
from pathlib import Path
from typing import Any
from urllib.parse import parse_qsl

from aiohttp import web

import config
import database

logger = logging.getLogger(__name__)

WEBAPP_DIR = Path(__file__).resolve().parent / "webapp"


def validate_telegram_init_data(init_data_raw: str, bot_token: str) -> dict[str, Any] | None:
    """
    Проверяет валидность строки initData от Telegram Web App по алгоритму HMAC-SHA-256.
    Возвращает dict с данными пользователя (user: dict, etc.), если валидно, иначе None.
    """
    if not init_data_raw:
        return None
    try:
        parsed_data = dict(parse_qsl(init_data_raw, keep_blank_values=True))
        if "hash" not in parsed_data:
            return None
        received_hash = parsed_data.pop("hash")

        # data_check_string: отсортированные по алфавиту ключи k=v через перевод строки
        sorted_items = sorted(parsed_data.items(), key=lambda x: x[0])
        data_check_string = "\n".join(f"{k}={v}" for k, v in sorted_items)

        # secret_key = HMAC_SHA256(key=b"WebAppData", msg=bot_token)
        secret_key = hmac.new(b"WebAppData", bot_token.encode("utf-8"), hashlib.sha256).digest()
        # calculated_hash = HMAC_SHA256(key=secret_key, msg=data_check_string)
        calculated_hash = hmac.new(secret_key, data_check_string.encode("utf-8"), hashlib.sha256).hexdigest()

        if hmac.compare_digest(calculated_hash, received_hash):
            user_raw = parsed_data.get("user")
            user_dict = json.loads(user_raw) if user_raw else {}
            return {
                "user": user_dict,
                "auth_date": parsed_data.get("auth_date"),
                "query_id": parsed_data.get("query_id"),
            }
        return None
    except Exception as e:
        logger.warning("Ошибка при проверке подписи Telegram initData: %s", e)
        return None


def check_auth(request: web.Request) -> tuple[bool, str]:
    """
    Проверяет права доступа к API.
    1. Если передан initData (через заголовок или query) — проверяет подпись Telegram и ADMIN_IDS.
    2. Если запрос из браузера напрямую — проверяет токен или локальный хост.
    """
    init_data = (
        request.headers.get("X-Telegram-Init-Data")
        or request.headers.get("Authorization", "").replace("tma ", "").replace("Tma ", "").strip()
        or request.query.get("initData", "").strip()
    )

    if init_data:
        val = validate_telegram_init_data(init_data, config.BOT_TOKEN)
        if val and val.get("user"):
            user_id = val["user"].get("id")
            if user_id in config.ADMIN_IDS:
                return True, f"Admin Telegram ID {user_id}"
            return False, f"User {user_id} is not an authorized administrator"
        return False, "Invalid Telegram WebApp signature"

    # Прямой доступ через браузер по токену администратора
    token_param = request.query.get("token") or request.headers.get("X-Admin-Token")
    if token_param and token_param == config.BOT_TOKEN:
        return True, "Bot Token Admin"

    # Доступ для администратора по Telegram ID в query (например для отладки в десктоп-браузере)
    admin_id_param = request.query.get("admin_id")
    if admin_id_param and admin_id_param.isdigit() and int(admin_id_param) in config.ADMIN_IDS:
        return True, f"Admin ID param {admin_id_param}"

    # Локальная разработка
    host = request.host
    if "localhost" in host or "127.0.0.1" in host:
        return True, "Localhost developer access"

    return False, "Требуется авторизация через Telegram Mini App"


# ==================== CORS MIDDLEWARE ====================

@web.middleware
async def cors_middleware(request: web.Request, handler: Any) -> web.Response:
    """Добавляет CORS-заголовки для работы Web App из Telegram и браузеров."""
    if request.method == "OPTIONS":
        response = web.Response(status=204)
    else:
        try:
            response = await handler(request)
        except web.HTTPException as ex:
            response = ex

    response.headers["Access-Control-Allow-Origin"] = "*"
    response.headers["Access-Control-Allow-Methods"] = "GET, POST, OPTIONS"
    response.headers["Access-Control-Allow-Headers"] = (
        "Content-Type, Authorization, X-Telegram-Init-Data, X-Admin-Token"
    )
    return response


# ==================== ОБРАБОТЧИКИ ЭНДПОИНТОВ ====================

async def handle_index(request: web.Request) -> web.Response:
    """Отдача главной страницы Mini App (webapp/index.html)."""
    index_file = WEBAPP_DIR / "index.html"
    if not index_file.exists():
        return web.Response(text="Web App index.html not found", status=404)

    html_content = index_file.read_text(encoding="utf-8")
    return web.Response(text=html_content, content_type="text/html")


async def handle_health(request: web.Request) -> web.Response:
    """Health-check эндпоинт для Render Web Service."""
    return web.Response(text="OK - Podryd Bot & Mini App are running", status=200)


async def handle_get_leads(request: web.Request) -> web.Response:
    """
    GET /api/leads
    Возвращает список подрядчиков с фильтрами, пагинацией и сводную статистику.
    """
    is_ok, reason = check_auth(request)
    if not is_ok:
        logger.warning("Отказ в доступе к /api/leads: %s", reason)
        return web.json_response({"success": False, "error": reason}, status=403)

    source = request.query.get("source")
    has_phone_raw = request.query.get("has_phone")
    has_phone = int(has_phone_raw) if has_phone_raw in ("0", "1") else None

    has_website_raw = request.query.get("has_website")
    has_website = int(has_website_raw) if has_website_raw in ("0", "1") else None

    region = request.query.get("region")
    status = request.query.get("status")
    search = request.query.get("search")

    try:
        limit = int(request.query.get("limit", "150"))
    except ValueError:
        limit = 150

    try:
        offset = int(request.query.get("offset", "0"))
    except ValueError:
        offset = 0

    try:
        leads, total = await database.get_leads_filtered(
            source=source,
            has_phone=has_phone,
            has_website=has_website,
            region=region,
            status=status,
            search=search,
            limit=limit,
            offset=offset,
        )
        stats = await database.get_leads_summary_stats()
        active_regions = await database.get_selected_region_names()

        return web.json_response({
            "success": True,
            "stats": stats,
            "leads": leads,
            "total": total,
            "regions": active_regions,
        })
    except Exception as e:
        logger.error("Ошибка при получении лидов для Web App: %s", e, exc_info=True)
        return web.json_response({"success": False, "error": str(e)}, status=500)


async def handle_update_lead_status(request: web.Request) -> web.Response:
    """
    POST /api/leads/{lead_id}/status
    Обновляет статус работы с подрядчиком и заметку.
    """
    is_ok, reason = check_auth(request)
    if not is_ok:
        logger.warning("Отказ в доступе к обновлению статуса: %s", reason)
        return web.json_response({"success": False, "error": reason}, status=403)

    try:
        lead_id = int(request.match_info["lead_id"])
    except (KeyError, ValueError):
        return web.json_response({"success": False, "error": "Некорректный ID подрядчика"}, status=400)

    try:
        payload = await request.json()
    except Exception:
        return web.json_response({"success": False, "error": "Некорректный JSON"}, status=400)

    status = payload.get("status", "").strip().lower()
    notes = payload.get("notes")
    if notes is not None:
        notes = str(notes).strip()

    allowed = {"new", "price_sent", "called", "offer_sent", "deal", "rejected"}
    if status not in allowed:
        return web.json_response(
            {"success": False, "error": f"Недопустимый статус. Разрешены: {', '.join(allowed)}"},
            status=400,
        )

    updated = await database.update_lead_status(lead_id, status, notes)
    if not updated:
        return web.json_response({"success": False, "error": "Подрядчик не найден"}, status=404)

    logger.info("Обновлен статус подрядчика #%d -> '%s' (notes: %s)", lead_id, status, bool(notes))
    return web.json_response({
        "success": True,
        "lead_id": lead_id,
        "status": status,
        "notes": notes,
    })


async def handle_get_regions(request: web.Request) -> web.Response:
    """
    GET /api/regions
    Возвращает список доступных регионов для фильтра.
    """
    try:
        regions = await database.get_selected_region_names()
        return web.json_response({"success": True, "regions": regions})
    except Exception as e:
        return web.json_response({"success": False, "error": str(e)}, status=500)


# ==================== СОЗДАНИЕ И ЗАПУСК ПРИЛОЖЕНИЯ ====================

def create_webapp() -> web.Application:
    """Создает и настраивает web.Application с маршрутами API и отдачей статики."""
    app = web.Application(middlewares=[cors_middleware])

    # Страницы
    app.router.add_get("/", handle_index)
    app.router.add_get("/webapp", handle_index)
    app.router.add_get("/health", handle_health)

    # API
    app.router.add_get("/api/leads", handle_get_leads)
    app.router.add_post("/api/leads/{lead_id}/status", handle_update_lead_status)
    app.router.add_get("/api/regions", handle_get_regions)

    # Статика (если есть дополнительные файлы в webapp/)
    if WEBAPP_DIR.exists():
        app.router.add_static("/static/", path=WEBAPP_DIR, name="static")

    return app


async def start_webapp_server(port: int) -> web.AppRunner:
    """Запускает HTTP-сервер на 0.0.0.0:port."""
    app = create_webapp()
    runner = web.AppRunner(app)
    await runner.setup()
    site = web.TCPSite(runner, "0.0.0.0", port)
    await site.start()
    logger.info("Mini App HTTP сервер успешно запущен на 0.0.0.0:%d (Render Web Service)", port)
    return runner
