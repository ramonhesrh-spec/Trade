// HesPulse service worker: bestaat alleen om de site installeerbaar te
// maken en een nette "geen verbinding" pagina te tonen, NIET om koersen,
// meldingen of trade-status offline beschikbaar te maken. Verouderde
// handelsdata tonen alsof het actueel is, is voor een trading tool
// gevaarlijker dan geen data tonen. Daarom: alleen de statische schil
// (logo, iconen, manifest, offline-pagina) wordt gecachet, en zelfs die
// altijd netwerk-eerst. Alle paginabezoeken en API-calls gaan gewoon naar
// het netwerk; alleen een mislukte paginabezoeken krijgt de offline-
// fallback.
const CACHE_NAME = "hespulse-shell-v1";
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
      Promise.all(keys.filter((k) => k !== CACHE_NAME).map((k) => caches.delete(k)))
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
