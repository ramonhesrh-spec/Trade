# Momentum and trend-following evidence in crypto (4h to daily), after costs

Method note: direct page fetches failed (DNS errors for arxiv.org and concretumgroup.com), so every finding below rests on search-result summaries, not on full-text reads. Figures should be verified in the papers before the final report quotes them. Where the lab comparison is mine, it is labelled as inference.

## 1. Time-series momentum / trend following (Donchian, MA, trailing stops, vol sizing)

### Takeaway
Published evidence supports trend-following on BTC and large coins at daily-plus horizons, with headline net Sharpe of 1.5 or higher for a vol-sized Donchian ensemble. The strongest numbers come from 2015-2025 samples dominated by a few bull runs and from preprints or working papers. The only formal out-of-sample warning I found (Hudson and Urquhart) says no Bitcoin predictability out of sample.

### Cited Findings
- Zarattini, Pagani and Barbon, "Catching Crypto Trends" (Swiss Finance Institute working paper, 2025): an ensemble of Donchian-channel models with different lookbacks, volatility-based position sizing, a rotating portfolio of the 20 most liquid coins, a dataset described as free of survivorship bias (coins traded since 2015). Reported net-of-fees Sharpe above 1.5 and annualized alpha of 10.8% versus Bitcoin. They also propose a portfolio technique to cut transaction costs. — [IDEAS/RePEc](https://ideas.repec.org/p/chf/rpseri/rp2580.html), [author page](https://abarbon.com/papers/catching-crypto-trends), [Concretum](https://concretumgroup.com/catching-crypto-trends-a-tactical-approach-for-bitcoin-and-altcoins/)
- Same authors' intraday Bitcoin trend study reports a gross-of-fees Sharpe of about 1.6 over 2018-2025 against a long-short portfolio scaled to 20% volatility. A long-only BTC portfolio with the same vol target had a Sharpe just under 0.8. This is gross of fees, so it is not comparable to the 1.5 net figure above. — [Concretum](https://concretumgroup.com/seasonality-in-bitcoin-intraday-trend-trading/)
- Liu and Tsyvinski (RFS 2021, NBER w24877): strong time-series momentum in BTC, ETH and XRP, significant at daily and weekly frequencies, weaker for ETH. Example: BTC next-week return averages 11.2% for the top fifth of last-week returns versus 2.6% for the bottom fifth. Sample is 2011-2018 (my reading of the paper's period, not in the snippet), so it is mostly pre-2019 and illiquid. — [NBER](https://www.nber.org/system/files/working_papers/w24877/w24877.pdf), [IDEAS](https://ideas.repec.org/a/oup/rfinst/v34y2021i6p2689-2727..html)
- Hudson and Urquhart, "Technical trading and cryptocurrencies" (Annals of Operations Research): about 15,000 rules in five classes, two Bitcoin markets plus three other coins, with multiple-hypothesis data-snooping controls. Profitable with breakeven costs far above typical crypto fees, but no predictability for Bitcoin in the out-of-sample period (it remained in the other coins). — [Hull repository](https://hull-repository.worktribe.com/output/2328042)
- Svogun and Bazan-Palomino (2022): 69 MA and breakout rules; costs reduce the chance of beating buy-and-hold for XRP and LTC but raise it for BTC and ETH, because rules sidestep drawdowns. Bubble-period dependence. — [Finance Research Letters/IDEAS listing](https://ideas.repec.org/a/eee/finana/v86y2023ics1057521923000327.html) (the search tool attributed the study to this link; verify)
- Swinkels (2018) as summarised: crypto time-series momentum seems to have disappeared after the introduction of Bitcoin futures. — [search summary, original not opened](https://zenodo.org/records/7326524) (low confidence on this attribution)
- Bui and Nguyen, arXiv 2602.11708 (Feb 2026, not peer reviewed, no replication found): "AdaptiveTrend" on 6h candles with a dynamic trailing stop, monthly asset selection by rolling Sharpe, 70/30 long-short. 150+ pairs, 36-month out-of-sample window 2022-2024: Sharpe 2.41, max drawdown -12.7%, Calmar 3.18. A search summary says it models a 4 bps taker fee, slippage and funding and reports simple TSMOM Sharpe of 0.5-0.65. — [arXiv](https://arxiv.org/pdf/2602.11708)
- Gbadebo (2026): eight major coins, 2020-2025, time-series momentum beat cross-sectional on a risk-adjusted basis, 31.96% annual return. Only a search summary; period is bull-heavy. — [Springer](https://link.springer.com/article/10.1007/s11408-025-00474-9) (attribution uncertain)

### Inferences
- A 2.4 Sharpe over 2022-2024 on 6h bars is the closest published analogue to the lab setup, but it is a single-author-team preprint, selects assets by rolling Sharpe, and runs 70/30 long-short. I would not treat it as validation of a 4h long-only-style Donchian system.
- Per-trade expectancy, win rate and payoff ratios were not reported in any source I could read. Papers report portfolio Sharpe, which hides the trade-level distribution. Direct comparison with the lab's +0.07 to +0.12R is not possible from this evidence.

### Gaps
- No full-text access: transaction-cost assumptions (fee level, funding, slippage) for Zarattini et al. and Hudson/Urquhart are not confirmed.
- No source with per-trade R, win rate or payoff for 4h Donchian on perps.
- No Man AHL / Winton / AQR crypto trend note was found.

## 2. Cross-sectional momentum, size, value, low-vol factors

### Takeaway
Cross-sectional momentum is documented in coin universes, but the tradable part is small after costs, depends on the short leg and on bull markets, and varies by sample. Size and volume anomalies come from micro-caps.

### Cited Findings
- Liu, Tsyvinski and Wu (Journal of Finance 2022, pp. 1133-1177): three factors (crypto market, size, momentum) explain cross-sectional returns; ten characteristics gave significant long-short returns and the three-factor model accounts for them. Sample: coins above $1M market cap, 109 coins in early 2014 growing to 1,583 by end 2018. — [NBER w25882](https://www.nber.org/papers/w25882.pdf), [SSRN](https://papers.ssrn.com/abstract=3379131), [Alpha Architect summary](https://alphaarchitect.com/factors-investing-in-cryptocurrency/)
- Fieberg, Liedtke and Zaremba, "Cryptocurrency anomalies and economic constraints" (International Review of Financial Analysis, 2024): size and volume anomalies come from economically negligible micro-caps. Momentum holds in larger coins but trading costs are substantial and most of its alpha comes from short positions. Abnormal returns concentrate in bull markets and weaken over time. They recommend long-only, cost-aware, recent-period focus. — [ICM repository](https://open.icm.edu.pl/handle/123456789/25544)
- Fieberg, Liedtke, Metko and Zaremba, "Cryptocurrency factor momentum" (Quantitative Finance 2023): over 3,900 coins, 2014-2022, 34 anomalies; past winners outperform losers across subperiods. — [ICM repository](https://open.icm.edu.pl/handle/123456789/25542)
- Grobys and Sapkota (Economics Letters 2019): 143 coins, 2014-2018, monthly returns, no significant momentum payoff. Grobys, Sandretto and Aijo, "On survivor cryptocurrency momentum": weekly data 2017-2024, momentum profitable only after trimming the dataset, highly sample-dependent. — [IDEAS](https://ideas.repec.org/a/eee/ecolet/v180y2019icp6-10.html), [OSUVA](https://osuva.uwasa.fi/items/99fceb0a-aaaa-4df2-aed1-09e6232a9df3/full)
- "Multi-Factor Inception" (arXiv 2307.13832): momentum (MOP) and reversal (REV) performance decays by about 50% moving from data-exploration to train-test-split strategies; best vol-scaled portfolio breakeven cost 54 bps, but from the exploration setup. — [arXiv](https://arxiv.org/pdf/2307.13832)
- An unreviewed GitHub README (Feb 2026) reports a 20-day momentum strategy turned negative out of sample and cites a 38% fall in cross-sectional dispersion after 2022; low reliability. — [README](https://raw.githubusercontent.com/prams2104/crypto-momentum-backtest/main/README.md)

### Inferences
- Short legs on perps carry funding and borrow costs, and small coins have wide spreads, so published long-short spreads overstate what a retail perp trader can capture. A long-only top-20 universe (as in the lab) sits where the literature says the surviving part is.

### Gaps
- No source quantified short-leg costs (funding, borrow) in numbers.
- Value and low-volatility factors: no usable evidence found in this pass.

## 3. Regime filters and volatility scaling

### Takeaway
I found no rigorous out-of-sample study showing that a BTC 200-day filter or vol targeting improves crypto trend results. What exists is mostly commentary.

### Cited Findings
- Vol-scaled variants improve in the sources above (Zarattini et al. use volatility sizing; Bui and Nguyen report regime-conditional analyses), but both are the authors' own backtests. — [IDEAS](https://ideas.repec.org/p/chf/rpseri/rp2580.html), [arXiv](https://arxiv.org/pdf/2602.11708)
- Long-only BTC at 20% vol target: Sharpe just under 0.8 versus about 1.6 for the long-short trend version (gross). — [Concretum](https://concretumgroup.com/seasonality-in-bitcoin-intraday-trend-trading/)
- K33 notes the 2026 breakdown below the 200-day MA lasted 189 days versus 85-132 in earlier cycles, with the 200-day MA trending lower, which is the situation a 200-EMA filter should handle but is not evidence on its own. — [The Block](https://www.theblock.co/post/401991/not-all-200-day-moving-averages-are-equal-k33-argues-februarys-60k-low-still-marks-cycles-maximum-drawdown)

### Inferences
- The filter mostly reduces exposure in bears; its value is drawdown, not expectancy per trade. The lab's 200-EMA on each coin is a coin-level filter, not a BTC-level regime gate. Testing a BTC-gate variant is untested by anything I found.

### Gaps
- No peer-reviewed test of a BTC 200-day gate. No ETF-era (2024-2026) comparison with and without it.

## 4. Horizon (hours versus days versus weeks)

### Takeaway
Evidence favours daily-to-weekly horizons; I found no source documenting edge on 15m/1h after costs, and no direct 4h-versus-1d comparison.

### Cited Findings
- Liu and Tsyvinski find momentum at daily and weekly frequency. — [NBER](https://www.nber.org/system/files/working_papers/w24877/w24877.pdf)
- Zarattini et al. use Donchian lookbacks on daily-type data and add a cost-reduction portfolio technique, which implies turnover cost is a binding issue. — [IDEAS](https://ideas.repec.org/p/chf/rpseri/rp2580.html)
- Bui and Nguyen use 6h bars with a trailing stop, the nearest published horizon to 4h. — [arXiv](https://arxiv.org/pdf/2602.11708)

### Inferences
- With perp taker fees of 0.04-0.06% per side plus slippage, round-trip cost is about 0.1-0.15% of price. A 2 ATR stop on 4h bars is typically a few percent, so cost is roughly 0.03-0.07R per trade on my rough arithmetic (not sourced). That is the same size as the lab's whole edge (+0.07 to +0.12R), consistent with the claim that edge decays when costs dominate at shorter horizons.

### Gaps
- No sourced 1h/15m crypto trend study after costs.

## 5. Is the lab pattern (36% win rate, big winners, +0.07 to +0.12R) consistent with the literature?

### Takeaway
Low win rate with positive skew is the standard trend-following profile, so the shape is consistent. The size of the edge, and the control result, are the concern. I found no source that reports crypto per-trade R figures to compare against.

### Cited Findings
- Published results are portfolio Sharpe ratios, not per-trade statistics, so win rates and payoff are not reported in the sources I read. See section 1.
- Fieberg et al. and Svogun/Bazan-Palomino both find results concentrated in bull or bubble periods. — [ICM repository](https://open.icm.edu.pl/handle/123456789/25544), [IDEAS](https://ideas.repec.org/a/eee/finana/v86y2023ics1057521923000327.html)

### Inferences
- A random-entry control scoring +0.03R to +0.11R with the same trailing exit says the exit and the bull-heavy drift of the sample carry much of the edge. That matches the literature's finding that long-only crypto strategies partly harvest positive drift (Bui and Nguyen justify a 70/30 allocation by crypto's positive drift). — [arXiv](https://arxiv.org/pdf/2602.11708)
- Failing a week-clustered margin test is expected when returns concentrate in a few trend weeks; independent-trade statistics overstate significance. I did not find a crypto paper on this clustering problem. Standard practitioner handling (block bootstrap, portfolio-level Sharpe with vol targeting, many uncorrelated markets) is my background knowledge, not sourced here.

### Gaps
- No sourced practitioner treatment of clustered returns in crypto. No source on payoff ratios or best-trade R.

## 6. Replication and decay (post-2021, ETF era)

### Takeaway
Mixed and thin. Several sources report weakening after 2021-2022, but they are weak sources, and the one 2022-2024 preprint reports strong results.

### Cited Findings
- Fieberg et al.: abnormal returns weaken over time and sit mostly in bull markets. — [ICM repository](https://open.icm.edu.pl/handle/123456789/25544)
- Swinkels: time-series momentum seemed to disappear after Bitcoin futures (2017). — [Zenodo](https://zenodo.org/records/7326524) (low confidence)
- Hudson and Urquhart: no out-of-sample BTC predictability. — [Hull repository](https://hull-repository.worktribe.com/output/2328042)
- Bui and Nguyen: Sharpe 2.41 in 2022-2024 (counter-evidence, unreviewed). — [arXiv](https://arxiv.org/pdf/2602.11708)
- K33 (2026): drawdown from the cycle peak about 54% versus 77.5-85% in earlier bear markets, with ETPs absorbing more than 14,000 BTC. This points to a more institutional, less volatile BTC, but it is commentary. — [FXStreet](https://www.fxstreet.com/cryptocurrencies/news/bitcoin-reclaims-key-moving-averages-altering-bear-cycle-pattern-k33-202609222010)

### Gaps
- No ETF-era academic study of trend profitability found. No Kaiko, Glassnode, Coin Metrics, Galaxy, Grayscale or Bitwise trend-decay research located.

## 7. Critical view: survivorship, look-ahead, snooping, overfitting

### Takeaway
Most positive results are in-sample or lightly out-of-sample, and honest holdouts shrink effects, often by half or more.

### Cited Findings
- Honest out-of-sample tests I found: Hudson/Urquhart (holdout, BTC fails), Multi-Factor Inception (about 50% decay train/test), Grobys papers (sample dependence). — links in sections 1-2
- Zarattini et al. state a survivorship-free dataset and test from 2015; Bui and Nguyen select assets by rolling Sharpe with a market-cap filter, a selection step that needs strict point-in-time implementation to avoid look-ahead. — [IDEAS](https://ideas.repec.org/p/chf/rpseri/rp2580.html), [arXiv](https://arxiv.org/pdf/2602.11708)
- Unrelated asset class but relevant: Hutchinson et al. (currencies) found mean Sharpe falling from 0.66 in sample to 0.06 out of sample, and returns not surviving modest costs. — [ADU repository](https://repository.adu.ac.ae/items/0406b1a3-d199-455b-858b-871e9ee35040)

### Inferences
- The lab's own 20-perp universe is probably survivor-biased (perps listed today with 3 years of history), and the 5-of-10 variant pass count means the multiple-testing burden is real. Both are consistent with the literature's caution; the stricter cluster test failing is the more credible reading.
- Rough count: of about eleven sources here, only three (Hudson/Urquhart, Multi-Factor Inception, Grobys follow-up) show a meaningful holdout, and two of those show decay or failure.

### Gaps
- No systematic count of honest out-of-sample tests in crypto trend literature was found; the count above is an informal tally of what this pass surfaced.
