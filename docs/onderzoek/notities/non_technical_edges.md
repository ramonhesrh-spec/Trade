# Non-technical and out-of-the-box edges in crypto for a tiny manual signal service

Method note: research done 2026-10-13 via web search only. WebFetch was down (DNS failures), so every figure below comes from search-result summaries, not from reading full papers. Primary papers were often not opened; where a number is a vendor or blog claim I say so. Nothing here is a backtest on the user's data.

## 1. Event and structural effects (listings, unlocks, ETF, stablecoins, treasuries, hacks): size, timing, decay

### Takeaway
Listing, unlock and hack effects are real but front-loaded (before or at the announcement), short-lived and mostly concentrated in small/mid-cap tokens, not the ~20 large perps. A retail trader on RSS/Telegram is typically late for the listing pop; the multi-day to multi-week effects (pre-unlock drift, post-hack suppression) are more tradable but mostly apply to coins outside a large-cap universe. ETF flows and stablecoin mints are contemporaneous or reverse-causal, not proven leading indicators.

### Cited Findings
- Listings, older benchmark: 2019 event study reports a 7.4% average abnormal return on listing day and 9.2% over a (-3,+3) window; only five exchanges showed significant positive returns over the 7-day window and for six the effect was negative — [Blockchain Research Lab](https://www.blockchainresearchlab.org/de/2019/09/10/market-reaction-to-exchange-listings-of-cryptocurrencies-2/)
- Coinbase vs Binance: an AFT 2025 extended abstract (Li, Luo, Wang, Wei) finds short-run abnormal returns positive on both, larger on Coinbase — [Dagstuhl AFT 2025](https://drops.dagstuhl.de/storage/00lipics/lipics-vol354-aft2025/html/LIPIcs.AFT.2025.11/LIPIcs.AFT.2025.11.html)
- Pre-announcement run-ups consistent with insider trading: a UTS study of 146 Coinbase listings (2018-2022) found significant abnormal returns in 10-25% of tokens, DEX patterns resembling insider run-ups — [OODA Loop summary](https://oodaloop.com/briefs/cyber/study-insider-trading-occurs-in-10-to-25-of-cryptocurrency-listings)
- 2026 industry analysis (The Tie, vendor, not peer reviewed): returns are front-loaded into the pre-announcement window; BTC-adjusted return largely dissipates within about two weeks of trading on the new venue; premium narrower than earlier cycles. Also a separate Tie piece says a Binance listing adds little for tokens already on 3+ major exchanges — [The Tie 2026](https://www.thetie.io/insights/what-does-an-exchange-listing-actually-deliver-in-2026), [The Tie, already-listed tokens](https://www.thetie.io/insights/what-a-binance-listing-delivers-for-already-listed-tokens)
- Conflicting industry numbers: one source cites Binance listings +41% afterward, Animoca Research cites average -49% after CEX listings — [RockawayX](https://rockawayx.com/insights/bullish-or-bearish-what-really-happens-when-tokens-list-on-a-cex). Treat as unreconciled (different samples, windows).
- Upbit/Bithumb: nearly all-retail market; minute-level moves reported (RAY ~$2.07 to $2.78 within minutes of an Upbit June 2025 announcement; PEPE +8.5% in the following minute on Bithumb, per news reports); Upbit restricts buy orders for about 5 minutes after trading starts; 4pillars argues the Upbit listing pump is dying — [4pillars](https://research.4pillars.io/en/data/content/the-dying-upbit-listing-pump), [Blockmedia 2025 KRW listings dataset (59 Upbit, 144 Bithumb)](https://www.blockmedia.co.kr/research-english/1064579), [Benzinga PEPE](https://benzinga.com/content/41996713/pepe-prices-rise-in-south-korea-after-upbit-listing-news)
- Token unlocks (Keyrock, 16,000+ unlocks; seen only via secondary summaries): larger unlocks (5-10% of supply) produce roughly 2.4x more severe drops than small ones; team unlocks worst at about -25% average drawdown; descriptive, not causal — [Keyrock](https://keyrock.com/from-locked-to-liquidity-what-16000-token-unlocks-teach-us/), [Streamflow summary](https://streamflow.finance/blog/token-unlock-report)
- Unlock timing: effects reportedly begin about 30 days before and stabilise within 14 days after; vendor FAQ claims under ~1% of circulating supply has little impact (no underlying study named) — [Streamflow](https://streamflow.finance/blog/do-token-unlocks-cause-price-drops), [Autheo FAQ](https://www.autheo.com/faq/do-token-unlocks-cause-price-drops)
- ETF flows: Mazur & Polyzos (2025) report net flows strongly predict price levels (R2 95%, levels regression, prone to spuriousness) and that most price changes occur outside ETF trading hours; Citi estimate ~4.7% return per $1bn inflow (broker claim); FalconX Granger test p=0.004 (preliminary); Volmex finds mixed results, only IBIT flows related to realized volatility — [Zayed Univ. listing](https://zuscholars.zu.ac.ae/works/7267), [FalconX](https://www.falconx.io/newsroom/what-can-spot-etf-flows-tell-us-about-the-trajectory-of-bitcoin-prices-a-preliminary-statistical-investigation), [Volmex](https://volmex.finance/Cryptocurrency-Market-Dynamics-Following-the-Approval-of-Bitcoin-ETFs.pdf), [Ecoinometrics](https://ecoinometrics.substack.com/p/bitcoin-returns-and-etf-flows-correlation)
- Stablecoins: Wei (2018) VAR/Granger: Tether issuance did not predict Bitcoin returns, only raised volume for a few days; Griffin & Shams link Tether purchases to post-downturn price jumps (manipulation claim); a 565-issuance event study finds positive abnormal returns around issuance; VoxEU argues issuance follows demand (reverse causality) — [Wei 2018](https://ideas.repec.org/a/eee/ecolet/v171y2018icp19-22.html), [BRL WP 11](https://www.blockchainresearchlab.org/wp-content/uploads/2020/05/The_Influence_of_Stablecoin_Issuances_on_Cryptocurrency_Markets_BRL_Working_Paper_No_11.pdf), [VoxEU](https://cepr.org/voxeu/columns/stable-coins-dont-inflate-crypto-markets), [2025 survey](https://arxiv.org/pdf/2507.13883)
- Treasury company purchases: K33 found BTC averages -2.2% on MicroStrategy announcement days, -0.2% over 7 days, but +6.2% during VWAP purchasing periods (single research firm, older sample) — [K33](https://k33.com/research/articles/what-happens-when-michael-saylor-buys-bitcoin)
- Hacks: Immunefi (vendor) 2021-2023, 176 hacks: 79.5% of hacked tokens still negatively impacted after two days; 2024-2025 update: 83.9% in sustained suppression at six months; earlier review of about -13% within 48h and -19.6% at 120h; cannot separate from market beta — [Immunefi 2024-25](https://immunefi.com/blog/research/what-an-onchain-hack-actually-costs-2024-2025-update/), [Crowdfund Insider](https://www.crowdfundinsider.com/?p=229334)
- Pump groups (context for small-cap event hunting): 2018 data, 3,767 Telegram signals; pumping obscure low-volume coins far more profitable than large ones; first 70 seconds +25% average price — [Hamrick et al. summary](https://arxiv.org/pdf/1811.10109), [Finance Magnates](https://www.financemagnates.com/cryptocurrency/news/telegram-is-a-hub-of-crypto-pump-and-dump-schemes-study-shows/)

### Inferences
- Speed classes: Upbit/Bithumb and Coinbase/Binance listing pops are seconds-to-minutes (not capturable via manual alerts, and the main run-up precedes the public announcement). Pre-unlock drift (weeks), post-hack suppression (days to months) and the ETF/treasury regime context are multi-hour to multi-day and compatible with manual execution.
- Most of these effects live in small caps. For a 20-large-perp universe, the realistic uses are: (a) shorting or avoiding coins with a large team/investor unlock (>~2-5% of supply, within 30 days) if any of the 20 have one, (b) a "do not long" veto after a hack/exploit on the coin's ecosystem, (c) BTC-level context only from ETF flows. These are filters, not standalone strategies.
- CME gap fill, protocol hard forks, airdrop/TGE and index-inclusion effects: I found no rigorous evidence in this pass (see Gaps). Absence of evidence is not evidence of absence, but I would not build on them.
- Stablecoin supply is best read as a slow liquidity/regime variable at best; evidence for it as a trading trigger is weak and causality is disputed.

### Gaps
- No peer-reviewed source opened for token unlocks (only vendor summaries of Keyrock); sample years and whether results survive market-beta adjustment unknown.
- CME gap fill: search returned nothing. Airdrop/TGE, index inclusion, hard-fork effects, exchange inflow/outflow, delisting announcements: not searched or not found.
- Effect sizes for large caps specifically (top 20) not isolated in any source found.
- Upbit/Bithumb effect: no academic minute-level study; the "dying" claim comes from a research blog.

## 2. Macro-calendar effects (CPI/FOMC/NFP/PCE/US open)

### Takeaway
Fed decisions demonstrably move bitcoin returns and volatility (Corbet et al.), and equity/FX literature documents a pre-FOMC drift with partial reversal, but I found no crypto-specific, out-of-sample estimate of drift or sell-the-news that is tradable after costs. Treat the macro calendar mainly as a volatility and risk-management tool.

### Cited Findings
- Corbet, McHugh, Meegan (2017), GARCH: Fed rate decisions significantly impact bitcoin returns; volatility effects from QE announcements — [Business Perspectives author page](https://businessperspectives.org/journals/author/shaen-corbet)
- Hourly study of FOMC effect on Bitcoin returns/volatility, Jan 2017-Aug 2023 exists (arXiv 2311.10739) but I could not read its results — [arXiv](https://arxiv.org/pdf/2311.10739)
- KSE thesis "Bitcoin's Reaction to U.S. FOMC and CPI Announcements" exists; findings not accessible — [KSE](https://kse.ua/wp-content/uploads/2026/05/illia-nazaruk_268722_assignsubmission_file_nazaruk_final_thesis.pdf)
- Equity benchmark: Lucca & Moench: large excess equity returns in the 24h before FOMC announcements, >80% of the equity premium over 17 years; no such pattern in bonds or USD — [NBER summary via search](https://www.aeaweb.org/conference/2021/preliminary/paper/QABNN7zD)
- FX: post-announcement returns cancel about 65% of pre-FOMC drift, mostly 12-24h after — [Lee & Wang, via search](https://ideas.repec.org/a/oup/rasset/v15y2025i3-4p247-287..html)
- Anecdotal: lower-than-expected CPI lifted BTC after compressed volatility — [K33 commentary](https://k33.com/research/articles/busy-macro-week)

### Inferences
- The robust, usable fact is vol expansion at release (seconds to a few hours); spreads and slippage widen then, which hurts a 0.06%/side manual trader. A sensible rule is a "no new entries 30 min before to 60 min after tier-1 releases" filter, and test it on the user's own trade log (their lab can measure R by hour).
- A pre-event drift or sell-the-news rule would need to be tested on the user's data; I have no external crypto evidence to cite for it.

### Gaps
- Could not read results of arXiv 2311.10739 or the CPI thesis. No source on NFP/PCE/US-open lead (US100/ES lead) found.

## 3. Seasonality and calendar

### Takeaway
The best academic study finds time-varying but not persistent calendar effects in Bitcoin; blog backtests of hour-of-day rules conflict with this and are likely data-mined.

### Cited Findings
- Baur, Cahill, Godfrey, Liu: 15M+ observations from seven exchanges; time-of-day/day-of-week/month effects exist but are not consistent or persistent; weekend volume effect and Monday return effect; volume higher when US stock exchanges are open, lowest around midnight-early morning — [UWA repository](https://research-repository.uwa.edu.au/en/publications/bitcoin-time-of-day-day-of-week-and-month-of-year-effects-in-retu/)
- Quantpedia blog: worst hours 03:00-04:00 UTC; claims buy 21:00 UTC / sell 23:00 UTC yields 33% annualised; also finds NYSE-open vs closed split in intraday vs overnight returns (blog, sample not clear, gross of costs) — [Quantpedia](https://quantpedia.com/are-there-seasonal-intraday-or-overnight-anomalies-in-bitcoin/)

### Inferences
- A two-hour holding rule costs 0.12% round trip against a claimed ~0.13% per day gross (33%/252 roughly), so cost drag would consume most of it even if it were real. This arithmetic is mine.
- Use sessions for volume/volatility scheduling, not direction.

### Gaps
- Halving cycle, quarterly expiry, turn-of-month: no crypto sources found. Weekend illiquidity: only the volume effect above.

## 4. Sentiment, attention, LLM-labelled news

### Takeaway
Sentiment indicators fit in-sample and mostly fail out-of-sample for crypto; the strongest LLM-news results are in equities, are before costs and decay with adoption. The user's news classifier is best used as a veto/context layer, not as a standalone entry signal.

### Cited Findings
- ChatGPT-labelled Bitcoin news: improved in-sample fit for returns and volatility, no statistically significant out-of-sample forecasting gain; authors read this as semi-strong efficiency — [arXiv 2304.07619 search summary / related](https://arxiv.org/abs/2304.07619v6) (note: that arXiv ID is the Lopez-Lira & Tang equity paper; the Bitcoin result came in the same search summary without its own URL, so verify before citing)
- Cross-section of crypto: pessimism in technical news positively priced, pessimism in fundamental news negatively priced, beyond standard factor models — [Quantpedia summary](https://vvv.quantpedia.com/?p=28913)
- Equities: GPT-4 headline scores predict drift, especially small stocks and negative news; about 34 bp/day pre-cost for overnight news, usable only at very low cost; returns decline as LLM adoption rises — [Lopez-Lira & Tang](https://arxiv.org/abs/2304.07619v6)
- Fear and Greed / Google Trends / Twitter: one ML study reports about 62% next-day accuracy with the change in Fear & Greed the top predictor, higher readings followed by negative returns (contrarian); abstract only, and F&G already contains Twitter and Google Trends — [Sharif repository](https://repository.sharif.edu/resource/501394/how-people--39-s-sentiment-and-attention-affect-the-return-of-bitcoin), [NewHedge F&G](https://newhedge.io/bitcoin/fear-and-greed-index)
- Early evidence for attention: Liu & Tsyvinski find investor-attention proxies forecast crypto returns (sample ends late 2010s) — [NBER w24877](https://www.nber.org/system/files/working_papers/w24877/w24877.pdf)
- A 2026 paper on constrained LLM agents building factors in crypto markets exists; contents not readable — [arXiv 2604.26747](https://arxiv.org/pdf/2604.26747)

### Inferences
- With speed disadvantage, the user's classifier cannot win on headline latency against bots. Its feasible edge is at hours-to-days horizon (e.g. hacks, unlock, regulatory items persist), and its value should be measured by logging classifier tag vs subsequent 1h/4h/24h BTC-adjusted return, with a fixed pre-registered rule, as the lab already does for technical rules.
- 62% next-day accuracy on a hit-rate basis is not an edge until net of costs and tested out of sample.

### Gaps
- No rigorous event-driven crypto trading study with LLM-labelled news and realistic costs found. Reddit/Telegram sentiment predictive power: not found.

## 5. Cross-asset and macro links

### Takeaway
BTC-Nasdaq correlation is regime-dependent and asymmetric (stronger on equity down days). I found no tested Nasdaq or risk-on filter for crypto trend systems; the asymmetry suggests such a filter helps mainly as a drawdown veto.

### Cited Findings
- Rolling correlation to Nasdaq 100/S&P peaked near 0.87 in 2024, varies by regime — [arXiv 2501.09911](https://arxiv.org/abs/2501.09911v1)
- Another reported path from -0.13 (2018) to about 0.76 (2023-24) (secondary, window-dependent) — [KuCoin blog](https://www.kucoin.com/blog/ae-why-bitcoin-and-crypto-often-move-with-nasdaq)
- Asymmetry: BTC falls harder when equities fall, participates weakly when they rise (Wintermute); large Nasdaq down days strongly predict large BTC declines (BitOoda 2022) — [Yahoo/CoinDesk](https://finance.yahoo.com/news/bitcoin-falls-harder-tech-nasdaq-085744323.html), [Crowdfund Insider](https://www.crowdfundinsider.com/2022/02/187405-bitcoin-btc-price-correlation-to-nasdaq-drops-to-51-relationship-is-strongest-when-nasdaq-is-down-big-report/)
- Momentum factors: Liu, Tsyvinski & Wu (three-factor model: market, size, momentum); factors gross of costs, early immature sample — [CXO Advisory](https://cxoadvisory.com/size-effect/cryptocurrency-factor-model), [NBER w25882](https://www.nber.org/papers/w25882.pdf)

### Inferences
- A concrete testable filter for the 4h trend engine (+0.1R, 36% win): only take longs when QQQ/ES is above its own trend, evaluate by R with and without. Not validated by any source here.

### Gaps
- No evidence on US100/ES lead at the US open, DXY/yields/gold regime effects, or post-2021 momentum decay.

## 6. Market structure inefficiencies

### Takeaway
Funding/basis carry is real but compressed and capital-heavy; arbitrage, MEV and market making are not for a manual, tiny operator. Carry is a yield floor, not a signal.

### Cited Findings
- BIS WP 1087: average annualised carry about 7% p.a. across exchanges, April 2019-July 2024; attributed to regulation-driven segmentation — [BIS](https://www.bis.org/publ/work1087.pdf)
- Decay: basis yields from 17% to about 4.7% in one year; 10x Research cites 1.0% perp funding and 4.3% CME basis; funding turned negative in the October 2025 crash (secondary sources) — [Sharpe.ai](https://www.sharpe.ai/arbitrage/guide/funding-rate-arbitrage), [MEXC mirror](https://www.mexc.com/it-IT/news/717545)
- Copy trading: unverified claim (AInvest) that 97% of leaders were profitable but only 43.6% generated positive returns for copiers across Binance/Bybit/MEXC over 90 days — [AInvest](https://www.ainvest.com/news/leader-copying-losing-point-2608/)

### Inferences
- Funding as a sentiment/positioning input (extreme positive funding as crowding) is plausible but I found no evidence either way here.
- Triangular arbitrage, DEX/CEX gaps, MEV: not researched; realistically bot-only.

### Gaps
- No source on triangular arbitrage, MEV, grid or market making profitability.

## 7. Signal-service reality check

### Takeaway
Evidence is thin on net-of-cost outcomes of signal services, but all indications are that followers earn less than providers, and pump group profits go to organisers. Only one rigorous-looking preprint (July 2026) tests popular retail signal families against multiplicity, costs and leverage; its results were not readable.

### Cited Findings
- arXiv 2607.20093 (Darmanin, "Retail Trader's Ruin") tests five retail signal families (trend, oscillator, candlestick, volume, calendar) through gates: edge after multiplicity correction, cost viability, survival under leverage; results not seen — [arXiv](https://arxiv.org/pdf/2607.20093)
- eToro/Wikifolio theses: no statistically significant outperformance vs S&P 500 (Vienna thesis); small samples (student work) — [Univ. Vienna thesis](https://utheses-gateway.univie.ac.at/api/document/get/file/73534), [TalTech thesis](https://digikogu.taltech.ee/en/Download/9c402020-d23e-447e-bcba-e41823baa02d)
- Pump groups: returns accrue to organisers/early insiders; newcomers stop after losing money (see section 1 citations)
- Copy-trading sites often assume same-day entry and omit spread/slippage — [GitHub reality-check commit (simulation, not a study)](https://git.dominik-roth.eu/dodox/smaug/commit/4d111e0a3a99b15f09e84953ca5a3fc5daac77f7.patch)
- A "70% of signal followers lose" claim exists but is uncited — [Traders Union](https://tradersunion.com/interesting-articles/pump-and-dump-explained-and-defined-with-examples/best-groups-in-telegram/binance/) (do not use)

### Inferences
- The user's -0.11R/trade over 15-47 signals/day, with 0.06%/side cost, is consistent with the literature direction: many low-edge signals lose to costs. Cutting signal count to a few high-conviction, cost-aware setups is the direction the evidence supports; the specific "share beating buy-and-hold" figure was not found.

### Gaps
- No credible figure for the share of crypto signal services beating buy-and-hold after costs.

## 8. Out-of-the-box ideas

### Takeaway
Evidence favours restricting activity (regime gating, vol sizing, fewer trades) and treating carry as a floor over hunting new alpha. Prediction markets look calibrated on average, so their value is as an input for event probabilities, not as a free edge.

### Cited Findings
- Low-volatility crypto portfolios (2017-mid 2021, liquid coins) earned significant excess returns, stop-loss improved Sharpe — [SFERA/Unife](https://sfera.unife.it/handle/11392/2586471) (short sample, in-sample selection risk)
- Crypto allocation improved Sharpe in 70% of rolling periods, 2018-Apr 2024 weekly — [study via search](https://usiena-air.unisi.it/handle/11365/1290454)
- Polymarket: Princeton thesis on 188,509 resolved markets: Brier Skill Score 0.398, best in Politics (0.565), worst in Sports (0.264), prices compressed towards 50% (favourite-longshot bias); Vanderbilt study 2024 cycle reports Polymarket 67% right vs Kalshi 78% (methodology disputed); no profitability test after fees — [Princeton thesis](https://theses-dissertations.princeton.edu/entities/publication/d5708372-5ea3-4252-b669-7f9cee07387c), [Yahoo](https://finance.yahoo.com/news/polymarket-kalshi-reliable-not-quite-201417879.html)

### Inferences
- Ranking by realism for this service (my judgement, not a sourced result):
  1. Do-nothing/regime gates and fewer signals (cheapest, aligned with loss data); vol-scaled sizing.
  2. Event vetoes: macro-release blackout, hack/exploit, large unlock within ~30 days, treasury/ETF-flow regime as context.
  3. Equity-risk filter on longs (testable on own data).
  4. LLM classifier as a logged, pre-registered hours-to-days overlay.
  5. Carry as a yield floor on idle capital (about 4-7% and falling; not a trading signal).
  6. Prediction-market probabilities for FOMC/CPI outcomes as inputs (untested for crypto).
  7. Listing/Upbit/pump-type events: dead for manual speed and for large caps.
- ETH/BTC relative value and sector rotation: no sources found; would have to be tested in the lab as pre-registered variants, accepting multiple-testing penalties.

### Gaps
- No evidence located for pairs/relative value, trading only a few setups per month, or low-correlation weak-edge portfolios in crypto. Prediction-market profitability net of fees for crypto-related hedging: not found.
