"""Luistert naar de Binance futures-stroom met gedwongen sluitingen en bewaart ze per coin per 5 minuten.
Waarom een eigen service: de stroom bestaat alleen live, er is geen history om later op te halen. Elke dag zonder dit
proces is voorgoed kwijt (zie deploy/crypto-liq.service). Een SELL-order is een geliquideerde long, een BUY een short."""
import asyncio
import json
import logging
from collections import defaultdict
from datetime import datetime, timezone
from typing import Optional

import aiohttp

from app import config, repo

logger = logging.getLogger("liquidations")

STREAM_URL = "wss://fstream.binance.com/ws/!forceOrder@arr"
FLUSH_SECONDS = 60
BUCKET_MINUTES = 5


def bucket_of(ms: int) -> str:
    t = datetime.fromtimestamp(ms / 1000, tz=timezone.utc)
    return t.replace(minute=t.minute - t.minute % BUCKET_MINUTES, second=0, microsecond=0).isoformat()


def parse_event(raw: str, coins: set[str]) -> Optional[tuple]:
    """(coin, bucket, long_usd, short_usd) of None voor een bericht dat niet telt (andere coin, andere soort, kapot)."""
    try:
        o = json.loads(raw)["o"]
        symbol = o["s"]
        if not symbol.endswith("USDT") or symbol[:-4] not in coins:
            return None
        usd = float(o["ap"]) * float(o["z"])
        if usd <= 0:
            return None
        long_usd, short_usd = (usd, 0.0) if o["S"] == "SELL" else (0.0, usd)
        return symbol[:-4], bucket_of(int(o["T"])), long_usd, short_usd
    except (KeyError, ValueError, TypeError, json.JSONDecodeError):
        return None


class Aggregator:
    def __init__(self) -> None:
        self.pending: dict[tuple, list] = defaultdict(lambda: [0.0, 0.0, 0])

    def add(self, event: tuple) -> None:
        coin, bucket, long_usd, short_usd = event
        cell = self.pending[(coin, bucket)]
        cell[0] += long_usd
        cell[1] += short_usd
        cell[2] += 1

    def drain(self) -> list[tuple]:
        rows = [(c, b, v[0], v[1], v[2]) for (c, b), v in self.pending.items()]
        self.pending.clear()
        return rows


async def run() -> None:
    coins = set(config.FIXED_COINS)
    agg = Aggregator()

    async def flusher() -> None:
        while True:
            await asyncio.sleep(FLUSH_SECONDS)
            rows = agg.drain()
            if rows:
                try:
                    repo.add_liquidations(rows)
                except Exception:
                    logger.exception("Liquidaties wegschrijven mislukt, %s rijen verloren", len(rows))

    task = asyncio.create_task(flusher())
    delay = 2
    try:
        while True:
            try:
                async with aiohttp.ClientSession() as session:
                    async with session.ws_connect(STREAM_URL, heartbeat=30) as ws:
                        logger.info("Verbonden met %s", STREAM_URL)
                        delay = 2
                        async for msg in ws:
                            if msg.type == aiohttp.WSMsgType.TEXT:
                                event = parse_event(msg.data, coins)
                                if event:
                                    agg.add(event)
                            elif msg.type in (aiohttp.WSMsgType.CLOSED, aiohttp.WSMsgType.ERROR):
                                break
            except Exception:
                logger.exception("Verbinding verbroken, opnieuw over %s s", delay)
            await asyncio.sleep(delay)
            delay = min(delay * 2, 60)
    finally:
        task.cancel()
        rows = agg.drain()
        if rows:
            repo.add_liquidations(rows)


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    from app import db
    db.init_db()
    asyncio.run(run())
