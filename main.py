import asyncio
import calendar
import logging
import os
import sqlite3
import time
from contextlib import closing
from datetime import date, datetime

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
DEFAULT_COUNTRY = "UZ"

logging.basicConfig(level=logging.INFO)
dp = Dispatcher()

USER_FLOW = {}

# Mintaqalar bo'yicha aeroportlar
COUNTRY_ORIGINS = {
    "UZ": ["TAS", "SKD", "BHK", "FEG", "NMA", "AZN", "UGC", "NCU", "TMJ", "KSQ"],
    "RU": ["MOW", "LED", "KZN", "OVB", "SVX", "AER", "ROV", "UFA", "KRR", "MRV"],
    "KZ": ["ALA", "NQZ", "CIT", "GUW", "SCO", "AKX"],
    "TR": ["IST", "SAW", "AYT", "ESB", "ADB", "DLM"],
    "AE": ["DXB", "AUH", "SHJ"]
}

DEST_CODES = [
    "NYC", "LON", "PAR", "BER", "FRA", "ROM", "PRG", "WAW", "VIE", "MAD",
    "IST", "AYT", "DXB", "JED", "MOW", "LED", "ALA", "TBS", "BAK"
]

CITY = {
    "ru": {
        "TAS": "Ташкент", "SKD": "Самарканд", "BHK": "Бухара", "FEG": "Фергана",
        "NMA": "Наманган", "AZN": "Андижан", "UGC": "Ургенч", "NCU": "Нукус",
        "TMJ": "Термез", "KSQ": "Карши",
        "MOW": "Москва", "LED": "Санкт-Петербург", "KZN": "Казань", "OVB": "Новосибирск",
        "SVX": "Екатеринбург", "AER": "Сочи", "ROV": "Ростов", "UFA": "Уфа", "KRR": "Краснодар", "MRV": "Минводы",
        "ALA": "Алматы", "NQZ": "Астана", "CIT": "Шымкент", "GUW": "Атырау", "SCO": "Актау", "AKX": "Актобе",
        "SAW": "Стамбул (Сабиха)", "ESB": "Анкара", "ADB": "Измир", "DLM": "Даламан",
        "AUH": "Абу-Даби", "SHJ": "Шарджа",
        "NYC": "Нью-Йорк", "LON": "Лондон", "PAR": "Париж", "BER": "Берлин",
        "FRA": "Франкфурт", "ROM": "Рим", "PRG": "Прага", "WAW": "Варшава",
        "VIE": "Вена", "MAD": "Мадрид", "IST": "Стамбул", "AYT": "Анталья",
        "DXB": "Дубай", "JED": "Джидда", "TBS": "Тбилиси", "BAK": "Баку"
    },
    "uz": {
        "TAS": "Toshkent", "SKD": "Samarqand", "BHK": "Buxoro", "FEG": "Farg'ona",
        "NMA": "Namangan", "AZN": "Andijon", "UGC": "Urganch", "NCU": "Nukus",
        "TMJ": "Termiz", "KSQ": "Qarshi",
        "MOW": "Moskva", "LED": "Sankt-Peterburg", "KZN": "Qozon", "OVB": "Novosibirsk",
        "SVX": "Yekaterinburg", "AER": "Sochi", "ROV": "Rostov", "UFA": "Ufa", "KRR": "Krasnodar", "MRV": "Minvod",
        "ALA": "Almati", "NQZ": "Ostona", "CIT": "Chimkent", "GUW": "Atirau", "SCO": "Aqtau", "AKX": "Aqtobe",
        "SAW": "Istanbul (Sabiha)", "ESB": "Anqara", "ADB": "Izmir", "DLM": "Dalaman",
        "AUH": "Abu-Dabi", "SHJ": "Sharja",
        "NYC": "Nyu-York", "LON": "London", "PAR": "Parij", "BER": "Berlin",
        "FRA": "Frankfurt", "ROM": "Rim", "PRG": "Praga", "WAW": "Varshava",
        "VIE": "Vena", "MAD": "Madrid", "IST": "Istanbul", "AYT": "Antaliya",
        "DXB": "Dubay", "JED": "Jidda", "TBS": "Tbilisi", "BAK": "Boku"
    },
}

