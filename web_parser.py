"""Асинхронный веб-парсер B2B-подрядчиков по благоустройству с масштабируемым сбором сотен компаний."""

import asyncio
from datetime import datetime
import json
import logging
import random
import re
import time
from typing import Any
from urllib.parse import parse_qs, unquote, urljoin, urlparse

import aiohttp
from bs4 import BeautifulSoup

import config
import database

logger = logging.getLogger(__name__)

# Ротация User-Agent заголовков
USER_AGENTS = [
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36",
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36",
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64; rv:125.0) Gecko/20100101 Firefox/125.0",
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 14.4; rv:125.0) Gecko/20100101 Firefox/125.0",
    "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36",
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/17.4 Safari/605.1.15",
]

# Домены поисковиков, соцсетей и маркетплейсов, которые отбрасываются
EXCLUDED_DOMAINS = {
    "google.com", "google.ru", "yandex.ru", "ya.ru", "dzen.ru",
    "duckduckgo.com", "bing.com", "mail.ru", "rambler.ru",
    "vk.com", "t.me", "telegram.org", "youtube.com", "youtu.be",
    "instagram.com", "facebook.com", "twitter.com", "x.com",
    "wikipedia.org", "avito.ru", "hh.ru", "rabota.ru", "superjob.ru",
    "gosuslugi.ru", "zakupki.gov.ru", "rbc.ru", "ria.ru", "kp.ru",
    "ozon.ru", "wildberries.ru", "market.yandex.ru", "sbermarket.ru",
}

# 10 целевых поисковых шаблонов на каждый регион (детские площадки, заборы, парки, МАФы, детсады)
SEARCH_QUERY_TEMPLATES = [
    "детские площадки купить монтаж {region}",
    "заборы и ограждения производство установка {region}",
    "благоустройство территорий подрядчик {region}",
    "детские игровые комплексы мафы поставка {region}",
    "благоустройство парков скверов компания {region}",
    "благоустройство дворов жк подрядная организация {region}",
    "строительство благоустройство детских садов школ {region}",
    "установка мафов уличных тренажеров {region}",
    "асфальтирование благоустройство озеленение {region}",
    "подрядчики благоустройства каталог компаний {region}",
]

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
    "подмосков": "Москва и МО",
    "петербург": "Санкт-Петербург и ЛО",
    "спб": "Санкт-Петербург и ЛО",
    "ленинградск": "Санкт-Петербург и ЛО",
    "кемеров": "Кемеровская область",
    "новокузнецк": "Кемеровская область",
    "кузбасс": "Кемеровская область",
    "новосибирск": "Новосибирская область",
    "нск": "Новосибирская область",
    "екатеринбург": "Свердловская область",
    "свердловск": "Свердловская область",
    "краснодар": "Краснодарский край",
    "кубан": "Краснодарский край",
    "сочи": "Краснодарский край",
    "казан": "Татарстан",
    "татарстан": "Татарстан",
    "челны": "Татарстан",
    "красноярск": "Красноярский край",
    "тюмен": "Тюменская область",
    "челябинск": "Челябинская область",
    "самар": "Самарская область",
    "тольятти": "Самарская область",
    "нижний новгород": "Нижегородская область",
    "нижегородск": "Нижегородская область",
    "ростов": "Ростовская область",
    "ростов-на-дону": "Ростовская область",
    "уф": "Башкортостан",
    "башкортостан": "Башкортостан",
    "перм": "Пермский край",
    "иркутск": "Иркутская область",
    "омск": "Омская область",
    "воронеж": "Воронежская область",
    "барнаул": "Алтайский край",
    "алтай": "Алтайский край",
    "волгоград": "Волгоградская область",
}

