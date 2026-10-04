"""Rapport voor het SMC-meetraam: waarom lopen setups dood (trechter), wat leveren
signalen op in R, hoe snel eindigen ze (minuten) en hoe hoog mogen de kosten zijn
voor de strategie nog wint."""
from collections import Counter
from typing import Optional

import pandas as pd

from app.replay.smc_engine import SmcFunnelEvent, SmcSignal

SKIP_KINDS = ("geen_structuurbreuk", "geen_sweep", "geen_confluentiezone", "geen_liquiditeitsdoel",
              "stop_of_doel_binnen_zone", "koers_al_in_zone")


def funnel_summary(setups: list[dict], events: list[SmcFunnelEvent]) -> dict:
    ended = Counter(s["ended_because"] for s in setups if s["invalidated_at"] is not None)
    skip = Counter(e.kind for e in events if e.kind in SKIP_KINDS)
    rejected = Counter(e.detail for e in events if e.kind == "afgewezen_geen_signaal")
    return {
        "gebouwd": len(setups),
        "signaal": sum(1 for s in setups if s["signal_id"] is not None),
        "vervallen": ended.get("vervallen", 0),
        "doorbroken": ended.get("doorbraak", 0),
        "tegenrichting": ended.get("tegenrichting", 0),
        "nog_bouwend": sum(1 for s in setups if s["signal_id"] is None and s["invalidated_at"] is None),
        "te_weinig_historie": sum(1 for e in events if e.kind == "te_weinig_historie"),
        "skip": dict(skip),
        "afgewezen_geen_signaal": dict(rejected),
    }


def performance(signals: list[SmcSignal]) -> dict:
    rows = [s for s in signals if s.outcome is not None]
    n = len(rows)
    tp = sum(1 for s in rows if s.outcome.result == "take_profit")
    sl = sum(1 for s in rows if s.outcome.result == "stop_loss")
    minutes = pd.Series([(s.outcome.exit_at - s.at).total_seconds() / 60 for s in rows], dtype=float)
    gross = pd.Series([s.outcome.r_gross for s in rows], dtype=float)
    net = pd.Series([s.outcome.r_net for s in rows], dtype=float)
    cost_per_pct = pd.Series([2 * s.entry / abs(s.entry - s.stop) / 100 for s in rows], dtype=float)
    breakeven: Optional[float] = None
    if n and gross.mean() > 0:
        breakeven = float(gross.mean() / cost_per_pct.mean())
    return {
        "n": n, "take_profit": tp, "stop_loss": sl, "expired": n - tp - sl,
        "winrate": tp / (tp + sl) if tp + sl else None,
        "expectancy_net": float(net.mean()) if n else None,
        "expectancy_gross": float(gross.mean()) if n else None,
        "median_minutes": float(minutes.median()) if n else None,
        "p90_minutes": float(minutes.quantile(0.9)) if n else None,
        "share_within_60m": float((minutes <= 60).mean()) if n else None,
        "avg_cost_r": float((gross - net).mean()) if n else None,
        "breakeven_cost_pct": breakeven,
    }


def _line(label: str, p: dict) -> str:
    wr = f"{p['winrate'] * 100:.0f}%" if p["winrate"] is not None else "-"
    net = f"{p['expectancy_net']:+.2f}R" if p["expectancy_net"] is not None else "-"
    gross = f"{p['expectancy_gross']:+.2f}R" if p["expectancy_gross"] is not None else "-"
    med = f"{p['median_minutes']:.0f} min" if p["median_minutes"] is not None else "-"
    return (f"{label:<12} n={p['n']:<4} TP={p['take_profit']:<3} SL={p['stop_loss']:<3} verlopen={p['expired']:<3} "
            f"winrate={wr:<5} netto={net:<8} bruto={gross:<8} mediaan {med}")