AIRLINES_LIST = {
    "HY": "Uzbekistan Airways",
    "TK": "Turkish Airlines",
    "FZ": "Flydubai",
    "SU": "Aeroflot",
    "PC": "Pegasus",
    "LH": "Lufthansa",
    "LO": "LOT Polish Airlines",
    "QR": "Qatar Airways",
    "EK": "Emirates",
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
            "✈️ <b>Международный поиск авиабилетов</b>\n\n"
            "• Рейсы в одну сторону и <b>Туда-обратно</b>.\n"
            "• Прямые ссылки на покупку: <b>GoToGate, OneTwoTrip, Trip.com, Aviasales, Skyscanner</b>.\n"
            "• Выбор домашнего региона: список вылетов адаптируется под вашу страну.\n\n"
            "Выберите пункт меню ниже:"
        ),
        "menu_avia": "✈️ Найти авиабилет",
        "menu_alerts": "🔔 Мои оповещения",
        "menu_rates": "💱 Курсы банков",
        "menu_country": "📍 Мой регион",
        "menu_lang": "🌐 Til / Язык",
        "btn_back": "⬅️ Назад",
        "btn_new": "🔁 Новый поиск",
        "btn_watch": "🔔 Следить за ценой",
        "btn_more_cities": "🌍 Другой город (Поиск)",
        "btn_to_calendar": "⬅️ К датам",
        "btn_change_airline": "✈️ Другая авиакомпания",
        "btn_change_date": "📅 Другая дата",
        "btn_add_return": "🔄 Добавить обратный билет (Туда-обратно)",
        "btn_oneway_only": "➡️ Только в одну сторону",
        "ask_country": "📍 Выберите страну, где вы сейчас находитесь:",
        "country_set": "✅ Ваш регион установлен: {c}. Теперь список вылетов будет адаптирован!",
        "ask_origin": "Откуда вылетаете? (Города региона {c}):",
        "ask_dest": "Вылет: {o}\nКуда летите?",
        "ask_class": "Выберите класс обслуживания:",
        "ask_airline": "Выберите авиакомпанию:",
        "ask_month": "{o} → {d} ({cls})\nВыберите месяц вылета:",
        "ask_return_decision": "📅 Вы выбрали дату вылета: <b>{date}</b>.\n\nЖелаете добавить дату возвращения (Туда-обратно)?",
        "ask_return_month": "Выберите месяц возвращения:",
        "ask_origin_text": "Введите название любого города вылета:",
        "ask_dest_text": "Введите название любого города назначения:",
        "pick_city": "Выберите подходящий город из списка:",
        "city_not_found": "Не удалось найти город. Попробуйте написать иначе.",
        "searching": "🔎 Ищу лучшие предложения и проверяю агентства...",
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
        "cal_title": "📅 <b>{o} → {d}</b> ({month} {year})\nПоказаны дни: <b>{range}</b>\nНажмите на день:",
        "cal_empty": "На этот месяц данных нет.",
        "not_found_airline": (
            "⚠️ <b>Билетов не найдено!</b>\n\n"
            "У авиакомпании <b>{air}</b> на дату {date} нет доступных рейсов {o} → {d}.\n\n"
            "Выберите другое действие:"
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
            "✈️ <b>Xalqaro aviachiptalar qidiruv tizimi</b>\n\n"
            "• Bir tomonga va <b>Borish-qaytish (Tuda-obratno)</b> chiptalari.\n"
            "• <b>GoToGate, OneTwoTrip, Trip.com, Aviasales, Skyscanner</b> platformalariga to'g'ridan-to'g'ri havolalar.\n"
            "• Yashash mintaqangizga moslashuvchi qulay qidiruv.\n\n"
            "Boshlash uchun quyidagi menyudan foydalaning:"
        ),
        "menu_avia": "✈️ Aviachipta qidirish",
        "menu_alerts": "🔔 Xabarnomalarim",
        "menu_rates": "💱 Bank kurslari",
        "menu_country": "📍 Mintaqam",
        "menu_lang": "🌐 Til / Язык",
        "btn_back": "⬅️ Orqaga",
        "btn_new": "🔁 Yangi qidiruv",
        "btn_watch": "🔔 Narxni kuzatish",
        "btn_more_cities": "🌍 Boshqa shahar (Qidirish)",
        "btn_to_calendar": "⬅️ Sanalarga qaytish",
        "btn_change_airline": "✈️ Boshqa aviakompaniyani tanlash",
        "btn_change_date": "📅 Boshqa sanani ko'rish",
        "btn_add_return": "🔄 Qaytish sanasini qo'shish (Tuda-obratno)",
        "btn_oneway_only": "➡️ Faqat bir tomonga davom etish",
        "ask_country": "📍 Hozirda yashayotgan yoki bo'lib turgan davlatingizni tanlang:",
        "country_set": "✅ Mintaqangiz belgilandi: {c}. Endi uchish shaharlari siz turgan davlatga moslashtiriladi!",
        "ask_origin": "Qayerdan uchasiz? ({c} mintaqasi shaharlari):",
        "ask_dest": "Uchish: {o}\nQayerga uchasiz?",
        "ask_class": "Xizmat ko'rsatish klassini tanlang:",
        "ask_airline": "Aviakompaniyani tanlang:",
        "ask_month": "{o} → {d} ({cls})\nUchish oyini tanlang:",
        "ask_return_decision": "📅 Uchish sanasi tanlandi: <b>{date}</b>.\n\nQaytish chiptasini ham qo'shamizmi (Tuda-obratno)?",
        "ask_return_month": "Qaytish oyini tanlang:",
        "ask_origin_text": "Istalgan uchish shahrini yozing:",
        "ask_dest_text": "Istalgan borish shahrini yozing:",
        "pick_city": "Ro'yxatdan kerakli aeroportni tanlang:",
        "city_not_found": "Bunday shahar topilmadi. Qayta yozib ko'ring.",
        "searching": "🔎 Agentliklar va aviakompaniyalardan narxlar qidirilmoqda...",
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
        "cal_title": "📅 <b>{o} → {d}</b> ({month} {year})\nKo'rsatilayotgan kunlar: <b>{range}</b>\nKunni bosing:",
        "cal_empty": "Bu oy uchun narxlar mavjud emas.",
        "not_found_airline": (
            "⚠️ <b>Chiptalar topilmadi!</b>\n\n"
            "<b>{air}</b> aviakompaniyasida {date} sanasida {o} → {d} yo'nalishida chipta topilmadi.\n\n"
            "Quyidagilardan birini tanlashingiz mumkin:"
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

COUNTRY_NAMES = {
    "UZ": {"uz": "O'zbekiston 🇺🇿", "ru": "Узбекистан 🇺🇿"},
    "RU": {"uz": "Rossiya 🇷🇺", "ru": "Россия 🇷🇺"},
    "KZ": {"uz": "Qozog'iston 🇰🇿", "ru": "Казахстан 🇰🇿"},
    "TR": {"uz": "Turkiya 🇹🇷", "ru": "Турция 🇹🇷"},
    "AE": {"uz": "BAA (Dubay) 🇦🇪", "ru": "ОАЭ (Дубай) 🇦🇪"}
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
        lang TEXT NOT NULL,
        country TEXT DEFAULT 'UZ'
    )""")
    db_exec("""CREATE TABLE IF NOT EXISTS places (
        code TEXT NOT NULL,
        lang TEXT NOT NULL,
        name TEXT NOT NULL,
        PRIMARY KEY (code, lang)
    )""")

def get_user_meta(user_id):
    rows = db_all("SELECT lang, country FROM users WHERE user_id=?", (user_id,))
    if rows:
        return rows[0]["lang"], rows[0].get("country", DEFAULT_COUNTRY)
    return None, DEFAULT_COUNTRY

def lang_of(user_id):
    l, _ = get_user_meta(user_id)
    return l or DEFAULT_LANG

def country_of(user_id):
    _, c = get_user_meta(user_id)
    return c or DEFAULT_COUNTRY

def set_lang(user_id, lang):
    _, c = get_user_meta(user_id)
    db_exec("INSERT OR REPLACE INTO users (user_id, lang, country) VALUES (?, ?, ?)", (user_id, lang, c))

def set_country(user_id, country):
    l = lang_of(user_id)
    db_exec("INSERT OR REPLACE INTO users (user_id, lang, country) VALUES (?, ?, ?)", (user_id, l, country))

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

# ---------- To'g'ridan-to'g'ri aniq chipta havolalari ----------
def build_direct_gotogate_url(origin, dest, dep_date, ret_date=None):
    """GoToGate'ning to'g'ridan-to'g'ri chipta qidiruv sahifasi"""
    if ret_date:
        return f"https://www.gotogate.com/air/search/roundtrip/{origin}/{dest}/{dep_date}/{ret_date}/1/0/0/Economy"
    return f"https://www.gotogate.com/air/search/oneway/{origin}/{dest}/{dep_date}/1/0/0/Economy"

def build_direct_onetwotrip_url(origin, dest, dep_date, ret_date=None):
    """OneTwoTrip'ning to'g'ridan-to'g'ri reyslar qidiruv sahifasi"""
    d = datetime.strptime(dep_date, "%Y-%m-%d").strftime("%d%m")
    if ret_date:
        r = datetime.strptime(ret_date, "%Y-%m-%d").strftime("%d%m")
        return f"https://www.onetwotrip.com/flights/{origin}{d}{dest}{r}100E/"
    return f"https://www.onetwotrip.com/flights/{origin}{d}{dest}100E/"

def build_direct_trip_com_url(origin, dest, dep_date, ret_date=None):
    """Trip.com xalqaro tizimining to'g'ridan-to'g'ri qidiruv sahifasi"""
    url = f"https://www.trip.com/flights/{origin}-to-{dest}/tickets-cheap?dcity={origin}&acity={dest}&ddate={dep_date}"
    if ret_date:
        url += f"&rdate={ret_date}&flighttype=roundtrip"
    else:
        url += "&flighttype=oneway"
    return url

def build_direct_skyscanner_url(origin, dest, dep_date, ret_date=None):
    """Skyscanner to'g'ridan-to'g'ri qidiruvi"""
    d = dep_date.replace("-", "")[2:]
    if ret_date:
        r = ret_date.replace("-", "")[2:]
        return f"https://www.skyscanner.com/transport/flights/{origin.lower()}/{dest.lower()}/{d}/{r}/"
    return f"https://www.skyscanner.com/transport/flights/{origin.lower()}/{dest.lower()}/{d}/"

def build_aviasales_url(origin, dest, dep_date, ret_date=None):
    """Aviasales rasmiy havolasi"""
    d = f"{dep_date[8:10]}{dep_date[5:7]}"
    url = f"https://www.aviasales.com/search/{origin}{d}{dest}"
    if ret_date:
        r = f"{ret_date[8:10]}{ret_date[5:7]}"
        url += f"{r}"
    url += "1"
    if MARKER:
        url += f"?marker={MARKER}"
    return url

# ---------- Menyular ----------
def kb_main_menu(lang):
    b = ReplyKeyboardBuilder()
    b.row(
        KeyboardButton(text=t(lang, "menu_avia")),
        KeyboardButton(text=t(lang, "menu_rates"))
    )
    b.row(
        KeyboardButton(text=t(lang, "menu_country")),
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

def kb_select_country(lang):
    b = InlineKeyboardBuilder()
    for code, names in COUNTRY_NAMES.items():
        b.button(text=names[lang], callback_data=f"cntry:{code}")
    b.adjust(2)
    return b.as_markup()

def kb_origins_for_country(user_country, lang):
    b = InlineKeyboardBuilder()
    codes = COUNTRY_ORIGINS.get(user_country, COUNTRY_ORIGINS["UZ"])
    for code in codes:
        b.button(text=city(code, lang), callback_data=f"o:{code}")
    b.adjust(2)
    b.row(InlineKeyboardButton(text=t(lang, "btn_more_cities"), callback_data="oo"))
    return b.as_markup()

def kb_dests(origin, lang):
    b = InlineKeyboardBuilder()
    for code in DEST_CODES:
        if code != origin:
            b.button(text=city(code, lang), callback_data=f"d:{origin}:{code}")
    b.adjust(2)
    b.row(InlineKeyboardButton(text=t(lang, "btn_more_cities"), callback_data=f"od:{origin}"))
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

def kb_months(origin, dest, cls, airline, is_return, lang, min_date=None):
    b = InlineKeyboardBuilder()
    today = date.today()
    start_y = min_date.year if min_date else today.year
    start_m = min_date.month if min_date else today.month
    
    y, m = start_y, start_m
    prefix = "rm" if is_return else "m"
    for _ in range(6):
        b.button(
            text=f"{MONTHS[lang][m].capitalize()} {y}",
            callback_data=f"{prefix}:{origin}:{dest}:{cls}:{airline}:{y}-{m:02d}:0"
        )
        m += 1
        if m > 12:
            m = 1
            y += 1
    b.adjust(2)
    back_dest = f"cls:{origin}:{dest}:{cls}" if not is_return else f"c_back:{origin}:{dest}:{cls}:{airline}"
    b.row(InlineKeyboardButton(text=t(lang, "btn_back"), callback_data=back_dest))
    return b.as_markup()

def kb_return_decision(origin, dest, cls, airline, dep_date, page_idx, lang):
    b = InlineKeyboardBuilder()
    b.button(text=t(lang, "btn_add_return"), callback_data=f"ask_ret_month:{origin}:{dest}:{cls}:{airline}:{dep_date}")
    b.button(text=t(lang, "btn_oneway_only"), callback_data=f"show_oneway:{origin}:{dest}:{cls}:{airline}:{dep_date}:{page_idx}")
    b.adjust(1)
    b.row(InlineKeyboardButton(text=t(lang, "btn_back"), callback_data=f"m:{origin}:{dest}:{cls}:{airline}:{dep_date[:7]}:{page_idx}"))
    return b.as_markup()

def kb_paged_calendar(origin, dest, cls, airline, year, month, prices, cheapest, page_idx, is_return, lang, min_day_date=None):
    b = InlineKeyboardBuilder()
    today = date.today()
    total_days = calendar.monthrange(year, month)[1]

    start_from = 1
    if min_day_date and year == min_day_date.year and month == min_day_date.month:
        start_from = min_day_date.day
    elif year == today.year and month == today.month:
        start_from = today.day

    valid_days = [d for d in range(start_from, total_days + 1)]
    per_page = 10
    chunks = [valid_days[i:i + per_page] for i in range(0, len(valid_days), per_page)]
    
    if not chunks:
        return b.as_markup(), ""

    page_idx = max(0, min(page_idx, len(chunks) - 1))
    current_chunk = chunks[page_idx]

    prefix = "rc" if is_return else "c"
    for day in current_chunk:
        day_date = date(year, month, day)
        key = day_date.isoformat()
        
        if key in prices:
            price = int(prices[key]["price"])
            icon = "🟢" if key in cheapest else "💵"
            b.button(
                text=f"{icon} {day}-{MONTHS[lang][month][:3]} | ${price}",
                callback_data=f"{prefix}:{origin}:{dest}:{cls}:{airline}:{key}:{page_idx}"
            )
        else:
            b.button(
                text=f"🗓❌ {day}-{MONTHS[lang][month][:3]}",
                callback_data=f"{prefix}:{origin}:{dest}:{cls}:{airline}:{key}:{page_idx}"
            )

    b.adjust(2)

    nav_btns = []
    month_prefix = "rm" if is_return else "m"
    if page_idx > 0:
        prev_chunk = chunks[page_idx - 1]
        nav_btns.append(InlineKeyboardButton(
            text=f"⬅️ {prev_chunk[0]}–{prev_chunk[-1]}",
            callback_data=f"{month_prefix}:{origin}:{dest}:{cls}:{airline}:{year}-{month:02d}:{page_idx - 1}"
        ))
    if page_idx < len(chunks) - 1:
        next_chunk = chunks[page_idx + 1]
        nav_btns.append(InlineKeyboardButton(
            text=f"{next_chunk[0]}–{next_chunk[-1]} ➡️",
            callback_data=f"{month_prefix}:{origin}:{dest}:{cls}:{airline}:{year}-{month:02d}:{page_idx + 1}"
        ))
    
    if nav_btns:
        b.row(*nav_btns)

    period = f"{year}-{month:02d}"
    b.row(InlineKeyboardButton(text=t(lang, "btn_watch"), callback_data=f"w:{origin}:{dest}:{period}:{cls}"))
    b.row(
        InlineKeyboardButton(text=t(lang, "btn_back"), callback_data=f"air:{origin}:{dest}:{cls}:{airline}"),
        InlineKeyboardButton(text=t(lang, "btn_new"), callback_data="go_avia")
    )
    return b.as_markup(), f"{current_chunk[0]}–{current_chunk[-1]}"

def kb_not_found_redirect(origin, dest, cls, airline, day, page_idx, lang):
    b = InlineKeyboardBuilder()
    period = day[:7]
    b.button(text=t(lang, "btn_change_airline"), callback_data=f"cls:{origin}:{dest}:{cls}")
    b.button(text=t(lang, "btn_change_date"), callback_data=f"m:{origin}:{dest}:{cls}:{airline}:{period}:{page_idx}")
    b.button(text=t(lang, "btn_new"), callback_data="go_avia")
    b.adjust(1)
    return b.as_markup()

# Har bir agentlikka to'g'ridan-to'g'ri olib boruvchi inline tugmalar (Trip.com bilan birga)
def kb_direct_agency_offers(origin, dest, cls, airline, dep_date, ret_date, page_idx, base_p, lang):
    b = InlineKeyboardBuilder()
    
    url_gotogate = build_direct_gotogate_url(origin, dest, dep_date, ret_date)
    url_onetwotrip = build_direct_onetwotrip_url(origin, dest, dep_date, ret_date)
    url_trip_com = build_direct_trip_com_url(origin, dest, dep_date, ret_date)
    url_skyscanner = build_direct_skyscanner_url(origin, dest, dep_date, ret_date)
    url_aviasales = build_aviasales_url(origin, dest, dep_date, ret_date)

    p_gotogate = base_p
    p_aviasales = round(base_p * 1.02)
    p_onetwotrip = round(base_p * 1.03)
    p_trip_com = round(base_p * 1.01)
    p_skyscanner = round(base_p * 1.04)

    b.button(text=f"🟢 GoToGate: ${p_gotogate:.0f} (To'g'ridan-to'g'ri)", url=url_gotogate)
    b.button(text=f"🟣 Trip.com: ${p_trip_com:.0f} (To'g'ridan-to'g'ri)", url=url_trip_com)
    b.button(text=f"🔵 OneTwoTrip: ${p_onetwotrip:.0f} (To'g'ridan-to'g'ri)", url=url_onetwotrip)
    b.button(text=f"🟡 Aviasales: ${p_aviasales:.0f}", url=url_aviasales)
    b.button(text=f"✈️ Skyscanner: ${p_skyscanner:.0f} (To'g'ridan-to'g'ri)", url=url_skyscanner)

    b.adjust(1)
    period = dep_date[:7]
    b.row(
        InlineKeyboardButton(text=t(lang, "btn_to_calendar"), callback_data=f"m:{origin}:{dest}:{cls}:{airline}:{period}:{page_idx}"),
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
        if len(code) == 3 and code not in seen:
            seen.add(code)
            result.append({"code": code, "name": name, "country": item.get("country_name", "")})
            save_place(code, lang, name)
            if len(result) >= 8:
                break
    return result

def format_tickets_post(origin, dest, dep_date, ret_date, ticket, rates, cls, lang):
    cls_name = t(lang, "cls_econ") if cls == "Y" else t(lang, "cls_biz")
    airline_code = ticket.get("airline", "Avia")
    airline_name = AIRLINES_LIST.get(airline_code, airline_code)
    
    base_p = float(ticket.get("price", 0))
    if ret_date:
        base_p = base_p * 1.85

    p_gotogate = base_p
    p_trip_com = round(base_p * 1.01)
    p_aviasales = round(base_p * 1.02)
    p_onetwotrip = round(base_p * 1.03)
    p_skyscanner = round(base_p * 1.04)

    mode_title = "🔄 <b>Borish-Qaytish (Tuda-obratno)</b>" if ret_date else "➡️ <b>Bir tomonga</b>"
    ret_line = f"📅 Qaytish sanasi: <b>{ret_date}</b>\n" if ret_date else ""

    lines = [
        f"{mode_title}\n"
        f"✈️ <b>{city(origin, lang)} ⇄ {city(dest, lang)}</b>",
        f"Klass: <b>{cls_name}</b> | Aviakompaniya: <b>{airline_name}</b>",
        f"🛫 Uchish sanasi: <b>{dep_date}</b>",
        ret_line,
        "🏢 <b>Kompaniyalar bo'yicha to'g'ridan-to'g'ri narxlar:</b>",
        f"• 🟢 <b>GoToGate:</b> {money(p_gotogate, rates['cbu'], lang)}",
        f"• 🟣 <b>Trip.com:</b> {money(p_trip_com, rates['cbu'], lang)}",
        f"• 🟡 <b>Aviasales:</b> {money(p_aviasales, rates['cbu'], lang)}",
        f"• 🔵 <b>OneTwoTrip:</b> {money(p_onetwotrip, rates['cbu'], lang)}",
        f"• ✈️ <b>Skyscanner:</b> {money(p_skyscanner, rates['cbu'], lang)}\n",
        "<i>To'g'ridan-to'g'ri chipta qidiruviga o'tish uchun quyidagi tugmani bosing:</i>\n",
        f"💱 <b>Bank kursi:</b> Ipak Yo'li: {spaced(rates['ipak'])} | NBU: {spaced(rates['nbu'])} so'm"
    ]
    return "\n".join(lines), base_p

# ---------- Handlers ----------
@dp.message(CommandStart())
async def cmd_start(message: Message):
    USER_FLOW.pop(message.from_user.id, None)
    lang, country = get_user_meta(message.from_user.id)
    if lang is None:
        await message.answer("🌐 Tilni tanlang / Выберите язык:", reply_markup=kb_lang())
        return
    await message.answer(t(lang, "help"), reply_markup=kb_main_menu(lang), parse_mode="HTML")

@dp.message(F.text.in_(["✈️ Aviachipta qidirish", "✈️ Найти авиабилет"]))
async def menu_avia_click(message: Message):
    lang = lang_of(message.from_user.id)
    u_country = country_of(message.from_user.id)
    c_name = COUNTRY_NAMES.get(u_country, {}).get(lang, u_country)
    USER_FLOW[message.from_user.id] = {"trip_class": "Y", "airline": "ALL", "ret_date": None}
    await message.answer(t(lang, "ask_origin", c=c_name), reply_markup=kb_origins_for_country(u_country, lang))

@dp.message(F.text.in_(["📍 Mintaqam", "📍 Мой регион"]))
async def menu_country_click(message: Message):
    lang = lang_of(message.from_user.id)
    await message.answer(t(lang, "ask_country"), reply_markup=kb_select_country(lang))

@dp.callback_query(F.data.startswith("cntry:"))
async def cb_set_country(call: CallbackQuery):
    await call.answer()
    lang = lang_of(call.from_user.id)
    country_code = call.data.split(":")[1]
    set_country(call.from_user.id, country_code)
    c_name = COUNTRY_NAMES.get(country_code, {}).get(lang, country_code)
    await call.message.edit_text(t(lang, "country_set", c=c_name))

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

@dp.message(F.text.in_(["🌐 Til / Яzyк", "🌐 Til / Язык"]))
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
    u_country = country_of(call.from_user.id)
    c_name = COUNTRY_NAMES.get(u_country, {}).get(lang, u_country)
    await call.message.edit_text(t(lang, "ask_origin", c=c_name), reply_markup=kb_origins_for_country(u_country, lang))

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
        reply_markup=kb_months(origin, dest, cls, airline, False, lang)
    )

@dp.callback_query(F.data.startswith("m:"))
async def cb_month(call: CallbackQuery):
    await call.answer()
    lang = lang_of(call.from_user.id)
    _, origin, dest, cls, airline, period, page_str = call.data.split(":")
    page_idx = int(page_str)
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

    kb, range_label = kb_paged_calendar(origin, dest, cls, airline, year, month, prices, cheapest, page_idx, False, lang)
    txt = t(
        lang, "cal_title",
        o=city(origin, lang), d=city(dest, lang),
        month=MONTHS[lang][month].capitalize(), year=year,
        range=range_label
    )
    await call.message.edit_text(txt, reply_markup=kb, parse_mode="HTML")

@dp.callback_query(F.data.startswith("c:"))
async def cb_day_selected(call: CallbackQuery):
    await call.answer()
    lang = lang_of(call.from_user.id)
    _, origin, dest, cls, airline, day, page_str = call.data.split(":")
    page_idx = int(page_str)

    txt = t(lang, "ask_return_decision", date=day)
    kb = kb_return_decision(origin, dest, cls, airline, day, page_idx, lang)
    await call.message.edit_text(txt, reply_markup=kb, parse_mode="HTML")

@dp.callback_query(F.data.startswith("show_oneway:"))
async def cb_show_oneway(call: CallbackQuery):
    await call.answer()
    lang = lang_of(call.from_user.id)
    _, origin, dest, cls, airline, day, page_str = call.data.split(":")
    page_idx = int(page_str)

    await call.message.edit_text(t(lang, "searching"))
    tickets = await fetch_tickets(origin, dest, day, trip_class=cls, airline=airline, limit=1)
    
    if not tickets:
        air_name = AIRLINES_LIST.get(airline, airline if airline != "ALL" else "Barcha aviakompaniyalar")
        not_found_txt = t(lang, "not_found_airline", air=air_name, date=day, o=city(origin, lang), d=city(dest, lang))
        kb_back_options = kb_not_found_redirect(origin, dest, cls, airline, day, page_idx, lang)
        await call.message.edit_text(not_found_txt, reply_markup=kb_back_options, parse_mode="HTML")
        return
    
    rates = await get_all_bank_rates()
    text, base_p = format_tickets_post(origin, dest, day, None, tickets[0], rates, cls, lang)
    kb = kb_direct_agency_offers(origin, dest, cls, airline, day, None, page_idx, base_p, lang)
    
    await call.message.edit_text(text, reply_markup=kb, parse_mode="HTML", link_preview_options=LinkPreviewOptions(is_disabled=True))

@dp.callback_query(F.data.startswith("ask_ret_month:"))
async def cb_ask_ret_month(call: CallbackQuery):
    await call.answer()
    lang = lang_of(call.from_user.id)
    _, origin, dest, cls, airline, dep_date = call.data.split(":")
    min_date = datetime.strptime(dep_date, "%Y-%m-%d").date()
    
    await call.message.edit_text(
        t(lang, "ask_return_month"),
        reply_markup=kb_months(f"{origin}:{dep_date}", dest, cls, airline, True, lang, min_date=min_date)
    )

@dp.callback_query(F.data.startswith("rm:"))
async def cb_return_month_cal(call: CallbackQuery):
    await call.answer()
    lang = lang_of(call.from_user.id)
    _, origin_payload, dest, cls, airline, period, page_str = call.data.split(":")
    origin, dep_date = origin_payload.split(":")
    page_idx = int(page_str)
    year, month = int(period[:4]), int(period[5:7])
    min_day_date = datetime.strptime(dep_date, "%Y-%m-%d").date()

    await call.message.edit_text(t(lang, "searching"))
    prices = await fetch_calendar(dest, origin, period, trip_class=cls)
    if not prices:
        prices = {}

    today = date.today().isoformat()
    future = {k: v for k, v in prices.items() if k >= today}
    top = sorted(future.items(), key=lambda kv: float(kv[1]["price"]))[:5]
    cheapest = {k for k, _ in top}

    kb, range_label = kb_paged_calendar(f"{origin}:{dep_date}", dest, cls, airline, year, month, prices, cheapest, page_idx, True, lang, min_day_date=min_day_date)
    txt = t(
        lang, "cal_title",
        o=city(dest, lang), d=city(origin, lang),
        month=MONTHS[lang][month].capitalize(), year=year,
        range=range_label
    )
    await call.message.edit_text(txt, reply_markup=kb, parse_mode="HTML")

@dp.callback_query(F.data.startswith("rc:"))
async def cb_return_day_selected(call: CallbackQuery):
    await call.answer()
    lang = lang_of(call.from_user.id)
    _, origin_payload, dest, cls, airline, ret_day, page_str = call.data.split(":")
    origin, dep_date = origin_payload.split(":")
    page_idx = int(page_str)

    await call.message.edit_text(t(lang, "searching"))
    tickets = await fetch_tickets(origin, dest, dep_date, trip_class=cls, airline=airline, limit=1)
    
    if not tickets:
        air_name = AIRLINES_LIST.get(airline, airline if airline != "ALL" else "Barcha aviakompaniyalar")
        not_found_txt = t(lang, "not_found_airline", air=air_name, date=dep_date, o=city(origin, lang), d=city(dest, lang))
        kb_back_options = kb_not_found_redirect(origin, dest, cls, airline, dep_date, page_idx, lang)
        await call.message.edit_text(not_found_txt, reply_markup=kb_back_options, parse_mode="HTML")
        return

    rates = await get_all_bank_rates()
    text, base_p = format_tickets_post(origin, dest, dep_date, ret_day, tickets[0], rates, cls, lang)
    kb = kb_direct_agency_offers(origin, dest, cls, airline, dep_date, ret_day, page_idx, base_p, lang)
    
    await call.message.edit_text(text, reply_markup=kb, parse_mode="HTML", link_preview_options=LinkPreviewOptions(is_disabled=True))

@dp.callback_query(F.data == "n")
async def cb_noop(call: CallbackQuery):
    await call.answer()

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
    parts = call.data.split(":")
    origin, dest, period, cls = parts[1], parts[2], parts[3], parts[4]
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
                body, base_p = format_tickets_post(origin, dest, period, None, tickets[0], rates, cls, lang)
                text += body
                kb = kb_direct_agency_offers(origin, dest, cls, "ALL", period, None, 0, base_p, lang)
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