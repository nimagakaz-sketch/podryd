"""Асинхронный веб-парсер B2B-подрядчиков по благоустройству."""

import asyncio
import logging
import random
import re
from urllib.parse import parse_qs, unquote, urljoin, urlparse

import aiohttp
from bs4 import BeautifulSoup

import config
import database

logger = logging.getLogger(__name__)

# Ротация User-Agent заголовков
USER_AGENTS = [
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36",
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36",
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64; rv:123.0) Gecko/20100101 Firefox/123.0",
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 14.3; rv:123.0) Gecko/20100101 Firefox/123.0",
    "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36",
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/17.3 Safari/605.1.15",
]

# Домены поисковиков и соцсетей, которые не являются целевыми компаниями
EXCLUDED_DOMAINS = {
    "google.com", "google.ru", "yandex.ru", "ya.ru", "dzen.ru",
    "duckduckgo.com", "bing.com", "mail.ru", "rambler.ru",
    "vk.com", "t.me", "telegram.org", "youtube.com", "youtu.be",
    "instagram.com", "facebook.com", "twitter.com", "x.com",
    "wikipedia.org", "avito.ru", "hh.ru", "rabota.ru", "superjob.ru",
    "gosuslugi.ru", "zakupki.gov.ru", "rbc.ru", "ria.ru", "kp.ru",
}

# Словарь ключевых слов для автоматического тегирования
CATEGORY_KEYWORDS = {
    "Детские площадки": [
        "детск площад", "игров площад", "детск комплекс", "детск город",
        "детск горк", "качалк", "карусел", "песочниц", "лазалк", "лабиринт",
        "детское игровое оборудование", "детские игровые площадки", "городок", "горок"
    ],
    "Заборы и ограждения": [
        "забор", "огражден", "огражд", "3d огражден", "евроштакетник", "газонн огражден",
        "металлоконструкц", "перил", "ограды", "оград", "сетка рабица", "профнастил забор"
    ],
    "Парки и скверы": [
        "парк", "сквер", "благоустройств", "озеленен", "городск сред",
        "общественн пространств", "парков мебель", "алле", "пешеходн зон"
    ],
    "Детсады и школы": [
        "детск сад", "детсад", "школ", "доу", "детск учрежден",
        "образовательн учрежден", "для детских садов"
    ],
    "Дворы и ЖК": [
        "двор", "жилой комплекс", "придомов территори", "жк", "тсж",
        "управляющ компан", "новостройк", "дворов территори"
    ],
    "МАФы": [
        "маф", "мал архитектурн форм", "скамейк", "скамеек", "скамей", "урн", "лавочк",
        "лавк", "пергол", "теневой навес", "велопарковк", "беседк", "вазон"
    ],
}

# Регионы и города РФ для определения геопривязки (корневые основы)
CITIES_MAP = {
    "москв": "Москва и МО",
    "московск": "Москва и МО",
    "петербург": "Санкт-Петербург",
    "спб": "Санкт-Петербург",
    "ленинградск": "Санкт-Петербург и ЛО",
    "екатеринбург": "Екатеринбург",
    "свердловск": "Свердловская область",
    "краснодар": "Краснодарский край",
    "кубан": "Краснодарский край",
    "сочи": "Краснодарский край",
    "казан": "Казань / Татарстан",
    "татарстан": "Казань / Татарстан",
    "новосибирск": "Новосибирск",
    "нижний новгород": "Нижний Новгород",
    "нижегородск": "Нижний Новгород",
    "самар": "Самара",
    "ростов": "Ростов-на-Дону",
    "уф": "Уфа / Башкортостан",
    "башкортостан": "Уфа / Башкортостан",
    "воронеж": "Воронеж",
    "тюмен": "Тюмень",
    "перм": "Пермь",
    "красноярск": "Красноярск",
    "челябинск": "Челябинск",
    "волгоград": "Волгоград",
}


def get_random_headers() -> dict[str, str]:
    """Генерирует заголовки с ротацией User-Agent."""
    return {
        "User-Agent": random.choice(USER_AGENTS),
        "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/webp,*/*;q=0.8",
        "Accept-Language": "ru-RU,ru;q=0.9,en-US;q=0.8,en;q=0.7",
        "Connection": "keep-alive",
        "DNT": "1",
    }