def format_smc_report(signals: list[SmcSignal], setups: list[dict], events: list[SmcFunnelEvent],
                      train_fraction: float = 0.7, notes: tuple[str, ...] = ()) -> str:
    out = ["Trechter (setups)"]
    f = funnel_summary(setups, events)
    out.append(f"gebouwd={f['gebouwd']}  signaal={f['signaal']}  vervallen={f['vervallen']}  doorbroken={f['doorbroken']}  "
               f"tegenrichting={f['tegenrichting']}  nog bouwend={f['nog_bouwend']}")
    if f["afgewezen_geen_signaal"]:
        out.append("afgewezen bij afwijzing, geen signaal: " + ", ".join(f"{k}={v}" for k, v in f["afgewezen_geen_signaal"].items()))
    if f["te_weinig_historie"]:
        out.append(f"stappen overgeslagen door te weinig 30m-historie: {f['te_weinig_historie']}")
    if f["skip"]:
        out.append("geen setup gebouwd, per reden (aantal stappen): " + ", ".join(f"{k}={v}" for k, v in f["skip"].items()))

    rows = [s for s in signals if s.outcome is not None]
    out.append("\nPrestaties")
    p = performance(rows)
    out.append(_line("alles", p))
    if not rows:
        return "\n".join(out + ["Geen signalen met uitkomst in deze run."] + [f"\nBeperking: {n}" for n in notes])

    frame = pd.DataFrame({"coin": [s.coin for s in rows], "at": [s.at for s in rows]})
    for coin in sorted(frame["coin"].unique()):
        out.append(_line(coin, performance([s for s in rows if s.coin == coin])))

    out.append("\nPer kwartaal")
    quarters = sorted({s.at.tz_convert(None).to_period("Q") for s in rows})
    for q in quarters:
        out.append(_line(str(q), performance([s for s in rows if s.at.tz_convert(None).to_period("Q") == q])))

    first, last = frame["at"].min(), frame["at"].max()
    cutoff = first + (last - first) * train_fraction
    out.append(f"\nTrain en test (splitsing op {cutoff:%Y-%m-%d}, {train_fraction:.0%} train)")
    out.append(_line("train", performance([s for s in rows if s.at <= cutoff])))
    out.append(_line("test", performance([s for s in rows if s.at > cutoff])))

    out.append("\nTempo: snelheid en kosten")
    out.append(f"mediaan {p['median_minutes']:.0f} min, 90e percentiel {p['p90_minutes']:.0f} min, "
               f"{p['share_within_60m'] * 100:.0f}% binnen 60 minuten klaar")
    out.append(f"gemiddelde kosten per trade: {p['avg_cost_r']:.2f}R (met de ingestelde fee en slippage)")
    if p["breakeven_cost_pct"] is not None:
        out.append(f"break-even: de strategie wint nog bij hoogstens {p['breakeven_cost_pct']:.3f}% kosten per kant (fee plus spread plus slippage)")
    else:
        out.append("break-even: geen positieve verwachting voor kosten, dus geen kostenruimte")
    for note in notes:
        out.append(f"\nBeperking: {note}")
    return "\n".join(out)


def first_step(start: pd.Timestamp, step_minutes: int, offset_minutes: int) -> pd.Timestamp:
    """Eerste scanmoment op of na `start`, met minuten = offset (mod stap). Live scant
    SMC op een kwartiersgrens niet, dus de stappen mogen er geen raken (zie replay_smc)."""
    if step_minutes < 1 or 60 % step_minutes:
        raise ValueError(f"--step-minutes moet een deler van 60 zijn (kreeg {step_minutes}).")
    t = start.ceil("min")
    while t.minute % step_minutes != offset_minutes % step_minutes:
        t += pd.Timedelta(minutes=1)
    if any((t + pd.Timedelta(minutes=step_minutes * i)).minute % 15 == 0 for i in range(60 // step_minutes)):
        raise ValueError(f"Stappen van {step_minutes} minuten vanaf offset {offset_minutes} raken een kwartiersgrens; "
                         "kies een andere --offset-minutes (bijvoorbeeld 3).")
    return t


SMC_NOTES = (
    "niet nagebootst: de scan_market-pre-checks voor de 4u-detectoren (die draaien niet in de SMC-snelcheck, dus ze beinvloeden SMC niet; vermeld voor volledigheid).",
    "niet nagebootst: de structurele tegenstrijdigheid-onderdrukking van scan_market.",
    "niet nagebootst: pushmeldingen en het journal (dubbele signalen, cooldowns en limieten per gebruiker).",
    "benaderd: entry is de laatste 1m-close op het scanmoment; uitkomsten zijn op 1m-candles gemeten, stop gaat voor bij gelijke candle; kosten, slippage en maximale looptijd volgens de opties van deze run.",
    "de laatste 24 uur van de run hebben een afgekapt uitkomstvenster (de run eindigt 1 dag voor de laatste candle, het venster is 48 uur); signalen daar kunnen als verlopen verschijnen.",
)


def cache_covers_until(cache_end: pd.Timestamp, until: pd.Timestamp) -> bool:
    """cache_end is de OPEN-tijd van de laatste candle; die candle dekt nog een minuut, en --until is exclusief."""
    return cache_end + pd.Timedelta(minutes=1) >= until
