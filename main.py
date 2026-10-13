import asyncio
import logging
import os
import sqlite3
from contextlib import closing
from datetime import date

import aiohttp
from aiogram import Bot, Dispatcher, F
from aiogram.exceptions import TelegramForbiddenError
from aiogram.filters import Command, CommandStart
from aiogram.types import CallbackQuery, InlineKeyboardButton, Message
from aiogram.utils.keyboard import InlineKeyboardBuilder
from dotenv import load_dotenv

load_dotenv()

BOT_TOKEN = os.getenv("BOT_TOKEN")
TP_TOKEN = os.getenv("TRAVELPAYOUTS_TOKEN")
MARKER = os.getenv("TRAVELPAYOUTS_MARKER", "")

API_URL = "https://api.travelpayouts.com/aviasales/v3/prices_for_dates"
SITE = "https://www.aviasales.com"

DB_PATH = os.getenv("DB_PATH", "bot.db")
CHECK_INTERVAL = int(os.getenv("CHECK_INTERVAL", "3600"))  # как часто проверять цены (секунды)
MAX_ALERTS = 5  # максимум оповещений на одного пользователя
DEFAULT_LANG = "uz"

logging.basicConfig(level=logging.INFO)
dp = Dispatcher()

# ---------- Города: коды IATA и названия на двух языках ----------
ORIGIN_CODES = ["TAS", "SKD", "BHK", "FEG", "NMA", "AZN", "UGC", "NCU", "TMJ", "KSQ"]
DEST_CODES = ["MOW", "LED", "IST", "DXB", "ALA", "DEL", "JED", "KUL", "BKK", "SEL", "BAK", "TBS"]

CITY = {
    "ru": {
        "TAS": "Ташкент", "SKD": "Самарканд", "BHK": "Бухара", "FEG": "Фергана",
        "NMA": "Наманган", "AZN": "Андижан", "UGC": "Ургенч", "NCU": "Нукус",
        "TMJ": "Термез", "KSQ": "Карши",
        "MOW": "Москва", "LED": "Санкт-Петербург", "IST": "Стамбул", "DXB": "Дубай",
        "ALA": "Алматы", "DEL": "Дели", "JED": "Джидда", "KUL": "Куала-Лумпур",
        "BKK": "Бангкок", "SEL": "Сеул", "BAK": "Баку", "TBS": "Тбилиси",
    },
    "uz": {
        "TAS": "Toshkent", "SKD": "Samarqand", "BHK": "Buxoro", "FEG": "Farg'ona",
        "NMA": "Namangan", "AZN": "Andijon", "UGC": "Urganch", "NCU": "Nukus",
        "TMJ": "Termiz", "KSQ": "Qarshi",
        "MOW": "Moskva", "LED": "Sankt-Peterburg", "IST": "Istanbul", "DXB": "Dubay",
        "ALA": "Almati", "DEL": "Dehli", "JED": "Jidda", "KUL": "Kuala-Lumpur",
        "BKK": "Bangkok", "SEL": "Seul", "BAK": "Boku", "TBS": "Tbilisi",
    },
}

MONTHS = {
    "ru": [
        "", "январь", "февраль", "март", "апрель", "май", "июнь",
        "июль", "август", "сентябрь", "октябрь", "ноябрь", "декабрь",
    ],
    "uz": [
        "", "yanvar", "fevral", "mart", "aprel", "may", "iyun",
        "iyul", "avgust", "sentyabr", "oktyabr", "noyabr", "dekabr",
    ],
}