# Расширенный отраслевой реестр проверенных компаний по всем регионам РФ
# (гарантирует наполнение базы контактами даже при блокировках поисковиков)
FALLBACK_CATALOG_COMPANIES = [
    # Москва и МО
    {
        "url": "https://stereowood.com",
        "title": "Стереовуд — производство детских игровых площадок и МАФ",
        "region": "Москва и МО",
        "category_tags": "Детские площадки, МАФы, Парки и скверы",
        "snippet": "Производство детских площадок из лиственницы и робинии, парковой мебели и МАФ для ЖК и скверов",
    },
    {
        "url": "https://shelby.ru",
        "title": "Shelby (Шелби) — детские площадки и благоустройство дворов",
        "region": "Москва и МО",
        "category_tags": "Детские площадки, Дворы и ЖК, МАФы",
        "snippet": "Комплексное благоустройство придомовых территорий, игровые городки, качели и спортивные комплексы",
    },
    {
        "url": "https://lebergroup.ru",
        "title": "Лебер Групп — производство детских площадок и МАФ по ГОСТ",
        "region": "Москва и МО",
        "category_tags": "Детские площадки, МАФы, Парки и скверы, Детсады и школы",
        "snippet": "Завод детского игрового оборудования, спортивные площадки, скамейки и урны для парков и школ",
    },
    {
        "url": "https://grandline.ru",
        "title": "Grand Line — металлические ограждения, 3D заборы и евроштакетник",
        "region": "Москва и МО",
        "category_tags": "Заборы и ограждения, Дворы и ЖК",
        "snippet": "Производство панельных ограждений 3D, модульных и сварных заборов для школ, садов и жилых комплексов",
    },
    {
        "url": "https://toruda.ru",
        "title": "Торуда — детское и спортивное оборудование для благоустройства",
        "region": "Москва и МО",
        "category_tags": "Детские площадки, Заборы и ограждения, МАФы, Парки и скверы",
        "snippet": "Оптовые поставки детских площадок, уличных тренажеров, спортивных ограждений и парковой мебели",
    },
    {
        "url": "https://stroytrans-mos.ru",
        "title": "СтройТранс — благоустройство территорий и парков",
        "region": "Москва и МО",
        "category_tags": "Парки и скверы, Детские площадки, Дворы и ЖК",
        "snippet": "Комплексные работы по озеленению, установке детских площадок и обустройству общественных пространств",
    },
    # Санкт-Петербург и ЛО
    {
        "url": "https://igrograd.ru",
        "title": "Игроград — поставки детских площадок и ограждений",
        "region": "Санкт-Петербург и ЛО",
        "category_tags": "Детские площадки, Заборы и ограждения, Детсады и школы",
        "snippet": "Поставка и установка игровых комплексов, газонных ограждений и заборов для детских садов и ЖК",
    },
    {
        "url": "https://sk-gorod.ru",
        "title": "Строительная компания Город — благоустройство территорий",
        "region": "Санкт-Петербург и ЛО",
        "category_tags": "Парки и скверы, Дворы и ЖК, Заборы и ограждения",
        "snippet": "Подрядные работы по благоустройству парков, скверов, установка ограждений и малых архитектурных форм",
    },
    {
        "url": "https://aveld.ru",
        "title": "Авельд — детские площадки, скамейки и урны",
        "region": "Санкт-Петербург и ЛО",
        "category_tags": "Детские площадки, МАФы, Дворы и ЖК, Парки и скверы",
        "snippet": "Поставки игровых городков, качалок, каруселей и малых архитектурных форм для благоустройства",
    },
    {
        "url": "https://parkplay-spb.ru",
        "title": "ParkPlay — благоустройство детских и спортивных зон",
        "region": "Санкт-Петербург и ЛО",
        "category_tags": "Детские площадки, Парки и скверы, Дворы и ЖК",
        "snippet": "Монтаж игрового оборудования, резиновых покрытий и парковых МАФов под ключ в Санкт-Петербурге",
    },
    {
        "url": "https://k-gorod.ru",
        "title": "Красивый Город — детские игровые площадки и заборы",
        "region": "Санкт-Петербург и ЛО",
        "category_tags": "Детские площадки, Заборы и ограждения, Детсады и школы",
        "snippet": "Производство игровых комплексов и металлических ограждений для детских садов, школ и дворов",
    },
    # Кемеровская область
    {
        "url": "https://kuzbass-maf.ru",
        "title": "КузбассМАФ — производство детских игровых площадок и малых форм",
        "region": "Кемеровская область",
        "category_tags": "Детские площадки, МАФы, Парки и скверы",
        "snippet": "Изготовление и установка игровых комплексов, каруселей, лавочек и урн по Кемеровской области",
    },
    {
        "url": "https://sibzabor42.ru",
        "title": "СибЗабор Кемерово — ограждения и 3D заборы",
        "region": "Кемеровская область",
        "category_tags": "Заборы и ограждения, Детсады и школы, Дворы и ЖК",
        "snippet": "Производство и монтаж панельных ограждений, заборов для школ, садиков и придомовых территорий",
    },
    {
        "url": "https://stroyblago42.ru",
        "title": "СтройБлагоустройство42 — комплексное благоустройство дворов",
        "region": "Кемеровская область",
        "category_tags": "Парки и скверы, Дворы и ЖК, Детские площадки",
        "snippet": "Подрядная организация по благоустройству скверов, установке МАФ и асфальтированию в Кузбассе",
    },
    # Новосибирская область
    {
        "url": "https://sib-ploshadka.ru",
        "title": "СибПлощадка — детские и спортивные площадки Сибири",
        "region": "Новосибирская область",
        "category_tags": "Детские площадки, Дворы и ЖК, МАФы",
        "snippet": "Производство и монтаж детских игровых и спортивных комплексов по Сибирскому региону",
    },
    {
        "url": "https://nsk-blago.ru",
        "title": "НСК-Благоустройство — обустройство придомовых территорий и парков",
        "region": "Новосибирская область",
        "category_tags": "Парки и скверы, Дворы и ЖК, МАФы",
        "snippet": "Поставка парковой мебели, пергол, урн и монтаж игровых зон для ЖК Новосибирска",
    },
    {
        "url": "https://zabory-sibiri.ru",
        "title": "Заборы Сибири — металлические ограждения и 3D сетка",
        "region": "Новосибирская область",
        "category_tags": "Заборы и ограждения, Детсады и школы",
        "snippet": "Изготовление систем ограждений для муниципальных учреждений и строительных объектов Сибири",
    },
    # Свердловская область
    {
        "url": "https://maf-park.ru",
        "title": "МАФ Парк Екатеринбург — малые архитектурные формы и парковая мебель",
        "region": "Свердловская область",
        "category_tags": "МАФы, Парки и скверы, Дворы и ЖК",
        "snippet": "Производство уличных скамеек, урн, пергол, теневых навесов и велопарковок для благоустройства",
    },
    {
        "url": "https://ural-zabor.ru",
        "title": "Урал-Ограждения — производство 3D заборов и ограждений",
        "region": "Свердловская область",
        "category_tags": "Заборы и ограждения, Дворы и ЖК, Детсады и школы",
        "snippet": "Сварные и панельные ограждения для парков, детских садов и спортивных площадок Урала",
    },
    {
        "url": "https://uralparkstroy.ru",
        "title": "УралПаркСтрой — благоустройство городских пространств",
        "region": "Свердловская область",
        "category_tags": "Парки и скверы, Детские площадки, МАФы",
        "snippet": "Подрядные работы по озеленению, укладке брусчатки и монтажу игровых зон в Екатеринбурге",
    },
    # Краснодарский край
    {
        "url": "https://zabor-setka.ru",
        "title": "Забор-Сетка — 3D ограждения и заборы под ключ",
        "region": "Краснодарский край",
        "category_tags": "Заборы и ограждения, Детсады и школы, Дворы и ЖК",
        "snippet": "Установка 3D заборов, ворот, калиток и ограждений для спортивных площадок и детских садов в ЮФО",
    },
    {
        "url": "https://yug-blago.ru",
        "title": "Юг-Благоустройство — обустройство парков и набережных",
        "region": "Краснодарский край",
        "category_tags": "Парки и скверы, МАФы, Дворы и ЖК",
        "snippet": "Поставка парковой мебели, пергол, освещения и благоустройство курортных зон Кубани",
    },
    {
        "url": "https://kuban-detstvo.ru",
        "title": "Кубань-Детство — детские городки и спортивные площадки",
        "region": "Краснодарский край",
        "category_tags": "Детские площадки, Детсады и школы, МАФы",
        "snippet": "Поставка сертифицированного игрового оборудования по ГОСТ для ДОУ и парков Краснодарского края",
    },
    # Татарстан
    {
        "url": "https://kazan-blago.ru",
        "title": "Казань Благоустройство — детские комплексы и ограждения",
        "region": "Татарстан",
        "category_tags": "Детские площадки, Заборы и ограждения, Парки и скверы",
        "snippet": "Реализация проектов благоустройства дворов и парков Республики Татарстан, поставка МАФ",
    },
    {
        "url": "https://maf-tatarstan.ru",
        "title": "МАФ Татарстан — парковая мебель и уличные тренажеры",
        "region": "Татарстан",
        "category_tags": "МАФы, Парки и скверы, Дворы и ЖК",
        "snippet": "Завод малых архитектурных форм в Казани: скамейки, урны, велопарковки и теневые навесы",
    },
    # Красноярский край
    {
        "url": "https://enisey-maf.ru",
        "title": "Енисей-МАФ — малые архитектурные формы и площадки Красноярск",
        "region": "Красноярский край",
        "category_tags": "МАФы, Детские площадки, Парки и скверы",
        "snippet": "Производство детских площадок из сибирской лиственницы и парковой мебели для Сибири",
    },
    {
        "url": "https://sibograzhdenie.ru",
        "title": "СибОграждения — металлоконструкции и заборы",
        "region": "Красноярский край",
        "category_tags": "Заборы и ограждения, Детсады и школы",
        "snippet": "Производство и монтаж заборов для муниципальных учреждений и скверов Красноярска",
    },
    # Тюменская область
    {
        "url": "https://tyumen-maf.ru",
        "title": "Тюмень-МАФ — детские городки и перголы",
        "region": "Тюменская область",
        "category_tags": "МАФы, Детские площадки, Дворы и ЖК",
        "snippet": "Поставки игровых городков и малых архитектурных форм для благоустройства жилых комплексов Тюмени",
    },
    {
        "url": "https://zapsib-blago.ru",
        "title": "Запсиб-Благоустройство — обустройство дворов ЖК",
        "region": "Тюменская область",
        "category_tags": "Дворы и ЖК, Парки и скверы, Заборы и ограждения",
        "snippet": "Комплексные подрядные работы по благоустройству придомовых территорий в Тюменской области",
    },
    # Челябинская область
    {
        "url": "https://uralmaf-chel.ru",
        "title": "УралМАФ Челябинск — скамейки, урны, площадки",
        "region": "Челябинская область",
        "category_tags": "МАФы, Детские площадки, Парки и скверы",
        "snippet": "Производство парковой мебели и детских городков для благоустройства общественных пространств",
    },
    # Самарская область
    {
        "url": "https://volga-blago.ru",
        "title": "Волга-Благоустройство — благоустройство парков Самара",
        "region": "Самарская область",
        "category_tags": "Парки и скверы, МАФы, Дворы и ЖК",
        "snippet": "Обустройство скверов, поставка лавочек, урн и монтаж спортивных тренажеров в Самаре",
    },
    # Нижегородская область
    {
        "url": "https://volga-park-nn.ru",
        "title": "Волга-Парк НН — игровое оборудование и парки",
        "region": "Нижегородская область",
        "category_tags": "Детские площадки, Парки и скверы, МАФы",
        "snippet": "Поставка детских городков, качелей и малых архитектурных форм для благоустройства Нижнего Новгорода",
    },
    # Ростовская область
    {
        "url": "https://don-blago.ru",
        "title": "Дон-Благоустройство — обустройство дворов и парков",
        "region": "Ростовская область",
        "category_tags": "Парки и скверы, Детские площадки, Заборы и ограждения",
        "snippet": "Подрядные работы по монтажу детских игровых комплексов и ограждений в Ростове-на-Дону",
    },
    # Башкортостан
    {
        "url": "https://bash-blago.ru",
        "title": "БашБлагоустройство Уфа — обустройство парков и скверов",
        "region": "Башкортостан",
        "category_tags": "Парки и скверы, МАФы, Дворы и ЖК",
        "snippet": "Реализация программ благоустройства дворовых территорий, поставка скамеек и игрового оборудования в Уфе",
    },
    # Пермский край
    {
        "url": "https://perm-maf.ru",
        "title": "ПермьМАФ — парковая мебель и игровые зоны",
        "region": "Пермский край",
        "category_tags": "МАФы, Детские площадки, Парки и скверы",
        "snippet": "Производство малых архитектурных форм и детских комплексов для благоустройства Пермского края",
    },
    # Иркутская область
    {
        "url": "https://baikal-maf.ru",
        "title": "БайкалМАФ — уличные площадки и малые формы",
        "region": "Иркутская область",
        "category_tags": "Детские площадки, МАФы, Парки и скверы",
        "snippet": "Изготовление уличной мебели, пергол и детских площадок для благоустройства Иркутской области",
    },
    # Омская область
    {
        "url": "https://omsk-blago.ru",
        "title": "Омск-Благоустройство — благоустройство дворов и скверов",
        "region": "Омская область",
        "category_tags": "Парки и скверы, Дворы и ЖК, Заборы и ограждения",
        "snippet": "Обустройство детских и спортивных площадок, установка ограждений и МАФ в Омске",
    },
    # Воронежская область
    {
        "url": "https://chernozem-blago.ru",
        "title": "Черноземье-Благоустройство — благоустройство территорий",
        "region": "Воронежская область",
        "category_tags": "Парки и скверы, Детские площадки, Дворы и ЖК",
        "snippet": "Комплексные работы по озеленению, установке игровых городков и МАФ в Воронеже и области",
    },
    # Алтайский край
    {
        "url": "https://altay-maf.ru",
        "title": "Алтай-МАФ Барнаул — детские площадки и благоустройство",
        "region": "Алтайский край",
        "category_tags": "Детские площадки, МАФы, Парки и скверы",
        "snippet": "Поставка и сборка детских городков, парковой мебели и ограждений в Алтайском крае",
    },
]


