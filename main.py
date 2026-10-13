import asyncio
import logging
import os
from datetime import date

import aiohttp
from aiogram import Bot, Dispatcher, F
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
    "Нажмите кнопку «Найти билет» и выберите город вылета, направление и месяц.\n\n"
    "Или введите команду вручную:\n"
    "/price TAS IST 2026-11-15  (на день)\n"
    "/price TAS IST 2026-12     (на месяц)"
)


# ---------- Клавиатуры ----------
def kb_start():
    b = InlineKeyboardBuilder()
    b.button(text="✈️ Найти билет", callback_data="go")
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
    return b.as_markup()


# ---------- Поиск билетов ----------
async def fetch_tickets(origin, destination, period):
    """Возвращает список билетов или None при ошибке."""
    params = {
        "origin": origin,
        "destination": destination,
        "departure_at": period,
        "one_way": "true",
        "sorting": "price",
        "currency": "usd",
        "limit": 5,
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
    tickets = await fetch_tickets(origin, destination, period)
    if tickets is None:
        return API_FAIL
    if not tickets:
        return NOT_FOUND
    return format_tickets(origin, destination, tickets)


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
    await message.answer("🔎 Ищу билеты...")
    text = await run_search(origin.upper(), destination.upper(), period)
    await message.answer(text, reply_markup=kb_again(), disable_web_page_preview=True)


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
    text = await run_search(origin, dest, period)
    await call.message.edit_text(text, reply_markup=kb_again(), disable_web_page_preview=True)


async def main():
    if not BOT_TOKEN or not TP_TOKEN:
        raise SystemExit("Заполните BOT_TOKEN и TRAVELPAYOUTS_TOKEN в Secrets или .env")
    bot = Bot(BOT_TOKEN)
    await dp.start_polling(bot)


if __name__ == "__main__":
    asyncio.run(main())