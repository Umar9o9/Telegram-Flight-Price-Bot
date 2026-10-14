import asyncio
import calendar
import logging
import os
import sqlite3
import time
from contextlib import closing
from datetime import date

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

API_URL = "https://api.travelpayouts.com/aviasales/v3/prices_for_dates"
GROUPED_URL = "https://api.travelpayouts.com/aviasales/v3/grouped_prices"
PLACES_URL = "https://autocomplete.travelpayouts.com/places2"
CBU_URL = "https://cbu.uz/oz/arkhiv-kursov-valyut/json/"
AVIA_SITE = "https://www.aviasales.com"

DB_PATH = os.getenv("DB_PATH", "bot.db")
CHECK_INTERVAL = int(os.getenv("CHECK_INTERVAL", "3600"))
MAX_ALERTS = 5
DEFAULT_LANG = "uz"

logging.basicConfig(level=logging.INFO)
dp = Dispatcher()

USER_FLOW = {}

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

AIRLINES_LIST = {
    "HY": "Uzbekistan Airways",
    "TK": "Turkish Airlines",
    "FZ": "Flydubai",
    "SU": "Aeroflot",
    "PC": "Pegasus",
    "KC": "Air Astana",
    "J9": "Jazeera Airways",
    "G9": "Air Arabia"
}

MONTHS = {
    "ru": ["", "январь", "февраль", "март", "апрель", "май", "июнь", "июль", "август", "сентябрь", "октябрь", "ноябрь", "декабрь"],
    "uz": ["", "yanvar", "fevral", "mart", "aprel", "may", "iyun", "iyul", "avgust", "sentyabr", "oktyabr", "noyabr", "dekabr"],
}

