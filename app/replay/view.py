"""Tijdgebonden marktdata voor het meetraam: dezelfde twee methodes als
app.exchange (fetch_ohlcv en fetch_24h_quote_volume), maar zonder vooruit te
kijken. Elke timeframe wordt uit de basis (15m of 1m) opgebouwd uit alleen candles die
op `at` al gesloten waren; de candle die op `at` nog loopt, is gedeeltelijk,
precies zoals de live scan hem ziet."""
import pandas as pd

from app.replay.candles import BASE_DELTA

TIMEFRAME_DELTAS = {
    "1m": pd.Timedelta(minutes=1),
    "5m": pd.Timedelta(minutes=5),
    "15m": pd.Timedelta(minutes=15),
    "30m": pd.Timedelta(minutes=30),
    "1h": pd.Timedelta(hours=1),
    "4h": pd.Timedelta(hours=4),
    "1d": pd.Timedelta(days=1),
}
# "24h" in plaats van "1D": alleen een Tick-achtige frequentie respecteert
# origin="epoch", en zo sluit de daily candle aan op Binance (00:00 UTC).
_RESAMPLE_RULES = {"5m": "5min", "15m": "15min", "30m": "30min", "1h": "1h", "4h": "4h", "1d": "24h"}


class ReplayData:
    def __init__(self, base: dict[str, pd.DataFrame], at: pd.Timestamp, base_delta: pd.Timedelta = BASE_DELTA):
        self._base_delta = base_delta
        self._base = {coin.upper(): df for coin, df in base.items()}
        self.at = at

    def _visible(self, coin: str, rows: int) -> pd.DataFrame:
        df = self._base[coin.upper()]
        end = df["timestamp"].searchsorted(self.at - self._base_delta, side="right")
        return df.iloc[max(0, end - rows):end]

    def fetch_ohlcv(
        self, coin: str, timeframe: str = "4h", limit: int = 200, since: int | None = None,
    ) -> pd.DataFrame:
        ratio = int(TIMEFRAME_DELTAS[timeframe] / self._base_delta)
        visible = self._visible(coin, limit * ratio + ratio)
        if TIMEFRAME_DELTAS[timeframe] == self._base_delta:
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
        # Anders dan op de beurs wordt `since` hier NA tail(limit) toegepast; de
        # sync-kernen gebruiken het niet.
        if since is not None:
            out = out[out["timestamp"] >= pd.Timestamp(since, unit="ms", tz="UTC")]
        return out.reset_index(drop=True)

    def fetch_24h_quote_volume(self, coin: str) -> float:
        visible = self._visible(coin, int(pd.Timedelta(hours=24) / self._base_delta))
        return float((visible["close"] * visible["volume"]).sum())