# ---------- Тексты бота на двух языках ----------
TEXTS = {
    "ru": {
        "help": (
            "✈️ Бот поиска дешёвых авиабилетов\n\n"
            "Нажмите «Найти билет» и выберите город вылета, направление и месяц. "
            "После результатов можно включить 🔔 оповещение: бот сам напишет, когда цена упадёт.\n\n"
            "Команды вручную:\n"
            "/price TAS IST 2026-11-15  (на день)\n"
            "/price TAS IST 2026-12     (на месяц)\n"
            "/alerts  (мои оповещения)\n"
            "/lang  (сменить язык)"
        ),
        "btn_find": "✈️ Найти билет",
        "btn_alerts": "🔔 Мои оповещения",
        "btn_lang": "🌐 Til / Язык",
        "btn_back": "⬅️ Назад",
        "btn_new": "🔁 Новый поиск",
        "btn_watch": "🔔 Следить за ценой",
        "ask_origin": "Откуда летите? Выберите город вылета:",
        "ask_dest": "Вылет: {o}\nКуда летите?",
        "ask_month": "{o} → {d}\nВыберите месяц вылета:",
        "searching": "🔎 Ищу билеты...",
        "route_title": "✈️ {o} → {d}: самые дешёвые варианты\n",
        "direct": "прямой",
        "stops": "пересадок: {n}",
        "footer": "Цены из кэша поисков, итоговую цену смотрите на сайте.",
        "not_found": (
            "Билетов не найдено. Данные берутся из кэша поисков, поэтому для редких "
            "направлений или дат он может быть пустым. Попробуйте другой месяц или направление."
        ),
        "api_fail": "⚠️ Не удалось получить данные. Попробуйте позже.",
        "watch_exists": "🔔 Это направление уже отслеживается: {route}\nСписок: /alerts",
        "watch_limit": "Достигнут лимит: {max} оповещений. Удалите ненужное в /alerts.",
        "watch_none": "Сейчас нет цен для этого направления, следить не получится.",
        "watch_ok": (
            "🔔 Слежу за ценой: {route}\n"
            "Сейчас от {price} USD. Напишу, если подешевеет.\n"
            "Все оповещения: /alerts"
        ),
        "alerts_empty": (
            "У вас пока нет оповещений.\n"
            "Сделайте поиск и нажмите «🔔 Следить за ценой» под результатами."
        ),
        "alerts_title": "🔔 Ваши оповещения.\nНажмите на оповещение, чтобы удалить его:",
        "alert_item": "❌ {o} → {d}, {period} (от {price})",
        "deleted": "Удалено",
        "dropped": "🔔 Цена упала: {old} → {new} USD\n\n",
        "lang_prompt": "🌐 Tilni tanlang / Выберите язык:",
    },
    "uz": {
        "help": (
            "✈️ Arzon aviachiptalar qidiruv boti\n\n"
            "«Chipta topish» tugmasini bosing va uchish shahri, yo'nalish hamda oyni tanlang. "
            "Natijalardan keyin 🔔 xabarnomani yoqishingiz mumkin: narx tushsa, bot o'zi yozadi.\n\n"
            "Buyruqlar:\n"
            "/price TAS IST 2026-11-15  (aniq kun uchun)\n"
            "/price TAS IST 2026-12     (butun oy uchun)\n"
            "/alerts  (xabarnomalarim)\n"
            "/lang  (tilni almashtirish)"
        ),
        "btn_find": "✈️ Chipta topish",
        "btn_alerts": "🔔 Xabarnomalarim",
        "btn_lang": "🌐 Til / Язык",
        "btn_back": "⬅️ Orqaga",
        "btn_new": "🔁 Yangi qidiruv",
        "btn_watch": "🔔 Narxni kuzatish",
        "ask_origin": "Qayerdan uchasiz? Uchish shahrini tanlang:",
        "ask_dest": "Uchish: {o}\nQayerga uchasiz?",
        "ask_month": "{o} → {d}\nUchish oyini tanlang:",
        "searching": "🔎 Chiptalar qidirilmoqda...",
        "route_title": "✈️ {o} → {d}: eng arzon variantlar\n",
        "direct": "to'g'ridan-to'g'ri",
        "stops": "almashinuvlar: {n}",
        "footer": "Narxlar qidiruv keshidan olingan, yakuniy narxni saytda ko'ring.",
        "not_found": (
            "Chiptalar topilmadi. Ma'lumotlar qidiruv keshidan olinadi, shuning uchun kam "
            "uchraydigan yo'nalish yoki sanalar uchun u bo'sh bo'lishi mumkin. "
            "Boshqa oy yoki yo'nalishni sinab ko'ring."
        ),
        "api_fail": "⚠️ Ma'lumotlarni olib bo'lmadi. Keyinroq urinib ko'ring.",
        "watch_exists": "🔔 Bu yo'nalish allaqachon kuzatilmoqda: {route}\nRo'yxat: /alerts",
        "watch_limit": "Limitga yetdingiz: {max} ta xabarnoma. Keraksizini /alerts orqali o'chiring.",
        "watch_none": "Hozir bu yo'nalish uchun narxlar yo'q, kuzatib bo'lmaydi.",
        "watch_ok": (
            "🔔 Narx kuzatilmoqda: {route}\n"
            "Hozir {price} USD dan. Arzonlashsa, yozaman.\n"
            "Barcha xabarnomalar: /alerts"
        ),
        "alerts_empty": (
            "Hozircha xabarnomalar yo'q.\n"
            "Qidiruv qiling va natijalar ostidagi «🔔 Narxni kuzatish» tugmasini bosing."
        ),
        "alerts_title": "🔔 Xabarnomalaringiz.\nO'chirish uchun xabarnomani bosing:",
        "alert_item": "❌ {o} → {d}, {period} ({price} dan)",
        "deleted": "O'chirildi",
        "dropped": "🔔 Narx tushdi: {old} → {new} USD\n\n",
        "lang_prompt": "🌐 Tilni tanlang / Выберите язык:",
    },
}