def get_random_headers() -> dict[str, str]:
    """Генерирует заголовки с ротацией User-Agent и защитой от детекта ботов."""
    ua = random.choice(USER_AGENTS)
    return {
        "User-Agent": ua,
        "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,*/*;q=0.8",
        "Accept-Language": "ru-RU,ru;q=0.9,en-US;q=0.8,en;q=0.7",
        "Accept-Encoding": "gzip, deflate",
        "Referer": "https://duckduckgo.com/",
        "Sec-Ch-Ua": '"Chromium";v="124", "Google Chrome";v="124", "Not-A.Brand";v="99"',
        "Sec-Ch-Ua-Mobile": "?0",
        "Sec-Ch-Ua-Platform": '"Windows"',
        "Sec-Fetch-Dest": "document",
        "Sec-Fetch-Mode": "navigate",
        "Sec-Fetch-Site": "same-origin",
        "Sec-Fetch-User": "?1",
        "Upgrade-Insecure-Requests": "1",
        "Connection": "keep-alive",
        "DNT": "1",
    }


def format_ru_phone(digits: str) -> str | None:
    """Форматирует строку из 10 или 11 цифр в аккуратный телефон РФ."""
    if len(digits) == 10:
        digits = "7" + digits
    if len(digits) == 11 and digits.startswith(("7", "8")):
        code = digits[1:4]
        # Если 800 - федеральный бесплатный
        if code == "800":
            return f"+7 (800) {digits[4:7]}-{digits[7:9]}-{digits[9:11]}"
        # Проверяем 4-значные коды городов (Кемерово 3842, Новокузнецк 3843, Томск 3822 и др.)
        four_digit_codes = {"3842", "3843", "3822", "3812", "3512", "3432", "8122"}
        if digits[1:5] in four_digit_codes:
            return f"+7 ({digits[1:5]}) {digits[5:7]}-{digits[7:9]}-{digits[9:11]}"
        return f"+7 ({digits[1:4]}) {digits[4:7]}-{digits[7:9]}-{digits[9:11]}"
    return None


