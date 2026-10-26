// HesPulse service worker. Drie taken: de site installeerbaar maken, een nieuwe versie pas laden als de gebruiker op de updatemelding tikt,
// en offline de laatst bekende Radar en Vandaag tonen met een balk "Offline, laatst bijgewerkt om HH:MM" (base.html).
// Verouderde handelsdata tonen alsof het actueel is, is voor een trading tool gevaarlijker dan geen data. Daarom is alles netwerk-eerst: een
// bewaarde pagina komt alleen terug als het netwerk faalt, en dan altijd met die balk. /api, POST en push gaan nooit door een cache.
// Verhoog SW_VERSION bij elke wijziging aan dit bestand (tests/test_pwa.py bewaakt dat): de nieuwe versie wacht dan op de updatemelding.
const SW_VERSION = 3;
const CACHE_NAME = "hespulse-shell-v" + SW_VERSION;
const PAGES_CACHE = "hespulse-pages-v" + SW_VERSION;
const NAV_CACHE = "hespulse-nav";
const PRECACHE_URLS = [
  "/static/offline.html",
  "/static/manifest.json",
  "/static/icon-192.png",
  "/static/icon-512.png",
  "/static/hespulse-logo.svg",
];
// Alleen deze paden, sleutel zonder query: /vandaag?bron=app (de start vanaf het beginscherm) en /vandaag delen één bewaarde versie.
const OFFLINE_PAGES = ["/vandaag", "/smc"];

self.addEventListener("install", (event) => {
  // Geen skipWaiting hier: een open pagina mag niet halverwege van versie wisselen. pwa.js toont de updatemelding en stuurt SKIP_WAITING.
  event.waitUntil(caches.open(CACHE_NAME).then((cache) => cache.addAll(PRECACHE_URLS)));
});

self.addEventListener("activate", (event) => {
  const keep = [CACHE_NAME, PAGES_CACHE, NAV_CACHE];
  event.waitUntil(
    caches.keys().then((keys) =>
      Promise.all(keys.filter((k) => k.startsWith("hespulse-") && !keep.includes(k)).map((k) => caches.delete(k)))
    )
  );
  self.clients.claim();
});

self.addEventListener("message", (event) => {
  const type = event.data && event.data.type;
  if (type === "SKIP_WAITING") self.skipWaiting();
  // Uitloggen: de pagina's van deze kijker mogen niet blijven staan voor wie hierna op dit apparaat inlogt.
  if (type === "hp-logout") event.waitUntil(caches.delete(PAGES_CACHE));
});

function pageKey(url) {
  const u = new URL(url);
  return u.origin === self.location.origin && OFFLINE_PAGES.includes(u.pathname) ? u.pathname : null;
}

async function savePage(key, res) {
  // Alleen een echte pagina van een ingelogde kijker: de server zet X-HP-Viewer (afgeleid van het gebruikers-id, zie web/main.py). Een
  // omleiding (naar /login, of de CEO van de appstart naar /ceo) is niet de pagina zelf.
  const viewer = res.headers.get("X-HP-Viewer");
  if (!res.ok || res.redirected || !viewer) return;
  const cache = await caches.open(PAGES_CACHE);
  // Een andere kijker op dit apparaat: eerst alles van de vorige weg, nooit twee kijkers naast elkaar in de cache.
  for (const req of await cache.keys()) {
    const old = await cache.match(req);
    if (!old || old.headers.get("X-HP-Viewer") !== viewer) await cache.delete(req);
  }
  const headers = new Headers(res.headers);
  headers.set("X-HP-Saved-At", new Date().toISOString());
  await cache.put(self.location.origin + key, new Response(await res.blob(), { status: 200, headers }));
}

async function savedPage(key) {
  const cache = await caches.open(PAGES_CACHE);
  const hit = await cache.match(self.location.origin + key);
  if (!hit) return null;
  // De pagina leest dit merkteken en toont de offline-balk met de tijd; zonder merkteken zou een oude pagina eruitzien als live.
  const at = hit.headers.get("X-HP-Saved-At") || "";
  const html = (await hit.text()).replace("<head>", '<head><meta name="hp-offline-at" content="' + at + '">');
  return new Response(html, { status: 200, headers: { "Content-Type": "text/html; charset=utf-8" } });
}

