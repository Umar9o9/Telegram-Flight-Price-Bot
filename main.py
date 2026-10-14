import asyncio
import calendar
import logging
import os
import sqlite3
import time
from contextlib import closing
from datetime import date, timedelta

import aiohttp
from aiogram import Bot, Dispatcher, F
from aiogram.exceptions import TelegramForbiddenError
from aiogram.filters import Command, CommandStart
from aiogram.types import (
    CallbackQuery,
    InlineKeyboardButton,
    KeyboardButton,
    LinkPreviewOptions,
    Message,
)
from aiogram.utils.keyboard import InlineKeyboardBuilder, ReplyKeyboardBuilder
from dotenv import load_dotenv

load_dotenv()

BOT_TOKEN = os.getenv("BOT_TOKEN")
TP_TOKEN = os.getenv("TRAVELPAYOUTS_TOKEN")
MARKER = os.getenv("TRAVELPAYOUTS_MARKER", "484848")
MANUAL_RATE = os.getenv("USD_UZS_RATE", "")

API_URL = "https://api.travelpayouts.com/aviasales/v3/prices_for_dates"
GROUPED_URL = "https://api.travelpayouts.com/aviasales/v3/grouped_prices"
PLACES_URL = "https://autocomplete.travelpayouts.com/places2"
HOTEL_LOOKUP_URL = "https://engine.hotellook.com/api/v2/lookup.json"

CBU_URL_USD = "https://cbu.uz/ru/arkhiv-kursov-valyut/json/USD/"
CBU_URL_ALL = "https://cbu.uz/ru/arkhiv-kursov-valyut/json/"
AVIA_SITE = "https://www.aviasales.com"

DB_PATH = os.getenv("DB_PATH", "bot.db")
CHECK_INTERVAL = int(os.getenv("CHECK_INTERVAL", "3600"))
MAX_ALERTS = 5
DEFAULT_LANG = "uz"

logging.basicConfig(level=logging.INFO)
dp = Dispatcher()

WAITING = {}

ORIGIN_CODES = ["TAS", "SKD", "BHK", "FEG", "NMA", "AZN", "UGC", "NCU", "TMJ", "KSQ"]
DEST_CODES = ["MOW", "LED", "IST", "DXB", "ALA", "DEL", "JED", "KUL", "BKK", "SEL", "BAK", "TBS", "AYT", "MED"]

CITY = {
    "ru": {
        "TAS": "Ташкент", "SKD": "Самарканд", "BHK": "Бухара", "FEG": "Фергана",
        "NMA": "Наманган", "AZN": "Андижан", "UGC": "Ургенч", "NCU": "Нукус",
        "TMJ": "Термез", "KSQ": "Карши", "MOW": "Москва", "LED": "Санкт-Петербург",
        "IST": "Стамбул", "DXB": "Дубай", "ALA": "Алматы", "DEL": "Дели",
        "JED": "Джидда", "KUL": "Куала-Лумпур", "BKK": "Бангкок", "SEL": "Сеул",
        "BAK": "Баку", "TBS": "Тбилиси", "AYT": "Анталья", "MED": "Медина",
    },
    "uz": {
        "TAS": "Toshkent", "SKD": "Samarqand", "BHK": "Buxoro", "FEG": "Farg'ona",
        "NMA": "Namangan", "AZN": "Andijon", "UGC": "Urganch", "NCU": "Nukus",
        "TMJ": "Termiz", "KSQ": "Qarshi", "MOW": "Moskva", "LED": "Sankt-Peterburg",
        "IST": "Istanbul", "DXB": "Dubay", "ALA": "Almati", "DEL": "Dehli",
        "JED": "Jidda", "KUL": "Kuala-Lumpur", "BKK": "Bangkok", "SEL": "Seul",
        "BAK": "Boku", "TBS": "Tbilisi", "AYT": "Antaliya", "MED": "Madina",
    },
}

MONTHS = {
    "ru": ["", "январь", "февраль", "март", "апрель", "май", "июнь", "июль", "август", "сентябрь", "октябрь", "ноябрь", "декабрь"],
    "uz": ["", "yanvar", "fevral", "mart", "aprel", "may", "iyun", "iyul", "avgust", "sentyabr", "oktyabr", "noyabr", "dekabr"],
}

WEEKDAYS = {
    "ru": ["Пн", "Вт", "Ср", "Чт", "Пт", "Сб", "Вс"],
    "uz": ["Du", "Se", "Ch", "Pa", "Ju", "Sh", "Ya"],
}