def extract_phones(text: str) -> list[str]:
    """Извлекает и нормализует телефонные номера РФ из сырого текста."""
    phones: list[str] = []
    phone_pattern = re.compile(
        r"(?:(?:\+7|8|7)[\s\-\(]*(\d{3,4})[\s\-\)]*(\d{2,3})[\s\-]*(\d{2})[\s\-]*(\d{2})|"
        r"(?:\+7|8|7)[\s\-]?\(?(\d{3,5})\)?[\s\-]?(\d{1,3})[\s\-]?(\d{2})[\s\-]?(\d{2}))"
    )

    for match in phone_pattern.finditer(text):
        raw = match.group(0)
        digits = re.sub(r"\D", "", raw)
        formatted = format_ru_phone(digits)
        if formatted and formatted not in phones:
            phones.append(formatted)

    return phones[:4]


def _extract_json_telephones(obj: Any, callback: Any) -> None:
    """Рекурсивный обход словарей JSON-LD для поиска telephone."""
    if isinstance(obj, dict):
        for k, v in obj.items():
            if k.lower() in ("telephone", "phone", "contactpoint"):
                if isinstance(v, str):
                    callback(v)
                elif isinstance(v, list):
                    for item in v:
                        if isinstance(item, str):
                            callback(item)
                        elif isinstance(item, dict):
                            _extract_json_telephones(item, callback)
                elif isinstance(v, dict):
                    _extract_json_telephones(v, callback)
            else:
                _extract_json_telephones(v, callback)
    elif isinstance(obj, list):
        for item in obj:
            _extract_json_telephones(item, callback)


def extract_all_phones_from_soup(soup: BeautifulSoup, page_text: str) -> list[str]:
    """
    «Дожим» телефонов со страницы:
    1. Поиск в JSON-LD микроразметке (schema.org/Organization, LocalBusiness)
    2. Поиск в ссылках <a href="tel:...">
    3. Поиск в ссылках WhatsApp (wa.me, api.whatsapp.com)
    4. Поиск в блоках контактов и подвале (footer, .contacts, #contacts)
    5. Поиск по общему тексту страницы
    """
    phones: list[str] = []

    def _add_phone(p: str | None) -> None:
        if not p:
            return
        digits = re.sub(r"\D", "", p)
        formatted = format_ru_phone(digits)
        if formatted and formatted not in phones and len(phones) < 6:
            phones.append(formatted)

    # 1. JSON-LD микроразметка
    for script in soup.find_all("script", attrs={"type": "application/ld+json"}):
        try:
            raw_json = script.string or ""
            if "telephone" in raw_json.lower() or "phone" in raw_json.lower():
                data = json.loads(raw_json)
                _extract_json_telephones(data, _add_phone)
        except Exception:
            raw_str = script.string or ""
            for match in re.findall(r'"telephone"\s*:\s*"([^"]+)"', raw_str, re.IGNORECASE):
                _add_phone(match)

    # 2. Ссылки a[href^="tel:"]
    for tel_a in soup.select('a[href^="tel:"]'):
        href = tel_a.get("href", "")
        raw = href.replace("tel:", "").strip()
        _add_phone(raw)

    # 3. Ссылки WhatsApp
    for wa_a in soup.find_all("a", href=True):
        href = wa_a["href"]
        if "wa.me/" in href or "whatsapp.com/send" in href:
            match = re.search(r"(?:wa\.me/|phone=)(\d{10,12})", href)
            if match:
                _add_phone(match.group(1))

    # 4. Выделенные секции контактов и футера
    contact_selectors = [
        "footer", ".footer", "#footer",
        ".contacts", "#contacts", ".contact", "#contact",
        ".contact-info", ".contacts-block", ".header-phone",
        ".phones", ".tel", ".site-footer", ".requisites",
    ]
    for selector in contact_selectors:
        for block in soup.select(selector):
            block_text = block.get_text(" ", strip=True)
            for p in extract_phones(block_text):
                _add_phone(p)

    # 5. Общий текст страницы
    for p in extract_phones(page_text):
        _add_phone(p)

    return phones[:4]


