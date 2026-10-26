// Laadt smooth.js met kale stubs en trekt de pagina met nagebootste aanrakingen omlaag: ververst hij wel of niet, en beweegt de hint.
const fs = require("fs"), vm = require("vm");
const src = fs.readFileSync(process.argv[2], "utf8");

async function pull({ dy = 120, dx = 0, scrollY = 0, reduce = false, hasRefresh = true, target = null }) {
  const docL = {}, log = { refreshed: 0, reloaded: 0, transforms: [] };
  const hint = { style: {}, setAttribute() {}, set textContent(v) { log.text = v; }, get textContent() { return log.text; } };
  const styleProxy = new Proxy({}, { set(o, k, v) { if (k === "transform") log.transforms.push(v); o[k] = v; return true; } });
  hint.style = styleProxy;
  const win = { addEventListener() {}, matchMedia: () => ({ matches: reduce }), scrollY };
  if (hasRefresh) win.hesRefresh = () => { log.refreshed += 1; return Promise.resolve(true); };
  const ctx = {
    location: { origin: "https://x.test", href: "https://x.test/smc", reload() { log.reloaded += 1; } }, URL, Date, Promise,
    setInterval: () => 0, setTimeout: () => 0, caches: undefined, navigator: {},
    document: { addEventListener: (n, f) => { docL[n] = f; }, querySelector: () => null, querySelectorAll: () => [], title: "",
                createElement: () => hint, body: { appendChild() {} } },
    window: win,
  };
  vm.createContext(ctx);
  vm.runInContext(src, ctx);
  const el = target || { closest: () => null };
  const touch = (x, y) => ({ touches: [{ clientX: x, clientY: y }], target: el });
  docL.touchstart(touch(100, 100));
  for (let i = 1; i <= 6; i++) docL.touchmove(touch(100 + (dx * i) / 6, 100 + (dy * i) / 6));
  docL.touchend({ touches: [] });
  await Promise.resolve(); await Promise.resolve();
  return log;
}

(async () => {
  const out = {
    pulled: await pull({}),
    short: await pull({ dy: 40 }),
    scrolled: await pull({ scrollY: 300 }),
    sideways: await pull({ dy: 90, dx: 160 }),
    upwards: await pull({ dy: -150 }),
    reduced: await pull({ reduce: true }),
    noRefresh: await pull({ hasRefresh: false }),
    inChart: await pull({ target: { closest: (sel) => (sel.indexOf("[data-levelchart]") !== -1 ? {} : null) } }),
  };
  out.reducedMoves = out.reduced.transforms.some((t) => !/,\s*0px\)$/.test(t));
  out.pulledMoves = out.pulled.transforms.some((t) => !/,\s*0px\)$/.test(t));
  for (const k of Object.keys(out)) if (out[k] && out[k].transforms) delete out[k].transforms;
  console.log(JSON.stringify(out));
})();
