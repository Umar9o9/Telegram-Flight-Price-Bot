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

logging.basicConfig(level=logging.INFO)
dp = Dispatcher()

# ---------- Справочники городов (код IATA -> название) ----------
ORIGINS = {
    "TAS": "Ташкент", "SKD": "Самарканд", "BHK": "Бухара", "FEG": "Фергана",
    "NMA": "Наманган", "AZN": "Андижан", "UGC": "Ургенч", "NCU": "Нукус",
    "TMJ": "Термез", "KSQ": "Карши",
}
DESTS = {
    "MOW": "Москва", "LED": "Санкт-Петербург", "IST": "Стамбул", "DXB": "Дубай",
    "ALA": "Алматы", "DEL": "Дели", "JED": "Джидда", "KUL": "Куала-Лумпур",
    "BKK": "Бангкок", "SEL": "Сеул", "BAK": "Баку", "TBS": "Тбилиси",
}
NAMES = {**ORIGINS, **DESTS}

MONTHS_RU = [
    "", "январь", "февраль", "март", "апрель", "май", "июнь",
    "июль", "август", "сентябрь", "октябрь", "ноябрь", "декабрь",
]

HELP = (
    "✈️ Бот поиска дешёвых авиабилетов\n\n"
    "Нажмите «Найти билет» и выберите город вылета, направление и месяц. "
    "После результатов можно включить 🔔 оповещение: бот сам напишет, когда цена упадёт.\n\n"
    "Команды вручную:\n"
    "/price TAS IST 2026-11-15  (на день)\n"
    "/price TAS IST 2026-12     (на месяц)\n"
    "/alerts  (мои оповещения)"
)


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


# ---------- Клавиатуры ----------
def kb_start():
    b = InlineKeyboardBuilder()
    b.button(text="✈️ Найти билет", callback_data="go")
    b.button(text="🔔 Мои оповещения", callback_data="alerts")
    b.adjust(1)
    return b.as_markup()


def kb_origins():
    b = InlineKeyboardBuilder()
    for code, name in ORIGINS.items():
        b.button(text=name, callback_data=f"o:{code}")
    b.adjust(2)
    return b.as_markup()


def kb_dests(origin):
    b = InlineKeyboardBuilder()
    for code, name in DESTS.items():
        if code != origin:
            b.button(text=name, callback_data=f"d:{origin}:{code}")
    b.adjust(2)
    b.row(InlineKeyboardButton(text="⬅️ Назад", callback_data="go"))
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


def kb_months(origin, dest):
    b = InlineKeyboardBuilder()
    for year, month in next_months():
        label = f"{MONTHS_RU[month].capitalize()} {year}"
        b.button(text=label, callback_data=f"m:{origin}:{dest}:{year}-{month:02d}")
    b.adjust(2)
    b.row(InlineKeyboardButton(text="⬅️ Назад", callback_data=f"o:{origin}"))
    return b.as_markup()


def kb_again():
    b = InlineKeyboardBuilder()
    b.button(text="🔁 Новый поиск", callback_data="go")
    b.button(text="🔔 Мои оповещения", callback_data="alerts")
    b.adjust(1)
    return b.as_markup()


def kb_results(origin, dest, period):
    b = InlineKeyboardBuilder()
    b.button(text="🔔 Следить за ценой", callback_data=f"w:{origin}:{dest}:{period}")
    b.button(text="🔁 Новый поиск", callback_data="go")
    b.adjust(1)
    return b.as_markup()


def alerts_view(user_id):
    rows = db_all("SELECT * FROM alerts WHERE user_id=? ORDER BY id", (user_id,))
    if not rows:
        return (
            "У вас пока нет оповещений.\n"
            "Сделайте поиск и нажмите «🔔 Следить за ценой» под результатами.",
            kb_again(),
        )
    b = InlineKeyboardBuilder()
    for r in rows:
        o = NAMES.get(r["origin"], r["origin"])
        d = NAMES.get(r["dest"], r["dest"])
        price = f"{r['last_price']:.0f}$" if r["last_price"] is not None else "—"
        b.button(text=f"❌ {o} → {d}, {r['period']} (от {price})", callback_data=f"x:{r['id']}")
    b.adjust(1)
    b.row(InlineKeyboardButton(text="🔁 Новый поиск", callback_data="go"))
    return (
        "🔔 Ваши оповещения.\nНажмите на оповещение, чтобы удалить его:",
        b.as_markup(),
    )


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


def format_tickets(origin, destination, tickets):
    o = NAMES.get(origin, origin)
    d = NAMES.get(destination, destination)
    lines = [f"✈️ {o} → {d}: самые дешёвые варианты\n"]
    for t in tickets:
        url = SITE + t.get("link", "")
        if MARKER:
            url += ("&" if "?" in url else "?") + f"marker={MARKER}"
        transfers = t.get("transfers", 0)
        stops = "прямой" if transfers == 0 else f"пересадок: {transfers}"
        lines.append(
            f"💵 {t.get('price')} USD | {str(t.get('departure_at', ''))[:10]} | "
            f"{t.get('airline', '')} | {stops}\n🔗 {url}\n"
        )
    lines.append("Цены из кэша поисков, итоговую цену смотрите на сайте.")
    return "\n".join(lines)