def extract_phones(text: str) -> list[str]:
    """Извлекает и нормализует телефонные номера РФ."""
    phones: list[str] = []
    # Паттерн для номеров РФ
    phone_pattern = re.compile(
        r"(?:(?:\+7|8|7)[\s\-\(]*(\d{3})[\s\-\)]*(\d{3})[\s\-]*(\d{2})[\s\-]*(\d{2})|"
        r"(?:\+7|8|7)[\s\-\(]*(\d{4})[\s\-\)]*(\d{2})[\s\-]*(\d{2})[\s\-]*(\d{2}))"
    )

    for match in phone_pattern.finditer(text):
        raw = match.group(0)
        digits = re.sub(r"\D", "", raw)
        if len(digits) == 11 and digits.startswith(("7", "8")):
            formatted = f"+7 ({digits[1:4]}) {digits[4:7]}-{digits[7:9]}-{digits[9:11]}"
            if formatted not in phones:
                phones.append(formatted)

    return phones[:4]


def detect_categories(text: str) -> list[str]:
    """Определяет категории/направления по тексту."""
    text_lower = text.lower()
    categories: list[str] = []

    for cat_name, keywords in CATEGORY_KEYWORDS.items():
        for kw in keywords:
            if kw in text_lower:
                categories.append(cat_name)
                break

    # Если ничего конкретного не найдено, но есть общие маркеры
    if not categories:
        if "благоустрой" in text_lower or "город" in text_lower or "территор" in text_lower:
            categories.extend(["Парки и скверы", "МАФы"])
        else:
            categories.append("Благоустройство")

    return categories


def detect_region(text: str, default_region: str = "Не указан") -> str:
    """Определяет регион по тексту страницы/адреса."""
    text_lower = text.lower()
    for kw, reg in CITIES_MAP.items():
        if kw in text_lower:
            return reg
    return default_region


def clean_company_name(raw_title: str) -> str:
    """Очищает заголовок страницы для получения названия компании."""
    if not raw_title:
        return "Не указано"

    parts = re.split(r"[\—\-\|\–\•]", raw_title)
    if parts:
        candidate = parts[0].strip()
        if len(candidate) > 2 and len(candidate) < 70:
            return candidate

    cleaned = raw_title.strip()
    return cleaned[:70] if cleaned else "Не указано"


