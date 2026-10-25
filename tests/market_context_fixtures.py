"""Antwoorden van de publieke API's zoals ze binnenkomen (ingekort tot een paar coins, getallen in de vorm van de echte bronnen: strings waar de beurs
strings stuurt). Waarom fixtures en geen netwerk: de sandbox bereikt de beurzen niet, en de parser moet het echte formaat lezen, niet een nagebouwd dict."""

# POST https://api.hyperliquid.xyz/info {"type": "metaAndAssetCtxs"}: [meta, assetCtxs], de lijsten staan in dezelfde volgorde.
HYPERLIQUID = [
    {"universe": [
        {"name": "BTC", "szDecimals": 5, "maxLeverage": 40},
        {"name": "ETH", "szDecimals": 4, "maxLeverage": 25},
        {"name": "kPEPE", "szDecimals": 0, "maxLeverage": 10},
        {"name": "SOL", "szDecimals": 2, "maxLeverage": 20},
    ]},
    [
        {"funding": "0.0000125", "openInterest": "28012.34", "prevDayPx": "66810.0", "dayNtlVlm": "1653728213.5", "premium": "0.0002",
         "oraclePx": "67402.0", "markPx": "67410.0", "midPx": "67408.5", "impactPxs": ["67408.0", "67409.0"]},
        {"funding": "0.00001", "openInterest": "512340.1", "prevDayPx": "2401.2", "dayNtlVlm": "702351234.1", "premium": "0.0001",
         "oraclePx": "2430.1", "markPx": "2430.6", "midPx": "2430.55", "impactPxs": ["2430.5", "2430.7"]},
        {"funding": "0.0000125", "openInterest": "9912345678.0", "prevDayPx": "0.0101", "dayNtlVlm": "1234567.0", "premium": "0.0",
         "oraclePx": "0.0102", "markPx": "0.0102", "midPx": "0.0102", "impactPxs": None},
        {"funding": "-0.0000031", "openInterest": "1234567.0", "prevDayPx": "139.1", "dayNtlVlm": "250000000.0", "premium": "-0.0003",
         "oraclePx": "140.8", "markPx": "140.75", "midPx": "140.76", "impactPxs": ["140.7", "140.8"]},
    ],
]

# GET https://api.bybit.com/v5/market/tickers?category=linear
BYBIT = {
    "retCode": 0, "retMsg": "OK",
    "result": {"category": "linear", "list": [
        {"symbol": "BTCUSDT", "lastPrice": "67405.10", "indexPrice": "67401.22", "markPrice": "67406.00", "openInterest": "55123.12",
         "openInterestValue": "3715000000.12", "fundingRate": "0.0001", "fundingIntervalHour": "8", "nextFundingTime": "1761379200000"},
        {"symbol": "ETHUSDT", "lastPrice": "2430.40", "indexPrice": "2430.10", "markPrice": "2430.45", "openInterest": "1012345.5",
         "openInterestValue": "2460000000.00", "fundingRate": "0.00005", "fundingIntervalHour": "8", "nextFundingTime": "1761379200000"},
        {"symbol": "SOLUSDT", "lastPrice": "140.81", "indexPrice": "140.79", "markPrice": "140.80", "openInterest": "5012345.1",
         "openInterestValue": "705000000.00", "fundingRate": "-0.0001", "fundingIntervalHour": "4", "nextFundingTime": "1761379200000"},
        {"symbol": "BTCPERP", "lastPrice": "67410.0", "markPrice": "67410.0", "fundingRate": "0.0001", "fundingIntervalHour": "8"},
    ]},
    "retExtInfo": {}, "time": 1761370000000,
}

# GET https://www.okx.com/api/v5/public/funding-rate?instId=BTC-USDT-SWAP
OKX_BTC = {
    "code": "0", "msg": "",
    "data": [{"instType": "SWAP", "instId": "BTC-USDT-SWAP", "method": "current_period", "fundingRate": "0.00008",
              "nextFundingRate": "", "fundingTime": "1761379200000", "nextFundingTime": "1761408000000",
              "minFundingRate": "-0.0375", "maxFundingRate": "0.0375", "settState": "settled", "settFundingRate": "0.0001", "ts": "1761370000000"}],
}
OKX_ERROR = {"code": "51001", "msg": "Instrument ID does not exist", "data": []}

# GET https://fapi.binance.com/fapi/v1/premiumIndex (zonder symbool: alle perpetuals)
BINANCE_PREMIUM = [
    {"symbol": "BTCUSDT", "markPrice": "67409.10000000", "indexPrice": "67401.50", "estimatedSettlePrice": "67400.1", "lastFundingRate": "0.00010000",
     "interestRate": "0.00010000", "nextFundingTime": 1761379200000, "time": 1761370000000},
    {"symbol": "ETHUSDT", "markPrice": "2430.50", "indexPrice": "2430.20", "estimatedSettlePrice": "2430.0", "lastFundingRate": "0.00006000",
     "interestRate": "0.00010000", "nextFundingTime": 1761379200000, "time": 1761370000000},
    {"symbol": "SOLUSDT", "markPrice": "140.80", "indexPrice": "140.79", "estimatedSettlePrice": "140.8", "lastFundingRate": "0.00002500",
     "interestRate": "0.00010000", "nextFundingTime": 1761379200000, "time": 1761370000000},
]
# GET https://fapi.binance.com/fapi/v1/fundingInfo: alleen symbolen met een afwijkend interval of andere grenzen staan erin.
BINANCE_FUNDING_INFO = [
    {"symbol": "SOLUSDT", "adjustedFundingRateCap": "0.02", "adjustedFundingRateFloor": "-0.02", "fundingIntervalHours": 4, "disclaimer": False},
]
# GET https://fapi.binance.com/futures/data/openInterestHist?symbol=BTCUSDT&period=1h&limit=25 (oudste eerst)
BINANCE_OI_HIST = [
    {"symbol": "BTCUSDT", "sumOpenInterest": "80000.0", "sumOpenInterestValue": "5000000000.0", "timestamp": 1761283200000 + i * 3600000}
    for i in range(24)
] + [{"symbol": "BTCUSDT", "sumOpenInterest": "82000.0", "sumOpenInterestValue": "5210000000.0", "timestamp": 1761283200000 + 24 * 3600000}]

# GET https://api.alternative.me/fng/?limit=1
FEAR_GREED = {"name": "Fear and Greed Index",
              "data": [{"value": "38", "value_classification": "Fear", "timestamp": "1761350400", "time_until_update": "40000"}],
              "metadata": {"error": None}}

# GET https://stablecoins.llama.fi/stablecoincharts/all (één rij per dag, oudste eerst; totalCirculatingUSD per peg in dollars)
STABLECOINS = [
    {"date": str(1760745600 + d * 86400),
     "totalCirculating": {"peggedUSD": 300e9 + d * 1e9, "peggedEUR": 0.5e9},
     "totalCirculatingUSD": {"peggedUSD": 300e9 + d * 1e9, "peggedEUR": 0.58e9}}
    for d in range(8)
]
