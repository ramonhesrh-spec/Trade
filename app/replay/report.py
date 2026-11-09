"""Samenvatting van een afspeelrun: aantal, winrate, verwachting in R en de
langste reeks verliezen, per coin en per kwartaal, met een train/test-splitsing
op tijd (eerst afstellen op het begin, dan toetsen op het eind)."""
import pandas as pd

from app.replay.engine import ReplaySignal


def to_frame(signals: list[ReplaySignal], confirmed_only: bool = True) -> pd.DataFrame:
    rows = [
        {"coin": s.coin, "direction": s.direction, "at": s.at, "confirmed": s.confirmed,
         "result": s.outcome.result, "r_gross": s.outcome.r_gross, "r_net": s.outcome.r_net}
        for s in signals if s.outcome is not None and (s.confirmed or not confirmed_only)
    ]
    frame = pd.DataFrame(rows, columns=["coin", "direction", "at", "confirmed", "result", "r_gross", "r_net"])
    return frame.sort_values("at").reset_index(drop=True)


def summarize(frame: pd.DataFrame) -> dict:
    n = len(frame)
    tp = int((frame["result"] == "take_profit").sum())
    sl = int((frame["result"] == "stop_loss").sum())
    streak = worst = 0
    for r in frame["r_net"]:
        streak = streak + 1 if r < 0 else 0
        worst = max(worst, streak)
    return {
        "n": n, "take_profit": tp, "stop_loss": sl, "expired": n - tp - sl,
        "winrate": tp / (tp + sl) if tp + sl else None,
        "expectancy_net": float(frame["r_net"].mean()) if n else None,
        "expectancy_gross": float(frame["r_gross"].mean()) if n else None,
        "worst_streak": worst,
    }


def _line(label: str, s: dict) -> str:
    winrate = f"{s['winrate'] * 100:.0f}%" if s["winrate"] is not None else "-"
    net = f"{s['expectancy_net']:+.2f}R" if s["expectancy_net"] is not None else "-"
    gross = f"{s['expectancy_gross']:+.2f}R" if s["expectancy_gross"] is not None else "-"
    return (f"{label:<14} n={s['n']:<5} TP={s['take_profit']:<4} SL={s['stop_loss']:<4} "
            f"verlopen={s['expired']:<4} winrate={winrate:<5} verw.netto={net:<8} verw.bruto={gross:<8} "
            f"langste verliesreeks={s['worst_streak']}")


def format_report(
    signals: list[ReplaySignal], train_fraction: float = 0.7, confirmed_only: bool = True,
    notes: tuple[str, ...] = (),
) -> str:
    frame = to_frame(signals, confirmed_only)
    lines = []
    if frame.empty:
        return "Geen signalen met uitkomst in deze run."
    lines.append(_line("alles", summarize(frame)))

    lines.append("\nPer coin")
    for coin, part in frame.groupby("coin"):
        lines.append(_line(coin, summarize(part)))

    lines.append("\nPer kwartaal")
    frame = frame.assign(quarter=frame["at"].dt.tz_convert(None).dt.to_period("Q").astype(str))
    for quarter, part in frame.groupby("quarter"):
        lines.append(_line(quarter, summarize(part)))

    first, last = frame["at"].min(), frame["at"].max()
    cutoff = first + (last - first) * train_fraction
    lines.append(f"\nTrain en test (splitsing op {cutoff:%Y-%m-%d}, {train_fraction:.0%} train)")
    lines.append(_line("train", summarize(frame[frame["at"] <= cutoff])))
    lines.append(_line("test", summarize(frame[frame["at"] > cutoff])))

    for note in notes:
        lines.append(f"\nBeperking: {note}")
    return "\n".join(lines)