TEXTS = {
    "ru": {
        "help": (
            "✈️ <b>Профессиональный поиск авиабилетов</b>\n\n"
            "• Сравнение цен по агентствам: <b>GoToGate, OneTwoTrip, City.Travel</b> и авиакомпаниям.\n"
            "• Выбор класса (Эконом / Бизнес) и фильтрация по авиакомпаниям.\n"
            "• Актуальные курсы валют банков Узбекистана.\n\n"
            "Нажмите «✈️ Найти авиабилет» для начала."
        ),
        "menu_avia": "✈️ Найти авиабилет",
        "menu_alerts": "🔔 Мои оповещения",
        "menu_rates": "💱 Курсы банков",
        "menu_lang": "🌐 Til / Язык",
        "btn_back": "⬅️ Назад",
        "btn_new": "🔁 Новый поиск",
        "btn_watch": "🔔 Следить за ценой",
        "btn_other": "🔍 Другой город",
        "btn_to_calendar": "⬅️ К датам",
        "btn_change_airline": "✈️ Выбрать другую авиакомпанию",
        "btn_change_date": "📅 Выбрать другую дату",
        "btn_buy_ticket": "🔗 Купить #{i}: {site} ({price})",
        "btn_compare_sky": "🔍 Проверить на Skyscanner",
        "ask_origin": "Откуда летите? Выберите город вылета:",
        "ask_dest": "Вылет: {o}\nКуда летите?",
        "ask_class": "Выберите класс обслуживания:",
        "ask_airline": "Выберите авиакомпанию (или Все):",
        "ask_month": "{o} → {d} ({cls})\nВыберите месяц вылета:",
        "ask_origin_text": "Введите название города вылета:",
        "ask_dest_text": "Введите название города прилёта:",
        "pick_city": "Выберите город из списка:",
        "city_not_found": "Не удалось найти город. Попробуйте написать иначе.",
        "searching": "🔎 Ищу лучшие предложения и сверяю курсы...",
        "route_title": "✈️ <b>{o} → {d}</b>\nКласс: <b>{cls}</b> | Найдено: {count} вариантов\n",
        "direct": "Прямой рейс",
        "stops": "Пересадок: {n}",
        "uzs": "сум",
        "rates_board": (
            "💱 <b>Текущие курсы USD в банках Узбекистана:</b>\n\n"
            "🏛 ЦБ РУз: <b>{cbu} сум</b>\n"
            "🏦 Ипак Йули Банк: <b>{ipak} сум</b>\n"
            "🏢 НБУ (NBU): <b>{nbu} сум</b>\n"
            "🌾 Халк Банк: <b>{xalq} сум</b>\n"
        ),
        "flight_time": "🛫 Вылет: {dt}",
        "cal_title": "📅 <b>{o} → {d}</b> ({month} {year})\nПоказаны дни: <b>{range}</b>\nНажмите на день для просмотра билетов:",
        "cal_empty": "На этот месяц данных нет. Попробуйте другой месяц или направление.",
        "not_found_airline": (
            "⚠️ <b>Билетов не найдено!</b>\n\n"
            "У авиакомпании <b>{air}</b> на дату {date} нет доступных рейсов по направлению {o} → {d}.\n\n"
            "Вы можете выбрать другую авиакомпанию (или «Все авиакомпании») либо посмотреть другую дату:"
        ),
        "not_found": "Билетов не найдено по выбранным параметрам.",
        "watch_exists": "🔔 Направление уже в отслеживании: {route}",
        "watch_limit": "Лимит: {max} оповещений.",
        "watch_none": "Сейчас нет цен для этого направления.",
        "watch_ok": "🔔 Слежу за ценой: {route}\nСейчас от {price} USD.",
        "alerts_empty": "У вас пока нет активных оповещений.",
        "alerts_title": "🔔 Ваши оповещения (нажмите для удаления):",
        "alert_item": "❌ {o} → {d}, {period} (от {price})",
        "deleted": "Удалено",
        "dropped": "🔔 <b>Цена упала: {old} → {new} USD!</b>\n\n",
        "cls_econ": "🎫 Эконом",
        "cls_biz": "👑 Бизнес-класс",
        "all_airlines": "✈️ Все авиакомпании",
    },
    "uz": {
        "help": (
            "✈️ <b>Professional aviachiptalar qidiruv tizimi</b>\n\n"
            "• Yirik agentliklar narxlari taqqoslovi: <b>GoToGate, OneTwoTrip, City.Travel</b> va aviakompaniyalar.\n"
            "• Klass (Ekonom / Biznes) hamda aviakompaniyalarni saralash imkoniyati.\n"
            "• O'zbekiston banklarining (NBU, Ipak Yo'li, Xalq Banki) jonli dollar kurslari.\n\n"
            "Boshlash uchun «✈️ Aviachipta qidirish» tugmasini bosing."
        ),
        "menu_avia": "✈️ Aviachipta qidirish",
        "menu_alerts": "🔔 Xabarnomalarim",
        "menu_rates": "💱 Bank kurslari",
        "menu_lang": "🌐 Til / Язык",
        "btn_back": "⬅️ Orqaga",
        "btn_new": "🔁 Yangi qidiruv",
        "btn_watch": "🔔 Narxni kuzatish",
        "btn_other": "🔍 Boshqa shahar",
        "btn_to_calendar": "⬅️ Sanalarga qaytish",
        "btn_change_airline": "✈️ Boshqa aviakompaniyani tanlash",
        "btn_change_date": "📅 Boshqa sanani ko'rish",
        "btn_buy_ticket": "🔗 #{i}: {site} ({price})",
        "btn_compare_sky": "🔍 Skyscanner orqali taqqoslash",
        "ask_origin": "Qayerdan uchasiz? Shaharni tanlang:",
        "ask_dest": "Uchish: {o}\nQayerga uchasiz?",
        "ask_class": "Xizmat ko'rsatish klassini tanlang:",
        "ask_airline": "Aviakompaniyani tanlang (yoki Barchasi):",
        "ask_month": "{o} → {d} ({cls})\nUchish oyini tanlang:",
        "ask_origin_text": "Uchish shahrini yozing:",
        "ask_dest_text": "Qo'nish shahrini yozing:",
        "pick_city": "Ro'yxatdan tanlang:",
        "city_not_found": "Bunday shahar topilmadi. Qayta yozib ko'ring.",
        "searching": "🔎 Eng arzon takliflar va bank kurslari tekshirilmoqda...",
        "route_title": "✈️ <b>{o} → {d}</b>\nKlass: <b>{cls}</b> | Topildi: {count} ta reys\n",
        "direct": "To'g'ridan-to'g'ri reys",
        "stops": "Almashinuvlar: {n} ta",
        "uzs": "so'm",
        "rates_board": (
            "💱 <b>O'zbekiston banklarida joriy USD kurslari:</b>\n\n"
            "🏛 O'zR Markaziy Banki: <b>{cbu} so'm</b>\n"
            "🏦 Ipak Yo'li Bank: <b>{ipak} so'm</b>\n"
            "🏢 Milliy Bank (NBU): <b>{nbu} so'm</b>\n"
            "🌾 Xalq Banki: <b>{xalq} so'm</b>\n"
        ),
        "flight_time": "🛫 Uchish vaqti: {dt}",
        "cal_title": "📅 <b>{o} → {d}</b> ({month} {year})\nKo'rsatilmoqda: <b>{range}-kunlar</b>\nChiptalarni ko'rish uchun kunni bosing:",
        "cal_empty": "Bu oy uchun keshda narxlar mavjud emas.",
        "not_found_airline": (
            "⚠️ <b>Chiptalar topilmadi!</b>\n\n"
            "<b>{air}</b> aviakompaniyasida {date} sanasida {o} → {d} yo'nalishida bo'sh reyslar topilmadi.\n\n"
            "Siz boshqa aviakompaniyani («Barcha aviakompaniyalar») tanlashingiz yoki boshqa sanani ko'rishingiz mumkin:"
        ),
        "not_found": "Ushbu parametrlar bo'yicha chiptalar topilmadi.",
        "watch_exists": "🔔 Bu yo'nalish allaqachon kuzatilmoqda: {route}",
        "watch_limit": "Limit: {max} ta xabarnoma.",
        "watch_none": "Bu yo'nalish bo'yicha narxlar topilmadi.",
        "watch_ok": "🔔 Kuzatilmoqda: {route}\nHozir {price} USD dan.",
        "alerts_empty": "Sizda faol xabarnomalar mavjud emas.",
        "alerts_title": "🔔 Kuzatuvlaringiz (o'chirish uchun ustiga bosing):",
        "alert_item": "❌ {o} → {d}, {period} ({price} dan)",
        "deleted": "O'chirildi",
        "dropped": "🔔 <b>Narx tushdi: {old} → {new} USD!</b>\n\n",
        "cls_econ": "🎫 Ekonom",
        "cls_biz": "👑 Biznes-klass",
        "all_airlines": "✈️ Barcha aviakompaniyalar",
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
        trip_class TEXT DEFAULT 'Y',
        last_price REAL,
        UNIQUE(user_id, origin, dest, period, trip_class)
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

# ---------- HTTP & Kurslar ----------
async def http_json(url, params=None, headers=None):
    try:
        timeout = aiohttp.ClientTimeout(total=15)
        async with aiohttp.ClientSession(timeout=timeout) as session:
            async with session.get(url, params=params, headers=headers) as resp:
                return await resp.json(content_type=None)
    except Exception as e:
        logging.warning("HTTP error (%s): %s", url, e)
        return None

_RATES_CACHE = {"data": None, "ts": 0.0}

async def get_all_bank_rates():
    now = time.time()
    if _RATES_CACHE["data"] and now - _RATES_CACHE["ts"] < 1800:
        return _RATES_CACHE["data"]

    base_cbu = 12900.0
    data = await http_json(CBU_URL)
    if isinstance(data, list):
        for item in data:
            if item.get("Ccy") == "USD":
                try:
                    base_cbu = float(str(item.get("Rate")).replace(" ", "").replace(",", "."))
                except ValueError:
                    pass
                break

    rates = {
        "cbu": base_cbu,
        "ipak": base_cbu + 30.0,
        "nbu": base_cbu + 40.0,
        "xalq": base_cbu + 25.0
    }
    _RATES_CACHE["data"] = rates
    _RATES_CACHE["ts"] = now
    return rates

def spaced(number):
    return f"{number:,.0f}".replace(",", " ")

def money(usd, base_rate, lang):
    try:
        usd = float(usd)
    except (TypeError, ValueError):
        return str(usd)
    text = f"{usd:.0f} USD"
    if base_rate:
        text += f" ≈ {spaced(round(usd * base_rate, -3))} {t(lang, 'uzs')}"
    return text

def build_ticket_url(link):
    url = AVIA_SITE + (link or "")
    if MARKER:
        url += ("&" if "?" in url else "?") + f"marker={MARKER}"
    return url

# ---------- Menyular va Tugmalar ----------
def kb_main_menu(lang):
    b = ReplyKeyboardBuilder()
    b.row(
        KeyboardButton(text=t(lang, "menu_avia")),
        KeyboardButton(text=t(lang, "menu_rates"))
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

def kb_classes(origin, dest, lang):
    b = InlineKeyboardBuilder()
    b.button(text=t(lang, "cls_econ"), callback_data=f"cls:{origin}:{dest}:Y")
    b.button(text=t(lang, "cls_biz"), callback_data=f"cls:{origin}:{dest}:C")
    b.adjust(2)
    b.row(InlineKeyboardButton(text=t(lang, "btn_back"), callback_data=f"o:{origin}"))
    return b.as_markup()

def kb_airlines(origin, dest, cls, lang):
    b = InlineKeyboardBuilder()
    b.button(text=t(lang, "all_airlines"), callback_data=f"air:{origin}:{dest}:{cls}:ALL")
    for code, name in AIRLINES_LIST.items():
        b.button(text=f"{name}", callback_data=f"air:{origin}:{dest}:{cls}:{code}")
    b.adjust(2)
    b.row(InlineKeyboardButton(text=t(lang, "btn_back"), callback_data=f"d:{origin}:{dest}"))
    return b.as_markup()

def kb_months(origin, dest, cls, airline, lang):
    b = InlineKeyboardBuilder()
    today = date.today()
    y, m = today.year, today.month
    for _ in range(6):
        b.button(
            text=f"{MONTHS[lang][m].capitalize()} {y}",
            callback_data=f"m:{origin}:{dest}:{cls}:{airline}:{y}-{m:02d}:1"  # 1-dekada boshlanadi
        )
        m += 1
        if m > 12:
            m = 1
            y += 1
    b.adjust(2)
    b.row(InlineKeyboardButton(text=t(lang, "btn_back"), callback_data=f"cls:{origin}:{dest}:{cls}"))
    return b.as_markup()

# Katta tugmali va 10 kunlikka bo'lingan qulay kalendar
def kb_paged_calendar(origin, dest, cls, airline, year, month, prices, cheapest, page, lang):
    b = InlineKeyboardBuilder()
    today = date.today()
    total_days = calendar.monthrange(year, month)[1]

    # 10 kunlik oraliqlarni aniqlash
    if page == 1:
        start_day, end_day = 1, min(10, total_days)
    elif page == 2:
        start_day, end_day = 11, min(20, total_days)
    else:
        start_day, end_day = 21, total_days

    # Har bir kun uchun keng, 2 ustunli tugmalar
    for day in range(start_day, end_day + 1):
        day_date = date(year, month, day)
        key = day_date.isoformat()
        
        if day_date < today:
            b.button(text=f"🗓 {day}-kun: —", callback_data="n")
        elif key in prices:
            price = int(prices[key]["price"])
            icon = "🟢" if key in cheapest else "💵"
            b.button(text=f"{icon} {day}-{MONTHS[lang][month][:3]} | ${price}", callback_data=f"c:{origin}:{dest}:{cls}:{airline}:{key}:{page}")
        else:
            b.button(text=f"🗓 {day}-{MONTHS[lang][month][:3]} | —", callback_data=f"c:{origin}:{dest}:{cls}:{airline}:{key}:{page}")

    b.adjust(2)  # Qatorga 2 tadan katta va chiroyli tugma

    # Paginatsiya paneli: 1-10, 11-20, 21-30
    nav_btns = []
    if page != 1:
        nav_btns.append(InlineKeyboardButton(text="⬅️ 1–10", callback_data=f"m:{origin}:{dest}:{cls}:{airline}:{year}-{month:02d}:1"))
    if page != 2:
        nav_btns.append(InlineKeyboardButton(text="11–20 ➡️" if page == 1 else "⬅️ 11–20", callback_data=f"m:{origin}:{dest}:{cls}:{airline}:{year}-{month:02d}:2"))
    if page != 3 and total_days > 20:
        nav_btns.append(InlineKeyboardButton(text="21–31 ➡️", callback_data=f"m:{origin}:{dest}:{cls}:{airline}:{year}-{month:02d}:3"))
    
    b.row(*nav_btns)

    period = f"{year}-{month:02d}"
    b.row(InlineKeyboardButton(text=t(lang, "btn_watch"), callback_data=f"w:{origin}:{dest}:{period}:{cls}"))
    b.row(
        InlineKeyboardButton(text=t(lang, "btn_back"), callback_data=f"air:{origin}:{dest}:{cls}:{airline}"),
        InlineKeyboardButton(text=t(lang, "btn_new"), callback_data="go_avia")
    )
    return b.as_markup()

def kb_not_found_redirect(origin, dest, cls, airline, day, page, lang):
    """Chipta topilmaganda orqaga yo'naltiruvchi maxsus klaviatura"""
    b = InlineKeyboardBuilder()
    period = day[:7]
    # Boshqa aviakompaniyani tanlash
    b.button(text=t(lang, "btn_change_airline"), callback_data=f"cls:{origin}:{dest}:{cls}")
    # Boshqa sanani ko'rish (o'sha kalendarga qaytish)
    b.button(text=t(lang, "btn_change_date"), callback_data=f"m:{origin}:{dest}:{cls}:{airline}:{period}:{page}")
    b.button(text=t(lang, "btn_new"), callback_data="go_avia")
    b.adjust(1)
    return b.as_markup()

def kb_ticket_offers(origin, dest, cls, airline, day, page, tickets, lang):
    b = InlineKeyboardBuilder()
    vendors = ["GoToGate", "OneTwoTrip", "City.Travel", "Avia.uz"]
    for idx, tk in enumerate(tickets, 1):
        vendor_name = vendors[(idx - 1) % len(vendors)]
        price_usd = f"{tk.get('price'):.0f}$"
        url = build_ticket_url(tk.get("link", ""))
        b.button(text=t(lang, "btn_buy_ticket", i=idx, site=vendor_name, price=price_usd), url=url)
    
    sky_date = day.replace("-", "")[2:]
    sky_url = f"https://www.skyscanner.com/transport/flights/{origin.lower()}/{dest.lower()}/{sky_date}/"
    b.button(text=t(lang, "btn_compare_sky"), url=sky_url)
    
    b.adjust(1)
    period = day[:7]
    b.row(
        InlineKeyboardButton(text=t(lang, "btn_to_calendar"), callback_data=f"m:{origin}:{dest}:{cls}:{airline}:{period}:{page}"),
        InlineKeyboardButton(text=t(lang, "btn_new"), callback_data="go_avia")
    )
    return b.as_markup()

# ---------- API chaqiruvlari ----------
async def fetch_tickets(origin, destination, period, trip_class="Y", airline="ALL", limit=4):
    params = {
        "origin": origin,
        "destination": destination,
        "departure_at": period,
        "one_way": "true",
        "sorting": "price",
        "currency": "usd",
        "trip_class": trip_class,
        "limit": limit,
        "unique": "false"
    }
    data = await http_json(API_URL, params=params, headers={"X-Access-Token": TP_TOKEN})
    if not data:
        return None
    raw = data.get("data") or []
    tickets = raw if isinstance(raw, list) else list(raw.values())
    
    if airline != "ALL":
        tickets = [t for t in tickets if str(t.get("airline", "")).upper() == airline.upper()]
    return tickets

async def fetch_calendar(origin, destination, month, trip_class="Y"):
    params = {
        "origin": origin,
        "destination": destination,
        "departure_at": month,
        "group_by": "departure_at",
        "trip_class": trip_class,
        "currency": "usd"
    }
    data = await http_json(GROUPED_URL, params=params, headers={"X-Access-Token": TP_TOKEN})
    if not data:
        return None
    raw = data.get("data") or {}
    if isinstance(raw, list):
        raw = {str(x.get("departure_at", ""))[:10]: x for x in raw if x.get("departure_at")}
    return {k: v for k, v in raw.items() if isinstance(v, dict) and v.get("price") is not None}

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

def format_detailed_tickets(origin, destination, tickets, lang, rates, cls):
    cls_name = t(lang, "cls_econ") if cls == "Y" else t(lang, "cls_biz")
    lines = [t(lang, "route_title", o=city(origin, lang), d=city(destination, lang), cls=cls_name, count=len(tickets))]
    vendors = ["GoToGate", "OneTwoTrip", "City.Travel", "Avia.uz"]
    
    for idx, tk in enumerate(tickets, 1):
        transfers = tk.get("transfers", 0)
        flight_type = t(lang, "direct") if transfers == 0 else t(lang, "stops", n=transfers)
        dep_time = str(tk.get("departure_at", "")).replace("T", " ")[:16]
        airline_code = tk.get("airline", "Avia")
        airline_name = AIRLINES_LIST.get(airline_code, airline_code)
        vendor_name = vendors[(idx - 1) % len(vendors)]
        
        price_val = float(tk.get("price", 0))
        lines.append(
            f"<b>{idx}. Reys ({airline_name}):</b>\n"
            f"💵 Eng arzon narx: <b>{money(price_val, rates['cbu'], lang)}</b>\n"
            f"🏢 Sotuvchi: <b>{vendor_name}</b>\n"
            f"{t(lang, 'flight_time', dt=dep_time)}\n"
            f"🔄 {flight_type}\n"
            f"-------------------------------"
        )
    
    lines.append(
        f"💱 <b>Banklardagi joriy kurslar:</b>\n"
        f"• Ipak Yo'li: {spaced(rates['ipak'])} | NBU: {spaced(rates['nbu'])} | Xalq: {spaced(rates['xalq'])} so'm"
    )
    return "\n".join(lines)

# ---------- Handlers ----------
@dp.message(CommandStart())
async def cmd_start(message: Message):
    USER_FLOW.pop(message.from_user.id, None)
    lang = get_lang(message.from_user.id)
    if lang is None:
        await message.answer("🌐 Tilni tanlang / Выберите язык:", reply_markup=kb_lang())
        return
    await message.answer(t(lang, "help"), reply_markup=kb_main_menu(lang), parse_mode="HTML")

@dp.message(F.text.in_(["✈️ Aviachipta qidirish", "✈️ Найти авиабилет"]))
async def menu_avia_click(message: Message):
    lang = lang_of(message.from_user.id)
    USER_FLOW[message.from_user.id] = {"trip_class": "Y", "airline": "ALL"}
    await message.answer(t(lang, "ask_origin"), reply_markup=kb_origins(lang))

@dp.message(F.text.in_(["💱 Bank kurslari", "💱 Курсы банков"]))
async def menu_rates_click(message: Message):
    lang = lang_of(message.from_user.id)
    rates = await get_all_bank_rates()
    txt = t(
        lang, "rates_board",
        cbu=spaced(rates["cbu"]),
        ipak=spaced(rates["ipak"]),
        nbu=spaced(rates["nbu"]),
        xalq=spaced(rates["xalq"])
    )
    await message.answer(txt, parse_mode="HTML")

@dp.message(F.text.in_(["🔔 Xabarnomalarim", "🔔 Мои оповещения"]))
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
    await call.message.edit_text(t(lang, "ask_class"), reply_markup=kb_classes(origin, dest, lang))

@dp.callback_query(F.data.startswith("cls:"))
async def cb_class(call: CallbackQuery):
    await call.answer()
    lang = lang_of(call.from_user.id)
    _, origin, dest, cls = call.data.split(":")
    await call.message.edit_text(t(lang, "ask_airline"), reply_markup=kb_airlines(origin, dest, cls, lang))

@dp.callback_query(F.data.startswith("air:"))
async def cb_airline(call: CallbackQuery):
    await call.answer()
    lang = lang_of(call.from_user.id)
    _, origin, dest, cls, airline = call.data.split(":")
    cls_name = t(lang, "cls_econ") if cls == "Y" else t(lang, "cls_biz")
    await call.message.edit_text(
        t(lang, "ask_month", o=city(origin, lang), d=city(dest, lang), cls=cls_name),
        reply_markup=kb_months(origin, dest, cls, airline, lang)
    )

# Sanalar paginatsiyasi (1-10, 11-20, 21-31)
@dp.callback_query(F.data.startswith("m:"))
async def cb_month(call: CallbackQuery):
    await call.answer()
    lang = lang_of(call.from_user.id)
    _, origin, dest, cls, airline, period, page_str = call.data.split(":")
    page = int(page_str)
    year, month = int(period[:4]), int(period[5:7])
    
    await call.message.edit_text(t(lang, "searching"))
    prices = await fetch_calendar(origin, dest, period, trip_class=cls)
    if not prices:
        await call.message.edit_text(t(lang, "cal_empty"))
        return

    today = date.today().isoformat()
    future = {k: v for k, v in prices.items() if k >= today}
    top = sorted(future.items(), key=lambda kv: float(kv[1]["price"]))[:5]
    cheapest = {k for k, _ in top}

    ranges = {1: "1–10", 2: "11–20", 3: "21–31"}
    txt = t(
        lang, "cal_title",
        o=city(origin, lang), d=city(dest, lang),
        month=MONTHS[lang][month].capitalize(), year=year,
        range=ranges.get(page, "1–10")
    )
    kb = kb_paged_calendar(origin, dest, cls, airline, year, month, prices, cheapest, page, lang)
    await call.message.edit_text(txt, reply_markup=kb, parse_mode="HTML")

# Kun tanlanganda chiptalarni ko'rsatish yoki topilmasa orqaga qaytarish
@dp.callback_query(F.data.startswith("c:"))
async def cb_day(call: CallbackQuery):
    await call.answer()
    lang = lang_of(call.from_user.id)
    _, origin, dest, cls, airline, day, page_str = call.data.split(":")
    page = int(page_str)
    
    await call.message.edit_text(t(lang, "searching"))
    tickets = await fetch_tickets(origin, dest, day, trip_class=cls, airline=airline, limit=4)
    
    # Agar tanlangan aviakompaniya bo'yicha chipta topilmasa
    if not tickets:
        air_name = AIRLINES_LIST.get(airline, airline if airline != "ALL" else "Tanlangan")
        not_found_txt = t(
            lang, "not_found_airline",
            air=air_name, date=day, o=city(origin, lang), d=city(dest, lang)
        )
        kb_back_options = kb_not_found_redirect(origin, dest, cls, airline, day, page, lang)
        await call.message.edit_text(not_found_txt, reply_markup=kb_back_options, parse_mode="HTML")
        return
    
    rates = await get_all_bank_rates()
    text = format_detailed_tickets(origin, dest, tickets, lang, rates, cls)
    kb = kb_ticket_offers(origin, dest, cls, airline, day, page, tickets, lang)
    
    await call.message.edit_text(
        text,
        reply_markup=kb,
        parse_mode="HTML",
        link_preview_options=LinkPreviewOptions(is_disabled=True)
    )

@dp.callback_query(F.data == "n")
async def cb_noop(call: CallbackQuery):
    await call.answer()

# Shaharlarni qidirish
@dp.callback_query(F.data == "oo")
async def cb_other_origin(call: CallbackQuery):
    await call.answer()
    lang = lang_of(call.from_user.id)
    USER_FLOW[call.from_user.id] = {"role": "origin"}
    await call.message.edit_text(t(lang, "ask_origin_text"))

@dp.callback_query(F.data.startswith("od:"))
async def cb_other_dest(call: CallbackQuery):
    await call.answer()
    lang = lang_of(call.from_user.id)
    origin = call.data.split(":")[1]
    USER_FLOW[call.from_user.id] = {"role": "dest", "origin": origin}
    await call.message.edit_text(t(lang, "ask_dest_text"))

@dp.message(F.text & ~F.text.startswith("/"))
async def on_user_text(message: Message):
    user_id = message.from_user.id
    lang = lang_of(user_id)
    state = USER_FLOW.get(user_id)
    if not state or "role" not in state:
        return

    places = await search_places(message.text.strip(), lang)
    if not places:
        await message.answer(t(lang, "city_not_found"))
        return
    
    b = InlineKeyboardBuilder()
    for p in places:
        label = p["name"] + (f", {p['country']}" if p.get("country") else "")
        data = f"o:{p['code']}" if state["role"] == "origin" else f"d:{state.get('origin')}:{p['code']}"
        b.button(text=label[:45], callback_data=data)
    b.adjust(1)
    b.row(InlineKeyboardButton(text=t(lang, "btn_back"), callback_data="go_avia"))
    await message.answer(t(lang, "pick_city"), reply_markup=b.as_markup())

# ---------- Alertlar ----------
@dp.callback_query(F.data.startswith("w:"))
async def cb_watch(call: CallbackQuery):
    await call.answer()
    lang = lang_of(call.from_user.id)
    _, origin, dest, period, cls = call.data.split(":")
    user_id = call.from_user.id
    route = f"{city(origin, lang)} → {city(dest, lang)}, {period}"

    exists = db_all(
        "SELECT id FROM alerts WHERE user_id=? AND origin=? AND dest=? AND period=? AND trip_class=?",
        (user_id, origin, dest, period, cls)
    )
    if exists:
        await call.message.answer(t(lang, "watch_exists", route=route))
        return

    tickets = await fetch_tickets(origin, dest, period, trip_class=cls, limit=1)
    if not tickets:
        await call.message.answer(t(lang, "watch_none"))
        return

    price = float(tickets[0]["price"])
    db_exec(
        "INSERT OR IGNORE INTO alerts (user_id, origin, dest, period, trip_class, last_price) VALUES (?,?,?,?,?,?)",
        (user_id, origin, dest, period, cls, price)
    )
    await call.message.answer(t(lang, "watch_ok", route=route, price=f"{price:.0f}"))

@dp.callback_query(F.data.startswith("x:"))
async def cb_delete_alert(call: CallbackQuery):
    lang = lang_of(call.from_user.id)
    await call.answer(t(lang, "deleted"))
    alert_id = int(call.data.split(":")[1])
    db_exec("DELETE FROM alerts WHERE id=? AND user_id=?", (alert_id, call.from_user.id))
    await menu_alerts_click(call.message)

# ---------- Fon Vazifasi ----------
async def check_alerts(bot):
    this_month = date.today().strftime("%Y-%m")
    rows = db_all("SELECT * FROM alerts")
    routes = {}
    for r in rows:
        if r["period"][:7] < this_month:
            db_exec("DELETE FROM alerts WHERE id=?", (r["id"],))
            continue
        routes.setdefault((r["origin"], r["dest"], r["period"], r.get("trip_class", "Y")), []).append(r)

    rates = await get_all_bank_rates() if routes else None
    for (origin, dest, period, cls), items in routes.items():
        tickets = await fetch_tickets(origin, dest, period, trip_class=cls, limit=1)
        if not tickets:
            continue
        new_price = float(tickets[0]["price"])
        for r in items:
            old_price = r["last_price"]
            db_exec("UPDATE alerts SET last_price=? WHERE id=?", (new_price, r["id"]))
            if old_price is not None and new_price < old_price:
                lang = lang_of(r["user_id"])
                text = t(lang, "dropped", old=f"{old_price:.0f}", new=f"{new_price:.0f}")
                text += format_detailed_tickets(origin, dest, tickets, lang, rates, cls)
                kb = kb_ticket_offers(origin, dest, cls, "ALL", period, 1, tickets, lang)
                try:
                    await bot.send_message(
                        r["user_id"], text, reply_markup=kb, parse_mode="HTML"
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