def t(lang, key, **kw):
    text = TEXTS[lang][key]
    return text.format(**kw) if kw else text


def city(code, lang):
    return CITY[lang].get(code, code)


# ---------- База данных (SQLite) ----------
def db_exec(sql, params=()):
    with closing(sqlite3.connect(DB_PATH)) as conn:
        cur = conn.execute(sql, params)
        conn.commit()
        return cur.rowcount


def db_all(sql, params=()):
    with closing(sqlite3.connect(DB_PATH)) as conn:
        conn.row_factory = sqlite3.Row
        rows = conn.execute(sql, params).fetchall()
        return [dict(r) for r in rows]


def init_db():
    db_exec(
        """CREATE TABLE IF NOT EXISTS alerts (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER NOT NULL,
            origin TEXT NOT NULL,
            dest TEXT NOT NULL,
            period TEXT NOT NULL,
            last_price REAL,
            UNIQUE(user_id, origin, dest, period)
        )"""
    )
    db_exec(
        """CREATE TABLE IF NOT EXISTS users (
            user_id INTEGER PRIMARY KEY,
            lang TEXT NOT NULL
        )"""
    )


def get_lang(user_id):
    """Язык пользователя или None, если ещё не выбирал."""
    rows = db_all("SELECT lang FROM users WHERE user_id=?", (user_id,))
    if rows and rows[0]["lang"] in TEXTS:
        return rows[0]["lang"]
    return None


def lang_of(user_id):
    return get_lang(user_id) or DEFAULT_LANG


def set_lang(user_id, lang):
    db_exec("INSERT OR REPLACE INTO users (user_id, lang) VALUES (?, ?)", (user_id, lang))


# ---------- Клавиатуры ----------
def kb_lang():
    b = InlineKeyboardBuilder()
    b.button(text="🇺🇿 O'zbekcha", callback_data="lang:uz")
    b.button(text="🇷🇺 Русский", callback_data="lang:ru")
    b.adjust(2)
    return b.as_markup()


def kb_start(lang):
    b = InlineKeyboardBuilder()
    b.button(text=t(lang, "btn_find"), callback_data="go")
    b.button(text=t(lang, "btn_alerts"), callback_data="alerts")
    b.button(text=t(lang, "btn_lang"), callback_data="lang_menu")
    b.adjust(1)
    return b.as_markup()


def kb_origins(lang):
    b = InlineKeyboardBuilder()
    for code in ORIGIN_CODES:
        b.button(text=city(code, lang), callback_data=f"o:{code}")
    b.adjust(2)
    return b.as_markup()


def kb_dests(origin, lang):
    b = InlineKeyboardBuilder()
    for code in DEST_CODES:
        if code != origin:
            b.button(text=city(code, lang), callback_data=f"d:{origin}:{code}")
    b.adjust(2)
    b.row(InlineKeyboardButton(text=t(lang, "btn_back"), callback_data="go"))
    return b.as_markup()


def next_months(count=6):
    today = date.today()
    year, month = today.year, today.month
    result = []
    for _ in range(count):
        result.append((year, month))
        month += 1
        if month > 12:
            month = 1
            year += 1
    return result


def kb_months(origin, dest, lang):
    b = InlineKeyboardBuilder()
    for year, month in next_months():
        label = f"{MONTHS[lang][month].capitalize()} {year}"
        b.button(text=label, callback_data=f"m:{origin}:{dest}:{year}-{month:02d}")
    b.adjust(2)
    b.row(InlineKeyboardButton(text=t(lang, "btn_back"), callback_data=f"o:{origin}"))
    return b.as_markup()


def kb_again(lang):
    b = InlineKeyboardBuilder()
    b.button(text=t(lang, "btn_new"), callback_data="go")
    b.button(text=t(lang, "btn_alerts"), callback_data="alerts")
    b.adjust(1)
    return b.as_markup()


def kb_results(origin, dest, period, lang):
    b = InlineKeyboardBuilder()
    b.button(text=t(lang, "btn_watch"), callback_data=f"w:{origin}:{dest}:{period}")
    b.button(text=t(lang, "btn_new"), callback_data="go")
    b.adjust(1)
    return b.as_markup()


