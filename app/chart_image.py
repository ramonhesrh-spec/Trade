"""Genereert een klein prijs-chartje als foto bij een Telegram melding.
Zuiver visueel, geen nieuwe berekening: gebruikt dezelfde OHLCV-data die
de melding zelf al ophaalde voor de technische toetsing.

matplotlib gebruikt de "Agg" backend (geen scherm nodig, werkt op een
headless VPS) en wordt hier pas geïmporteerd na het instellen daarvan.
"""
import io

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt  # noqa: E402
import pandas as pd  # noqa: E402

CANDLES_SHOWN = 50

# Donkere stijl, aansluitend bij het donkere thema van het dashboard zelf.
BG_COLOR = "#0d1117"
GRID_COLOR = "#21262d"
BORDER_COLOR = "#30363d"
TEXT_COLOR = "#8b949e"
LINE_COLOR = "#4f8cff"
STOP_COLOR = "#e5484d"
TARGET_COLOR = "#30a46c"


def render_signal_chart(df: pd.DataFrame, direction: str, stop_loss: float, take_profit: float) -> bytes:
    """df: OHLCV DataFrame zoals exchange.fetch_ohlcv teruggeeft. Tekent de
    laatste CANDLES_SHOWN sluitkoersen als lijn, met stop loss (rood,
    gestippeld) en take profit (groen, gestippeld) als horizontale lijnen.
    Geeft PNG-bytes terug, klaar om als foto te versturen."""
    recent = df.tail(CANDLES_SHOWN)

    fig, ax = plt.subplots(figsize=(6, 3.2), dpi=150)
    fig.patch.set_facecolor(BG_COLOR)
    ax.set_facecolor(BG_COLOR)

    ax.plot(recent["timestamp"], recent["close"], color=LINE_COLOR, linewidth=1.6)
    ax.axhline(stop_loss, color=STOP_COLOR, linestyle="--", linewidth=1.2,
               label=f"Stop loss {stop_loss:.4f}")
    ax.axhline(take_profit, color=TARGET_COLOR, linestyle="--", linewidth=1.2,
               label=f"Take profit {take_profit:.4f}")

    ax.legend(loc="upper left", fontsize=8, frameon=False, labelcolor=TEXT_COLOR)
    ax.tick_params(colors=TEXT_COLOR, labelsize=7)
    ax.grid(color=GRID_COLOR, linewidth=0.5)
    for spine in ax.spines.values():
        spine.set_color(BORDER_COLOR)
    fig.tight_layout()

    buf = io.BytesIO()
    fig.savefig(buf, format="png", facecolor=fig.get_facecolor())
    plt.close(fig)
    buf.seek(0)
    return buf.getvalue()
