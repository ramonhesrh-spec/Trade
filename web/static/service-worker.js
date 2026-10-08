// HesPulse service worker: bestaat alleen om de site installeerbaar te
// maken en een nette "geen verbinding" pagina te tonen, NIET om koersen,
// meldingen of trade-status offline beschikbaar te maken. Verouderde
// handelsdata tonen alsof het actueel is, is voor een trading tool
// gevaarlijker dan geen data tonen. Daarom: alleen de statische schil
// (logo, iconen, manifest, offline-pagina) wordt gecachet, en zelfs die
// altijd netwerk-eerst. Alle paginabezoeken en API-calls gaan gewoon naar
// het netwerk; alleen een mislukte paginabezoeken krijgt de offline-
// fallback.
const CACHE_NAME = "hespulse-shell-v2";
const PRECACHE_URLS = [
  "/static/offline.html",
  "/static/manifest.json",
  "/static/icon-192.png",
  "/static/icon-512.png",
  "/static/hespulse-logo.svg",
];

self.addEventListener("install", (event) => {
  event.waitUntil(
    caches.open(CACHE_NAME).then((cache) => cache.addAll(PRECACHE_URLS))
  );
  self.skipWaiting();
});

self.addEventListener("activate", (event) => {
  event.waitUntil(
    caches.keys().then((keys) =>
      Promise.all(keys.filter((k) => k !== CACHE_NAME && k !== "hespulse-nav").map((k) => caches.delete(k)))
    )
  );
  self.clients.claim();
});

self.addEventListener("fetch", (event) => {
  const req = event.request;
  if (req.method !== "GET") return;

  if (req.mode === "navigate") {
    event.respondWith(fetch(req).catch(() => caches.match("/static/offline.html")));
    return;
  }

  if (PRECACHE_URLS.some((url) => req.url.endsWith(url))) {
    event.respondWith(
      fetch(req)
        .then((res) => {
          const clone = res.clone();
          caches.open(CACHE_NAME).then((cache) => cache.put(req, clone));
          return res;
        })
        .catch(() => caches.match(req))
    );
  }
});

self.addEventListener("push", (event) => {
  if (!event.data) return;
  const data = event.data.json();
  event.waitUntil(
    self.registration.showNotification(data.title, {
      body: data.body,
      icon: data.icon,
      silent: !!data.silent,
      // Een nieuwere melding voor dezelfde coin en soort vervangt de vorige in plaats van te stapelen.
      tag: data.tag || undefined,
      renotify: !!data.tag && !data.silent,
      data: { url: data.url },
    })
  );
});

const NAV_CACHE = "hespulse-nav";

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
