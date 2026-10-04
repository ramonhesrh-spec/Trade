"""Tijdgebonden marktdata voor het meetraam: dezelfde twee methodes als
app.exchange (fetch_ohlcv en fetch_24h_quote_volume), maar zonder vooruit te
kijken. Elke timeframe wordt uit de 15m-basis opgebouwd uit alleen candles die
op `at` al gesloten waren; de candle die op `at` nog loopt, is gedeeltelijk,
precies zoals de live scan hem ziet."""
import pandas as pd

from app.replay.candles import BASE_DELTA

TIMEFRAME_DELTAS = {
    "15m": pd.Timedelta(minutes=15),
    "1h": pd.Timedelta(hours=1),
    "4h": pd.Timedelta(hours=4),
    "1d": pd.Timedelta(days=1),
}
# "24h" in plaats van "1D": alleen een Tick-achtige frequentie respecteert
# origin="epoch", en zo sluit de daily candle aan op Binance (00:00 UTC).
_RESAMPLE_RULES = {"1h": "1h", "4h": "4h", "1d": "24h"}
_QUOTE_VOLUME_CANDLES = 96  # 24 uur aan 15m-candles


class ReplayData:
    def __init__(self, base: dict[str, pd.DataFrame], at: pd.Timestamp):
        self._base = {coin.upper(): df for coin, df in base.items()}
        self.at = at

    def _visible(self, coin: str, rows: int) -> pd.DataFrame:
        df = self._base[coin.upper()]
        end = df["timestamp"].searchsorted(self.at - BASE_DELTA, side="right")
        return df.iloc[max(0, end - rows):end]

    def fetch_ohlcv(
        self, coin: str, timeframe: str = "4h", limit: int = 200, since: int | None = None,
    ) -> pd.DataFrame:
        ratio = int(TIMEFRAME_DELTAS[timeframe] / BASE_DELTA)
        visible = self._visible(coin, limit * ratio + ratio)
        if timeframe == "15m":
            out = visible
        else:
            out = (
                visible.set_index("timestamp")
                .resample(_RESAMPLE_RULES[timeframe], origin="epoch", label="left", closed="left")
                .agg({"open": "first", "high": "max", "low": "min", "close": "last", "volume": "sum"})
                .dropna()
                .reset_index()
            )
        out = out.tail(limit)
        if since is not None:
            out = out[out["timestamp"] >= pd.Timestamp(since, unit="ms", tz="UTC")]
        return out.reset_index(drop=True)

    def fetch_24h_quote_volume(self, coin: str) -> float:
        visible = self._visible(coin, _QUOTE_VOLUME_CANDLES)
        return float((visible["close"] * visible["volume"]).sum())
