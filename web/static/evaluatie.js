(function () {
  const container = document.getElementById("eval-chart");
  if (!container || typeof evalBalanceCurve === "undefined" || !evalBalanceCurve.length) return;

  const startRect = container.getBoundingClientRect();
  const chart = LightweightCharts.createChart(container, {
    width: Math.round(startRect.width) || window.innerWidth,
    height: Math.round(startRect.height) || 260,
    layout: { background: { color: "#131a1b" }, textColor: "#b7c4c2" },
    grid: { vertLines: { color: "#1c2526" }, horzLines: { color: "#1c2526" } },
    timeScale: { timeVisible: true, borderColor: "#232d2f" },
    rightPriceScale: { borderColor: "#232d2f" },
  });

  // Drawdown-bodem als basiswaarde: een baseline-serie kleurt zichzelf
  // groen boven en rood onder die ene prijs, dus de lijn toont zelf of
  // het saldo aan de veilige of gevaarlijke kant zit, zonder een losse,
  // door de library niet ondersteunde kleurverloop-hack.
  const drawdownFloor = (evalTierAmount && evalMaxDrawdownPct)
    ? evalTierAmount * (1 - evalMaxDrawdownPct / 100)
    : 0;

  const series = chart.addBaselineSeries({
    baseValue: { type: "price", price: drawdownFloor },
    topLineColor: "#33d69f", topFillColor1: "rgba(51, 214, 159, 0.28)", topFillColor2: "rgba(51, 214, 159, 0.05)",
    bottomLineColor: "#f2685c", bottomFillColor1: "rgba(242, 104, 92, 0.05)", bottomFillColor2: "rgba(242, 104, 92, 0.28)",
    lineWidth: 2,
  });

  // LightweightCharts eist strikt oplopende, unieke tijdstippen. Twee
  // trades die toevallig in dezelfde seconde sluiten zouden een reeks
  // met een gelijk of dalend tijdstip opleveren, wat de hele setData()
  // laat falen — vandaar de expliciete "minstens 1 seconde later dan het
  // vorige punt"-correctie, in plaats van aan te nemen dat exit_time
  // altijd al uniek oplopend is.
  let lastTime = -Infinity;
  const points = evalBalanceCurve.map((p) => {
    let t = Math.floor(new Date(p.time).getTime() / 1000);
    if (!Number.isFinite(t)) return null;
    if (t <= lastTime) t = lastTime + 1;
    lastTime = t;
    return { time: t, value: p.balance };
  }).filter(Boolean);

  series.setData(points);

  if (evalTierAmount && evalMaxDrawdownPct) {
    series.createPriceLine({
      price: drawdownFloor,
      color: "#f2685c", lineWidth: 1, lineStyle: LightweightCharts.LineStyle.Dashed,
      axisLabelVisible: true, title: "max drawdown",
    });
  }
  if (evalTierAmount && evalProfitTargetPct) {
    series.createPriceLine({
      price: evalTierAmount * (1 + evalProfitTargetPct / 100),
      color: "#33d69f", lineWidth: 1, lineStyle: LightweightCharts.LineStyle.Dashed,
      axisLabelVisible: true, title: "winstdoel",
    });
  }

  chart.timeScale().fitContent();

  new ResizeObserver((entries) => {
    const { width, height } = entries[0].contentRect;
    chart.applyOptions({ width: Math.round(width), height: Math.round(height) || 260 });
  }).observe(container);

  // Ademende vulling in de gevarenzone: canvas-rendering kan niet met
  // CSS-animaties bewogen worden, dus dit gebeurt via een interval dat de
  // opaciteit van de rode vulling laat pulseren — zelfde 85%-drempel als
  // .risk-pulse elders in de app, alleen actief op een lopende run, nooit
  // als het tabblad niet zichtbaar is, en helemaal niet bij
  // prefers-reduced-motion.
  const inDangerZone = evalIsActive && (evalDailyLossUsedPct >= 85 || evalDrawdownUsedPct >= 85);
  const reduceMotion = window.matchMedia && window.matchMedia("(prefers-reduced-motion: reduce)").matches;
  let pulseTimer = null;

  function startPulse() {
    if (pulseTimer) return;
    let dim = false;
    pulseTimer = setInterval(() => {
      dim = !dim;
      series.applyOptions({
        bottomFillColor1: dim ? "rgba(242, 104, 92, 0.02)" : "rgba(242, 104, 92, 0.10)",
        bottomFillColor2: dim ? "rgba(242, 104, 92, 0.10)" : "rgba(242, 104, 92, 0.32)",
      });
    }, 1200);
  }
  function stopPulse() {
    if (pulseTimer) { clearInterval(pulseTimer); pulseTimer = null; }
  }

  if (inDangerZone && !reduceMotion) {
    startPulse();
    document.addEventListener("visibilitychange", () => {
      if (document.hidden) stopPulse();
      else if (inDangerZone && !reduceMotion) startPulse();
    });
  }
})();