TEXTS = {
    "ru": {
        "help": (
            "🌐 <b>Поиск дешёвых авиабилетов, отелей и хостелов!</b>\n\n"
            "✈️ <b>Авиабилеты:</b> сравнение цен через GoToGate, OneTwoTrip, City.Travel, Skyscanner и Google Flights.\n"
            "🏨 <b>Отели и Хостелы:</b> сравнение Booking.com, Agoda, Ostrovok и Hotellook.\n\n"
            "Воспользуйтесь меню ниже:"
        ),
        "menu_avia": "✈️ Авиабилеты",
        "menu_hotel": "🏨 Отели и Хостелы",
        "menu_alerts": "🔔 Оповещения",
        "menu_lang": "🌐 Til / Язык",
        "btn_back": "⬅️ Назад",
        "btn_new": "🔁 Новый поиск",
        "btn_watch": "🔔 Следить за ценой",
        "btn_other": "🔍 Другой город",
        "btn_to_calendar": "⬅️ К календарю",
        "btn_buy_ticket": "🔗 Купить билет #{i} (GoToGate / OneTwoTrip)",
        "btn_compare_sky": "🔍 Сравнить на Skyscanner",
        "btn_hotel_book": "🏨 Открыть все отели и хостелы ({p})",
        "ask_origin": "Откуда летите? Выберите город вылета:",
        "ask_dest": "Вылет: {o}\nКуда летите?",
        "ask_month": "{o} → {d}\nВыберите месяц вылета:",
        "ask_origin_text": "Введите название города вылета (например: Самара):",
        "ask_dest_text": "Введите название города прилёта (например: Париж):",
        "ask_hotel_city": "🏨 Введите название города для поиска отелей и хостелов (например: Дубай, Стамбул, Ташкент):",
        "pick_city": "Выберите город из списка:",
        "city_not_found": "Не удалось найти город. Попробуйте написать иначе.",
        "searching": "🔎 Ищу дешёвые варианты среди всех агентств...",
        "route_title": "✈️ <b>{o} → {d}</b>\nНайдено билетов: {count} шт.\n",
        "hotel_found_title": "🏨 <b>Отели и хостелы в г. {city}</b>\n\nСервис агрегирует лучшие цены с <b>Booking.com, Agoda, Ostrovok</b>.\n\nНажмите на кнопку ниже, чтобы увидеть список самых дешёвых вариантов с возможностью бронирования:",
        "direct": "Прямой рейс",
        "stops": "Пересадок: {n}",
        "uzs": "сум",
        "rate_line": "💱 Курс: 1 USD = {rate} сум",
        "flight_time": "🛫 Вылет: {dt}",
        "airline": "🏢 Авиакомпания: {a}",
        "cal_title": "📅 {o} → {d}, {month} {year}",
        "cal_cheapest": "Самые дешёвые дни:",
        "cal_line": "• {date} — {price}",
        "cal_legend": "🟢 — самые дешёвые дни, цифра — есть цена, · — нет данных.",
        "cal_empty": "На этот месяц данных нет. Попробуйте другой месяц.",
        "not_found": "Ничего не найдено. Попробуйте изменить параметры поиска.",
        "api_fail": "⚠️ Ошибка связи с сервисом.",
        "watch_exists": "🔔 Это направление уже отслеживается: {route}",
        "watch_limit": "Лимит: {max} оповещений.",
        "watch_none": "Сейчас нет цен для этого направления.",
        "watch_ok": "🔔 Слежу за ценой: {route}\nСейчас от {price} USD.",
        "alerts_empty": "У вас пока нет активных оповещений.",
        "alerts_title": "🔔 Ваши оповещения (нажмите для удаления):",
        "alert_item": "❌ {o} → {d}, {period} (от {price})",
        "deleted": "Удалено",
        "dropped": "🔔 <b>Цена упала: {old} → {new} USD!</b>\n\n",
    },
    "uz": {
        "help": (
            "🌐 <b>Arzon aviachiptalar, mehmonxona va hostellar qidiruv boti!</b>\n\n"
            "✈️ <b>Aviachiptalar:</b> GoToGate, OneTwoTrip, City.Travel, Skyscanner va aviakompaniyalar narxlari taqqoslovi.\n"
            "🏨 <b>Mehmonxona va Hostellar:</b> Booking.com, Agoda, Ostrovok tizimlaridagi eng arzon variantlar.\n\n"
            "Quyidagi menyudan kerakli bo'limni tanlang:"
        ),
        "menu_avia": "✈️ Aviachiptalar",
        "menu_hotel": "🏨 Mehmonxona va Hostellar",
        "menu_alerts": "🔔 Xabarnomalarim",
        "menu_lang": "🌐 Til / Язык",
        "btn_back": "⬅️ Orqaga",
        "btn_new": "🔁 Yangi qidiruv",
        "btn_watch": "🔔 Narxni kuzatish",
        "btn_other": "🔍 Boshqa shahar",
        "btn_to_calendar": "⬅️ Kalendarga",
        "btn_buy_ticket": "🔗 #{i}-chipta (GoToGate / OneTwoTrip orqali)",
        "btn_compare_sky": "🔍 Skyscanner orqali taqqoslash",
        "btn_hotel_book": "🏨 Barcha arzon variantlarni ko'rish ({p})",
        "ask_origin": "Qayerdan uchasiz? Shaharni tanlang:",
        "ask_dest": "Uchish: {o}\nQayerga uchasiz?",
        "ask_month": "{o} → {d}\nUchish oyini tanlang:",
        "ask_origin_text": "Uchish shahrini yozing (masalan: Moskva):",
        "ask_dest_text": "Qo'nish shahrini yozing (masalan: Parij):",
        "ask_hotel_city": "🏨 Qaysi shahardan mehmonxona yoki hostel qidiryapsiz? (Masalan: Toshkent, Samarqand, Istanbul, Dubay):",
        "pick_city": "Ro'yxatdan tanlang:",
        "city_not_found": "Bunday shahar topilmadi. Qayta yozib ko'ring.",
        "searching": "🔎 Barcha yirik agentliklardan eng arzon narxlar qidirilmoqda...",
        "route_title": "✈️ <b>{o} → {d}</b>\nTopilgan chiptalar: {count} ta\n",
        "hotel_found_title": "🏨 <b>{city} shahridagi mehmonxona va hostellar</b>\n\nTizim <b>Booking.com, Agoda, Ostrovok</b> bo'yicha eng arzon narxlarni taqqosladi.\n\nQuyidagi tugma orqali filtrlangan barcha arzon variantlarni ko'rishingiz va joy band qilishingiz mumkin:",
        "direct": "To'g'ridan-to'g'ri reys",
        "stops": "Almashinuvlar: {n} ta",
        "uzs": "so'm",
        "rate_line": "💱 Kurs: 1 USD = {rate} so'm",
        "flight_time": "🛫 Uchish vaqti: {dt}",
        "airline": "🏢 Aviakompaniya: {a}",
        "cal_title": "📅 {o} → {d}, {month} {year}",
        "cal_cheapest": "Eng arzon kunlar:",
        "cal_line": "• {date} — {price}",
        "cal_legend": "🟢 — eng arzon kunlar, raqam — narx bor, · — ma'lumot yo'q.",
        "cal_empty": "Bu oy uchun keshda narxlar mavjud emas.",
        "not_found": "Hech qanday ma'lumot topilmadi.",
        "api_fail": "⚠️ Xizmatda uzilish yuz berdi.",
        "watch_exists": "🔔 Bu yo'nalish allaqachon kuzatilmoqda: {route}",
        "watch_limit": "Limit: {max} ta xabarnoma.",
        "watch_none": "Bu yo'nalish bo'yicha narxlar topilmadi.",
        "watch_ok": "🔔 Kuzatilmoqda: {route}\nHozir {price} USD dan.",
        "alerts_empty": "Sizda faol xabarnomalar mavjud emas.",
        "alerts_title": "🔔 Kuzatuvlaringiz (o'chirish uchun ustiga bosing):",
        "alert_item": "❌ {o} → {d}, {period} ({price} dan)",
        "deleted": "O'chirildi",
        "dropped": "🔔 <b>Narx tushdi: {old} → {new} USD!</b>\n\n",
    },
}

