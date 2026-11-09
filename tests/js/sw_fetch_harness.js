// Draait de install-, activate-, message- en fetch-regels van de service worker met een nagebootste Cache API en fetch, en geeft per
// scenario terug wat er gecachet, geserveerd of gewist werd.
const fs = require("fs");
const src = fs.readFileSync(process.argv[2], "utf8");
const ORIGIN = "https://hespulse.test";

function makeCaches() {
  const stores = {};
  const keyOf = (k, opts) => {
    const u = new URL(typeof k === "string" ? k : k.url, ORIGIN);
    return opts && opts.ignoreSearch ? u.origin + u.pathname : u.href;
  };
  const api = {
    stores,
    open: async (name) => {
      const m = (stores[name] = stores[name] || new Map());
      return {
        put: async (k, v) => { m.set(keyOf(k), v); },
        match: async (k, o) => {
          const key = keyOf(k, o);
          for (const [kk, v] of m) if ((o && o.ignoreSearch ? kk.split("?")[0] : kk) === key) return v.clone();
          return undefined;
        },
        delete: async (k) => m.delete(keyOf(k)),
        keys: async () => [...m.keys()].map((url) => ({ url })),
        addAll: async (urls) => { for (const u of urls) m.set(keyOf(u), new Response("precached " + u, { headers: { "Content-Type": "text/html" } })); },
      };
    },
    match: async (k, o) => {
      for (const name of Object.keys(stores)) {
        const hit = await (await api.open(name)).match(k, o);
        if (hit) return hit;
      }
      return undefined;
    },
    keys: async () => Object.keys(stores),
    delete: async (n) => { const had = n in stores; delete stores[n]; return had; },
  };
  return api;
}

function page(body, { viewer, redirectedTo } = {}) {
  const headers = { "Content-Type": "text/html; charset=utf-8" };
  if (viewer) headers["X-HP-Viewer"] = viewer;
  const res = new Response(body, { status: 200, headers });
  if (redirectedTo) {
    Object.defineProperty(res, "redirected", { value: true });
    Object.defineProperty(res, "url", { value: ORIGIN + redirectedTo });
  }
  return res;
}

function boot() {
  const listeners = {}, log = { skipWaiting: 0 };
  const caches = makeCaches();
  let network = null;               // functie (url, req) -> Response; null = offline
  const fakeSelf = {
    addEventListener: (n, f) => { listeners[n] = f; }, location: { origin: ORIGIN },
    skipWaiting() { log.skipWaiting += 1; return Promise.resolve(); }, clients: { claim() {} }, registration: {},
  };
  const fetchFn = async (req) => {
    if (!network) throw new TypeError("offline");
    return network(new URL(typeof req === "string" ? req : req.url, ORIGIN).pathname + (new URL(typeof req === "string" ? req : req.url, ORIGIN).search), req);
  };
  new Function("self", "caches", "clients", "Response", "URL", "fetch", src)(
    fakeSelf, caches, { matchAll: async () => [], openWindow: async () => {}, claim() {} }, Response, URL, fetchFn);

  async function settle(event) {
    let seen = 0;
    while (seen < event.waits.length) { const batch = event.waits.slice(seen); seen = event.waits.length; await Promise.allSettled(batch); }
  }
  async function lifecycle(name, data) {
    const event = { waits: [], waitUntil(p) { this.waits.push(p); }, data };
    listeners[name](event);
    await settle(event);
  }
  async function request(path, { method = "GET", mode = "navigate" } = {}) {
    const event = {
      request: { url: ORIGIN + path, method, mode, headers: new Headers() },
      responded: null, waits: [],
      respondWith(p) { this.responded = p; }, waitUntil(p) { this.waits.push(p); },
    };
    listeners.fetch(event);
    let out = { handled: !!event.responded };
    if (event.responded) {
      const res = await event.responded;
      out.text = res ? await res.text() : null;
    }
    await settle(event);
    return out;
  }
  async function stored(prefix) {
    const out = {};
    for (const name of Object.keys(caches.stores)) {
      if (!name.startsWith(prefix)) continue;
      for (const [k, v] of caches.stores[name]) out[new URL(k).pathname + new URL(k).search] = { viewer: v.headers.get("X-HP-Viewer"), saved: !!v.headers.get("X-HP-Saved-At") };
    }
    return out;
  }
  return { listeners, log, caches, lifecycle, request, stored, setNetwork: (f) => { network = f; } };
}

