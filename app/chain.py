"""Ketting van vingerafdrukken: elk signaal krijgt bij het melden een hash over zijn plan en de hash van het vorige signaal. Wie later het plan
aanpast, een signaal weglaat of er een tussenvoegt, breekt de ketting. Iedereen kan dit narekenen met /keten.json, ook zonder login.
Pure functies; de database zit in repo.record_chain. Wat erin zit is het plan op het moment van melden, niet de uitkomst."""
import hashlib
import json
from typing import Optional

GENESIS = "genesis"
FIELDS = ("id", "created_at", "coin", "direction", "trade_type", "price", "stop_loss", "take_profit")


def payload(signal: dict) -> str:
    """Vaste tekstvorm van het plan: gesorteerde sleutels, geen spaties, zodat elke machine dezelfde bytes krijgt."""
    return json.dumps({f: signal.get(f) for f in FIELDS}, sort_keys=True, separators=(",", ":"), ensure_ascii=False)


def link(prev: Optional[str], body: str) -> str:
    return hashlib.sha256(f"{prev or GENESIS}|{body}".encode("utf-8")).hexdigest()


def verify(rows: list[dict]) -> tuple[bool, Optional[int]]:
    """rows: [{signal_id, prev, payload, hash}] oud naar nieuw. Geeft (klopt, eerste kapotte signal_id)."""
    expected_prev = None
    for i, r in enumerate(rows):
        if i and r["prev"] != expected_prev:
            return False, r["signal_id"]
        if link(r["prev"], r["payload"]) != r["hash"]:
            return False, r["signal_id"]
        expected_prev = r["hash"]
    return True, None