def t(lang, key, **kw):
    text = TEXTS[lang].get(key, "")
    return text.format(**kw) if kw else text

# ---------- SQLite ----------
def db_exec(sql, params=()):
    with closing(sqlite3.connect(DB_PATH)) as conn:
        cur = conn.execute(sql, params)
        conn.commit()
        return cur.rowcount

def db_all(sql, params=()):
    with closing(sqlite3.connect(DB_PATH)) as conn:
        conn.row_factory = sqlite3.Row
        return [dict(r) for r in conn.execute(sql, params).fetchall()]

def init_db():
    db_exec("""CREATE TABLE IF NOT EXISTS alerts (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        user_id INTEGER NOT NULL,
        origin TEXT NOT NULL,
        dest TEXT NOT NULL,
        period TEXT NOT NULL,
        last_price REAL,
        UNIQUE(user_id, origin, dest, period)
    )""")
    db_exec("""CREATE TABLE IF NOT EXISTS users (
        user_id INTEGER PRIMARY KEY,
        lang TEXT NOT NULL
    )""")
    db_exec("""CREATE TABLE IF NOT EXISTS places (
        code TEXT NOT NULL,
        lang TEXT NOT NULL,
        name TEXT NOT NULL,
        PRIMARY KEY (code, lang)
    )""")

def get_lang(user_id):
    rows = db_all("SELECT lang FROM users WHERE user_id=?", (user_id,))
    return rows[0]["lang"] if rows and rows[0]["lang"] in TEXTS else None

def lang_of(user_id):
    return get_lang(user_id) or DEFAULT_LANG

def set_lang(user_id, lang):
    db_exec("INSERT OR REPLACE INTO users (user_id, lang) VALUES (?, ?)", (user_id, lang))

