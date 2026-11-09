# Short-horizon mean reversion, reversal, seasonality, lead-lag and order-flow effects in crypto (minutes to days)

Method caveat for the report writer: sources were found via web search summaries; direct page fetches failed (DNS errors for arxiv.org and quantpedia.com), so figures come from search-result abstracts/snippets, not full-text reading. Claims are marked accordingly. Many requested items (CME gaps, Deribit expiry, funding-time effects, squeeze/NR7, candlestick/H&S, large-cap to small-cap lead-lag, liquidation-cascade buy-the-dip) returned no rigorous peer-reviewed evidence; these are flagged as gaps rather than filled from memory.

## 1. Short-term reversal / overreaction (1h-3d), liquidity-driven reversal, buy-the-dip after liquidations; large vs small caps

### Takeaway
Documented reversals are concentrated in small, illiquid coins and are best read as a liquidity-provision premium; the largest coins show daily/weekly momentum instead. Evidence is mostly daily/weekly, mostly pre-2023, and not net of realistic costs for small coins, so it does not support a retail 1h-30m reversal signal on liquid majors (consistent with the user's lab losses).

### Cited Findings
- Kozlowski, Puleo & Zhou (200 coins, 2015-2019): reversals at daily, weekly and monthly horizons, robust to size/illiquidity controls, strongest in smaller, less liquid coins — [Cryptocurrency return reversals](https://fairfield.elsevierpure.com/en/publications/cryptocurrency-return-reversals/) (as summarized by search tool).
- Zaremba et al. 2021 (IRFA, >3,600 coins): prior-day return predicts next-day return (reversal), attributed to illiquidity; the few largest/most tradeable coins show daily momentum instead — [Up or down? Short-term reversal, momentum, and liquidity effects](https://earsiv.medeniyet.edu.tr/items/23a96c9f-3952-4bdf-aec5-abafb3aaab70).
- Bianchi, Babiak & Dickerson 2022 (J. Banking & Finance): short-term reversal returns proxy liquidity provision, concentrated in pairs with low market activity, linked to adverse selection and inventory risk — [Trading volume and liquidity provision in cryptocurrency markets (Riksbank WP 413)](https://www.riksbank.se/globalassets/media/rapporter/working-papers/2022/no.-413-trading-volume-and-liquidity-provision-in-cryptocurreny-markets.pdf); [RePEc](https://econpapers.repec.org/RePEc:eee:jbfina:v:142:y:2022:i:c:s0378426622001418).
- Ficura 2023 (working paper): weekly reversal only for small/illiquid coins, large liquid coins show weekly momentum; reversal driven mostly by low volume — [FFA WP 5:003](https://wp.ffu.vse.cz/artkey/wps-202301-0003_impact-of-size-and-volume-on-cryptocurrency-momentum-and-reversal.php).
- A 2026 review (via search summary) reports at hourly frequency no model beats a random walk, while one 1-4h study found significant negative first-order autocorrelation (mean reversion) — [arXiv 2606.00071](https://arxiv.org/pdf/2606.00071). Not verified at full text; effect size not obtained.
- Liquidation cascades: Oct 2025 cascade on Hyperliquid had intraday disruption, spreads widened sharply at peak, recovery well underway by day end — [J. Financial Data Analytics](https://journals.lincoln.ac.nz/index.php/JFDA/article/view/1395). A preprint of seven major perp cascades 2022-2025 found the Oct 2025 event subcritical (branching ratio ~0.1-0.2) — [IDEAS arXiv 2608.03616](https://ideas.repec.org/p/arx/papers/2608.03616.html). Bank of Canada documents temporary price impact from on-chain (Ethereum) collateral liquidations — [swp2025-12](https://bankofcanada.ca/wp-content/uploads/2025/03/swp2025-12.pdf).
- Practitioner claim that wicks reverse once forced sellers are exhausted is commentary, not a test — [CoinShares](https://coinshares.com/se/insights/knowledge/billions-in-liquidations-what-happened).
- A preprint on seven BTC crashes found no price/leverage/order-flow metric warned consistently before every cascade — [CryptoSlate summary](https://cryptoslate.com/new-bitcoin-study-shows-the-strongest-recurring-liquidation-warning-signs-cannot-warn-of-an-individual-crash/) (secondary).

### Inferences
- If reversal profit is compensation for liquidity provision in illiquid names, it accrues to passive limit-order makers with inventory tolerance, not to a manual taker entering at market after the move; costs for small coins (wide spreads) likely eat much of it. This is consistent with, but not proof of, the user's -0.06R to -0.12R lab results on liquid pairs.
- "Dip after liquidation" is a tail-event, few-sample setup (handful of events), unsuitable for a statistically validated rule; the reversion within hours is documented only descriptively.

### Gaps
- No net-of-cost effect sizes (bps per trade) found for 1h-3d reversal; no post-2023 replication found; no study quantifying forward returns after liquidation spikes (e.g., >$X liquidated) across many events.
- Sample periods mostly 2014-2022, many bull-heavy; not checked per paper.

## 2. Intraday and weekly seasonality (hour, weekday, weekend, funding, sessions, month-end, CME gaps, Deribit expiry)

### Takeaway
Calendar effects in BTC are time-varying and unstable; the best documented hourly pattern (late-UTC hours positive, 03-04 UTC weak) comes from older Gemini data and may have faded post-ETF. CME gaps and Deribit expiry/max-pain have only media claims, no rigorous test found. Funding-time price effects: no empirical study found.

### Cited Findings
- Baur, Cahill, Godfrey & Liu (>15M obs, 7 exchanges): time-varying intraday/calendar effects, no stable pattern, BTC markets efficient; activity higher when US exchanges open, lower midnight to early morning; lower weekend volume, higher Monday returns — [Quantpedia summary](https://quantpedia.com/Blog/Details/are-there-any-simple-calendar-effects-in-bitcoin-market) (secondary).
- Liu (Oct 2015-Nov 2021): significant anomalies for Fridays and specific intraday periods but not pervasive enough to imply inefficiency — same Quantpedia search results; [UWA record](https://research-repository.uwa.edu.au/en/publications/bitcoin-time-of-day-day-of-week-and-month-of-year-effects-in-retu/) is a related paper (details not verified).
- Padysak & Vojtko (hourly Gemini data): 22:00 and 23:00 UTC most significant, 03:00-04:00 UTC worst; reported rule "long 21:00-23:00 UTC" ~33% annualized, vol 20.93%, max drawdown -22.45%; write-ups disagree on entry hour (21:00 vs 22:00) — [Quantpedia](https://quantpedia.com/how-to-profitably-trade-bitcoins-overnight-sessions/). A Nov 2024 Quantpedia update suggests ETFs may push BTC toward traditional-hours behaviour, so older seasonality may not hold — same source. Costs not reported in snippet.
- A 2026 Finance Research Letters study (12 coins, hourly), via Securities.io only: positive Monday effect daily, but hour-level analysis suggests day-of-week effects come from a few short periods — [Securities.io](https://securities.io/crypto-day-of-the-week-effects-intraday-patterns/) (secondary, paper not accessed).
- Kim & Hansen 2026 (arXiv, working paper, Binance USDT perps BTC/ETH/XRP/SOL/DOGE/ADA, Jan 2021-Oct 2024): volatility/volume bursts at 1-, 5- and quarter-hour marks tied to algorithmic trading; opening returns predictable out of sample; opening order imbalance predicts returns over ~4-12 hours — [arXiv 2607.09426](https://arxiv.org/pdf/2607.09426); [IDEAS](https://ideas.repec.org/p/arx/papers/2607.09426.html). Not peer reviewed; effect size and costs not obtained.
- Bitcoin intraday momentum (first half-hour predicts last half-hour with volume clock) attributed to liquidity provision — [Birmingham record](https://research.birmingham.ac.uk/en/publications/bitcoin-intraday-time-series-momentum/) (abstract-level).
- CME gaps: "95% fill" and CoinDesk "all but one of 80" are media/TradingView claims with no named study; Feb 2026 ~$6,375 gap not filled during drop to ~$60k — [CryptoSlate](https://cryptoslate.com/do-cme-gaps-always-have-to-fill-bitcoins-60k-flush-says-no/). Fill-eventually is not a timing signal (no horizon/adverse excursion given).
- Deribit expiry: only news coverage; Decrypt states big expiries do not automatically move BTC; max-pain levels quoted by executives varied widely, hit rate unreported — [Decrypt](https://decrypt.co/376752); [CoinDesk](https://www.coindesk.com/bitcoin-options-market-expiry-may).
- Funding: Binance funding settles every 8h, interest component 0.01% per 8h, premium sampled with linearly rising weights toward settlement; only positions open at settlement pay/receive — [Fundamentals of Perpetual Futures](https://arxiv.org/pdf/2212.06888). No return-around-funding study found.

### Inferences
- Hour-of-day edges, if any, are a few bps per hour; with 0.06% round-trip cost a 2h hold needs roughly >6 bps average gross edge just to break even, and the effect is not shown to survive cost or post-2022 regimes. Treat as unproven.
- Quarter-hour effect is a scheduling insight (avoid entering on the minute mark, spreads/volatility burst) more than a signal; its 4-12h imbalance result is the one claimed horizon plausibly manual-usable, but needs replication.

### Gaps
- No post-2022 verified weekend/hour study with costs; no month/quarter-end flow study found; no US/EU/Asia session study with effect sizes; no rigorous CME gap or Deribit expiry study; no funding-time return study.

## 3. Lead-lag (BTC/ETH to altcoins, large to small caps)

### Takeaway
BTC lead over other venues/coins exists but at seconds scale; no source found showing a lead usable at minute-to-hour horizons by a manual trader, nor a large-cap to small-cap hourly predictability test.

### Cited Findings
- BTC leads Cardano by 16-118 seconds (avg ~57s), tick data Jan 2019-May 2021 — [Investment Management and Financial Innovations](https://businessperspectives.org/journals/investment-management-and-financial-innovations/issue-421/a-tick-by-tick-level-measurement-of-the-lead-lag-duration-between-cryptocurrencies-the-case-of-bitcoin-versus-cardano).
- Cross-exchange BTC price lags up to 15 seconds (2018 tick data, master's thesis, weak source) — [CBS thesis](https://research-api.cbs.dk/ws/portalfiles/portal/59795067/612646_High_Frequency_Lead_Lag_Relationships_in_The_Bitcoin_Market.pdf).
- Intraday study: BTC contains information that nonlinearly forecasts other digital currencies; dominance survives intraday data — [NJIT record](https://researchwith.njit.edu/en/publications/does-bitcoin-still-own-the-dominant-power-an-intraday-analysis/) (abstract-level).
- Tokyo Tech work tests BTC-to-altcoin delay (CCF, Granger, VAR) focused on small caps; lag figures and results not seen — [repository](https://t2r2.star.titech.ac.jp/rrws/file/CTT100941776/ATD100000413/).

### Inferences
- Lags of tens of seconds are HFT/API-automation territory; Telegram alert latency plus manual order entry exceeds the lead. No evidence of a half-life at 1m-1h.
- BTC trend filters for alt signals (as in the user's system) are a regime/risk control, not a demonstrated lead-lag edge.

### Gaps
- No half-life estimates; no post-2022 or multi-altcoin hourly study; no verified large-cap to small-cap predictive result.

## 4. Order flow imbalance, taker ratio, book imbalance

### Takeaway
OFI/book imbalance predictive power is documented at sub-second to few-minute horizons and is not manually tradeable; the only longer-horizon claim (4-12h opening imbalance) is a single 2026 working paper.

### Cited Findings
- Binance Futures 1-second data: stable cross-asset OFI/top-of-book patterns for very short-horizon prediction (Jan 2026) — [arXiv 2602.00776](https://arxiv.org/pdf/2602.00776).
- Crypto LOB deep learning: persistence of imbalance across top levels; predictability depends on horizon — [arXiv 2010.01241](https://arxiv.org/pdf/2010.01241).
- Search-aggregator claims OFI power peaks at 1-2 minutes (Hu et al. 2025) and decays out of sample beyond 1 day (Lu et al. 2022): not crypto-specific, unverified — [Emergent Mind](https://www.emergentmind.com/articles/order-flow-imbalance-prediction).
- 4-12h opening order imbalance predicts returns — [arXiv 2607.09426](https://arxiv.org/pdf/2607.09426).

### Inferences
- Taker buy/sell ratio on 15m+ candles is a slower proxy of the same thing; no source tested it net of costs. Treat any such factor as untested.

### Gaps
- No Binance taker-ratio test at 1h-1d; no cost-adjusted OFI results.

## 5. Volatility effects (clustering, compression breakouts, VRP)

### Takeaway
No rigorous test of Bollinger squeeze / NR7 / "compression leads to continuation" in crypto was found; the only results were educational posts and one unvalidated backtest. Volatility clustering itself is well established generally but I found no crypto source in this session.

### Cited Findings
- Squeeze material found is practitioner content; a QuantConnect run shows 632% CAGR with 79% drawdown and no out-of-sample validation — [QuantConnect](https://www.quantconnect.com/terminal/cache/embedded_backtest_6535e797e18edcd11cc628937532ebff.html). Not evidence.
- Periodicity in crypto volatility and liquidity (intraday clock effects) — [arXiv 2109.12142](https://arxiv.org/pdf/2109.12142) (title seen only).

### Inferences
- Compression predicts a larger subsequent move in magnitude (volatility clustering logic) but not its direction; a stop-and-reverse structure with costs would be needed. Unsupported by sources here.

### Gaps
- No peer-reviewed squeeze/NR7 test, no VRP (DVOL vs realized) horizon study located.

## 6. Technical-analysis pattern evidence after data-snooping correction

### Takeaway
Only rule-universe studies (MA, filter, channel breakout) exist; they show profits that decay and fail out of sample for BTC. No source tested head-and-shoulders or candlestick patterns in crypto with snooping correction.

### Cited Findings
- Hudson & Urquhart 2019 (Annals of OR): ~15,000 rules on BTC and other coins; multiple-hypothesis procedures confirm predictive power and breakeven costs above typical crypto costs, but no BTC predictability out of sample (other coins still had) — [Springer](https://link.springer.com/article/10.1007/s10479-019-03357-1).
- Bakker (Erasmus thesis): 3,312 intraday rules on 5m BTC/USD 2013-2017; profitable after snooping and costs but unstable and declining — [thesis](https://thesis.eur.nl/pub/41546/Bakker.pdf) (thesis, weaker).
- Li et al. 2023 (J. Accounting & Finance): 4 strategies on BTC/USDT, ETH/USDT 2022-2023, no profitable strategies even after snooping adjustment, in-sample and prediction periods — [JAF](https://articlegateway.com/index.php/JAF/article/view/6453).
- FX support/resistance range-break profits survive costs (not crypto) — [FMG DP](https://www.fmg.ac.uk/publications/discussion-papers/when-supportresistance-levels-are-broken-can-profits-be-made).

### Inferences
- Pre-2020 positive results are bull/young-market artefacts that decayed; the 2022-23 null aligns with the user's rejection (-0.09R over 2175) and sweep (-0.06 to -0.11R) results.

### Gaps
- No peer-reviewed double top/bottom, H&S, candlestick crypto test found; Hudson/Urquhart bull-market share of sample not checked.

## 7. Costs, stop size, and market-maker-only edges

### Takeaway
At 0.06% round trip, cost in R is 0.06%/stop%. This is arithmetic, not from a source. Costs dominate below ~0.5% stops.

### Cited Findings
- Hudson & Urquhart report breakeven costs well above typical crypto costs for their rule universe — [Springer](https://link.springer.com/article/10.1007/s10479-019-03357-1) (but unstable out of sample).
- Reversal returns concentrate where liquidity is thin and attributed to adverse selection/inventory risk — [Riksbank WP 413](https://www.riksbank.se/globalassets/media/rapporter/working-papers/2022/no.-413-trading-volume-and-liquidity-provision-in-cryptocurreny-markets.pdf).
- Cascades widen spreads sharply at peak, so stop fills slip most exactly when reversal setups trigger — [JFDA](https://journals.lincoln.ac.nz/index.php/JFDA/article/view/1395).

### Inferences
- Cost drag in R (own computation, 0.06% round trip): stop 0.4% = 0.15R; 0.6% = 0.10R; 1% = 0.06R; 2% = 0.03R; 3% = 0.02R. The user's 5m/15m figure (~0.09R at 0.7-1.3% stops) is consistent with the low end of that range plus slippage. Adding 0.02-0.05% stop slippage roughly adds 0.03-0.1R at 0.5-1% stops.
- Break-even requires gross expectancy above cost: with a 1:2 setup, win rate needs to rise about cost/(R-units) above the 33% breakeven (e.g. +2 points at 1% stop, +5 points at 0.4%). Practical guidance: stops >=1.5% (1h-4h holds) to keep cost <=0.04R; below 0.5% only market makers with maker rebates plausibly retain an edge.
- Edges documented at seconds-to-minutes (lead-lag, OFI, quarter-hour effects) are market-maker/HFT territory; manually executed signals face alert latency larger than the effect half-life.

### Gaps
- No empirical Binance slippage-on-stop distribution found; user's own fills data would be the right source.
