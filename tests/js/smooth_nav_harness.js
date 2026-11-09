// Laadt smooth.js met kale stubs en toetst de navigatie na een tik op een melding: bij het laden, bij terugkeer naar de app en bij een verlopen bestemming.
const fs = require("fs"), vm = require("vm");
function run(pending, event) {
  const docL = {}, winL = {};
  const store = pending ? { "/__pending-nav": { json: async () => pending } } : {};
  const cache = { match: async (k) => store[k], delete: (k) => { delete store[k]; } };
  const location = { origin: "https://x.test", href: "https://x.test/vandaag" };
  const ctx = {
    location, URL, Date, Promise, setInterval: () => 0, setTimeout: () => 0,
    caches: { open: async () => cache },
    navigator: { serviceWorker: { addEventListener: () => {} } },
    document: { addEventListener: (n, f) => { docL[n] = f; }, querySelector: () => null, querySelectorAll: () => [], visibilityState: "hidden", title: "" },
    window: { addEventListener: (n, f) => { winL[n] = f; }, matchMedia: () => ({ matches: false }), scrollY: 0 },
  };
  ctx.window.caches = ctx.caches;
  vm.createContext(ctx);
  vm.runInContext(fs.readFileSync(process.argv[2], "utf8"), ctx);
  return new Promise((resolve) => setTimeout(async () => {
    if (event === "visible") { ctx.document.visibilityState = "visible"; docL.visibilitychange(); }
    await new Promise((r) => setImmediate(r)); await new Promise((r) => setImmediate(r)); await new Promise((r) => setImmediate(r));
    resolve({ href: location.href, left: Object.keys(store).length });
  }, 0));
}
(async () => {
  const now = Date.now();
  const out = {
    onLoad: await run({ url: "https://x.test/structuur#tab-ranges", at: now }),
    onReturn: await run(null, "visible"),
    stale: await run({ url: "https://x.test/structuur", at: now - 300000 }),
  };
  // Bij terugkeer: de bestemming komt pas binnen nadat de app al geladen was.
  const docL = {}, store = {};
  const cache = { match: async (k) => store[k], delete: (k) => { delete store[k]; } };
  const location = { origin: "https://x.test", href: "https://x.test/vandaag" };
  const ctx = { location, URL, Date, Promise, setInterval: () => 0, setTimeout: () => 0, caches: { open: async () => cache },
    navigator: { serviceWorker: { addEventListener: () => {} } },
    document: { addEventListener: (n, f) => { docL[n] = f; }, querySelector: () => null, querySelectorAll: () => [], visibilityState: "hidden", title: "" },
    window: { addEventListener: () => {}, matchMedia: () => ({ matches: false }), scrollY: 0 } };
  ctx.window.caches = ctx.caches;
  vm.createContext(ctx);
  vm.runInContext(fs.readFileSync(process.argv[2], "utf8"), ctx);
  await new Promise((r) => setImmediate(r));
  store["/__pending-nav"] = { json: async () => ({ url: "https://x.test/structuur#tab-ranges", at: Date.now() }) };
  ctx.document.visibilityState = "visible"; docL.visibilitychange();
  for (let i = 0; i < 4; i++) await new Promise((r) => setImmediate(r));
  out.afterBackground = { href: location.href };
  // Koude start: de bestemming komt binnen nadat de pagina al geladen was en er geen terugkeer of focus meer volgt. Alleen de herhaalde controle vangt dat op.
  const timers = [], store2 = {};
  const cache2 = { match: async (k) => store2[k], delete: (k) => { delete store2[k]; } };
  const location2 = { origin: "https://x.test", href: "https://x.test/ceo" };
  const ctx2 = { location: location2, URL, Date, Promise, setInterval: (f) => { timers.push(f); return timers.length; }, clearInterval: () => {}, setTimeout: () => 0,
    caches: { open: async () => cache2 },
    navigator: { serviceWorker: { addEventListener: () => {} } },
    document: { addEventListener: () => {}, querySelector: () => null, querySelectorAll: () => [], visibilityState: "visible", title: "" },
    window: { addEventListener: () => {}, matchMedia: () => ({ matches: false }), scrollY: 0 } };
  ctx2.window.caches = ctx2.caches;
  vm.createContext(ctx2);
  vm.runInContext(fs.readFileSync(process.argv[2], "utf8"), ctx2);
  await new Promise((r) => setImmediate(r));
  store2["/__pending-nav"] = { json: async () => ({ url: "https://x.test/kans/7", at: Date.now() }) };
  timers.forEach((f) => f());
  for (let i = 0; i < 4; i++) await new Promise((r) => setImmediate(r));
  out.coldStart = { href: location2.href };
  console.log(JSON.stringify(out));
})();