def save_place(code, lang, name):
    db_exec("INSERT OR REPLACE INTO places (code, lang, name) VALUES (?, ?, ?)", (code, lang, name))

def city(code, lang):
    name = CITY[lang].get(code)
    if name:
        return name
    rows = db_all("SELECT name FROM places WHERE code=? AND lang=?", (code, lang))
    if rows:
        return rows[0]["name"]
    return code

# ---------- HTTP & Valyuta ----------
async def http_json(url, params=None, headers=None):
    try:
        timeout = aiohttp.ClientTimeout(total=15)
        async with aiohttp.ClientSession(timeout=timeout) as session:
            async with session.get(url, params=params, headers=headers) as resp:
                return await resp.json(content_type=None)
    except Exception as e:
        logging.warning("HTTP error (%s): %s", url, e)
        return None

_RATE = {"value": None, "ts": 0.0}

async def get_rate():
    if MANUAL_RATE:
        try:
            return float(MANUAL_RATE.replace(" ", "").replace(",", "."))
        except ValueError:
            pass
    now = time.time()
    if _RATE["value"] and now - _RATE["ts"] < 3600:
        return _RATE["value"]
    for url in (CBU_URL_USD, CBU_URL_ALL):
        data = await http_json(url)
        if isinstance(data, list):
            for row in data:
                if isinstance(row, dict) and row.get("Ccy") == "USD":
                    try:
                        rate = float(str(row.get("Rate")).replace(" ", "").replace(",", "."))
                        if rate > 0:
                            _RATE["value"] = rate
                            _RATE["ts"] = now
                            return rate
                    except ValueError:
                        continue
    return _RATE["value"]

def spaced(number):
    return f"{number:,.0f}".replace(",", " ")

def money(usd, rate, lang):
    try:
        usd = float(usd)
    except (TypeError, ValueError):
        return str(usd)
    text = f"{usd:.0f} USD"
    if rate:
        text += f" ≈ {spaced(round(usd * rate, -3))} {t(lang, 'uzs')}"
    return text

def build_ticket_url(link):
    url = AVIA_SITE + (link or "")
    if MARKER:
        url += ("&" if "?" in url else "?") + f"marker={MARKER}"
    return url

def build_skyscanner_url(origin, dest, dep_date):
    """Skyscanner orqali xuddi shu sanadagi reyslarni taqqoslash havolasi"""
    date_formatted = dep_date.replace("-", "")[2:]  # YYMMDD
    return f"https://www.skyscanner.com/transport/flights/{origin.lower()}/{dest.lower()}/{date_formatted}/"

# ---------- Menyular ----------
def kb_main_menu(lang):
    b = ReplyKeyboardBuilder()
    b.row(
        KeyboardButton(text=t(lang, "menu_avia")),
        KeyboardButton(text=t(lang, "menu_hotel"))
    )
    b.row(
        KeyboardButton(text=t(lang, "menu_alerts")),
        KeyboardButton(text=t(lang, "menu_lang"))
    )
    return b.as_markup(resize_keyboard=True)

def kb_lang():
    b = InlineKeyboardBuilder()
    b.button(text="🇺🇿 O'zbekcha", callback_data="lang:uz")
    b.button(text="🇷🇺 Русский", callback_data="lang:ru")
    b.adjust(2)
    return b.as_markup()

def kb_origins(lang):
    b = InlineKeyboardBuilder()
    for code in ORIGIN_CODES:
        b.button(text=city(code, lang), callback_data=f"o:{code}")
    b.adjust(2)
    b.row(InlineKeyboardButton(text=t(lang, "btn_other"), callback_data="oo"))
    return b.as_markup()

def kb_dests(origin, lang):
    b = InlineKeyboardBuilder()
    for code in DEST_CODES:
        if code != origin:
            b.button(text=city(code, lang), callback_data=f"d:{origin}:{code}")
    b.adjust(2)
    b.row(InlineKeyboardButton(text=t(lang, "btn_other"), callback_data=f"od:{origin}"))
    b.row(InlineKeyboardButton(text=t(lang, "btn_back"), callback_data="go_avia"))
    return b.as_markup()

def kb_places(places, role, origin, lang):
    b = InlineKeyboardBuilder()
    for p in places:
        label = p["name"] + (f", {p['country']}" if p.get("country") else "")
        data = f"o:{p['code']}" if role == "origin" else f"d:{origin}:{p['code']}"
        b.button(text=label[:50], callback_data=data)
    b.adjust(1)
    b.row(InlineKeyboardButton(text=t(lang, "btn_back"), callback_data="go_avia"))
    return b.as_markup()

def next_months(count=6):
    today = date.today()
    y, m = today.year, today.month
    res = []
    for _ in range(count):
        res.append((y, m))
        m += 1
        if m > 12:
            m = 1
            y += 1
    return res

