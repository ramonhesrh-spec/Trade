# Honest testing methodology for crypto perp strategies (small team, ~3y 1h/4h data, 20 perps, few hundred live trades)

Method note: web search in this session returned summaries, not primary PDFs. Items under "Cited Findings" are what sources confirmed. Formulas, rules of thumb and numbers under "Inferences" are my own knowledge or my own arithmetic (computed with Python in this session) and are NOT source-verified. Verify the formulas against the original papers before implementing.

## 1. Multiple testing and data snooping (DSR, PBO, Reality Check, SPA, Romano-Wolf, t>3, 30+ variants)

### Takeaway
After N tried variants, the best one's apparent edge must be compared with the expected maximum of N null results, not with zero. For roughly 30 to 50 variants the null-best t-stat is already about 2.1 to 2.3 before any dependence adjustment, so a "pass" at t about 2 means nothing. Use t of about 3 (Harvey-Liu-Zhu) as the headline hurdle for a new rule, and count every variant ever looked at.

### Cited Findings
- Deflated Sharpe Ratio (Bailey and López de Prado 2014) corrects Sharpe significance for selection bias, backtest overfitting, sample length and non-normality; it equals the Probabilistic Sharpe Ratio evaluated against a hurdle equal to the expected maximum Sharpe over N unskilled trials — [Wikipedia](https://en.wikipedia.org/wiki/Deflated_Sharpe_ratio), [LuxAlgo](https://www.luxalgo.com/library/concept/deflated-sharpe-ratio/)
- The hurdle is sqrt(V) times a combination of two inverse-normal quantiles (at 1-1/N and 1-1/(N·e)) weighted by the Euler-Mascheroni constant (~0.5772); parametrizations differ between sources — [LuxAlgo](https://www.luxalgo.com/library/concept/deflated-sharpe-ratio.md)
- The expected maximum grows roughly with sqrt(log N), so each extra order of magnitude of trials costs less than the last — [Quantt](https://www.quantt.co.uk/resources/sharpe-ratio-of-pure-noise)
- The DSR correction assumes independent trials, which fails when parameter sets are correlated — [Trading Strategy glossary](https://tradingstrategy.ai/glossary/probabilistic-sharpe-ratio)
- Harvey, Liu, Zhu (RFS 2016, NBER w20592): with hundreds of tested factors, the conventional t of 2.0 is inadequate; a new factor needs t above 3.0 (p about 0.27% two-sided); multiple-testing framework allows correlated tests and missing data; "most claimed research findings in financial economics are likely false" — [NBER](https://nber.org/papers/w20592), [SSRN](https://papers.ssrn.com/abstract=2513152)
- Probability of Backtest Overfitting (Bailey, Borwein, López de Prado, Zhu, J. Computational Finance 2017) is estimated with combinatorially symmetric cross-validation (CSCV), model-free and nonparametric; hold-out alone is called unreliable for backtests; CRAN package `pbo` exists — [SSRN](https://papers.ssrn.com/abstract=2326253), [CRAN pbo readme](https://cran.hafro.is/web/packages/pbo/readme/README.html)
- I found no source for White's Reality Check, Hansen's SPA and Romano-Wolf in this session (search covered only the stationary bootstrap); see Inferences.

### Inferences
Formulas (own knowledge; verify):
- PSR(SR*) = Phi( (SR_hat - SR*) * sqrt(T-1) / sqrt(1 - g3*SR_hat + ((g4-1)/4)*SR_hat^2) ), SR per period (per trade or per day), g3 skew, g4 kurtosis (non-excess).
- Expected max over N null trials: E[max SR] ≈ sqrt(V) * [ (1-γ)·Z^-1(1-1/N) + γ·Z^-1(1-1/(N·e)) ], V = cross-trial variance of Sharpe estimates, γ=0.5772. DSR = PSR(SR* = E[max SR]). Use effective N (see below), not raw N.
- In t-stat units for a null with unit variance (my computation, independent trials): N=5: 1.19; 10: 1.57; 20: 1.90; 30: 2.07; 50: 2.28; 100: 2.53; 200: 2.77. So "best of 30 with t=2.1" is exactly what noise produces. Rule of thumb: required t ≈ max(3.0, E[max] + 1.0) for a promotion decision; for N≈30-50 that gives about 3.1 to 3.3. Variants that are near-duplicates (same entry on 15m vs 1h, same rule with nearby parameters) count as less than one trial each: estimate N_eff from the cluster count of the variant return-correlation matrix (e.g. number of eigenvalues needed for 90% variance, or average-linkage clusters at rho<0.7). If unsure, use raw N: it is conservative.
- Count honestly: every variant, parameter, timeframe, coin subset, filter and exit tweak ever evaluated on this data counts, including ones discarded informally. "0 of 20+ passed" is the expected result if the true edge is ≈0 and the bar is real; the right reaction is NOT to relax the bar.
- White's Reality Check (2000): bootstrap (stationary) the vector of per-period performance differences f_k = performance of variant k minus benchmark; statistic V = max_k sqrt(T)*mean(f_k); p-value from the bootstrap distribution of max_k sqrt(T)*(mean*(f_k) - mean(f_k)). Hansen SPA (2005): same but studentized and with a recentering that drops clearly bad variants, so adding junk variants does not destroy power. Romano-Wolf stepdown: bootstrap-based FWER control that reports which individual variants are significant (stepwise). All three handle dependence between variants, which is what the user's lab needs; implementable with the `arch` Python package (`arch.bootstrap.SPA`, `StepM`) — package names from memory, verify.
- CSCV/PBO steps: matrix M (T rows x N variants of per-period returns), split into S even blocks (S=8 to 16), for each of C(S,S/2) block combinations: best in-sample variant n*, its out-of-sample rank omega, logit lambda=ln(omega/(1-omega)); PBO = fraction lambda<=0. PBO above ~0.5 means selection by in-sample is no better than random. Needs the full variant matrix, so the lab should persist per-trade or per-day returns for ALL variants.
- Practical adjustment for the lab: (a) keep a persistent registry of every variant evaluated (the `rule_status`/lab output already prints the count; add it to the pass criterion); (b) raise the per-variant t hurdle with count (table above), or use the Bonferroni/Sidak equivalent p = 0.05/N_eff; (c) run one family-wise test (SPA or Romano-Wolf) over the whole matrix instead of independent per-variant verdicts.

### Gaps
- Original DSR paper formula not fetched; parametrization (sqrt(V) scaling, per-period vs annualized) must be checked.
- White 2000 / Hansen 2005 / Romano-Wolf 2005 not sourced here.

## 2. Dependence among trades (BTC beta, clustering, block bootstraps, effective sample size)

### Takeaway
A per-trade i.i.d. bootstrap overstates confidence because trades on 20 coins opened in the same week are largely one bet on the market. The user's weekly-cluster bootstrap is the right idea; the effective number of independent observations is far below the trade count.

### Cited Findings
- The stationary bootstrap (Politis and Romano 1994) resamples blocks of geometric random length (mean 1/p) so resamples stay stationary; the user must choose the average block length, with Politis-White automatic selection as one method — [Gnosis/UCY record](https://gnosis.library.ucy.ac.cy/handle/7/57533), [MetricGate](https://metricgate.com/docs/stationary-bootstrap-politis-romano/), [asbates](https://asbates.rbind.io/2019/03/30/time-series-bootstrap-methods/)
- The DSR/PBO literature itself flags dependence among trials as a limitation — [Trading Strategy glossary](https://tradingstrategy.ai/glossary/probabilistic-sharpe-ratio)

### Inferences
- Design effect: n_eff = n / (1 + (m-1)·rho), m = average trades per cluster (week), rho = intra-cluster correlation of trade R. Alt-coin trades in the same direction in the same week typically have rho of 0.2 to 0.5 in R terms (my estimate; MEASURE it with an ANOVA on your own trade R by week). With m=8 trades per week and rho=0.3, n_eff ≈ n/3.1.
- Independent observations in a 3-year, 20-coin test: weeks ≈ 156, and the crypto market factor means effectively ~156 weekly "market states" times a modest number of idiosyncratic bets. A safe working count: n_eff between 150 and ~600, NOT thousands. Regimes (bull/bear/range) number perhaps 4 to 8 over 3 years: regime-level claims have almost no power.
- Procedures: (1) cluster by week (existing); also try calendar-day and 2-week clusters, and report the most pessimistic. (2) Aggregate to a portfolio daily/weekly R series (sum of R closed that day) and run a stationary bootstrap (mean block length ≈ 5 to 10 days; use Politis-White) on that series; this absorbs both cross-sectional and serial dependence. (3) Report BTC-beta-adjusted result: regress daily strategy R on BTC (or total market) return and test the alpha intercept; a long-biased rule on a bull-market sample can show positive R that is just beta. (4) Compare against equal-time buy-and-hold of the same coins with the same exposure.
- Cluster bootstrap with ~156 clusters is OK but the CI is itself noisy; below ~50 clusters (e.g. a single regime) don't trust it.

### Gaps
- No source quantified typical intra-week correlation of crypto trade returns; own estimate only, measure it.

## 3. Walk-forward, purging, out-of-sample discipline

### Takeaway
With 3 years, only a truly locked, never-looked-at final period (plus pre-registered rules) gives an unbiased number; purged/embargoed CV and CPCV help estimate the distribution but do not cure repeated looking.

### Cited Findings
- Purging removes training observations whose labels overlap in time with the test set; the embargo removes training observations immediately following the test set to guard against serial correlation. Method from López de Prado, AFML 2018 ch. 7 — [Wikipedia: Purged cross-validation](https://en.wikipedia.org/wiki/Purged_cross-validation), [skfolio](https://skfolio.org/generated/skfolio.model_selection.CombinatorialPurgedCV.html)
- CPCV splits the timeline into n contiguous groups and holds out every combination of k groups: C(n,k) splits that recombine into several out-of-sample paths, giving a distribution of performance rather than one number — [skfolio](https://skfolio.org/generated/skfolio.model_selection.CombinatorialPurgedCV.html), [fynance](https://fynance.readthedocs.io/en/latest/generated/fynance.data.combinatorial_purged_cv.html)
- Hold-out alone is considered unreliable for backtests that are selected among many trials — [SSRN PBO paper](https://papers.ssrn.com/abstract=2326253)

### Inferences
- For rule-based (non-fitted) strategies purging matters only for trades whose holding period spans the fold boundary: drop trades whose entry-to-exit interval overlaps the boundary; embargo at least the max holding time (for 1h/4h swings, 5 to 10 days).
- Half-split (current): a weak, single-split test with large noise. With true edge 0.1R and sd 1.5, a half of 500 trades has SE 0.095R: the second-half sign is close to a coin flip even for a real edge (P(positive) ≈ 85% for a real +0.1R, 50% for none). Treat "positive in both halves" as a sanity screen only, never as evidence. Better: k=6 to 8 contiguous time blocks, report fraction of blocks positive and the worst block; CPCV (n=8, k=2 gives 28 splits, 7 paths) if the rule has fitted parameters.
- Rolling vs anchored: use anchored/expanding if parameters are estimated (more data helps); rolling if you suspect regime drift. For fixed pre-set rules there is nothing to refit, so "walk-forward" reduces to time-block stability.
- Discipline: write the rule (entry, exit, universe, costs, success criteria, N) into a dated file/commit BEFORE running; lock the most recent 6 to 9 months as final holdout, hash the data slice, touch it once per candidate family, and if a holdout is used to choose between two candidates it is no longer a holdout. The live paper-forward period is the true holdout; a lab pass followed by shadow/live running (as `rule_live` does) is the right architecture.

### Gaps
- No empirical source found on how many holdout touches degrade it; rule is general practice.

## 4. Placebo, permutation, benchmarks, regimes

### Takeaway
A random-entry placebo with the same exit proves the entry timing adds value over the exit/stop/market drift, not that the rule is profitable. It is a good control; the margin must be defined relative to its own noise, not as a fixed 0.03R.

### Cited Findings
- No source retrieved in this session specifically on placebo/random-entry tests (not searched).

### Inferences
- What the placebo proves: entries beat random timing under identical exits, sizing, universe, and holding period. It controls for drift, for exit mechanics (trailing stops on trending assets produce positive R on random longs in bull markets), and for costs. It does NOT prove absolute profitability or robustness out of sample.
- Better design: B=1000 random-entry sets matching the rule's count per coin, per month, and direction mix (preserve long/short ratio and time distribution, otherwise beta leaks in). Compute the p-value = fraction of placebo mean-R >= rule mean-R, and compare in SE units. The fixed "margin ≥ 0.03R" is arbitrary: with SE of placebo mean about 1.5/sqrt(n) (0.067 at n=500), 0.03R is only 0.45 SE and passes often by chance. Replace with p<0.05 (more with N-adjustment) against the placebo distribution AND margin>0.
- Permutation test on signals: shuffle signal timestamps within each coin (block-wise by week to keep clustering) and rerun; or circularly shift the signal series relative to prices by random offsets (preserves the signal's autocorrelation).
- Benchmarks to always report: buy-and-hold on the same coins and period, equal-weight; a simple trend filter (price>200-period MA / 55-day Donchian) with same costs; BTC-only. Edge must beat the trend filter after costs else it is repackaged beta.
- Per-regime breakdown: split by BTC 50/200d trend (up/down/range), by realized-vol tercile and by year; require no regime with a large significant negative R and report the number of weeks per regime. Do not use regime splits to select (adds N).

### Gaps
- No quantitative literature found on random-entry placebo thresholds in this session.

## 5. Costs and execution realism on perps

### Takeaway
Fees alone are ~0.07% to 0.10% round trip at taker rates; in R this is cost_pct/stop_pct, which is large for tight stops (a 1% stop turns 0.1% costs into 0.1R, the entire claimed edge). Model costs conservatively and per-coin; test at 1.5x to 2x assumed costs.

### Cited Findings
- Binance USDⓈ-M futures, regular user (VIP 0): maker 0.02%, taker 0.05%; BNB payment gives 10% discount; VIP volume thresholds are 5x spot; fees subject to change — [Binance support](https://www.binance.com/en/support/articles/360033544231) (via search summary of the localized pages), [Finder](https://www.finder.com/binance-futures-fees); one secondary source lists 0.04% taker, which conflicts with the official figure — [Traders Union](https://tradersunion.com/brokers/crypto/view/binance/futures-fees/)
- Bybit USDT perps non-VIP: maker 0.02%, taker 0.055% — [Matrixport fee rules](https://matrixport.helpjuice.com/en_US/trading-fee-rules), [Bitsgap](https://bitsgap.com/blog/bybit-trading-fees-explained-what-it-costs)
- OKX base: maker 0.02%, taker 0.05%; VIP tables differ between sources (OKX reportedly moved to nine VIP levels in April 2026) — [OKX Learn](https://www.okx.com/ru/learn/crypto-futures-fees-compared), [Traders Second Brain](https://traderssecondbrain.com/tools/exchange-fees)
- Hyperliquid base perps tier (<$5M 14d weighted volume): taker 0.045%, maker 0.015%; tier 1 (>$5M) 0.040%/0.012%; tier 2 (>$25M) 0.035%/0.008%; higher tiers conflict between sources (an older $5B/0.024% claim vs a table that runs to $7B) — [Hyperliquid docs](https://hyperliquid.gitbook.io/hyperliquid-docs/trading/fees), [Dwellir](https://www.dwellir.com/blog/hyperliquid-fees-explained)
- Funding is a separate cost from trading commission (Binance) — [datawallet review](https://www.datawallet.com/zh/隐蔽性/binance-futures-review)
- Not found in this session: Kraken Futures fee schedule, Binance funding interval documentation, slippage studies.

### Inferences
- Cost to R: cost_R = (fee_in + fee_out + slip_in + slip_out + funding_paid) / stop_distance_pct, all in % of notional. Example: taker/taker 0.05%+0.05%, slippage 0.03% each side for liquid alts, = 0.16% / stop 1.5% = 0.107R per trade. Entry as maker limit (0.02%) with stop-out as taker (0.05%) and target as maker: 0.07% to 0.10%. A claimed net +0.1R with 1% stops is break-even under realistic costs: check which stop distances the edge lives in; edges concentrated in tiny stops are usually cost artefacts.
- Funding: Binance and Bybit settle every 8h (some symbols 4h/1h; check exchange info per symbol) at a base of 0.01% per 8h (≈0.03%/day, ~11% annualized for longs in neutral markets, and can spike to 0.05% to 0.3% per period in manias). A 3-day long hold ≈ 9 periods ≈ 0.09% at base, which on a 2% stop is ~0.05R. Model with actual historical funding per symbol (sign-aware: shorts earn when funding positive). Align by settlement timestamp: charge only if the position was open at the settlement instant.
- Slippage model: slip_pct ≈ half-spread + k·sigma_1h·sqrt(order_size/ADV_1h-ish); for retail order sizes (a few thousand USD) on top-20 perps use 1 to 3 bps for majors, 3 to 10 bps for mid-cap alts, higher at night/weekend and in stop-run candles. Stop orders fill through levels: assume fill at stop minus 0.5·ATR-fraction in gap candles; market-on-trigger stops at worst of (stop, next-candle open when it gapped through).
- Intra-candle tie-breaking: if a 1h candle's range contains both stop and target, assume the stop hit first (conservative). If entry candle also hits the stop, count it as a loss. Use 5m or 1m data to resolve ties when available: if >5% of trades are ambiguous, results are not trustworthy at that granularity.
- Run the whole test at cost multipliers 1.0, 1.5, 2.0; a rule that dies at 1.5x is fragile. Report gross vs net R per trade.

### Gaps
- Kraken Futures fees, Binance funding documentation, and empirical slippage studies were not retrieved. Treat slippage numbers as assumptions to calibrate against your own fills.

## 6. Survivorship bias and look-ahead

### Takeaway
A universe of 20 perps that exist today and traded for the full 3 years is survivor-selected (coins that were top-20 and still listed), which flatters long-only and breakout rules. Look-ahead bugs (pivot confirmation, signal candle high/low, timestamps) are the most common source of a fake edge.

### Cited Findings
- No sourced material was retrieved for this section (not searched). All below is own knowledge/engineering practice; the user's own project notes already flag pivot confirmation (pivot known only p+n candles later) and closed-candle-only 4h filters.

### Inferences
- Universe: define the universe point-in-time (e.g. top 20 by trailing 30d quote volume, recomputed monthly, from a snapshot) including coins later delisted or collapsed (LUNA, FTT, etc., whose perps were delisted or illiquid). If delisted-coin data is unavailable, state the bias direction (upward for long rules) and discount accordingly. Coins listed mid-period enter only after listing + N warm-up candles (indicator warm-up and a stability period of ~30 days because new listings have anomalous behavior).
- Vendor differences: Binance, Bybit, OKX perp candles differ in volume, wicks and funding; test on a second venue's candles as robustness; use trade-through/mark-price rules consistently for stop triggers (Binance stops trigger on last or mark price depending on setting, which differs from candle high/low).
- Checklist of look-ahead: (1) signal computed on candle t close; entry no earlier than open of t+1 (or limit order filled only if later price trades through it by a margin, not touching). (2) Never use the high/low of the signal candle to set a level that is then "filled" within the same candle. (3) Pivots/fractals: a pivot with n right-hand bars is known at p+n close; use it only from there. (4) Indicators with repainting (zigzag, some HTF resamples): compute HTF values only from fully closed HTF bars, shift by one. (5) Timestamp convention: Binance kline open_time is the START of the bar; align funding (settled at 00/08/16 UTC) and open interest (snapshots at period end) with closes, not opens; OI/long-short data are often published with delay. (6) Sort/merge asof with direction='backward' only. (7) Normalizing with full-sample statistics (z-scores, percentiles) leaks the future; use expanding or rolling windows.
- Test for leaks mechanically: shift the signal by +1 bar and by -1 bar; a leak-free edge decays smoothly with delay, a leak collapses or oddly improves at negative shifts.

### Gaps
- No quantitative source on delisting/survivorship impact for crypto perps found.

## 7. Sample size for +0.1R with sd 1.5R; promoting and demoting live rules

### Takeaway
Detecting +0.1R at sd 1.5R needs about 1,400 independent trades for a one-sided 5% test at 80% power, about 3,300 for the t>3 hurdle. A few hundred trades cannot confirm such an edge; they can only reject large positive edges or gross failure. So the user's 500-trade minimum is not the real bottleneck: independence is.

### Cited Findings
- No source retrieved on sequential testing (SPRT/CUSUM) or Bayesian updating in this session (not searched). Content below is derived calculation or standard statistics.

### Inferences
Calculation (n = ((z_alpha + z_power)·sd/delta)^2, power 80% => z=0.84; computed in Python):
- delta 0.1R, sd 1.5: one-sided 5%: n=1,389; two-sided 5%: 1,764; t=3.0: 3,318; t=3.5: 4,238.
- sd 1.2 (if wins/loses are bounded around ±1R, a 36% winner at 3R target has sd closer to 1.5; compute your own sd): t=3.0: 2,123.
- delta 0.05: two-sided 5%: 7,056.
- SE of mean R: n=300: 0.087R; n=500: 0.067R; n=1,000: 0.047R. So a few hundred trades gives a 95% CI of roughly ±0.13 to ±0.17R: a measured +0.1R is consistent with -0.05 to +0.25. Divide effective n by the design effect from section 2 (n_eff = n/3 typical) and the CI widens by ~1.7x.
- Independent weeks: 156 weeks cannot test +0.1R/trade unless trade frequency per week is high and rho is low. Per-week-aggregate: with m=8 trades/week and rho=0.3, the weekly mean-R SD ≈ 1.5·sqrt((1+(m-1)rho)/m)= about 1.5*0.62 ≈ 0.93... i.e. SE over 156 weeks ≈ 0.075R-equivalent per trade; t of about 1.3 for a true +0.1R. A pass is not achievable unless the true edge is ≥ +0.2R or sample ≥ 6 years equivalent.
- Consequence for the user's gates: the current best candidates (~+0.1R net, 36% win) are by arithmetic not detectable at the present sample, so "0 of 20 passed" tells you little about whether they are real; it mostly tells you the data cannot separate +0.1R from 0. Do not lower thresholds to get a pass; instead (a) widen sample (more coins, longer history, lower timeframes for more trades, but remember N_eff), (b) look for edges with larger R (>0.25R) or a lower-variance payoff, (c) prefer pooling by structural family (a pooled test of all swing variants) over per-variant tests.
- Sequential monitoring (own knowledge): SPRT on mean R with H0: mu=0, H1: mu=+0.1R (normal sd 1.5): log-likelihood ratio increments (mu1/sd^2)(x - mu1/2) per trade; accept H1 at ln((1-beta)/alpha) = ln(0.8/0.05) ≈ 2.8, accept H0 at ln(beta/(1-alpha)) ≈ -1.6. Expected ~1,000+ trades, so with sd 1.5 it will mostly end "inconclusive" within a few hundred trades. Use one-sided CUSUM for demotion: S_t = max(0, S_{t-1} + (mu0 - x_t) - k), k = 0.05R, alarm when S_t > h (set h≈ 5 to 8R by simulation of the in-control ARL, ≥ 300 trades). Demote on CUSUM alarm or when the lower 90% bound of the cluster-bootstrap mean on the last 100 trades is below -0.15R (current live design uses "last 100 not clearly under 0").
- Bayesian updating: prior on true mean edge mu ~ Normal(0, tau^2) with tau = 0.05R to 0.1R (a skeptical prior reflecting that most ideas have ~0 edge, plus a haircut); posterior mean = n_eff·xbar/(n_eff + sd^2/tau^2). Example: xbar=+0.10R, sd 1.5, n_eff=150, tau=0.07: shrink factor = 150/(150 + 459) = 0.25, posterior mean ≈ +0.025R. Promote only when P(mu > cost buffer 0) > 0.9 to 0.95 under this prior; this makes the shrinkage explicit and avoids hard thresholds.
- Win rate 36% with payoff ~2R to 3R: is plausible (36% × 2.5R − 64% × 1R ≈ +0.26R gross); a +0.1R net estimate depends heavily on the winners' size, a few outliers drive it: report median, trimmed mean, and mean without top 3 winners.

### Gaps
- SPRT/CUSUM thresholds above are derived from standard theory, not a source; simulate with your own R distribution.

## 8. Position sizing and risk

### Takeaway
At 35 to 40% win rate, double-digit losing streaks are normal and not evidence of failure. Fractional Kelly with an uncertain edge implies tiny sizes; 0.25% to 1% risk per trade with a portfolio-level heat cap is appropriate, plus correlated-trade aggregation.

### Cited Findings
- No source retrieved in this session (not searched). The content below is own computation/standard theory.

### Inferences
- Losing streaks (computed): for p_loss=0.64, expected longest losing streak ≈ log(n·0.36)/log(1/0.64): 8.0 in 100 trades, 10.5 in 300, 13.2 in 1,000; the 95th percentile is ≈ 3 to 5 trades longer (≈15 to 18 at 300 to 1,000 trades). User's "15 to 26" is plausible across several hundred to thousands of trades and consistent with a 60 to 65% loss rate, given bad luck.
- Drawdown: with 1R risk/trade and a +0.1R edge, sd 1.5, a drawdown of 20R is routine; max drawdown over N trades for a zero-drift walk is ~ sd·sqrt(N)·0.8 ≈ 1.5·0.8·sqrt(500) ≈ 27R. At 1% risk that is a ~24% account drawdown even for a worthless strategy. So size so that a 30R drawdown is tolerable: risk ≤ 0.5% to 1% per trade.
- Kelly: continuous approximation f* = mu/sigma^2 in R units per unit risk = 0.1/2.25 = 0.044, i.e. risk 4.4% per trade at full Kelly if the +0.1R were certain; with parameter uncertainty (SE 0.07R at 500 trades) the shrunken edge ≈ 0.025R gives f* ≈ 1.1%; half Kelly = 0.55%. Rule: size at ≤ 1/4 to 1/2 Kelly of the SHRUNKEN estimate; overestimating edge is far more costly than underbetting (growth falls to 0 at 2x Kelly).
- Correlated trades: crypto alt correlation to BTC is typically 0.6 to 0.9 on hourly returns (own knowledge; measure). With k simultaneous same-direction trades at correlation rho, aggregate risk ≈ k·r·sqrt((1+(k-1)rho)/k). For k=5, rho=0.7, aggregate = 3.9 r not 2.2 r. Cap open risk (portfolio heat) at ~3% to 4% and net directional exposure by beta-to-BTC.
- Volatility targeting: scale position by target_vol/realized_vol (Carver), cap leverage; stop distance in ATR units already does most of this per trade.

### Gaps
- Carver/Chan specifics and correlation numbers not verified here.

## 9. Live-vs-backtest decay and sane haircut

### Takeaway
Published equity anomalies lose about a quarter out of sample (data-mining part) and about 58% after publication; for a privately-mined crypto rule selected from 20+ variants, plan for at least a 50% haircut on net R before costs are re-tested, and treat a backtest edge under 2x costs as zero.

### Cited Findings
- McLean and Pontiff (J. Finance 2016, 97 predictors): portfolio returns are 26% lower out-of-sample and 58% lower post-publication; the 26% is an upper bound on data-mining effects, the further ~32% is attributed to publication-informed trading — [Ivey copy of paper](https://ivey.uwo.ca/media/3775549/pontiff.pdf), [Counterpoint PDF](https://counterpointfunds.com/wp-content/uploads/2017/07/PredictabilityMcleanPontiff.pdf), [Chronicle summary](https://www.chronicle.com/blogs/percolator/academic-research-destroys-stock-values)
- Earlier working-paper versions reported different figures (about 35% for 82 characteristics; 56% with 95 predictors), so numbers depend on the version — [hedgefundalpha summary](https://hedgefundalpha.com/?p=521337), [Bocconi working paper copy](https://finance.unibocconi.eu/sites/default/files/files/media/attachments/The%2520Observation%2520Effect%2520%282%2920130502142550.pdf)
- Decline was largest in stocks easiest to trade — [Fortune](https://fortune.com/2012/11/02/academics-academia-destroys-stock-picking-strategies)
- No retail/live shrinkage factor source for crypto found.

### Inferences
- Haircut rule (judgment, not empirical for crypto): lab-selected from N≈20 to 50 variants: multiply the in-sample mean R by 0.5 (or use the Bayesian shrinkage in section 7, which gave 0.25 for +0.1R at n_eff 150); then subtract costs again at 1.5x. A +0.1R net candidate becomes ≈ +0.03 to +0.05R expected live, which does not justify the risk of live capital by itself.
- Crypto-specific decay drivers: regime dependence (2021 vs 2022 vs 2024), funding-rate regime, capacity crowding of simple breakouts, exchange microstructure changes.

### Gaps
- No crypto-specific decay study found.

## Assessment of the user's current framework and recommended changes

### Takeaway
The design is directionally good (cost-aware, cluster bootstrap, placebo, MIN_TRADES). It is broadly right to be strict: the gates are not the problem, the sample cannot detect +0.1R. A few gates are mis-specified (half-split, fixed 0.03R placebo margin, no N correction).

### Cited Findings
- (See sections above; the user's gates are described in the assignment, no outside source.)

### Inferences
Verdicts on each current gate:
- Per-trade bootstrap: too loose as evidence (ignores clustering); keep only as a diagnostic, never as a gate. Cluster-bootstrap must be the binding one.
- Half-split (both halves mean R > 0): too noisy to be informative (see section 3) yet also somewhat strict for a real small edge (each half passes only about 85% for a true +0.1R at n=250 per half; both halves ≈ 70%). Replace with 6 to 8 time blocks, require ≥ 60% of blocks positive and no block worse than about -0.3R, as a stability check rather than a significance test.
- Weekly-cluster bootstrap margin > 0: sensible, but a lower bound > 0 at 95% on 156 weeks needs real effect; and "margin > 0" should be a one-sided lower confidence bound (e.g. 5th percentile), at the N-adjusted level (see below).
- Placebo margin 0.03R fixed: too loose if the placebo's own noise is 0.05 to 0.07R; use placebo p-value (≤ 0.05/N_eff-adjusted or at least 0.05) with matched direction/time/coin mix, B=1000, plus margin > cost-uncertainty (0.03R fine as a floor).
- 500 trades minimum: fine as a floor, but binds less than n_eff; add a floor on weeks (≥ 100 active weeks) and clusters.
- Multiple testing: missing. Add (a) registry count N; (b) hurdle: cluster-bootstrap one-sided p < 0.05/N_eff (≈ t of 3 for N_eff≈20 to 30) or SPA/Romano-Wolf p<0.05 over the whole variant matrix; (c) report DSR/PBO from the stored variant-return matrix.
- Costs: test at 1.0x and 1.5x; real funding per symbol; same-candle tie = stop first.
- Lock a final holdout (last ~6 to 9 months) and test pre-registered finalists once.
- Live promotion: current rule (50 live trades with net mean ≥ 0, last 100 not clearly below 0) is too easy to satisfy by luck (SE at n=50 is 0.21R, so P(mean ≥ 0 | true edge 0) = 50%). Require n_eff-based Bayesian posterior P(mu>0) ≥ 0.9 under a skeptical prior, or at minimum a lower confidence bound; keep it a demotion-quick, promotion-slow asymmetric rule (CUSUM demotion).

Per-candidate checklist:
1. Pre-register rule, universe, costs, N count (all variants ever tried on this data) in a dated commit.
2. Point-in-time universe, listing-date warm-up; leakage test with ±1-bar shifts.
3. Net R at 1.0x/1.5x/2.0x costs incl. actual funding, conservative stop-first ties, stop gap fills.
4. Weekly-cluster (and 2-week) bootstrap one-sided lower bound > 0 at N-adjusted level; report n_eff and design effect.
5. Matched random-entry placebo p-value (B ≥ 1000) plus buy-and-hold and simple trend-filter benchmarks.
6. Time-block stability (6 to 8 blocks), per-regime and per-year table, BTC-beta-adjusted alpha.
7. Concentration check: result without top 3 winners, without best coin, without best month.
8. Family-wise test (SPA/Romano-Wolf) and DSR/PBO over the stored variant matrix.
9. One-shot touch of the locked holdout.
10. Shadow/live start at ≤ 0.25% risk, Bayesian-shrunk expectation, CUSUM demotion, promotion only after posterior P(mu>0) ≥ 0.9.

### Gaps
- All numeric thresholds above (N_eff estimates, rho, CUSUM h, haircut 50%) are judgment calls to be calibrated by simulation on the team's own data.
