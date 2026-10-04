"""Koppeling tussen echte (live) signalen en een afspeelrun, voor de controle
van het meetraam. Puur, zodat het zonder database te testen is."""
import pandas as pd

TOLERANCE = pd.Timedelta(hours=2)


def window_end(live_row: dict, all_live: list[dict], until: pd.Timestamp) -> pd.Timestamp:
    """Een open live signaal wordt elke cyclus ververst en houdt zijn
    created_at van de eerste aanmaak; zijn bevestiging kan dus later vallen.
    Het venster loopt tot de volgende live rij van dezelfde coin (elke
    richting), anders tot `until`."""
    later = [r["at"] for r in all_live if r["coin"] == live_row["coin"] and r["at"] > live_row["at"]]
    return min(later) if later else until


def found_in_trace(live_row: dict, all_live: list[dict], trace: list[tuple], until: pd.Timestamp,
                   tolerance: pd.Timedelta = TOLERANCE) -> bool:
    """Is er een bevestigde beoordeling (coin, richting, tijd, confirmed) van
    de replay in [created_at - tolerantie, einde van het venster]?"""
    start, end = live_row["at"] - tolerance, window_end(live_row, all_live, until)
    return any(
        coin == live_row["coin"] and direction == live_row["direction"] and confirmed and start <= t <= end
        for coin, direction, t, confirmed in trace
    )


def found_strict(live_row: dict, replay_rows: list[dict], tolerance: pd.Timedelta = TOLERANCE) -> bool:
    """Strikte variant: een bevestigd replay-signaal binnen de tolerantie."""
    return any(
        r["confirmed"] and r["coin"] == live_row["coin"] and r["direction"] == live_row["direction"]
        and abs(r["at"] - live_row["at"]) <= tolerance
        for r in replay_rows
    )