def kb_months(origin, dest, lang):
    b = InlineKeyboardBuilder()
    for year, month in next_months():
        b.button(text=f"{MONTHS[lang][month].capitalize()} {year}", callback_data=f"m:{origin}:{dest}:{year}-{month:02d}")
    b.adjust(2)
    b.row(InlineKeyboardButton(text=t(lang, "btn_back"), callback_data=f"o:{origin}"))
    return b.as_markup()

def kb_calendar(origin, dest, year, month, prices, cheapest, lang):
    b = InlineKeyboardBuilder()
    for wd in WEEKDAYS[lang]:
        b.button(text=wd, callback_data="n")
    today = date.today()
    for week in calendar.Calendar(firstweekday=0).monthdayscalendar(year, month):
        for day in week:
            if day == 0:
                b.button(text="·", callback_data="n")
                continue
            key = date(year, month, day).isoformat()
            if date(year, month, day) < today or key not in prices:
                b.button(text="·", callback_data="n")
            else:
                label = f"🟢{day}" if key in cheapest else str(day)
                b.button(text=label, callback_data=f"c:{origin}:{dest}:{key}")
    b.adjust(7)
    period = f"{year}-{month:02d}"
    b.row(InlineKeyboardButton(text=t(lang, "btn_watch"), callback_data=f"w:{origin}:{dest}:{period}"))
    b.row(
        InlineKeyboardButton(text=t(lang, "btn_back"), callback_data=f"d:{origin}:{dest}"),
        InlineKeyboardButton(text=t(lang, "btn_new"), callback_data="go_avia")
    )
    return b.as_markup()

def kb_day_tickets(tickets, origin, dest, day, lang):
    b = InlineKeyboardBuilder()
    # GoToGate, OneTwoTrip va boshqa agentliklarning eng arzon havolalari
    for idx, tk in enumerate(tickets, 1):
        url = build_ticket_url(tk.get("link", ""))
        b.button(text=t(lang, "btn_buy_ticket", i=idx), url=url)
    
    # Qo'shimcha Skyscanner agregatori orqali tekshirish
    sky_url = build_skyscanner_url(origin, dest, day)
    b.button(text=t(lang, "btn_compare_sky"), url=sky_url)
    
    b.adjust(1)
    b.row(InlineKeyboardButton(text=t(lang, "btn_watch"), callback_data=f"w:{origin}:{dest}:{day}"))
    b.row(
        InlineKeyboardButton(text=t(lang, "btn_to_calendar"), callback_data=f"m:{origin}:{dest}:{day[:7]}"),
        InlineKeyboardButton(text=t(lang, "btn_new"), callback_data="go_avia")
    )
    return b.as_markup()

# ---------- API chaqiruvlari ----------
async def search_places(term, lang):
    params = {"term": term, "locale": "ru" if lang == "ru" else "en", "types[]": "city"}
    data = await http_json(PLACES_URL, params=params)
    if not isinstance(data, list):
        return []
    result, seen = [], set()
    for item in data:
        code = str(item.get("code") or "").upper()
        name = item.get("name") or item.get("city_name") or ""
        if item.get("type") == "city" and len(code) == 3 and code not in seen:
            seen.add(code)
            result.append({"code": code, "name": name, "country": item.get("country_name", "")})
            save_place(code, lang, name)
            if len(result) >= 6:
                break
    return result

async def fetch_tickets(origin, destination, period, limit=3, direct=False):
    params = {
        "origin": origin, "destination": destination, "departure_at": period,
        "one_way": "true", "sorting": "price", "currency": "usd", "limit": limit, "unique": "false"
    }
    if direct:
        params["direct"] = "true"
    data = await http_json(API_URL, params=params, headers={"X-Access-Token": TP_TOKEN})
    if not data:
        return None
    raw = data.get("data") or []
    return raw if isinstance(raw, list) else list(raw.values())

async def fetch_calendar(origin, destination, month):
    params = {
        "origin": origin, "destination": destination, "departure_at": month,
        "group_by": "departure_at", "currency": "usd"
    }
    data = await http_json(GROUPED_URL, params=params, headers={"X-Access-Token": TP_TOKEN})
    if not data:
        return None
    raw = data.get("data") or {}
    if isinstance(raw, list):
        raw = {str(x.get("departure_at", ""))[:10]: x for x in raw if x.get("departure_at")}
    return {k: v for k, v in raw.items() if isinstance(v, dict) and v.get("price") is not None}

