"""Het Logboek als dagtijdlijn (fase 2): pure functies zonder database of netwerk. De route geeft de rijen uit app/repo.py mee."""
from datetime import date, datetime, timedelta, timezone
from typing import Optional

from app import track_record


def _parse(value: str) -> datetime:
    t = datetime.fromisoformat(value)
    return t if t.tzinfo else t.replace(tzinfo=timezone.utc)


def checklist_seconds(opened_at: Optional[str], done_at: Optional[str]) -> Optional[int]:
    """Hoe lang de checklist openstond tot alle stappen stonden; alleen als beide tijden bestaan, anders bestaat het getal niet."""
    if not opened_at or not done_at:
        return None
    seconds = int((_parse(done_at) - _parse(opened_at)).total_seconds())
    return seconds if seconds >= 0 else None


def duration_text(seconds: int) -> str:
    hours, rest = divmod(seconds, 3600)
    minutes, secs = divmod(rest, 60)
    if hours:
        return f"{hours} u {minutes} min" if minutes else f"{hours} u"
    if minutes:
        return f"{minutes} min {secs} s" if secs else f"{minutes} min"
    return f"{secs} s"

DAYS_SHOWN = 14
TAKEN_STATUSES = ("genomen", "aangepast")
DAY_NAMES = ("maandag", "dinsdag", "woensdag", "donderdag", "vrijdag", "zaterdag", "zondag")
MONTHS = ("januari", "februari", "maart", "april", "mei", "juni", "juli", "augustus", "september", "oktober", "november", "december")


def r_text(value: float) -> str:
    """Eén decimaal en een echt minteken, zoals het ontwerp: +2,0 R, −1,0 R, 0,0 R."""
    text = f"{abs(value):.1f}".replace(".", ",") + " R"
    if round(value, 1) == 0:
        return text
    return ("+" if value > 0 else "−") + text


def price_text(value: float) -> str:
    return (f"{value:.4f}" if abs(value) < 100 else f"{value:.2f}").replace(".", ",")


def date_text(d: date) -> str:
    return f"{DAY_NAMES[d.weekday()].capitalize()} {d.day} {MONTHS[d.month - 1]}"


def short_date(d: date) -> str:
    return f"{DAY_NAMES[d.weekday()].capitalize()} {d.day} {MONTHS[d.month - 1][:3]}"


def _event(kind: str, at: datetime, tz, title: str, sub: str, *, r: Optional[float] = None, r_label: str = "", tone: str = "line",
           url: Optional[str] = None, replay_url: Optional[str] = None) -> dict:
    local = at.astimezone(tz)
    return {"kind": kind, "at": at, "day": local.date(), "time": f"{local:%H:%M}", "title": title, "sub": sub, "r": r,
            "r_text": r_label if r_label else (r_text(r) if r is not None else ""), "tone": tone, "url": url, "replay_url": replay_url}


def _resolved(signal: Optional[dict]) -> Optional[float]:
    return track_record.signal_r(signal) if signal and signal.get("auto_outcome") in ("take_profit", "stop_loss") else None


def _close_events(signal: dict, entered: datetime, tz) -> list[dict]:
    name = f"{signal['coin']} {signal['direction']}"
    outcome, at = signal.get("auto_outcome"), signal.get("auto_outcome_at")
    if not outcome or not at:
        return []
    closed = _parse(at)
    if outcome == "vervallen":
        return [_event("expired", closed, tz, f"{name} vervallen", "Geen doel en geen stop geraakt binnen de looptijd.", url=f"/kans/{signal['id']}")]
    r = _resolved(signal)
    if r is None:
        return []
    what = "Doel geraakt" if outcome == "take_profit" else "Stop geraakt"
    after = int((closed - entered).total_seconds())
    sub = f"{what}, {duration_text(after)} na instap." if after >= 0 else f"{what}."
    return [_event("closed", closed, tz, f"{name} gesloten", sub, r=r, tone="win" if r > 0 else "loss",
                   url=f"/kans/{signal['id']}", replay_url=f"/logboek/replay/{signal['id']}")]


def _skip_outcome(signal: Optional[dict]) -> str:
    r = _resolved(signal)
    if r is None:
        return ""
    if signal["auto_outcome"] == "take_profit":
        return f" Haalde later zijn doel ({r_text(r)} niet genomen)."
    return f" Raakte later de stop ({r_text(r)})."


