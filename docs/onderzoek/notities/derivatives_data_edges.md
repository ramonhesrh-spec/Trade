# Derivatives-data edges for swing trading (funding, basis/carry, OI, liquidations, positioning, options)

Scope note: research budget was ~12 tool calls. WebFetch could not reach arxiv.org or developers.binance.com (DNS failure), so many findings rest on search-result summaries of primary sources, not full-text reads. Where I found no rigorous evidence I say so. Nothing below is a verified backtest result of ours.

## Funding rate: contrarian signal, carry, regime

### Takeaway
Funding is best supported as a carry/premium (cash-and-carry) and as a pricing-anchor variable, not as a proven directional timing signal. The one rigorous carry paper shows very large but time-varying and risky carry, and a 2025 paper reports the carry strategy compressed sharply from 2024 and turned negative in 2025. I found no rigorous peer-reviewed test that extreme positive funding predicts lower swing returns; contrarian claims come from blogs.

### Cited Findings
- BIS WP 1087 "Crypto carry" (Schmeling, Schrimpf, Todorov; first published April 2023, revised October 2025): the futures basis for BTC/ETH can be very large (abstract says up to 60% p.a.; a RePEc record says above 40%, versions differ). Authors attribute it to demand from smaller trend-chasing leveraged investors plus limited arbitrage capital because of regulatory and margin frictions; the trade is risky due to margin spikes and liquidations in drawdowns; observable fundamentals do not explain its size/volatility. Also in the sample perpetuals are >98% of BTC futures volume. — [BIS WP 1087](https://bis.org/publ/work1087.htm); [VoxEU/CEPR column](https://cepr.org/voxeu/columns/crypto-carry-market-segmentation-and-price-distortions-digital-asset-markets)
- A 2025 arXiv asset-class paper reports carry profitability compressed sharply since 2024: full-sample annualised Sharpe 6.45, 4.06 from 2024, negative in 2025. (Second-hand via search summary; full text not read.) — [arXiv 2510.14435](https://arxiv.org/pdf/2510.14435)
- He, Manela, Ross, von Wachter "Fundamentals of Perpetual Futures": perp deviations from no-arbitrage prices are much larger than in FX, comove across coins and diminish over time as markets mature; a simple arbitrage strategy gives large Sharpe even at highest Binance fees (sample ends before the 2024-26 compression). — [arXiv 2212.06888](https://arxiv.org/html/2212.06888v5)
- Ackerer, Hugonnier, Jermann "Perpetual Futures Pricing" (NBER w32936; Mathematical Finance 36(3)): theory; perp price = risk-neutral expectation of spot at a random time, funding anchors perp to spot. Pricing theory, not a return-predictability test. — [arXiv 2310.11771](https://arxiv.org/pdf/2310.11771); [NBER](https://www.nber.org/papers/w32936)
- BitMEX study: funding rates are heteroskedastic, Granger-linked to inverse-perp prices, and forecastable with GARCH (predicting funding itself, not returns). Another thesis finds funding predictability varies over time and across exchanges. — [arXiv 1912.03270](https://www.arxiv.org/abs/1912.03270); [York thesis](https://yorkspace.library.yorku.ca/items/21b012fb-41e8-4da7-9fc3-0daaecdd39ff)
- Practitioner claim (unverified): funding jumping above 0.05% in 24h preceded 5-10% drawdowns. Treat as blog heuristic. — [search result summary of practitioner pieces, e.g. Amberdata/axeladlerjr](https://axeladlerjr.com/bitcoin-open-interest-funding-rate/); practitioners also note funding alone has a high false-signal rate in trends.
- Oct 10, 2025: funding had been elevated for weeks before the ~$19B (CoinShares figure) liquidation wave; this is an anecdote of one event, not a test. — [Whale Alert](https://whale-alert.io/stories/b18701fb9e3a7e/Weeks-of-rising-leverage-falling-exchange-supply-preceded-Oct-10-2025-19B-Bitcoin-long-liquidation-early-warning-signs-to-watch); [CoinShares](https://coinshares.com/insights/knowledge/billions-in-liquidations-what-happened/)

### Inferences
- Carry/delta-neutral is not a swing-trade edge for a manual directional retail trader: it needs spot + short perp capital on two venues, ties up margin and carries liquidation/exchange risk; with compression to near zero/negative in 2025 I would not rely on it. I did not find a sourced "realistic net APR after fees" for 2026; do not quote one.
- Test of contrarian funding with our fields: per coin, funding_rate (8h, aligned by funding timestamp; use only values published at or before the signal bar close) -> z-score within a rolling window (e.g. 90d) -> forward 8h/24h/72h return from OHLCV, long/short at extremes, net of 0.04-0.06% per side plus funding paid. Use non-overlapping bars or block bootstrap by week, 7 coins pooled with coin fixed effects, and a placebo (random entries with same exit). Funding history on Binance is long (since 2019 for BTC) so this is testable with decent sample; expect a regime split (pre/post 2024).
- Funding as a regime flag (crowded-long vs crowded-short) is more defensible as a filter on existing strategies than as a standalone entry; test as a conditioning variable on the lab's existing rules.

### Gaps
- No rigorous out-of-sample paper found that funding extremes predict 1h-multi-day returns, nor per-coin effect sizes.
- No sourced 2026 net carry APR; Kraken-specific funding/carry not covered.

## Open interest: price/OI quadrants, divergences, flushes

### Takeaway
No academic evidence found that OI changes predict returns; the only peer-reviewed item found concerns volatility. Quadrant readings (price up/OI up = new longs) are practitioner interpretation. Flush-as-bottom is untested in anything I could find.

### Cited Findings
- Zhang, Ma, Arkorful, Peng (2023, Int. Review of Financial Analysis 86): in the long run unexpected changes in BTC futures OI are negatively associated with spot volatility while unexpected futures volume is positively associated; focus is volatility, not direction. — [IDEAS](https://ideas.repec.org/a/eee/finana/v86y2023ics1057521923000133.html)
- Practitioners: rising OI with rising price signals leverage-driven rallies prone to reversal; falling OI in price drops means position closing rather than spot selling. Not peer reviewed. — [MEXC/CryptoQuant summary](https://www.mexc.com/news/238004)
- Glassnode reportedly says 30-day OI changes became more volatile since the Jan 2024 spot ETF launch (structural break warning). — [Cointelegraph](https://cointelegraph.com/markets/bitcoin-leverage-use-sends-oi-to-96b-but-there-s-a-catch)
- OI figures for the same Oct 10, 2025 event conflict across sources (Amberdata: BTC OI 54.7B -> 31.9B, -42%; CoinShares citing Amberdata: all-crypto OI 175B -> 125B), likely scope differences. Illustrates how aggregate-OI numbers differ by definition. — [Amberdata](https://blog.amberdata.io/leverage-liquidations-the-31b-deleveraging); [CoinShares](https://coinshares.com/insights/knowledge/billions-in-liquidations-what-happened/)
- A blog proposes entering after OI drops >30% within 7 days; unvalidated. — [Axel Adler Jr.](https://axeladlerjr.com/bitcoin-liquidation-cascades-guide/)

### Inferences
- Test with our fields: OI (hourly) delta over k hours (1/4/24h) as % of OI, joined with return over the same window into a 2x2 (or tercile) grid; forward return at +1h/+4h/+24h; flush = OI drop beyond a pre-registered percentile (e.g. bottom 1-2% of 24h changes per coin) AND price drop; compare with price-drop-only controls (the key control: does OI add information beyond the price move itself?). Because flushes are rare, expect tiny n per coin; pool coins and report cluster-robust (by event day) stats. Pre-register thresholds; don't tune.
- OI in USD vs coins: price moves change USD OI mechanically; use coin-denominated OI (Binance gives both) to avoid spurious "OI up with price up".

### Gaps
- Free Binance OI history is limited (see positioning section), so only about a month of fine-grained data; the lab's own hourly cache accumulates its own history.
- No sourced study on what OI flushes predict at 1h-1d.

## Liquidations: cascades, clusters, forward returns

### Takeaway
Liquidations are real and large and cascades are well documented descriptively, but I found no rigorous forward-return study. "Heatmap magnets" and "flush = bottom" are blog-level claims. Data is also incomplete by construction.

### Cited Findings
- arXiv 2102.04591 (Bitcoin futures liquidation/leverage/margin): average daily long and short liquidations about 3.51% and 1.89% of OI; liquidated traders averaged ~58x leverage or higher in its sample. Its main findings were not read. — [arXiv 2102.04591](https://arxiv.org/pdf/2102.04591)
- Oct 10, 2025: Amberdata reports about $2.3B liquidated in one day with 86% longs (BTC-focused view) while CoinShares reports a ~$19B wave and says true total could exceed $50B; BTC fell from ~122.6k to ~104.8k. Source disagreement on totals. — [Amberdata](https://blog.amberdata.io/leverage-liquidations-the-31b-deleveraging); [CoinShares](https://coinshares.com/insights/knowledge/billions-in-liquidations-what-happened/)
- BIS crypto carry paper links margin spikes and liquidations in drawdowns to the arbitrage limits. — [BIS WP 1087](https://bis.org/publ/work1087.htm)

### Inferences
- Binance's force-order stream (from memory, not verified here) pushes only the latest liquidation per symbol per second, so snapshots undercount; the lab's "liquidation snapshots" should be treated as a lower bound. Verify against current Binance docs before relying on it.
- Test: define spike as liquidation notional above the coin's rolling 99th percentile, split long/short-liquidation spikes, measure forward 1h/4h/24h returns vs. random times with equal prior-return conditions. Decay: report returns per horizon to show whether any bounce vanishes inside costs (0.08-0.12% round trip plus spread/slippage in a cascade, which is the hardest time to get a fill).
- Entering during a cascade has awful execution; any apparent edge in bar data likely shrinks.

### Gaps
- No peer-reviewed study of forward returns after liquidation spikes found; no evidence for liquidation clusters acting as magnets beyond blogs; Coinglass methodology not examined.

## Positioning: top-trader vs global L/S, taker ratio, data limits

### Takeaway
No rigorous evidence found for any of these ratios. The decisive practical point: Binance free history for these endpoints is only the latest 30 days, so you must record it yourself going forward, and any backtest depth comes only from the lab's cache.

### Cited Findings
- Binance docs: Top Trader Long/Short Ratio (Positions) states "only the data of the latest 30 days is available" (page found is the coin-margined version; USDS-M wrapper docs repeat the 30-day window). Positions ratio = net long/short positions of the top 20% of users by margin balance. — [Binance docs (coin-M)](https://developers.binance.com/docs/derivatives/coin-margined-futures/market-data/Top-Trader-Long-Short-Ratio); [USDS-M wrapper docs](https://binance-futures.hexdocs.pm/BinanceFutures.USDM.MarketData-function-top_long_short_account_ratio.html)
- Third-party adapter notes: openInterestHist serves a rolling 30-day window, errors (-1130) when startTime is at/beyond the boundary; periods 5m through 1d. — [Apify aggregator listing](https://apify.com/gochujang/long-short-oi-aggregator) and [binance-public-data issue](https://github.com/binance/binance-public-data/issues/211)
- Binance public daily metrics files include taker long/short volume ratio, OI and top-trader ratios (may provide longer history than the REST API; coverage start date not verified). — [binance-public-data issue 211](https://github.com/binance/binance-public-data/issues/211)

### Inferences
- Test with our fields: z-score each of global L/S, top-trader L/S (account vs position), and taker buy/sell ratio per coin; forward returns at 1h/4h/24h; test both signs (trend vs contrarian) and the spread (top minus global = "smart vs retail"). Look-ahead guard: these stats are stamped at period end/close; use value for period ending at t only for entries at t+. Since history is ~30 days from the API, only the lab's accumulated cache is usable; with short samples (<1 year) no result should be called an edge until it replicates on newer data (forward-only validation).
- Survivorship: ratios are defined on Binance accounts only; the user trades Kraken/Binance-style perps, so cross-venue transfer is unproven.

### Gaps
- Could not read the official USDS-M page or exact max `limit`; verify.
- No source on actual 2026 history limits beyond the 30-day statements; no whale-position evidence found.

## Options: GEX, max pain, IV/RV, skew (BTC/ETH only)

### Takeaway
Only practitioner evidence found. Crypto GEX relies on inferred dealer positioning, which is a known weakness; pinning claims are commentary. Relevant only to BTC and ETH among our 7 base coins (others lack liquid options).

### Cited Findings
- Glassnode: standard equity-style GEX is problematic for crypto because dealer positioning is hard to infer; it proposes a taker-flow-based GEX. — [Glassnode](https://insights.glassnode.com/gamma-exposure)
- Amberdata says its Deribit gamma uses actual dealer positions rather than the inferred convention. — [Amberdata](https://amberdataderivatives.substack.com/p/fresh-feature-deribit-gamma-profiles)
- WisdomTree: its net gamma is a strike-level proxy from public OI and IV, not observed dealer inventory. — [WisdomTree](https://www.wisdomtree.com/de/insights/blog/whats-hot-bitcoin-is-priced-in-leverage)
- Deribit executive (Blockworks): expiry impact matters mainly when OI is concentrated near spot; otherwise minor. Press notes large 2025 expiries did not derail spot. — [Blockworks](https://blockworks.com/news/deribit-bitcoin-options-volatility-impact); [Forklog](https://forklog.com/en/experts-predict-volatility-following-10-1-billion-bitcoin-options-expiry/)

### Inferences
- Not testable with the lab's current fields (no options data). Deribit public API offers option chain snapshots and DVOL (not verified here); history would need to be recorded or fetched. Reasonable test: DVOL minus trailing realized vol as a vol-regime filter for position sizing/stop width (not direction), BTC/ETH only. Max pain and GEX: low priority given inferred inputs and no academic support.

### Gaps
- No peer-reviewed test of pinning, GEX or skew predictability in crypto found; Deribit API history limits not checked.

## Basis, term structure, perp premium; cross-exchange

### Takeaway
Basis was a rich carry in 2024 and compressed to near zero (even negative on CME) in 2025; no study found that basis predicts spot returns. Cross-exchange funding/price dislocations are an institutional/automated game.

### Cited Findings
- Reported annualised BTC basis: 20-25% at 2024 peaks, ~10% by mid-2025 (BIT knowledge hub; dates inconsistent), vs CME premium <0.1% in Mar-Apr 2025 with real yield near zero after costs (Block Media citing CoinDesk ~2%), and a brief about -2.35% in late 2025 with >$4B ETF outflows in Oct-Nov 2025 attributed to basis-trade unwinds (Spark glossary). The sources conflict on mid-2025 level; treat the direction (decline) as supported, levels as unreliable. — [BIT](https://www.bit.com/knowledge-hub/basis-trade); [Block Media](https://www.blockmedia.co.kr/research-english/893046); [Spark](https://www.spark.money/glossary/basis-trade); [Benzinga, Oct 2024: ~9.6%](https://www.benzinga.com/markets/cryptocurrency/24/10/41524936/institutional-bitcoin-investors-have-their-own-trading-strategies-heres-one)
- He et al.: perp mispricings comove across coins and shrink over time. — [arXiv 2212.06888](https://arxiv.org/html/2212.06888v5)

### Inferences
- Perp premium index (mark vs index) is effectively what funding is built on; the lab can test it via funding history rather than needing separate data. Quarterly basis needs dated-futures data (Binance delivery contracts), not in the lab.
- Cross-exchange funding differential trades need accounts, capital on both venues and two-leg execution; I judge them unrealistic for a manual swing trader, consistent with the BIS view that arbitrage capital faces margin frictions. Kraken vs Binance funding comparison could serve only as a sanity check on cost of holding.

### Gaps
- No rigorous 2026 numbers; no cross-exchange differential study found.

## Critical view: blogs vs tests, look-ahead, breaks

### Takeaway
The strongest findings concern pricing (basis/funding anchor) and risk, not directional alpha. Most directional claims are blog heuristics on single events. The data constraints (30-day windows, short histories, definition differences) make credible validation hard.

### Cited Findings
- Same event, divergent numbers across sources (liquidations $2.3B vs $19B vs >$50B; OI drop 42% vs 175B->125B). — [Amberdata](https://blog.amberdata.io/leverage-liquidations-the-31b-deleveraging); [CoinShares](https://coinshares.com/insights/knowledge/billions-in-liquidations-what-happened/)
- Structural breaks: carry Sharpe fell post-2024 (ETF/CME era) per [arXiv 2510.14435](https://arxiv.org/pdf/2510.14435); OI dynamics more volatile after Jan 2024 ETFs per [Cointelegraph](https://cointelegraph.com/markets/bitcoin-leverage-use-sends-oi-to-96b-but-there-s-a-catch).
- Funding predictability varies over time and across exchanges. — [York thesis](https://yorkspace.library.yorku.ca/items/21b012fb-41e8-4da7-9fc3-0daaecdd39ff)

### Inferences
- Test protocol consistent with the project's lab rules: pre-register variants, count tested variants, require positive net R in both halves, week-clustered bootstrap, placebo entries with same exit, 0.04-0.06% per side + funding actually paid on holds. Treat each derivatives signal as a filter on an existing entry before a standalone strategy.
- Look-ahead hygiene: funding is known before settlement (8h stamps; use the rate in force, and note the realized rate settles at the stamp); OI/ratio stats are stamped at period close (use only after close); liquidation stream timestamps are event time; hourly cache joins must shift by one bar.
- Priority ranking for tests with lab fields (my judgment, not sourced): (1) funding z-score as regime filter / contrarian at extremes; (2) OI-delta x price quadrants with a price-only control; (3) taker buy/sell imbalance as short-horizon flow (1-4h); (4) top-vs-global L/S spread; (5) liquidation spikes (data quality caveat); options/basis need new data.

### Gaps
- Did not find SSRN/arXiv studies on OI or liquidation predictability, BIS/IMF notes beyond carry, Kaiko/Laevitas/Block Scholes research, or Hyperliquid/Bybit/OKX history limits. Full texts of the key papers were not read because arxiv.org was unreachable from the fetch tool.