self.addEventListener("fetch", (event) => {
  const req = event.request;
  if (req.method !== "GET") return;
  const url = new URL(req.url);
  if (url.origin !== self.location.origin || url.pathname.startsWith("/api/")) return;

  if (req.mode === "navigate") {
    const key = pageKey(req.url);
    event.respondWith(
      fetch(req)
        .then((res) => {
          if (res.redirected && new URL(res.url).pathname === "/login") event.waitUntil(caches.delete(PAGES_CACHE));
          else if (key && !res.redirected) event.waitUntil(savePage(key, res.clone()));
          return res;
        })
        .catch(async () => (key && (await savedPage(key))) || caches.match("/static/offline.html"))
    );
    return;
  }

  // Statische bestanden: netwerk eerst, met de laatst bekende versie als reserve zodat een bewaarde pagina offline zijn opmaak houdt. Sleutel
  // zonder ?v=: elke nieuwe versie overschrijft de vorige in plaats van zich op te stapelen.
  if (url.pathname.startsWith("/static/")) {
    const key = self.location.origin + url.pathname;
    event.respondWith(
      fetch(req)
        .then((res) => {
          if (res.ok) {
            const clone = res.clone();
            event.waitUntil(caches.open(CACHE_NAME).then((cache) => cache.put(key, clone)));
          }
          return res;
        })
        .catch(async () => (await caches.match(key)) || Response.error())
    );
  }
});

self.addEventListener("push", (event) => {
  if (!event.data) return;
  const data = event.data.json();
  const tasks = [
    self.registration.showNotification(data.title, {
      body: data.body,
      icon: data.icon,
      silent: !!data.silent,
      // Een nieuwere melding voor dezelfde coin en soort vervangt de vorige in plaats van te stapelen.
      tag: data.tag || undefined,
      renotify: !!data.tag && !data.silent,
      data: { url: data.url },
    }),
  ];
  // Het getal op het appicoon (kansen in de zone) komt alleen mee bij een zone-melding. Zonder Badging API (oudere browsers, iOS buiten
  // een geïnstalleerde app) blijft het bij de melding.
  const nav = self.navigator;
  if (typeof data.badge === "number" && nav && "setAppBadge" in nav) {
    try {
      tasks.push((data.badge > 0 ? nav.setAppBadge(data.badge) : nav.clearAppBadge()).catch(() => {}));
    } catch (e) {}
  }
  event.waitUntil(Promise.all(tasks));
});

self.addEventListener("notificationclick", (event) => {
  event.notification.close();
  const relativeUrl = event.notification.data && event.notification.data.url;
  if (!relativeUrl) return;
  // Absoluut pad, niet het kale relatieve pad dat de server meestuurt (clients.openWindow met een relatief pad is op iOS/WebKit onbetrouwbaar).
  const targetUrl = new URL(relativeUrl, self.location.origin).href;
  event.waitUntil((async () => {
    // Twee wegen, omdat iOS in een geïnstalleerde app de link vaak negeert: client.navigate doet niets op een open app en openWindow opent bij een koude
    // start de startpagina. (1) De open app krijgt een bericht en navigeert zelf. (2) De bestemming staat kort in een cache; de pagina leest die bij het
    // laden en gaat er alsnog heen (zie smooth.js).
    try {
      const cache = await caches.open(NAV_CACHE);
      await cache.put("/__pending-nav", new Response(JSON.stringify({ url: targetUrl, at: Date.now() }), { headers: { "Content-Type": "application/json" } }));
    } catch (e) { /* zonder cache valt alleen de koude-startroute weg */ }
    const windowClients = await clients.matchAll({ type: "window", includeUncontrolled: true });
    for (const client of windowClients) {
      if ("focus" in client) {
        try { await client.focus(); } catch (e) { /* focus mislukt: het bericht hieronder werkt toch */ }
        client.postMessage({ hespulseNavigate: targetUrl });
        return;
      }
    }
    return clients.openWindow(targetUrl);
  })());
});