async def search_hotel_destination(city_query, lang):
    """Shaharni topib, Hotellook / Booking agregatori uchun to'g'ri havolani yaratish"""
    params = {"query": city_query, "lang": "ru" if lang == "ru" else "en", "lookFor": "city"}
    data = await http_json(HOTEL_LOOKUP_URL, params=params)
    if not data or not data.get("results", {}).get("locations"):
        return None
    
    loc = data["results"]["locations"][0]
    loc_name = loc.get("fullName", city_query)
    loc_id = loc.get("id")
    
    # Bugungi va ertangi sana (standart 1 kecha uchun eng arzon narxlar)
    today = date.today()
    check_in = today.strftime("%Y-%m-%d")
    check_out = (today + timedelta(days=1)).strftime("%Y-%m-%d")
    
    # Booking, Agoda va Ostrovok'ning barcha arzon variantlarini o'zida jamlagan rasmiy yo'naltirish
    direct_hotel_url = (
        f"https://search.hotellook.com/?locationId={loc_id}&checkIn={check_in}&checkOut={check_out}"
        f"&adults=1&language={'ru' if lang == 'ru' else 'en'}&currency=usd"
    )
    if MARKER:
        direct_hotel_url += f"&marker={MARKER}"

    # Qo'shimcha to'g'ridan-to'g'ri Booking.com orqali eng arzon filtr bilan ochish
    booking_url = f"https://www.booking.com/searchresults.html?ss={city_query}&order=price"

    return loc_name, direct_hotel_url, booking_url

def format_tickets_details(origin, destination, tickets, lang, rate=None):
    lines = [t(lang, "route_title", o=city(origin, lang), d=city(destination, lang), count=len(tickets))]
    for idx, tk in enumerate(tickets, 1):
        transfers = tk.get("transfers", 0)
        flight_type = t(lang, "direct") if transfers == 0 else t(lang, "stops", n=transfers)
        dep_time = str(tk.get("departure_at", "")).replace("T", " ")[:16]
        airline = tk.get("airline", "Avia")
        flight_num = tk.get("flight_number", "")
        air_info = f"{airline} ({flight_num})" if flight_num else airline

        lines.append(
            f"<b>#{idx}-Chipta ma'lumotlari:</b>\n"
            f"💵 Narxi: <b>{money(tk.get('price'), rate, lang)}</b>\n"
            f"{t(lang, 'flight_time', dt=dep_time)}\n"
            f"{t(lang, 'airline', a=air_info)}\n"
            f"🔄 {flight_type}\n"
            f"<i>(GoToGate, OneTwoTrip, City.Travel bo'yicha eng past narx)</i>\n"
            f"-------------------------------"
        )
    if rate:
        lines.append(t(lang, "rate_line", rate=spaced(rate)))
    return "\n".join(lines)

def format_calendar(origin, dest, year, month, prices, rate, lang):
    today = date.today().isoformat()
    future = {k: v for k, v in prices.items() if k >= today}
    top = sorted(future.items(), key=lambda kv: float(kv[1]["price"]))[:5]
    cheapest = {k for k, _ in top}
    lines = [
        t(lang, "cal_title", o=city(origin, lang), d=city(dest, lang), month=MONTHS[lang][month].capitalize(), year=year),
        "", t(lang, "cal_cheapest")
    ]
    for key, tk in top:
        pretty = f"{key[8:10]}.{key[5:7]}"
        lines.append(t(lang, "cal_line", date=pretty, price=money(tk["price"], rate, lang)))
    lines.append("")
    lines.append(t(lang, "cal_legend"))
    if rate:
        lines.append(t(lang, "rate_line", rate=spaced(rate)))
    return "\n".join(lines), cheapest

# ---------- Handlers ----------
@dp.message(CommandStart())
async def cmd_start(message: Message):
    WAITING.pop(message.from_user.id, None)
    lang = get_lang(message.from_user.id)
    if lang is None:
        await message.answer("🌐 Tilni tanlang / Выберите язык:", reply_markup=kb_lang())
        return
    await message.answer(t(lang, "help"), reply_markup=kb_main_menu(lang), parse_mode="HTML")

@dp.message(F.text.in_(["✈️ Aviachiptalar", "✈️ Авиабилеты"]))
async def menu_avia_click(message: Message):
    lang = lang_of(message.from_user.id)
    WAITING.pop(message.from_user.id, None)
    await message.answer(t(lang, "ask_origin"), reply_markup=kb_origins(lang))

@dp.message(F.text.in_(["🏨 Mehmonxona va Hostellar", "🏨 Отели и Хостелы"]))
async def menu_hotel_click(message: Message):
    lang = lang_of(message.from_user.id)
    WAITING[message.from_user.id] = {"role": "hotel"}
    await message.answer(t(lang, "ask_hotel_city"))

@dp.message(F.text.in_(["🔔 Xabarnomalarim", "🔔 Оповещения"]))
async def menu_alerts_click(message: Message):
    lang = lang_of(message.from_user.id)
    rows = db_all("SELECT * FROM alerts WHERE user_id=? ORDER BY id", (message.from_user.id,))
    if not rows:
        await message.answer(t(lang, "alerts_empty"))
        return
    b = InlineKeyboardBuilder()
    for r in rows:
        price = f"{r['last_price']:.0f}$" if r["last_price"] is not None else "—"
        label = t(lang, "alert_item", o=city(r["origin"], lang), d=city(r["dest"], lang), period=r["period"], price=price)
        b.button(text=label, callback_data=f"x:{r['id']}")
    b.adjust(1)
    await message.answer(t(lang, "alerts_title"), reply_markup=b.as_markup())