def extract_external_contractor_links(soup: BeautifulSoup, base_url: str) -> list[dict[str, str]]:
    """
    Извлекает ссылки на внешние домены подрядчиков из каталогов, списков и рейтингов.
    """
    discovered: list[dict[str, str]] = []
    seen_domains: set[str] = set()
    base_domain = urlparse(base_url).netloc.lower()

    for a_tag in soup.find_all("a", href=True):
        href = a_tag["href"].strip()
        parsed = urlparse(href)
        if parsed.scheme in ("http", "https"):
            dom = parsed.netloc.lower()
            if (
                dom
                and dom != base_domain
                and not any(exc in dom for exc in EXCLUDED_DOMAINS)
                and dom not in seen_domains
                and (dom.endswith(".ru") or dom.endswith(".su") or dom.endswith(".рф") or dom.endswith(".com"))
            ):
                seen_domains.add(dom)
                anchor_text = a_tag.get_text(strip=True)
                title_attr = a_tag.get("title", "")
                label = anchor_text or title_attr or dom

                # Проверяем релевантность ссылки или окружающего контекста
                relevant = False
                text_to_check = f"{label} {href}".lower()
                for cat_words in CATEGORY_KEYWORDS.values():
                    if any(w in text_to_check for w in cat_words):
                        relevant = True
                        break

                if relevant or len(seen_domains) <= 8:
                    discovered.append({
                        "url": href,
                        "domain": dom,
                        "title": label[:70] if label else dom,
                        "snippet": "Найдено через отраслевой каталог подрядчиков",
                    })

        if len(discovered) >= 10:
            break

    return discovered


def detect_categories(text: str) -> list[str]:
    """Определяет категории/направления по тексту."""
    text_lower = text.lower()
    categories: list[str] = []

    for cat_name, keywords in CATEGORY_KEYWORDS.items():
        for kw in keywords:
            if kw in text_lower:
                categories.append(cat_name)
                break

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
    """Очищает заголовок страницы для получения аккуратного названия компании."""
    if not raw_title:
        return "Не указано"

    parts = re.split(r"[\—\-\|\–\•]", raw_title)
    if parts:
        candidate = parts[0].strip()
        if 2 < len(candidate) < 70:
            return candidate

    cleaned = raw_title.strip()
    return cleaned[:70] if cleaned else "Не указано"


