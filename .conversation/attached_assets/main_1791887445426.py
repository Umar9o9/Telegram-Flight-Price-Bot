import asyncio
import logging
import os

import aiohttp
from aiogram import Bot, Dispatcher
from aiogram.filters import Command, CommandStart
from aiogram.types import Message
from dotenv import load_dotenv

load_dotenv()

BOT_TOKEN = os.getenv("BOT_TOKEN")                  # токен от @BotFather
TP_TOKEN = os.getenv("TRAVELPAYOUTS_TOKEN")         # API-токен Travelpayouts
MARKER = os.getenv("TRAVELPAYOUTS_MARKER", "")      # ваш партнёрский marker (для заработка)

API_URL = "https://api.travelpayouts.com/aviasales/v3/prices_for_dates"
SITE = "https://www.aviasales.com"

logging.basicConfig(level=logging.INFO)
dp = Dispatcher()

HELP = (
    "✈️ Бот поиска дешёвых авиабилетов\n\n"
    "Формат команды:\n"
    "/price ОТКУДА КУДА ДАТА\n\n"
    "Примеры:\n"
    "/price TAS IST 2026-11-15  (на конкретный день)\n"
    "/price TAS MOW 2026-12     (на весь месяц)\n\n"
    "Коды городов: TAS = Ташкент, IST = Стамбул, MOW = Москва, DXB = Дубай."
)


@dp.message(CommandStart())
async def cmd_start(message: Message):
    await message.answer(HELP)


@dp.message(Command("price"))
async def cmd_price(message: Message):
    parts = (message.text or "").split()
    if len(parts) != 4:
        await message.answer(HELP)
        return

    _, origin, destination, date = parts
    params = {
        "origin": origin.upper(),
        "destination": destination.upper(),
        "departure_at": date,
        "one_way": "true",
        "sorting": "price",
        "currency": "usd",
        "limit": 5,
        "unique": "false",
    }
    headers = {"X-Access-Token": TP_TOKEN}

    await message.answer("🔎 Ищу билеты...")
    try:
        timeout = aiohttp.ClientTimeout(total=20)
        async with aiohttp.ClientSession(timeout=timeout) as session:
            async with session.get(API_URL, params=params, headers=headers) as resp:
                data = await resp.json()
    except Exception as e:
        logging.exception("API error: %s", e)
        await message.answer("⚠️ Не удалось получить данные. Попробуйте позже.")
        return

    tickets = data.get("data") or []
    if not tickets:
        await message.answer(
            "Билетов не найдено. Данные берутся из кэша поисков, "
            "поэтому для редких направлений или дат он может быть пустым. "
            "Попробуйте указать месяц или другое направление."
        )
        return

    lines = [f"✈️ {origin.upper()} → {destination.upper()}: самые дешёвые варианты\n"]
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
    await message.answer("\n".join(lines), disable_web_page_preview=True)


async def main():
    if not BOT_TOKEN or not TP_TOKEN:
        raise SystemExit("Заполните BOT_TOKEN и TRAVELPAYOUTS_TOKEN в Secrets или .env")
    bot = Bot(BOT_TOKEN)
    await dp.start_polling(bot)


if __name__ == "__main__":
    asyncio.run(main())