@dp.message(F.text.in_(["🌐 Til / Язык"]))
@dp.message(Command("lang"))
async def menu_lang_click(message: Message):
    await message.answer("🌐 Tilni tanlang / Выберите язык:", reply_markup=kb_lang())

@dp.callback_query(F.data.startswith("lang:"))
async def cb_lang_set(call: CallbackQuery):
    await call.answer()
    lang = call.data.split(":")[1]
    set_lang(call.from_user.id, lang)
    await call.message.answer(t(lang, "help"), reply_markup=kb_main_menu(lang), parse_mode="HTML")

@dp.callback_query(F.data == "go_avia")
async def cb_go_avia(call: CallbackQuery):
    await call.answer()
    lang = lang_of(call.from_user.id)
    await call.message.edit_text(t(lang, "ask_origin"), reply_markup=kb_origins(lang))

@dp.callback_query(F.data == "oo")
async def cb_other_origin(call: CallbackQuery):
    await call.answer()
    lang = lang_of(call.from_user.id)
    WAITING[call.from_user.id] = {"role": "origin"}
    await call.message.edit_text(t(lang, "ask_origin_text"))

@dp.callback_query(F.data.startswith("od:"))
async def cb_other_dest(call: CallbackQuery):
    await call.answer()
    lang = lang_of(call.from_user.id)
    origin = call.data.split(":")[1]
    WAITING[call.from_user.id] = {"role": "dest", "origin": origin}
    await call.message.edit_text(t(lang, "ask_dest_text"))

@dp.callback_query(F.data.startswith("o:"))
async def cb_origin(call: CallbackQuery):
    await call.answer()
    lang = lang_of(call.from_user.id)
    origin = call.data.split(":")[1]
    await call.message.edit_text(t(lang, "ask_dest", o=city(origin, lang)), reply_markup=kb_dests(origin, lang))

@dp.callback_query(F.data.startswith("d:"))
async def cb_dest(call: CallbackQuery):
    await call.answer()
    lang = lang_of(call.from_user.id)
    _, origin, dest = call.data.split(":")
    await call.message.edit_text(t(lang, "ask_month", o=city(origin, lang), d=city(dest, lang)), reply_markup=kb_months(origin, dest, lang))

@dp.callback_query(F.data.startswith("m:"))
async def cb_month(call: CallbackQuery):
    await call.answer()
    lang = lang_of(call.from_user.id)
    _, origin, dest, period = call.data.split(":")
    year, month = int(period[:4]), int(period[5:7])
    await call.message.edit_text(t(lang, "searching"))
    prices = await fetch_calendar(origin, dest, period)
    if not prices:
        await call.message.edit_text(t(lang, "cal_empty"))
        return
    rate = await get_rate()
    text, cheapest = format_calendar(origin, dest, year, month, prices, rate, lang)
    await call.message.edit_text(text, reply_markup=kb_calendar(origin, dest, year, month, prices, cheapest, lang))

@dp.callback_query(F.data.startswith("c:"))
async def cb_day(call: CallbackQuery):
    await call.answer()
    lang = lang_of(call.from_user.id)
    _, origin, dest, day = call.data.split(":")
    await call.message.edit_text(t(lang, "searching"))
    tickets = await fetch_tickets(origin, dest, day, limit=3)
    if not tickets:
        await call.message.edit_text(t(lang, "not_found"))
        return
    rate = await get_rate()
    text = format_tickets_details(origin, dest, tickets, lang, rate)
    kb = kb_day_tickets(tickets, origin, dest, day, lang)
    await call.message.edit_text(
        text,
        reply_markup=kb,
        parse_mode="HTML",
        link_preview_options=LinkPreviewOptions(is_disabled=True)
    )

@dp.callback_query(F.data == "n")
async def cb_noop(call: CallbackQuery):
    await call.answer()