(async () => {
  const out = {};

  // Installeren: alleen de schil voorcachen, niet zelf doorschuiven (dat doet de gebruiker met de updatemelding).
  let sw = boot();
  await sw.lifecycle("install");
  out.install = { skipWaiting: sw.log.skipWaiting, shell: Object.keys(sw.caches.stores) };
  await sw.lifecycle("message", { type: "SKIP_WAITING" });
  out.install.afterMessage = sw.log.skipWaiting;

  // Activeren: oude schilcaches weg, de huidige schil, de pagina's en de meldingsbestemming blijven.
  sw = boot();
  for (const n of ["hespulse-shell-v1", "hespulse-shell-v2", "hespulse-pages-v0", "hespulse-nav", "iets-anders"]) await sw.caches.open(n);
  await sw.lifecycle("install");
  sw.setNetwork(() => page("<html><head></head><body>r</body></html>", { viewer: "kijker-a" }));
  await sw.request("/smc");
  await sw.lifecycle("activate");
  out.activate = Object.keys(sw.caches.stores);

  // Geen /api, geen POST, geen push-aanroepen: de service worker raakt ze niet aan.
  sw = boot();
  sw.setNetwork(() => new Response("{}", { headers: { "Content-Type": "application/json" } }));
  out.untouched = {
    apiGet: (await sw.request("/api/radar", { mode: "cors" })).handled,
    apiNavigate: (await sw.request("/api/vandaag")).handled,
    post: (await sw.request("/api/push/subscribe", { method: "POST", mode: "cors" })).handled,
    postNavigate: (await sw.request("/logout", { method: "POST" })).handled,
    pushPreview: (await sw.request("/push/voorbeeld", { method: "POST" })).handled,
  };
  out.untouched.stored = await sw.stored("");

  // Online: Radar en Vandaag worden per pad bewaard (zonder query), andere pagina's niet.
  sw = boot();
  await sw.lifecycle("install");
  sw.setNetwork((p) => page("<html><head><title>" + p + "</title></head><body>pagina " + p + "</body></html>", { viewer: "kijker-a" }));
  out.online = { smc: (await sw.request("/smc")).text };
  await sw.request("/vandaag?bron=app");
  await sw.request("/kans/5");
  await sw.request("/bewijs");
  out.online.stored = await sw.stored("hespulse-pages");

  // Offline: de laatst bekende Radar met een markering, een onbekende pagina krijgt de offline-pagina.
  sw.setNetwork(null);
  out.offline = {
    smc: (await sw.request("/smc")).text,
    vandaagFromApp: (await sw.request("/vandaag?bron=app")).text,
    kans: (await sw.request("/kans/5")).text,
    staticMiss: (await sw.request("/static/onbekend.js", { mode: "no-cors" })).text,
  };

  // Een andere kijker online: wat van de vorige kijker was, gaat eerst weg.
  sw.setNetwork((p) => page("<html><head></head><body>van b " + p + "</body></html>", { viewer: "kijker-b" }));
  await sw.request("/vandaag");
  out.otherViewer = await sw.stored("hespulse-pages");

  // Sessie verlopen: een omleiding naar /login wist de bewaarde pagina's.
  sw.setNetwork((p) => page("<html><head></head><body>login</body></html>", { redirectedTo: "/login" }));
  await sw.request("/smc");
  out.loginRedirect = await sw.stored("hespulse-pages");

  // De CEO wordt van /vandaag?bron=app naar /ceo gestuurd: dat antwoord is niet de Vandaag-pagina en wordt niet bewaard.
  sw.setNetwork((p) => page("<html><head></head><body>ceo</body></html>", { viewer: "kijker-a", redirectedTo: "/ceo" }));
  await sw.request("/vandaag?bron=app");
  out.ceoRedirect = await sw.stored("hespulse-pages");

  // Zonder kijker-kop (niet ingelogd of een oude server) wordt niets bewaard.
  sw.setNetwork((p) => page("<html><head></head><body>anoniem</body></html>"));
  await sw.request("/smc");
  out.noViewer = await sw.stored("hespulse-pages");

  // Uitloggen: de pagina stuurt een bericht en alles van de kijker is weg.
  sw.setNetwork((p) => page("<html><head></head><body>x</body></html>", { viewer: "kijker-a" }));
  await sw.request("/smc");
  const before = Object.keys(await sw.stored("hespulse-pages")).length;
  await sw.lifecycle("message", { type: "hp-logout" });
  out.logout = { before, after: await sw.stored("hespulse-pages") };

  // Statische bestanden: netwerk eerst, offline de laatst bekende versie, ook als de ?v= intussen anders is.
  sw = boot();
  sw.setNetwork((p) => new Response("css " + p, { headers: { "Content-Type": "text/css" } }));
  await sw.request("/static/style.css?v=1", { mode: "no-cors" });
  sw.setNetwork(null);
  out.staticOffline = (await sw.request("/static/style.css?v=2", { mode: "no-cors" })).text;

  console.log(JSON.stringify(out));
})();