class WebCollector:
    """Асинхронный сборщик подрядчиков по благоустройству."""

    def __init__(self) -> None:
        self.is_running = False
        self._cancel_requested = False

    async def fetch_page(
        self, session: aiohttp.ClientSession, url: str
    ) -> tuple[str | None, str | None]:
        """Загружает страницу и возвращает (HTML, финальный URL)."""
        try:
            headers = get_random_headers()
            async with session.get(
                url,
                headers=headers,
                timeout=aiohttp.ClientTimeout(total=12),
                allow_redirects=True,
                ssl=False,
            ) as resp:
                if resp.status == 200:
                    content_type = resp.headers.get("Content-Type", "").lower()
                    if "text/html" in content_type or not content_type:
                        html = await resp.text(errors="replace")
                        return html, str(resp.url)
        except Exception as e:
            logger.debug("Ошибка загрузки %s: %s", url, e)
        return None, None

    async def parse_search_results(
        self, session: aiohttp.ClientSession, query: str
    ) -> list[dict[str, str]]:
        """
        Ищет компании через поисковую выдачу DuckDuckGo HTML.
        Возвращает список найденных сайтов со сниппетами.
        """
        results: list[dict[str, str]] = []
        search_url = f"https://html.duckduckgo.com/html/?q={query}"

        html, _ = await self.fetch_page(session, search_url)
        if not html:
            return results

        soup = BeautifulSoup(html, "html.parser")
        result_nodes = soup.select(".result, .web-result")

        for node in result_nodes:
            # Извлекаем ссылку
            link_tag = node.select_one(".result__url, .result__title a, a.result__snippet")
            if not link_tag:
                continue

            raw_href = link_tag.get("href", "")
            # DuckDuckGo оборачивает URL в /l/?uddg=...
            target_url = raw_href
            if "uddg=" in raw_href:
                parsed_q = parse_qs(urlparse(raw_href).query)
                if "uddg" in parsed_q:
                    target_url = unquote(parsed_q["uddg"][0])

            parsed_target = urlparse(target_url)
            domain = parsed_target.netloc.lower()
            if not domain or any(exc in domain for exc in EXCLUDED_DOMAINS):
                continue

            title_tag = node.select_one(".result__title, h2")
            title = title_tag.get_text(strip=True) if title_tag else domain

            snippet_tag = node.select_one(".result__snippet")
            snippet = snippet_tag.get_text(strip=True) if snippet_tag else ""

            results.append({
                "url": target_url,
                "domain": domain,
                "title": title,
                "snippet": snippet,
            })

        return results

    async def scrape_target_site(
        self, session: aiohttp.ClientSession, site_info: dict[str, str], query_region: str
    ) -> dict[str, Any] | None:
        """Глубокий парсинг сайта: главная + поиск контактной страницы."""
        url = site_info["url"]
        domain = site_info["domain"]
        initial_title = site_info.get("title", domain)
        initial_snippet = site_info.get("snippet", "")

        html, final_url = await self.fetch_page(session, url)
        if not html:
            # Даже если главная не ответила, сохраняем сниппет и домен из поиска!
            cats = detect_categories(initial_title + " " + initial_snippet)
            return {
                "website": domain,
                "company_name": clean_company_name(initial_title),
                "region": query_region,
                "phone": "Не указан",
                "category_tags": ", ".join(cats),
                "snippet": initial_snippet or "Найдено по поисковому запросу благоустройства",
            }

        soup = BeautifulSoup(html, "html.parser")

        # Название компании из title или h1
        title_tag = soup.find("title")
        page_title = title_tag.get_text(strip=True) if title_tag else initial_title
        h1_tag = soup.find("h1")
        h1_text = h1_tag.get_text(strip=True) if h1_tag else ""

        full_text = soup.get_text(" ", strip=True)

        # Телефоны с главной страницы
        phones = extract_phones(full_text)

        # Ищем tel: ссылки
        for tel_a in soup.select('a[href^="tel:"]'):
            href = tel_a.get("href", "")
            raw_phone = href.replace("tel:", "").strip()
            extracted = extract_phones(raw_phone)
            for p in extracted:
                if p not in phones:
                    phones.append(p)

        # Ищем контактную страницу
        contact_urls: list[str] = []
        for a_tag in soup.find_all("a", href=True):
            href = a_tag["href"].lower()
            if any(part in href for part in [
                "contact", "kontakt", "o-nas", "about", "requisite",
                "rekvizit", "uslugi", "contacts"
            ]):
                full_contact_url = urljoin(final_url or url, a_tag["href"])
                if full_contact_url not in contact_urls:
                    contact_urls.append(full_contact_url)

        # Если нашли контактные страницы, парсим первую для доп. телефонов и адреса
        if contact_urls and len(phones) < 2:
            contact_html, _ = await self.fetch_page(session, contact_urls[0])
            if contact_html:
                contact_soup = BeautifulSoup(contact_html, "html.parser")
                contact_text = contact_soup.get_text(" ", strip=True)
                contact_phones = extract_phones(contact_text)
                for cp in contact_phones:
                    if cp not in phones:
                        phones.append(cp)
                full_text += " " + contact_text

        # Определение региона
        region = detect_region(full_text, default_region=query_region)

        # Определение категорий
        combined_text = f"{page_title} {h1_text} {initial_snippet} {full_text[:3000]}"
        categories = detect_categories(combined_text)

        # Сниппет
        snippet = initial_snippet
        if not snippet:
            meta_desc = soup.find("meta", attrs={"name": "description"})
            if meta_desc and meta_desc.get("content"):
                snippet = meta_desc["content"].strip()
            else:
                snippet = full_text[:250].replace("\n", " ").strip()

        company_name = clean_company_name(page_title or h1_text)

        return {
            "website": domain,
            "company_name": company_name,
            "region": region,
            "phone": ", ".join(phones) if phones else "Не указан",
            "category_tags": ", ".join(categories),
            "snippet": snippet,
        }

    async def run(
        self,
        progress_callback: Any = None,
    ) -> dict[str, int]:
        """
        Запуск цикла сбора данных по всем запросам и регионам.
        """
        if self.is_running:
            return {"status": "already_running", "added": 0, "updated": 0}

        self.is_running = True
        self._cancel_requested = False
        added_count = 0
        updated_count = 0
        processed_domains = set()

        logger.info("Запуск веб-парсера подрядчиков...")

        try:
            async with aiohttp.ClientSession() as session:
                # 1. Сбор по поисковым запросам и регионам
                queries_to_run = []
                for query in config.SEARCH_QUERIES:
                    for reg in config.TARGET_REGIONS[:4]:  # Первые 4 основных региона
                        queries_to_run.append((f"{query} {reg}", reg))

                total_tasks = len(queries_to_run) + len(config.SEED_URLS)
                current_step = 0

                # Обработка поисковых запросов
                for query_str, region_name in queries_to_run:
                    if self._cancel_requested:
                        break

                    current_step += 1
                    if progress_callback:
                        await progress_callback(
                            f"🔍 Сбор по запросу ({current_step}/{total_tasks}): «{query_str}»..."
                        )

                    search_results = await self.parse_search_results(session, query_str)
                    await asyncio.sleep(config.PARSER_DELAY)

                    for site_info in search_results[:config.PARSER_MAX_PER_QUERY]:
                        if self._cancel_requested:
                            break

                        domain = site_info["domain"]
                        if domain in processed_domains:
                            continue
                        processed_domains.add(domain)

                        lead_data = await self.scrape_target_site(session, site_info, region_name)
                        if lead_data:
                            _, is_new = await database.save_lead(
                                source="web_parser",
                                region=lead_data["region"],
                                phone=lead_data["phone"],
                                website=lead_data["website"],
                                company_name=lead_data["company_name"],
                                category_tags=lead_data["category_tags"],
                                snippet=lead_data["snippet"],
                            )
                            if is_new:
                                added_count += 1
                            else:
                                updated_count += 1

                        await asyncio.sleep(config.PARSER_DELAY)

                # 2. Обработка стартовых каталогов SEED_URLS
                for seed_url in config.SEED_URLS:
                    if self._cancel_requested:
                        break

                    current_step += 1
                    if progress_callback:
                        await progress_callback(f"🌐 Обработка каталога: {seed_url}...")

                    html, _ = await self.fetch_page(session, seed_url)
                    await asyncio.sleep(config.PARSER_DELAY)
                    if not html:
                        continue

                    soup = BeautifulSoup(html, "html.parser")
                    # Ищем внешние ссылки на организации
                    for a_tag in soup.find_all("a", href=True):
                        href = a_tag["href"]
                        parsed = urlparse(href)
                        if parsed.scheme in ("http", "https"):
                            dom = parsed.netloc.lower()
                            if dom and not any(exc in dom for exc in EXCLUDED_DOMAINS) and dom not in processed_domains:
                                processed_domains.add(dom)
                                lead_data = await self.scrape_target_site(
                                    session,
                                    {
                                        "url": href,
                                        "domain": dom,
                                        "title": a_tag.get_text(strip=True) or dom,
                                        "snippet": "Каталог благоустройства",
                                    },
                                    query_region="Не указан",
                                )
                                if lead_data:
                                    _, is_new = await database.save_lead(
                                        source="web_parser",
                                        region=lead_data["region"],
                                        phone=lead_data["phone"],
                                        website=lead_data["website"],
                                        company_name=lead_data["company_name"],
                                        category_tags=lead_data["category_tags"],
                                        snippet=lead_data["snippet"],
                                    )
                                    if is_new:
                                        added_count += 1
                                    else:
                                        updated_count += 1

                                await asyncio.sleep(config.PARSER_DELAY)

        except Exception as e:
            logger.error("Ошибка при работе веб-парсера: %s", e)
        finally:
            self.is_running = False

        logger.info(
            "Веб-парсер завершил работу. Новых: %d, обновлено: %d",
            added_count,
            updated_count,
        )
        return {
            "status": "completed",
            "added": added_count,
            "updated": updated_count,
            "total_processed": len(processed_domains),
        }


# Глобальный экземпляр сборщика
collector = WebCollector()