def _seen_events(seen: list[dict], tz) -> list[dict]:
    """Per dag één regel: hoeveel plannen er ontstonden en hoeveel er in de zone kwamen, elk op de dag van zijn eigen tijdstip."""
    created: dict = {}
    zoned: dict = {}
    for s in seen:
        c = _parse(s["created_at"])
        created.setdefault(c.astimezone(tz).date(), []).append(c)
        if s.get("zone_at"):
            z = _parse(s["zone_at"])
            zoned.setdefault(z.astimezone(tz).date(), []).append(z)
    out = []
    for day in set(created) | set(zoned):
        n_new, n_zone = len(created.get(day, [])), len(zoned.get(day, []))
        parts = []
        if n_new:
            parts.append(f"{n_new} nieuw{'e' if n_new != 1 else ''} plan{'nen' if n_new != 1 else ''}.")
        if n_zone:
            parts.append(f"{n_zone} kwam{'en' if n_zone != 1 else ''} in de zone.")
        first = min(created.get(day, []) + zoned.get(day, []))
        out.append(_event("seen", first, tz, "Wat de app zag", " ".join(parts), tone="quiet"))
    return out


def timeline(*, skips: list[dict], runs: list[dict], plans: dict, signals: dict, taken: list[dict], seen: list[dict], now: datetime, tz,
             days: int = DAYS_SHOWN) -> list[dict]:
    """De dagen van het Logboek, nieuwste eerst, met hun momenten van laat naar vroeg. Alles komt van deze ene gebruiker: zijn overgeslagen
    plannen (skips), zijn checklists (runs) en zijn genomen journaalregels (taken). `plans` (sleutel -> plan met signal_id) en `signals`
    (id -> signaalrij met r_override) zijn gedeeld. Een trade is een plan waarvan jij de checklist afrondde, of een journaalregel die je als
    genomen of aangepast markeerde; zijn R komt alleen uit track_record.signal_r. Oefentrades doen nergens mee."""
    real = {sid: s for sid, s in signals.items() if not s.get("is_practice")}
    done_keys = {r["plan_key"] for r in runs if r.get("done_at")}
    events: list[dict] = []
    trade_entries: dict[int, tuple[str, datetime, Optional[float]]] = {}

    for run in runs:
        seconds = checklist_seconds(run.get("opened_at"), run.get("done_at"))
        if run.get("done_at"):
            sub = f"Checklist in {duration_text(seconds)}." if seconds is not None else "Checklist afgerond."
            events.append(_event("order", _parse(run["done_at"]), tz, f"{run['coin']} {run['direction']} order gezet", sub, tone="accent"))
            sid = (plans.get(run["plan_key"]) or {}).get("signal_id")
            if sid in real:
                trade_entries[sid] = ("filled", _parse(real[sid]["created_at"]), None)

    for row in taken:
        sid = row["signal_id"]
        if row.get("status") not in TAKEN_STATUSES or sid not in real or sid in trade_entries or not row.get("entry_time"):
            continue
        trade_entries[sid] = ("taken", _parse(row["entry_time"]), row.get("entry_price"))

    for sid, (kind, at, own_price) in trade_entries.items():
        s = real[sid]
        name = f"{s['coin']} {s['direction']}"
        if kind == "filled":
            events.append(_event("filled", at, tz, f"{name} gevuld", f"Limit op {price_text(s['price'])}.", tone="accent", url=f"/kans/{sid}"))
        else:
            events.append(_event("taken", at, tz, f"{name} genomen", f"Instap {price_text(own_price if own_price is not None else s['price'])}.",
                                 tone="accent", url=f"/kans/{sid}"))
        events += _close_events(s, at, tz)

    for skip in skips:
        if skip["plan_key"] in done_keys:
            continue
        p = plans.get(skip["plan_key"]) or {}
        coin, direction = skip.get("coin") or p.get("coin") or "?", skip.get("direction") or p.get("direction") or ""
        signal = real.get(p.get("signal_id"))
        events.append(_event("skipped", _parse(skip["skipped_at"]), tz, f"{coin} {direction} overgeslagen".replace("  ", " "),
                             "Jouw keuze." + _skip_outcome(signal), r_label="0 R", tone="muted",
                             replay_url=f"/logboek/replay/{signal['id']}" if _resolved(signal) is not None else None))

    events += _seen_events(seen, tz)

    today_local = now.astimezone(tz).date()
    first = today_local - timedelta(days=days - 1)
    by_day: dict = {today_local: []}
    for e in events:
        if first <= e["day"] <= today_local:
            by_day.setdefault(e["day"], []).append(e)
    out = []
    for day in sorted(by_day, reverse=True):
        evs = sorted(by_day[day], key=lambda e: e["at"], reverse=True)
        rs = [e["r"] for e in evs if e["kind"] == "closed"]
        total = sum(rs) if rs else None
        total_text = r_text(total) if total is not None else "0 R"
        trades = len(rs)
        summary = f"{short_date(day)} · " + (f"{r_text(total)} · {trades} trade{'s' if trades != 1 else ''}" if trades else "geen trades")
        out.append({"date": day, "is_today": day == today_local, "date_text": date_text(day), "summary": summary, "events": evs,
                    "total_r": total, "total_text": total_text, "trades": trades})
    return out
