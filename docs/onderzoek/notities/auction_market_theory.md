# Auction Market Theory / Volume Profile / Value Area: empirical evidence

Scope note: about 11 searches and 1 failed fetch (nexusfi.com did not resolve, so NexusFi figures come from search-result summaries only). Headline result: no peer-reviewed or SSRN/arXiv study of value-area, 80%-rule or volume-profile trading rules was found, in any market. Everything below on those rules is practitioner or vendor material. Adjacent academic work (support/resistance, intraday reversals, crypto technical analysis, wash trading, backtest overfitting) is cited for context.

## Do VAH/VAL/POC, 80% rule, acceptance/rejection and balance/imbalance rules have a measurable edge after costs (crypto, ES/NQ, FX, equities)?

### Takeaway
No rigorous evidence found. No peer-reviewed paper or credible reproducible backtest with costs, out-of-sample testing and sample sizes was found for Market Profile rules in any market. The adjacent academic literature (intraday reversals, technical rules in crypto) says edges that look real gross shrink or vanish after costs and out-of-sample. This agrees with the user's own lab (-0.06R to -0.12R per trade for sweeps and rejections after 0.06% round-trip costs; phase did not separate results).

### Cited Findings
- Search for SSRN-type papers testing volume-profile strategies returned only TradingView scripts and QuantConnect code snippets, with no academic or out-of-sample results — [TradingView volume profile idea test](https://www.tradingview.com/chart/ES1!/2Aiijm0n-volume-profile-trading-idea-test-spx); [QuantConnect backtest page](https://quantconnect.com/terminal/cache/embedded_backtest_c92486fcf1f50bcb2a54fb878c673464.html)
- A TradingView "Volume Profile VPOC/VAH/VAL" strategy script claims a "vast majority of green" over 26,000 trades at 1:1 RR on 5m with default inputs. This is an unverified, in-sample vendor claim, labelled by its author as for testing and education; treat as marketing — [VERY GREEN strategy](https://it.tradingview.com/script/Rzyqmul1-Volume-Profile-VPOC-VAH-VAL-VERY-GREEN-STRATEGY)
- Bitcoin POC "mean reversion": only TradingView chart commentary and indicator descriptions. No published test of POC reversion for BTC found. One author notes the BTC POC differed by venue (about 8,300 on Bitstamp vs about 6,250 on another feed in 2020), which shows that profile levels are data-source dependent — [TradingView BLX idea](https://it.tradingview.com/chart/BLX/fYAFsDj8-BTCUSD-Volume-Profile-Accumulation-Zone-5-910-8-630)
- Hudson & Urquhart (2019, Annals of Operations Research), about 15,000 technical rules on crypto: breakeven costs were well above typical crypto costs, but no predictability for Bitcoin out-of-sample, although other coins retained some. These are generic rules (MA, filters, etc.), not value-area rules — [Springer](https://link.springer.com/article/10.1007/s10479-019-03357-1)
- Bakker thesis (Erasmus, BTC 5-minute data 2013-2017, thesis not peer-reviewed): some rules significant even after data-snooping and cost adjustment, but profitability unstable and declining over time — [Erasmus thesis](https://thesis.eur.nl/pub/41546/)
- Bazán-Palomino & Svogun (2023, Int. Review of Financial Analysis): cost-adjusted technical-analysis returns in crypto 2016-2021 are driven only by VIX among the drivers tested, which suggests regime dependence — [UP faculty page](https://faculty.up.edu.pe/en/publications/on-the-drivers-of-technical-analysis-profits-in-cryptocurrency-ma)
- Cross-asset technical analysis thesis (Charles University, 2014-2024) with data-snooping-robust framework including costs: risk-unadjusted outperformance vs buy-and-hold but very insignificant risk-adjusted outperformance (thesis, weak source) — [Charles Univ.](https://dspace.cuni.cz/handle/20.500.11956/193503)

### Inferences
- Because Market Profile rules are discretionary and mostly session-based, they have rarely been formalised, so the lack of papers is absence of testing rather than evidence of failure. It also means the user's own lab is more rigorous than anything public on this topic.
- Generic-rule studies show a pattern (gross edge, then cost, data-snooping and out-of-sample erosion, regime dependence) that is the sensible prior for value-area rules too.

### Gaps
- No Dalton/Steidlmayer-style rule (VA acceptance, POC rejection, balance vs imbalance) was found tested with costs in any market. CME education material was not searched and is educational, not evidence, in any case.
- No Quantpedia, Robot Wealth, Alvarez, Hudson Thames or Kaiko/Glassnode piece on volume profile edge turned up; I did not search those sites individually.

## The 80% rule: measured hit rates, costs, sessions, translation to 24/7 crypto

### Takeaway
The only measured numbers are small practitioner tallies, and they are well below 80%: about 50% under strict criteria on ES in one NexusFi analysis, and 5 of 8 (62%) in a personal four-year tally. The 80% figure is a rule of thumb from Market Profile teaching, not an audited statistic. No cost-adjusted test, and no crypto test, found.

### Cited Findings
- Classic definition: price opens outside the prior session's value area, re-enters, and holds for two consecutive 30-minute periods (TPO brackets) inside; target is the opposite value area edge. Value area is conventionally 70% of volume — [LuxAlgo 80% rule](https://www.luxalgo.com/library/concept/80-percent-rule/); [MarketCalls](https://www.marketcalls.in/market-profile/market-profile-how-to-play-80-percentage-rule.html)
- LuxAlgo describes the 80% figure as a rule-of-thumb label rather than a rigorously audited statistic; measured success rates vary by market and era; modern traders often relax the two-bracket requirement and use "acceptance" instead — [LuxAlgo](https://www.luxalgo.com/library/concept/80-percent-rule/)
- NexusFi analysis (as summarised in search results, page itself not fetched): under strict criteria the setup triggers on only a handful of ES days per year; a downward re-entry case showed 6 of 12 qualifying days reaching the opposite edge (about 50%); loose criteria give more trades with lower reliability. The summary also mentions "67 qualifying days, 12 with second bar fully inside value", which I could not reconcile; treat the numbers as unverified — [NexusFi](https://nexusfi.com/a/concepts/80-percent-rule)
- A personal tally of 5 of 8 days (62%) over four years for a similar setup; anecdotal — [search-result listings for 80% rule discussions, e.g. Elitetrader thread](https://elitetrader.com/et/threads/trading-with-market-profile.9727/post-598444)
- Open-source TradingView "80% Rule Backtest" exists: ETH futures 22-hour session, requires 45 minutes inside value on 15m charts, exits at POC. Replicable in principle, but no verified results were reviewed — [TradingView script](https://it.tradingview.com/script/rsTzArCv-80-Rule-Backtest)
- Dalton-linked filters listed by practitioners (distance from value, VA width, market direction) are the kind of parameters that invite overfitting — [Elitetrader](https://elitetrader.com/et/threads/trading-with-market-profile.9727/post-598444)

### Inferences
- With n of 12 or 8, the 95% interval around 50-60% is roughly 25-85%, so none of these tallies distinguishes between 50% and 80%.
- The rule is defined on RTH sessions with a defined open and prior-day profile. Crypto has no open, no overnight gap and no natural prior-session value area. Any translation (UTC day, 22-hour session as in the TradingView script) is a free parameter, so it is an untested analogue, not the rule.
- Even at 80% hit rate, payoff depends on target distance and stop; a 50% hit rate with the target at the far value edge and a stop beyond the entry edge gives expectancy near zero before costs. (Reasoning, not a sourced result.)

### Gaps
- No large-sample (hundreds of sessions) hit-rate study for ES/NQ, FX, equities or crypto. No cost or slippage-adjusted version found.
- NexusFi page could not be fetched; verify the 6/12 and 67-day numbers before relying on them.

## Acceptance vs rejection: definitions and which has evidence

### Takeaway
Definitions are discretionary (two 30-min brackets in the classic rule; 45 minutes on 15m in one script; "acceptance" loosely elsewhere). No evidence found comparing definitions (closes, time, volume).

### Cited Findings
- Classic acceptance = two consecutive 30-minute periods inside the area; variants relax this to a time or close-count rule — [LuxAlgo](https://www.luxalgo.com/library/concept/80-percent-rule/); [TradingView 80% Rule Backtest](https://it.tradingview.com/script/rsTzArCv-80-Rule-Backtest)
- Nothing found that tests number of closes vs time vs volume as the acceptance criterion.

### Inferences
- A defensible approach is pre-registering one or two definitions and testing both with a multiple-testing correction (see the overfitting item below), rather than tuning.

### Gaps
- No evidence for any definition. Not answerable from sources found.

## Failed breakouts / false breakouts / liquidity sweeps

### Takeaway
Best academic analogue: intraday reversals in US stock index futures are statistically significant gross but their significance falls sharply after a bid-ask transaction-cost proxy. Osler's FX work gives a plausible mechanism (order clustering at levels) but is about 1999-2000 data and not a tradable-after-costs result. No crypto sweep study found.

### Cited Findings
- Grant, Wolf & Yu, 15-year study of US stock index futures (1987-2002): highly significant intraday reversals after large opening moves, but the significance is sharply reduced once gross results are adjusted by a bid-ask proxy for costs; the authors regard consistent profitability as unresolved — [Montclair record](https://researchwith.montclair.edu/en/publications/intraday-price-reversals-in-the-us-stock-index-futures-market-a-1/)
- Osler (FRBNY Staff Report 125; about 9,700 orders at a large FX dealing bank, Sept 1999-Apr 2000, USD/JPY, GBP/USD, EUR/USD): take-profit orders cluster at round numbers and tend to follow trends; stop-loss orders intensify trends. This is offered as an explanation for why published support/resistance levels predict short-term bounces — [FRBNY SR125](https://www.newyorkfed.org/medialibrary/media/research/staff_reports/sr125.html)
- Osler (SR150): trends are unusually rapid when rates reach levels with documented stop-loss clusters ("price cascades"), and rates reverse relatively often at take-profit clusters. Both directions occur, so a level can produce a sweep-and-reverse or a cascade-and-continue — [FRBNY SR150](https://www.newyorkfed.org/medialibrary/media/research/staff_reports/sr150.pdf)
- Osler (2000, FRBNY Economic Policy Review): tested support/resistance levels published by six firms against one-minute quotes (mark, yen, pound); reported that they predicted intraday trend interruptions better than chance (the retrieved snippet was cut off, so check wording) — [EPR PDF](https://resources.newyorkfed.org/medialibrary/media/research/epr/00v06n2/0007osle.pdf)
- A Benzinga crude oil false-breakout backtest (2010-2024, about 3,000 trades, average trade about $33, max drawdown about $29,000); the snippet did not show whether costs were modelled, so low weight — [Benzinga](https://www.benzinga.com/trading-ideas/technicals/25/05/45202553/is-the-false-breakout-strategy-worth-using-on-crude-oil-futures)

### Inferences
- FX evidence is pre-2001 and about bounces, not net P&L after spread. It suggests levels matter mechanically but not that a retail rule on OHLCV nets out positive; the user's -0.06 to -0.12R results are consistent with gross-small, cost-eaten effects.
- Failure mode: the same level can produce either reversal or cascade, so unconditional rules average to near zero; regime (trend vs range, volatility) dependence is plausible and is what the VIX-driven finding above hints at.

### Gaps
- No post-2018 peer-reviewed test of failed breakouts or liquidity sweeps after costs in crypto, ES/NQ or equities.

## Crypto specifics: perps vs spot, fragmented and wash-traded volume, 24/7, sessions

### Takeaway
Volume-based profiles are only as good as the volume. Reported volume on unregulated exchanges was found heavily wash-traded in 2019; perps dominate volume; profile levels differ by venue. No source defines or validates sessions for crypto profiles.

### Cited Findings
- Cong, Li, Tang, Yang, "Crypto Wash Trading" (NBER WP 30783, Dec 2022; data 9 Jul-3 Nov 2019, 29 exchanges): wash trading averaged over 70% of reported volume on unregulated exchanges; regulated exchanges looked like real markets. Working paper; 2019 data, so may not hold now — [NBER PDF](https://www.nber.org/system/files/working_papers/w30783/w30783.pdf); [Kitco summary](https://www.kitco.com/news/article/2022-12-29/wash-trading-rampant-unregulated-crypto-exchanges-nber-study)
- Kaiko (as reported by Bloomberg, May 2023): BTC perpetual volume about six times spot; perps argued to be the bigger driver of price — [Bloomberg](https://www.bloomberg.com/news/articles/2023-05-05/bitcoin-btc-perpetuals-seen-becoming-an-even-bigger-driver-of-prices); [Business Standard](https://www.business-standard.com/markets/cryptocurrency/bitcoin-perpetuals-becoming-an-even-bigger-driver-of-digital-token-s-price-123050501173_1.html)
- Norwegian business school thesis (2021 data): Binance linear perp appears to lead its market; price discovery also substantial on CME futures and Binance swap — [NHH thesis](https://openaccess.nhh.no/nhh-xmlui/handle/11250/2766908)
- A secondary news repost claims a perp/spot volume ratio of 7.87 on Binance on 3 Feb (2026); not verified against a primary source — [MEXC news](https://www.mexc.com/news/660610)
- Profile POC differs by venue (BTC example above).

### Inferences
- For a Binance perp-only system, perp volume on a top exchange is arguably the relevant volume, and wash-trading concerns are smaller for large regulated-like venues than the 70% average suggests, but this was not tested here. Profile built from one venue's perp volume is not equal to market-wide volume.
- Session definition (UTC day vs Asia/EU/US) is an untested design choice; testing several multiplies the number of hypotheses.

### Gaps
- No source on Asia/EU/US session segmentation for crypto volume profiles; no current (2024-2026) wash-trading estimate for Binance perps found.

## Why such rules look good: selection bias, small samples, replication

### Takeaway
Chart screenshots are survivorship-biased and hindsight-drawn, and multiple-testing machinery exists to quantify the effect. No replication study of Market Profile rules exists (since there is no original rigorous study to replicate).

### Cited Findings
- Bailey & López de Prado, Deflated Sharpe Ratio (J. Portfolio Management 2014): corrects Sharpe for selection bias from multiple trials and non-normal returns — [SSRN 2460551](https://papers.ssrn.com/abstract=2460551)
- Bailey, Borwein, López de Prado, Zhu, Probability of Backtest Overfitting (J. Computational Finance 2015): standard hold-out is unreliable for backtests; proposes combinatorially symmetric cross-validation — [SSRN 2326253](https://papers.ssrn.com/abstract=2326253)
- The 80% rule: loose criteria produce more trades but lower reliability; strict criteria give very few trades (NexusFi, above), which is the usual tradeoff that makes cherry-picking easy.

### Inferences
- Variants multiply quickly (VA %, session definition, bracket count, entry location, target, filters), so any single positive backtest of this family needs a deflated-Sharpe style haircut. (Formulas not checked against the originals.)

### Gaps
- No documented replication failure specific to Market Profile; only the general overfitting literature.

## Open-source implementations and datasets for replication with 1h/15m OHLCV

### Takeaway
Only TradingView/QuantConnect scripts exist, none validated.

### Cited Findings
- TradingView "80% Rule Backtest" (ETH futures, 22h session, 15m, 45-minute hold, POC exit) — [script](https://it.tradingview.com/script/rsTzArCv-80-Rule-Backtest)
- TradingView "Volume Profile VPOC/VAH/VAL" strategy — [script](https://it.tradingview.com/script/Rzyqmul1-Volume-Profile-VPOC-VAH-VAL-VERY-GREEN-STRATEGY)
- QuantConnect volume profile algorithm (2-hour profile, Nasdaq-100 E-mini) — [example](https://quantconnect.com/terminal/cache/embedded_backtest_c92486fcf1f50bcb2a54fb878c673464.html)

### Inferences
- Replication on 1h/15m OHLCV needs a proxy for volume-at-price (distribute each bar's volume across its range), which blurs the profile; tick or trade data from Binance would be better. This is a design remark, not sourced.

### Gaps
- No academic dataset or GitHub repo with a reproducible, cost-aware value-area study found (GitHub was not searched directly).