def alerts_view(user_id, lang):
    rows = db_all("SELECT * FROM alerts WHERE user_id=? ORDER BY id", (user_id,))
    if not rows:
        return t(lang, "alerts_empty"), kb_again(lang)
    b = InlineKeyboardBuilder()
    for r in rows:
        price = f"{r['last_price']:.0f}$" if r["last_price"] is not None else "—"
        label = t(
            lang, "alert_item",
            o=city(r["origin"], lang), d=city(r["dest"], lang), period=r["period"], price=price,
        )
        b.button(text=label, callback_data=f"x:{r['id']}")
    b.adjust(1)
    b.row(InlineKeyboardButton(text=t(lang, "btn_new"), callback_data="go"))
    return t(lang, "alerts_title"), b.as_markup()


# ---------- Поиск билетов ----------
async def fetch_tickets(origin, destination, period, limit=5):
    """Возвращает список билетов или None при ошибке."""
    params = {
        "origin": origin,
        "destination": destination,
        "departure_at": period,
        "one_way": "true",
        "sorting": "price",
        "currency": "usd",
        "limit": limit,
        "unique": "false",
    }
    headers = {"X-Access-Token": TP_TOKEN}
    try:
        timeout = aiohttp.ClientTimeout(total=20)
        async with aiohttp.ClientSession(timeout=timeout) as session:
            async with session.get(API_URL, params=params, headers=headers) as resp:
                data = await resp.json()
        return data.get("data") or []
    except Exception as e:
        logging.exception("API error: %s", e)
        return None


def format_tickets(origin, destination, tickets, lang):
    lines = [t(lang, "route_title", o=city(origin, lang), d=city(destination, lang))]
    for tk in tickets:
        url = SITE + tk.get("link", "")
        if MARKER:
            url += ("&" if "?" in url else "?") + f"marker={MARKER}"
        transfers = tk.get("transfers", 0)
        stops = t(lang, "direct") if transfers == 0 else t(lang, "stops", n=transfers)
        lines.append(
            f"💵 {tk.get('price')} USD | {str(tk.get('departure_at', ''))[:10]} | "
            f"{tk.get('airline', '')} | {stops}\n🔗 {url}\n"
        )
    lines.append(t(lang, "footer"))
    return "\n".join(lines)


async def run_search(origin, destination, period, lang):
    """Возвращает (текст, клавиатура)."""
    tickets = await fetch_tickets(origin, destination, period)
    if tickets is None:
        return t(lang, "api_fail"), kb_again(lang)
    if not tickets:
        return t(lang, "not_found"), kb_again(lang)
    return (
        format_tickets(origin, destination, tickets, lang),
        kb_results(origin, destination, period, lang),
    )


# ---------- Обработчики: язык ----------
@dp.message(CommandStart())
async def cmd_start(message: Message):
    lang = get_lang(message.from_user.id)
    if lang is None:
        await message.answer(TEXTS["ru"]["lang_prompt"], reply_markup=kb_lang())
        return
    await message.answer(t(lang, "help"), reply_markup=kb_start(lang))


@dp.message(Command("lang"))
async def cmd_lang(message: Message):
    await message.answer(TEXTS["ru"]["lang_prompt"], reply_markup=kb_lang())


@dp.callback_query(F.data == "lang_menu")
async def cb_lang_menu(call: CallbackQuery):
    await call.answer()
    await call.message.answer(TEXTS["ru"]["lang_prompt"], reply_markup=kb_lang())


@dp.callback_query(F.data.startswith("lang:"))
async def cb_lang_set(call: CallbackQuery):
    await call.answer()
    lang = call.data.split(":")[1]
    if lang not in TEXTS:
        return
    set_lang(call.from_user.id, lang)
    await call.message.edit_text(t(lang, "help"), reply_markup=kb_start(lang))


# ---------- Обработчики: поиск ----------
@dp.message(Command("price"))
async def cmd_price(message: Message):
    lang = lang_of(message.from_user.id)
    parts = (message.text or "").split()
    if len(parts) != 4:
        await message.answer(t(lang, "help"), reply_markup=kb_start(lang))
        return
    _, origin, destination, period = parts
    origin, destination = origin.upper(), destination.upper()
    await message.answer(t(lang, "searching"))
    text, kb = await run_search(origin, destination, period, lang)
    await message.answer(text, reply_markup=kb, disable_web_page_preview=True)


@dp.callback_query(F.data == "go")
async def cb_go(call: CallbackQuery):
    await call.answer()
    lang = lang_of(call.from_user.id)
    await call.message.edit_text(t(lang, "ask_origin"), reply_markup=kb_origins(lang))