@dp.message(F.text & ~F.text.startswith("/"))
async def on_user_text(message: Message):
    user_id = message.from_user.id
    lang = lang_of(user_id)
    state = WAITING.get(user_id)
    if not state:
        return

    # Mehmonxona va hostellar qidiruvi
    if state.get("role") == "hotel":
        WAITING.pop(user_id, None)
        await message.answer(t(lang, "searching"))
        res = await search_hotel_destination(message.text.strip(), lang)
        if not res:
            await message.answer(t(lang, "city_not_found"))
            return
        
        loc_name, direct_url, booking_url = res
        txt = t(lang, "hotel_found_title", city=loc_name)
        
        b = InlineKeyboardBuilder()
        b.button(text=t(lang, "btn_hotel_book", p="Booking / Agoda / Ostrovok"), url=direct_url)
        b.button(text="🏨 Booking.com (Eng arzon filtr)", url=booking_url)
        b.adjust(1)
        
        await message.answer(txt, reply_markup=b.as_markup(), parse_mode="HTML")
        return

    # Aviachipta uchun shahar qidiruvi
    places = await search_places(message.text.strip(), lang)
    if not places:
        await message.answer(t(lang, "city_not_found"))
        return
    if state["role"] == "dest":
        places = [p for p in places if p["code"] != state.get("origin")]
    await message.answer(t(lang, "pick_city"), reply_markup=kb_places(places, state["role"], state.get("origin"), lang))

# ---------- Alertlar ----------
@dp.callback_query(F.data.startswith("w:"))
async def cb_watch(call: CallbackQuery):
    await call.answer()
    lang = lang_of(call.from_user.id)
    _, origin, dest, period = call.data.split(":")
    user_id = call.from_user.id
    route = f"{city(origin, lang)} → {city(dest, lang)}, {period}"

    exists = db_all("SELECT id FROM alerts WHERE user_id=? AND origin=? AND dest=? AND period=?", (user_id, origin, dest, period))
    if exists:
        await call.message.answer(t(lang, "watch_exists", route=route))
        return

    count = db_all("SELECT COUNT(*) AS n FROM alerts WHERE user_id=?", (user_id,))[0]["n"]
    if count >= MAX_ALERTS:
        await call.message.answer(t(lang, "watch_limit", max=MAX_ALERTS))
        return

    tickets = await fetch_tickets(origin, dest, period, limit=1)
    if not tickets:
        await call.message.answer(t(lang, "watch_none"))
        return

    price = float(tickets[0]["price"])
    db_exec("INSERT OR IGNORE INTO alerts (user_id, origin, dest, period, last_price) VALUES (?,?,?,?,?)", (user_id, origin, dest, period, price))
    await call.message.answer(t(lang, "watch_ok", route=route, price=f"{price:.0f}"))

@dp.callback_query(F.data.startswith("x:"))
async def cb_delete_alert(call: CallbackQuery):
    lang = lang_of(call.from_user.id)
    await call.answer(t(lang, "deleted"))
    alert_id = int(call.data.split(":")[1])
    db_exec("DELETE FROM alerts WHERE id=? AND user_id=?", (alert_id, call.from_user.id))
    await menu_alerts_click(call.message)

# ---------- Fon vazifasi ----------
async def check_alerts(bot):
    this_month = date.today().strftime("%Y-%m")
    rows = db_all("SELECT * FROM alerts")
    routes = {}
    for r in rows:
        if r["period"][:7] < this_month:
            db_exec("DELETE FROM alerts WHERE id=?", (r["id"],))
            continue
        routes.setdefault((r["origin"], r["dest"], r["period"]), []).append(r)

    rate = await get_rate() if routes else None
    for (origin, dest, period), items in routes.items():
        tickets = await fetch_tickets(origin, dest, period, limit=1)
        if not tickets:
            continue
        new_price = float(tickets[0]["price"])
        for r in items:
            old_price = r["last_price"]
            db_exec("UPDATE alerts SET last_price=? WHERE id=?", (new_price, r["id"]))
            if old_price is not None and new_price < old_price:
                lang = lang_of(r["user_id"])
                text = t(lang, "dropped", old=f"{old_price:.0f}", new=f"{new_price:.0f}")
                text += format_tickets_details(origin, dest, tickets, lang, rate)
                kb = InlineKeyboardBuilder()
                kb.button(text=t(lang, "btn_buy_ticket", i=1), url=build_ticket_url(tickets[0].get("link")))
                try:
                    await bot.send_message(
                        r["user_id"], text, reply_markup=kb.as_markup(), parse_mode="HTML"
                    )
                except TelegramForbiddenError:
                    db_exec("DELETE FROM alerts WHERE user_id=?", (r["user_id"],))
                except Exception as e:
                    logging.warning("Xabar yuborishda xatolik: %s", e)
        await asyncio.sleep(1)

async def alerts_loop(bot):
    await asyncio.sleep(30)
    while True:
        try:
            await check_alerts(bot)
        except Exception as e:
            logging.error("Alerts loop xatosi: %s", e)
        await asyncio.sleep(CHECK_INTERVAL)

async def main():
    if not BOT_TOKEN or not TP_TOKEN:
        raise SystemExit("BOT_TOKEN va TRAVELPAYOUTS_TOKEN sozlanmagan!")
    init_db()
    bot = Bot(BOT_TOKEN)
    loop_task = asyncio.create_task(alerts_loop(bot))
    try:
        await dp.start_polling(bot)
    finally:
        loop_task.cancel()

if __name__ == "__main__":
    asyncio.run(main())