NOT_FOUND = (
    "Билетов не найдено. Данные берутся из кэша поисков, поэтому для редких "
    "направлений или дат он может быть пустым. Попробуйте другой месяц или направление."
)
API_FAIL = "⚠️ Не удалось получить данные. Попробуйте позже."


async def run_search(origin, destination, period):
    """Возвращает (текст, клавиатура)."""
    tickets = await fetch_tickets(origin, destination, period)
    if tickets is None:
        return API_FAIL, kb_again()
    if not tickets:
        return NOT_FOUND, kb_again()
    return format_tickets(origin, destination, tickets), kb_results(origin, destination, period)


# ---------- Обработчики ----------
@dp.message(CommandStart())
async def cmd_start(message: Message):
    await message.answer(HELP, reply_markup=kb_start())


@dp.message(Command("price"))
async def cmd_price(message: Message):
    parts = (message.text or "").split()
    if len(parts) != 4:
        await message.answer(HELP, reply_markup=kb_start())
        return
    _, origin, destination, period = parts
    origin, destination = origin.upper(), destination.upper()
    await message.answer("🔎 Ищу билеты...")
    text, kb = await run_search(origin, destination, period)
    await message.answer(text, reply_markup=kb, disable_web_page_preview=True)


@dp.message(Command("alerts"))
async def cmd_alerts(message: Message):
    text, kb = alerts_view(message.from_user.id)
    await message.answer(text, reply_markup=kb)


@dp.callback_query(F.data == "go")
async def cb_go(call: CallbackQuery):
    await call.answer()
    await call.message.edit_text("Откуда летите? Выберите город вылета:", reply_markup=kb_origins())


@dp.callback_query(F.data.startswith("o:"))
async def cb_origin(call: CallbackQuery):
    await call.answer()
    origin = call.data.split(":")[1]
    await call.message.edit_text(
        f"Вылет: {NAMES.get(origin, origin)}\nКуда летите?", reply_markup=kb_dests(origin)
    )


@dp.callback_query(F.data.startswith("d:"))
async def cb_dest(call: CallbackQuery):
    await call.answer()
    _, origin, dest = call.data.split(":")
    await call.message.edit_text(
        f"{NAMES.get(origin, origin)} → {NAMES.get(dest, dest)}\nВыберите месяц вылета:",
        reply_markup=kb_months(origin, dest),
    )


@dp.callback_query(F.data.startswith("m:"))
async def cb_month(call: CallbackQuery):
    await call.answer()
    _, origin, dest, period = call.data.split(":")
    await call.message.edit_text("🔎 Ищу билеты...")
    text, kb = await run_search(origin, dest, period)
    await call.message.edit_text(text, reply_markup=kb, disable_web_page_preview=True)


@dp.callback_query(F.data.startswith("w:"))
async def cb_watch(call: CallbackQuery):
    await call.answer()
    _, origin, dest, period = call.data.split(":")
    user_id = call.from_user.id
    route = f"{NAMES.get(origin, origin)} → {NAMES.get(dest, dest)}, {period}"

    exists = db_all(
        "SELECT id FROM alerts WHERE user_id=? AND origin=? AND dest=? AND period=?",
        (user_id, origin, dest, period),
    )
    if exists:
        await call.message.answer(f"🔔 Это направление уже отслеживается: {route}\nСписок: /alerts")
        return

    count = db_all("SELECT COUNT(*) AS n FROM alerts WHERE user_id=?", (user_id,))[0]["n"]
    if count >= MAX_ALERTS:
        await call.message.answer(
            f"Достигнут лимит: {MAX_ALERTS} оповещений. Удалите ненужное в /alerts."
        )
        return

    tickets = await fetch_tickets(origin, dest, period, limit=1)
    if not tickets:
        await call.message.answer("Сейчас нет цен для этого направления, следить не получится.")
        return

    price = float(tickets[0]["price"])
    db_exec(
        "INSERT OR IGNORE INTO alerts (user_id, origin, dest, period, last_price) VALUES (?,?,?,?,?)",
        (user_id, origin, dest, period, price),
    )
    await call.message.answer(
        f"🔔 Слежу за ценой: {route}\n"
        f"Сейчас от {price:.0f} USD. Напишу, если подешевеет.\n"
        "Все оповещения: /alerts"
    )


@dp.callback_query(F.data == "alerts")
async def cb_alerts(call: CallbackQuery):
    await call.answer()
    text, kb = alerts_view(call.from_user.id)
    await call.message.answer(text, reply_markup=kb)


@dp.callback_query(F.data.startswith("x:"))
async def cb_delete_alert(call: CallbackQuery):
    await call.answer("Удалено")
    alert_id = int(call.data.split(":")[1])
    db_exec("DELETE FROM alerts WHERE id=? AND user_id=?", (alert_id, call.from_user.id))
    text, kb = alerts_view(call.from_user.id)
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
                text = (
                    f"🔔 Цена упала: {old_price:.0f} → {new_price:.0f} USD\n\n"
                    + format_tickets(origin, dest, tickets)
                )
                try:
                    await bot.send_message(
                        r["user_id"], text, reply_markup=kb_again(), disable_web_page_preview=True
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