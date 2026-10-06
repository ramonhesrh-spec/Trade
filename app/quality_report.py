"""Wekelijks kwaliteitsrapport: meet automatisch wat wel en niet werkt, in R na kosten, zodat niemand
analyses hoeft te plakken. Alleen lezen en een rustige melding op /meldingen (geen push, geen wijziging aan
signalen). Draait via een systemd timer, zie deploy/crypto-quality-report.service en .timer.

Twee delen: (1) wat de scan zelf vond, per type (smc, patroon, day_trading, swing), laatste 28 dagen en alles
samen, uit de automatische uitkomst per signaal; (2) de community-calls: gaat de koers na een bericht de kant
op van het bericht, tegen een controle, en wat levert elke call als vaste trade. Het oordeel over de community
komt pas bij genoeg onafhankelijke calls: MIN_CALLS_FOR_VERDICT."""
import argparse
import logging
from datetime import datetime, timedelta, timezone
from typing import Optional

import pandas as pd

from app import config, repo
from app.replay import candles, community

logger = logging.getLogger("quality_report")

RECENT_DAYS = 28
MIN_CALLS_FOR_VERDICT = 60
MIN_T_FOR_EDGE = 2.0
MIN_CALLS_PER_COIN = 8
FEE_PCT = 0.02
SLIPPAGE_PCT = 0.01
TYPE_ORDER = ("smc", "patroon", "day_trading", "swing", "samenval", "script", "structuur", "structuur_c", "trend", "smc_waarschuwing")


def _r_of(row: dict) -> Optional[float]:
    """R van een afgerond signaal: take geeft de verhouding van take tot stop, stop geeft -1. Anders None."""
    risk = abs((row["price"] or 0) - (row["stop_loss"] or 0))
    if row["auto_outcome"] == "take_profit" and risk > 0 and row["take_profit"] is not None:
        return abs(row["take_profit"] - row["price"]) / risk
    if row["auto_outcome"] == "stop_loss":
        return -1.0
    return None


def scan_stats(rows: list[dict]) -> dict:
    """Per trade_type: afgerond, winst, verlies, winrate, gemiddelde R (bruto) en aantal vervallen of open.
    Alleen signalen die de scan zelf vond (geen bericht), alle signalen van dat type ongeacht bevestiging."""
    stats: dict = {}
    for r in rows:
        if r["message_id"] is not None:
            continue
        value = _r_of(r)
        # Samenval-signalen tellen ook mee onder hun eigen soort (smc) en staan daarnaast apart.
        for name in (r["trade_type"], "samenval") if r.get("samenval") else (r["trade_type"],):
            s = stats.setdefault(name, {"tp": 0, "sl": 0, "other": 0, "r": []})
            if value is None:
                s["other"] += 1
            else:
                s["tp" if value > 0 else "sl"] += 1
                s["r"].append(value)
    return stats


def _scan_line(name: str, s: dict) -> str:
    done = s["tp"] + s["sl"]
    if not done:
        return f"{name}: nog niets afgerond ({s['other']} open of vervallen)."
    return (f"{name}: {done} afgerond, {s['tp']} winst, winrate {s['tp'] / done * 100:.0f}%, "
            f"gemiddeld {sum(s['r']) / len(s['r']):+.2f}R bruto, {s['other']} open of vervallen.")


def verdict(summary: dict) -> str:
    """Eén zin over de community. Pas bij genoeg calls en een voorsprong tegen de controle, én een positieve
    netto R als trade, staat er dat er een voorsprong lijkt te zijn."""
    alle = summary.get("alle", {})
    n = alle.get("n", 0)
    if n < MIN_CALLS_FOR_VERDICT:
        return f"Te weinig onafhankelijke calls voor een oordeel ({n} van {MIN_CALLS_FOR_VERDICT})."
    t, trades = alle.get("t"), alle.get("trades")
    if t is None or not trades:
        return "Geen meting mogelijk, er ontbreken candles."
    if t >= MIN_T_FOR_EDGE and trades["net"] > 0:
        return "De community lijkt een voorsprong te hebben: de koers loopt na een bericht vaker de goede kant op dan de controle."
    return "Geen voorsprong gemeten bij de community."