@dp.callback_query(F.data.startswith("o:"))
async def cb_origin(call: CallbackQuery):
    await call.answer()
    lang = lang_of(call.from_user.id)
    origin = call.data.split(":")[1]
    await call.message.edit_text(
        t(lang, "ask_dest", o=city(origin, lang)), reply_markup=kb_dests(origin, lang)
    )


@dp.callback_query(F.data.startswith("d:"))
async def cb_dest(call: CallbackQuery):
    await call.answer()
    lang = lang_of(call.from_user.id)
    _, origin, dest = call.data.split(":")
    await call.message.edit_text(
        t(lang, "ask_month", o=city(origin, lang), d=city(dest, lang)),
        reply_markup=kb_months(origin, dest, lang),
    )


@dp.callback_query(F.data.startswith("m:"))
async def cb_month(call: CallbackQuery):
    await call.answer()
    lang = lang_of(call.from_user.id)
    _, origin, dest, period = call.data.split(":")
    await call.message.edit_text(t(lang, "searching"))
    text, kb = await run_search(origin, dest, period, lang)
    await call.message.edit_text(text, reply_markup=kb, disable_web_page_preview=True)


# ---------- Обработчики: оповещения ----------
@dp.message(Command("alerts"))
async def cmd_alerts(message: Message):
    lang = lang_of(message.from_user.id)
    text, kb = alerts_view(message.from_user.id, lang)
    await message.answer(text, reply_markup=kb)


@dp.callback_query(F.data.startswith("w:"))
async def cb_watch(call: CallbackQuery):
    await call.answer()
    lang = lang_of(call.from_user.id)
    _, origin, dest, period = call.data.split(":")
    user_id = call.from_user.id
    route = f"{city(origin, lang)} → {city(dest, lang)}, {period}"

    exists = db_all(
        "SELECT id FROM alerts WHERE user_id=? AND origin=? AND dest=? AND period=?",
        (user_id, origin, dest, period),
    )
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
    db_exec(
        "INSERT OR IGNORE INTO alerts (user_id, origin, dest, period, last_price) VALUES (?,?,?,?,?)",
        (user_id, origin, dest, period, price),
    )
    await call.message.answer(t(lang, "watch_ok", route=route, price=f"{price:.0f}"))


@dp.callback_query(F.data == "alerts")
async def cb_alerts(call: CallbackQuery):
    await call.answer()
    lang = lang_of(call.from_user.id)
    text, kb = alerts_view(call.from_user.id, lang)
    await call.message.answer(text, reply_markup=kb)


@dp.callback_query(F.data.startswith("x:"))
async def cb_delete_alert(call: CallbackQuery):
    lang = lang_of(call.from_user.id)
    await call.answer(t(lang, "deleted"))
    alert_id = int(call.data.split(":")[1])
    db_exec("DELETE FROM alerts WHERE id=? AND user_id=?", (alert_id, call.from_user.id))
    text, kb = alerts_view(call.from_user.id, lang)
    await call.message.edit_text(text, reply_markup=kb)


# ---------- Фоновая проверка цен ----------
async def check_alerts(bot):
    this_month = date.today().strftime("%Y-%m")
    rows = db_all("SELECT * FROM alerts")
    routes = {}
    for r in rows:
        if r["period"][:7] < this_month:  # период уже прошёл
            db_exec("DELETE FROM alerts WHERE id=?", (r["id"],))
            continue
        routes.setdefault((r["origin"], r["dest"], r["period"]), []).append(r)

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
                text += format_tickets(origin, dest, tickets, lang)
                try:
                    await bot.send_message(
                        r["user_id"], text, reply_markup=kb_again(lang), disable_web_page_preview=True
                    )
                except TelegramForbiddenError:
                    # пользователь заблокировал бота: удаляем его оповещения
                    db_exec("DELETE FROM alerts WHERE user_id=?", (r["user_id"],))
                except Exception as e:
                    logging.exception("Send error: %s", e)
        await asyncio.sleep(1)  # небольшая пауза между запросами к API


async def alerts_loop(bot):
    await asyncio.sleep(30)
    while True:
        try:
            await check_alerts(bot)
        except Exception as e:
            logging.exception("Alerts loop error: %s", e)
        await asyncio.sleep(CHECK_INTERVAL)


async def main():
    if not BOT_TOKEN or not TP_TOKEN:
        raise SystemExit("Заполните BOT_TOKEN и TRAVELPAYOUTS_TOKEN в Secrets или .env")
    init_db()
    bot = Bot(BOT_TOKEN)
    loop_task = asyncio.create_task(alerts_loop(bot))
    try:
        await dp.start_polling(bot)
    finally:
        loop_task.cancel()


if __name__ == "__main__":
    asyncio.run(main())