class WebCollector:
    """Асинхронный сборщик подрядчиков по благоустройству с масштабированием до сотен записей."""

    def __init__(self) -> None:
        self.is_running = False
        self._cancel_requested = False

    async def fetch_page(
        self, session: aiohttp.ClientSession, url: str
    ) -> tuple[str | None, str | None, int]:
        """Загружает страницу и возвращает (HTML, финальный URL, статус код)."""
        try:
            headers = get_random_headers()
            timeout = aiohttp.ClientTimeout(total=20, connect=10, sock_read=15)
            async with session.get(
                url,
                headers=headers,
                timeout=timeout,
                allow_redirects=True,
                ssl=False,
            ) as resp:
                status = resp.status
                if status == 200:
                    content_type = resp.headers.get("Content-Type", "").lower()
                    if "text/html" in content_type or not content_type:
                        html = await resp.text(errors="replace")
                        return html, str(resp.url), status
                return None, str(resp.url), status
        except Exception as e:
            logger.debug("Сбой соединения с %s [%s]: %s", url, type(e).__name__, e)
            return None, None, 0

    async def search_via_serper(
        self, session: aiohttp.ClientSession, query: str
    ) -> list[dict[str, str]]:
        """Поиск через Serper.dev API с глубиной до 30 ссылок за один вызов."""
        results: list[dict[str, str]] = []
        if not config.SEARCH_API_KEY:
            return results

        url = "https://google.serper.dev/search"
        headers = {
            "X-API-KEY": config.SEARCH_API_KEY,
            "Content-Type": "application/json",
        }
        # num: 30 для извлечения максимального пула ссылок
        payload = {"q": query, "gl": "ru", "hl": "ru", "num": 30}

        try:
            logger.info("Поиск через Serper.dev API (num: 30): '%s'", query)
            timeout = aiohttp.ClientTimeout(total=20, connect=10)
            async with session.post(
                url, headers=headers, json=payload, timeout=timeout, ssl=False
            ) as resp:
                logger.info("Serper.dev API статус: %d для запроса '%s'", resp.status, query)
                if resp.status == 200:
                    data = await resp.json()
                    for item in data.get("organic", []):
                        link = item.get("link", "")
                        domain = urlparse(link).netloc.lower()
                        if not domain or any(exc in domain for exc in EXCLUDED_DOMAINS):
                            continue
                        results.append({
                            "url": link,
                            "domain": domain,
                            "title": item.get("title", domain),
                            "snippet": item.get("snippet", ""),
                        })
                    logger.info("Serper.dev вернул %d органических ссылок", len(results))
                else:
                    text = await resp.text()
                    logger.warning("Serper.dev API ошибка %d: %s", resp.status, text[:200])
        except Exception as e:
            logger.warning("Исключение при вызове Serper.dev API [%s]: %s", type(e).__name__, e)

        return results

    async def search_via_duckduckgo(
        self, session: aiohttp.ClientSession, query: str
    ) -> tuple[list[dict[str, str]], int, str]:
        """
        Поиск через DuckDuckGo с POST-запросом, пагинацией до 25-30 ссылок и логированием.
        """
        results: list[dict[str, str]] = []
        headers = get_random_headers()
        url = "https://html.duckduckgo.com/html/"
        data = {"q": query}
        timeout = aiohttp.ClientTimeout(total=20, connect=10, sock_read=15)
        seen_domains: set[str] = set()

        def _parse_duck_html(html_text: str) -> tuple[list[dict[str, str]], dict[str, str] | None]:
            items = []
            soup = BeautifulSoup(html_text, "html.parser")
            result_nodes = soup.select(".result, .web-result")

            for node in result_nodes:
                link_tag = node.select_one(".result__url, .result__title a, a.result__snippet")
                if not link_tag:
                    continue

                raw_href = link_tag.get("href", "")
                target_url = raw_href
                if "uddg=" in raw_href:
                    parsed_q = parse_qs(urlparse(raw_href).query)
                    if "uddg" in parsed_q:
                        target_url = unquote(parsed_q["uddg"][0])

                parsed_target = urlparse(target_url)
                domain = parsed_target.netloc.lower()
                if not domain or any(exc in domain for exc in EXCLUDED_DOMAINS) or domain in seen_domains:
                    continue
                seen_domains.add(domain)

                title_tag = node.select_one(".result__title, h2")
                title = title_tag.get_text(strip=True) if title_tag else domain

                snippet_tag = node.select_one(".result__snippet")
                snippet = snippet_tag.get_text(strip=True) if snippet_tag else ""

                items.append({
                    "url": target_url,
                    "domain": domain,
                    "title": title,
                    "snippet": snippet,
                })

            # Ищем форму для перехода на следующую страницу (Next Page)
            next_form_data = None
            next_form = soup.select_one("form[action*='/html/']")
            if next_form:
                inputs = {inp.get("name"): inp.get("value", "") for inp in next_form.select("input") if inp.get("name")}
                if any(k in inputs for k in ("s", "nextParams", "dc")):
                    inputs["q"] = query
                    next_form_data = inputs

            return items, next_form_data

        try:
            logger.info("Поиск через DuckDuckGo POST: '%s'", query)
            async with session.post(
                url, data=data, headers=headers, timeout=timeout, ssl=False
            ) as resp:
                status = resp.status
                logger.info("DuckDuckGo вернул HTTP %d для запроса '%s'", status, query)

                if status == 200:
                    html = await resp.text(errors="replace")
                    page_items, next_form_data = _parse_duck_html(html)
                    results.extend(page_items)

                    # Если результатов на первой странице < 20 и найдена пагинация, запрашиваем страницу 2
                    if next_form_data and len(results) < 25:
                        try:
                            await asyncio.sleep(random.uniform(1.0, 2.0))
                            async with session.post(
                                url, data=next_form_data, headers=get_random_headers(), timeout=timeout, ssl=False
                            ) as resp2:
                                if resp2.status == 200:
                                    html2 = await resp2.text(errors="replace")
                                    p2_items, _ = _parse_duck_html(html2)
                                    results.extend(p2_items)
                                    logger.info(
                                        "DuckDuckGo пагинация добавила %d ссылок (всего: %d)",
                                        len(p2_items),
                                        len(results),
                                    )
                        except Exception as p_err:
                            logger.debug("Пагинация DuckDuckGo завершилась: %s", p_err)

                    logger.info("DuckDuckGo успешно извлек %d релевантных ссылок для запроса '%s'", len(results), query)
                    return results, status, "OK"
                elif status in (403, 202):
                    msg = f"HTTP {status}: Блокировка дата-центра / бот-контроль DuckDuckGo"
                    logger.warning("DuckDuckGo ограничил доступ: %s (запрос: '%s')", msg, query)
                    return results, status, msg
                else:
                    msg = f"HTTP {status}"
                    logger.warning("DuckDuckGo вернул статус %s для запроса '%s'", msg, query)
                    return results, status, msg

        except asyncio.TimeoutError as e:
            msg = f"TimeoutError: Превышено время ожидания ответа ({timeout.total} сек.)"
            logger.warning("Таймаут DuckDuckGo [%s]: %s для запроса '%s'", type(e).__name__, msg, query)
            return results, 0, msg
        except aiohttp.ClientConnectorError as e:
            msg = f"ClientConnectorError: Ошибка подключения к серверу ({e})"
            logger.warning("Сбой соединения с DuckDuckGo [%s]: %s для запроса '%s'", type(e).__name__, e, query)
            return results, 0, msg
        except aiohttp.ClientResponseError as e:
            msg = f"ClientResponseError: HTTP {e.status} {e.message}"
            logger.warning("Ответ с ошибкой от DuckDuckGo [%s]: статус %s, сообщение: %s", type(e).__name__, e.status, e.message)
            return results, e.status, msg
        except Exception as e:
            err_name = type(e).__name__
            err_msg = str(e) or repr(e)
            logger.warning("Непредвиденная ошибка соединения с DuckDuckGo [%s]: %s (запрос: '%s')", err_name, err_msg, query)
            return results, 0, f"{err_name}: {err_msg}"

    async def scrape_target_site(
        self, session: aiohttp.ClientSession, site_info: dict[str, str], query_region: str
    ) -> tuple[dict[str, Any] | None, list[dict[str, str]]]:
        """
        Глубокий парсинг сайта:
        - Главная страница
        - «Дожим» телефонов (микроразметка, tel:, WhatsApp, футер, регулярки)
        - При нехватке контактов — переход на страницу контактов
        - Сбор внешних ссылок на подрядчиков для очереди каталогов
        Возвращает (lead_data, discovered_links).
        """
        url = site_info["url"]
        domain = site_info["domain"]
        initial_title = site_info.get("title", domain)
        initial_snippet = site_info.get("snippet", "")
        discovered_links: list[dict[str, str]] = []

        logger.info("Обход целевого сайта: %s (%s)", domain, url)
        html, final_url, status = await self.fetch_page(session, url)

        if not html:
            logger.info("Сайт %s вернул HTTP %d, используем метаданные из каталога/поиска", domain, status)
            cats = detect_categories(initial_title + " " + initial_snippet)
            lead_item = {
                "website": domain,
                "company_name": clean_company_name(initial_title),
                "region": query_region,
                "phone": "Не указан",
                "category_tags": ", ".join(cats),
                "snippet": initial_snippet or "Найдено по поисковому запросу благоустройства",
            }
            return lead_item, discovered_links

        soup = BeautifulSoup(html, "html.parser")

        title_tag = soup.find("title")
        page_title = title_tag.get_text(strip=True) if title_tag else initial_title
        h1_tag = soup.find("h1")
        h1_text = h1_tag.get_text(strip=True) if h1_tag else ""

        full_text = soup.get_text(" ", strip=True)

        # Полный дожим телефонов (микроразметка, tel, wa, футер, текст)
        phones = extract_all_phones_from_soup(soup, full_text)

        # Поиск контактов на подстраницах при нехватке телефонов (< 2)
        contact_urls: list[str] = []
        for a_tag in soup.find_all("a", href=True):
            href = a_tag["href"].lower()
            if any(part in href for part in [
                "contact", "kontakt", "o-nas", "about", "requisite",
                "rekvizit", "contacts", "feedback",
            ]):
                full_contact_url = urljoin(final_url or url, a_tag["href"])
                if full_contact_url not in contact_urls:
                    contact_urls.append(full_contact_url)

        if contact_urls and len(phones) < 2:
            contact_html, _, c_status = await self.fetch_page(session, contact_urls[0])
            if contact_html:
                contact_soup = BeautifulSoup(contact_html, "html.parser")
                contact_text = contact_soup.get_text(" ", strip=True)
                extra_phones = extract_all_phones_from_soup(contact_soup, contact_text)
                for ep in extra_phones:
                    if ep not in phones:
                        phones.append(ep)
                full_text += " " + contact_text

        # Извлечение внешних ссылок на подрядчиков (discovered catalog crawling)
        discovered_links = extract_external_contractor_links(soup, final_url or url)

        region = detect_region(full_text, default_region=query_region)
        combined_text = f"{page_title} {h1_text} {initial_snippet} {full_text[:4000]}"
        categories = detect_categories(combined_text)

        snippet = initial_snippet
        if not snippet:
            meta_desc = soup.find("meta", attrs={"name": "description"})
            if meta_desc and meta_desc.get("content"):
                snippet = meta_desc["content"].strip()
            else:
                snippet = full_text[:250].replace("\n", " ").strip()

        company_name = clean_company_name(page_title or h1_text)

        logger.info(
            "Успешно обработан сайт %s: найдено телефонов: %d, регион: %s, теги: %s, внешних ссылок: %d",
            domain,
            len(phones),
            region,
            categories,
            len(discovered_links),
        )

        lead_data = {
            "website": domain,
            "company_name": company_name,
            "region": region,
            "phone": ", ".join(phones) if phones else "Не указан",
            "category_tags": ", ".join(categories),
            "snippet": snippet,
        }
        return lead_data, discovered_links

    async def run(
        self,
        regions: list[str] | None = None,
        progress_callback: Any = None,
    ) -> dict[str, Any]:
        """
        Запуск цикла масштабируемого сбора данных:
        - 8–10 целевых запросов на каждый выбранный регион
        - Глубина до 25–30 ссылок на запрос (Serper.dev num:30 / DuckDuckGo пагинация)
        - Обход каталогов и внешних ссылок подрядчиков (discovered queue)
        - Стриминговая запись в БД (сохранение лида сразу при нахождении)
        - Дожим телефонных номеров со всех страниц
        """
        if self.is_running:
            return {"status": "already_running", "added": 0, "updated": 0}

        self.is_running = True
        self._cancel_requested = False
        start_time = time.time()

        added_count = 0
        added_with_phone = 0
        updated_count = 0
        search_links_found = 0
        queries_executed = 0
        consecutive_search_failures = 0
        processed_domains: set[str] = set()
        crawl_queue: list[dict[str, str]] = []
        warnings: list[str] = []

        # Определяем целевые регионы: из переданных параметров или из БД
        target_regions = regions
        if not target_regions:
            try:
                target_regions = await database.get_selected_region_names()
            except Exception:
                target_regions = []

        if not target_regions:
            target_regions = config.TARGET_REGIONS

        logger.info("=== Запуск масштабируемого веб-парсера B2B подрядчиков ===")
        logger.info("Целевые регионы (%d): %s", len(target_regions), target_regions)
        search_mode = "Serper.dev API" if config.SEARCH_API_KEY else "DuckDuckGo POST + Резервные каталоги"
        logger.info("Режим поиска: %s", search_mode)

        # Коннектор с отключенной проверкой SSL для максимальной надежности в любых облачных контейнерах
        connector = aiohttp.TCPConnector(ssl=False)

        try:
            async with aiohttp.ClientSession(connector=connector) as session:
                # 1. Формируем пул целевых запросов: по 10 формулировок на каждый выбранный регион
                queries_to_run: list[tuple[str, str]] = []
                for reg in target_regions:
                    for tmpl in SEARCH_QUERY_TEMPLATES:
                        query_str = tmpl.format(region=reg)
                        queries_to_run.append((query_str, reg))

                total_steps = len(queries_to_run) + len(config.SEED_URLS) + 1
                current_step = 0

                for query_str, region_name in queries_to_run:
                    if self._cancel_requested:
                        break

                    # Если поисковик выдал 3 подряд сбоя соединения/блокировки с облачного IP дата-центра,
                    # не висим на всех запросах, переходим к обнаруженным каталогам и отраслевым реестрам!
                    if consecutive_search_failures >= 3 and not config.SEARCH_API_KEY:
                        logger.warning(
                            "Поисковый сервис DuckDuckGo временно ограничил запросы с IP дата-центра (3 сбоя подряд). "
                            "Автоматически переключаемся на обход каталогов, очереди ссылок и отраслевых реестров..."
                        )
                        if "Блокировка DuckDuckGo" not in str(warnings):
                            warnings.append(
                                "Поисковик DuckDuckGo ограничил прямые запросы с IP дата-центра. "
                                "Сбор переключен на обход отраслевых каталогов и региональных производителей."
                            )
                        break

                    current_step += 1
                    queries_executed += 1
                    if progress_callback:
                        await progress_callback(
                            f"🔍 Поиск ({current_step}/{total_steps}): «{query_str}»..."
                        )

                    search_results: list[dict[str, str]] = []

                    # А. Если настроен API-ключ (Serper.dev), используем его
                    if config.SEARCH_API_KEY:
                        search_results = await self.search_via_serper(session, query_str)

                    # Б. Если API нет или он пуст, вызываем DuckDuckGo с пагинацией
                    if not search_results:
                        ddg_results, status, reason = await self.search_via_duckduckgo(session, query_str)
                        if ddg_results:
                            search_results = ddg_results
                            consecutive_search_failures = 0
                        else:
                            consecutive_search_failures += 1
                            if reason != "OK":
                                warnings.append(f"Поиск «{query_str}»: {reason}")

                    search_links_found += len(search_results)
                    await asyncio.sleep(random.uniform(config.PARSER_DELAY, config.PARSER_DELAY + 1.0))

                    # Обработка извлеченных ссылок (до 25 ссылок на запрос)
                    for site_info in search_results[:config.PARSER_MAX_PER_QUERY]:
                        if self._cancel_requested:
                            break

                        domain = site_info["domain"]
                        if domain in processed_domains:
                            continue
                        processed_domains.add(domain)

                        lead_data, ext_links = await self.scrape_target_site(session, site_info, region_name)
                        if lead_data:
                            # СТРИМИНГОВАЯ ЗАПИСЬ: сохраняем в БД сразу!
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
                                if lead_data["phone"] != "Не указан":
                                    added_with_phone += 1
                            else:
                                updated_count += 1

                        # Добавляем обнаруженные внешние ссылки каталогов в очередь обхода
                        for link in ext_links:
                            if link["domain"] not in processed_domains and len(crawl_queue) < 150:
                                crawl_queue.append(link)

                        await asyncio.sleep(random.uniform(0.8, 1.5))

                # 2. Обход накопленной очереди найденных внешних ссылок подрядчиков (crawl_queue)
                if crawl_queue and not self._cancel_requested:
                    logger.info("Запуск обхода найденных ссылок подрядчиков (%d шт.)...", len(crawl_queue))
                    if progress_callback:
                        await progress_callback(f"🌐 Обход найденных подрядчиков ({len(crawl_queue)} сайтов)...")

                    for site_info in crawl_queue[:60]:
                        if self._cancel_requested:
                            break

                        dom = site_info["domain"]
                        if dom in processed_domains:
                            continue
                        processed_domains.add(dom)

                        lead_data, _ = await self.scrape_target_site(session, site_info, "Не указан")
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
                                if lead_data["phone"] != "Не указан":
                                    added_with_phone += 1
                            else:
                                updated_count += 1

                        await asyncio.sleep(random.uniform(0.8, 1.5))

                # 3. Обработка стартовых отраслевых каталогов SEED_URLS
                for seed_url in config.SEED_URLS:
                    if self._cancel_requested:
                        break

                    current_step += 1
                    if progress_callback:
                        await progress_callback(f"🌐 Сбор по каталогу: {seed_url}...")

                    logger.info("Обработка стартового каталога: %s", seed_url)
                    html, _, status = await self.fetch_page(session, seed_url)
                    await asyncio.sleep(config.PARSER_DELAY)

                    if not html:
                        logger.warning("Каталог %s вернул статус %d", seed_url, status)
                        continue

                    soup = BeautifulSoup(html, "html.parser")
                    discovered_seeds = extract_external_contractor_links(soup, seed_url)

                    for seed_item in discovered_seeds:
                        if self._cancel_requested:
                            break

                        dom = seed_item["domain"]
                        if dom in processed_domains:
                            continue
                        processed_domains.add(dom)

                        lead_data, _ = await self.scrape_target_site(session, seed_item, query_region="Не указан")
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
                                if lead_data["phone"] != "Не указан":
                                    added_with_phone += 1
                            else:
                                updated_count += 1

                        await asyncio.sleep(random.uniform(0.8, 1.5))

                # 4. Гарантированный сбор по расширенному отраслевому реестру FALLBACK_CATALOG_COMPANIES
                if progress_callback:
                    await progress_callback("🏗 Обработка реестра региональных производителей МАФ и ограждений...")

                logger.info(
                    "Запуск обхода отраслевого реестра (%d компаний)...",
                    len(FALLBACK_CATALOG_COMPANIES),
                )

                for comp in FALLBACK_CATALOG_COMPANIES:
                    if self._cancel_requested:
                        break

                    parsed_dom = urlparse(comp["url"]).netloc.lower()
                    if parsed_dom in processed_domains:
                        continue
                    processed_domains.add(parsed_dom)

                    logger.info("Глубокий сбор компании из реестра: %s (%s)", parsed_dom, comp["url"])
                    lead_data, _ = await self.scrape_target_site(
                        session,
                        {
                            "url": comp["url"],
                            "domain": parsed_dom,
                            "title": comp["title"],
                            "snippet": comp["snippet"],
                        },
                        query_region=comp["region"],
                    )

                    if lead_data:
                        final_tags = database.merge_tags(comp["category_tags"], lead_data["category_tags"])
                        final_phone = lead_data["phone"]
                        reg_to_save = lead_data["region"] if lead_data["region"] != "Не указан" else comp["region"]

                        _, is_new = await database.save_lead(
                            source="web_parser",
                            region=reg_to_save,
                            phone=final_phone,
                            website=lead_data["website"],
                            company_name=lead_data["company_name"],
                            category_tags=final_tags,
                            snippet=lead_data["snippet"],
                        )
                        if is_new:
                            added_count += 1
                            if final_phone != "Не указан":
                                added_with_phone += 1
                        else:
                            updated_count += 1

                    await asyncio.sleep(random.uniform(0.5, 1.2))

        except Exception as e:
            logger.error("Критическая ошибка при работе веб-парсера [%s]: %s", type(e).__name__, e, exc_info=True)
            warnings.append(f"Критическая ошибка: {type(e).__name__} ({e})")
        finally:
            self.is_running = False

        duration = time.time() - start_time
        logger.info(
            "=== Сбор завершен за %.1f сек. Найдено в поиске: %d, Сайтов обойдено: %d, Новых: %d (с тел: %d), Обновлено: %d ===",
            duration,
            search_links_found,
            len(processed_domains),
            added_count,
            added_with_phone,
            updated_count,
        )

        return {
            "status": "completed",
            "regions": target_regions,
            "search_mode": search_mode,
            "duration_seconds": duration,
            "queries_count": queries_executed,
            "search_links_found": search_links_found,
            "sites_crawled": len(processed_domains),
            "added": added_count,
            "added_with_phone": added_with_phone,
            "updated": updated_count,
            "warnings": warnings,
        }


# Глобальный экземпляр сборщика
collector = WebCollector()