def _community_lines(summary: dict, horizon_hours: int) -> list[str]:
    lines = []
    for key, label in (("alle", "Alle echte calls"), ("day_trading", "Alleen day_trading")):
        e = summary.get(key, {})
        if not e.get("n"):
            continue
        parts = [f"{label}: {e['n']} onafhankelijke calls."]
        if "diff_mean" in e:
            parts.append(f"Na {horizon_hours} uur {e['call_mean']:+.2f}% tegen controle {e['ctl_mean']:+.2f}%, verschil {e['diff_mean']:+.2f}% (t={e['t']:+.1f}).")
        if "trades" in e:
            t = e["trades"]
            wr = f"winrate {t['winrate'] * 100:.0f}%, " if t["winrate"] is not None else ""
            parts.append(f"Als trade: {wr}{t['gross']:+.2f}R bruto, {t['net']:+.2f}R netto.")
        lines.append(" ".join(parts))
    return lines


def load_frames(calls: pd.DataFrame, now: pd.Timestamp) -> dict:
    frames = {}
    counts = calls["coin"].value_counts()
    for coin in [c for c, n in counts.items() if n >= MIN_CALLS_PER_COIN]:
        first = calls.loc[calls["coin"] == coin, "at"].min()
        try:
            frames[coin] = candles.update_candles(coin, first, "1m")
        except Exception:
            logger.exception("Candles voor %s niet op te halen", coin)
    return frames


def build_report(now: Optional[datetime] = None, frames: Optional[dict] = None) -> tuple[str, str]:
    """Geeft (titel, tekst). `frames` kan in tests worden meegegeven; anders worden de 1m-candles bijgewerkt."""
    now = now or datetime.now(timezone.utc)
    recent_iso = (now - timedelta(days=RECENT_DAYS)).isoformat()
    lines: list[str] = []
    recent, overall = scan_stats(repo.list_signals_for_quality_report(recent_iso)), scan_stats(repo.list_signals_for_quality_report(None))
    lines.append(f"Wat de scan zelf vond, laatste {RECENT_DAYS} dagen:")
    for name in TYPE_ORDER:
        if name in recent or name in overall:
            lines.append(_scan_line(name, recent.get(name, {"tp": 0, "sl": 0, "other": 0, "r": []})))
    lines.append("Alles samen sinds het begin:")
    for name in TYPE_ORDER:
        if name in overall:
            lines.append(_scan_line(name, overall[name]))

    calls = pd.DataFrame(repo.list_community_calls())
    lines.append("")
    if calls.empty:
        lines.append("Community-calls: geen berichten met coin en richting.")
    else:
        calls["at"] = calls["at"].map(lambda v: pd.Timestamp(v).tz_localize("UTC") if pd.Timestamp(v).tzinfo is None else pd.Timestamp(v).tz_convert("UTC"))
        calls["coin"] = calls["coin"].str.upper()
        calls = calls.drop_duplicates(["message_id", "coin"])
        frames = frames if frames is not None else load_frames(calls, pd.Timestamp(now))
        summary = community.community_summary(calls, frames, FEE_PCT, SLIPPAGE_PCT)
        lines.append(f"Community-calls (sinds {calls['at'].min():%d-%m-%Y}, kosten {2 * (FEE_PCT + SLIPPAGE_PCT):.2f}% per rondreis, 15 minuten vertraging):")
        lines += _community_lines(summary, 4)
        lines.append(verdict(summary))
    title = f"Kwaliteitsrapport {now:%d-%m-%Y}"
    return title, "\n".join(lines)


def run(username: Optional[str] = None) -> None:
    title, body = build_report()
    print(f"{title}\n{body}")
    user_id = None
    if username:
        user = repo.get_user_by_username(username)
        if user is None:
            logger.error("Gebruiker %s bestaat niet, rapport alleen als admin-melding", username)
        else:
            user_id = user["id"]
    repo.create_notification(user_id, "quality_report", title, body, "/meldingen")


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    parser = argparse.ArgumentParser()
    parser.add_argument("--user", default=config.ADMIN_USERNAME or None, help="gebruikersnaam die het rapport op /meldingen krijgt (standaard ADMIN_USERNAME)")
    args = parser.parse_args()
    run(args.user)
