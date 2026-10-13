// Draait de push-regel van de service worker met nagebootste browserobjecten: toont hij de melding en zet hij het getal op het appicoon.
const fs = require("fs");
const src = fs.readFileSync(process.argv[2], "utf8");

async function scenario(payload, withApi) {
  const listeners = {}, log = { shown: 0, badge: [] };
  const nav = withApi ? { setAppBadge: async (n) => { log.badge.push(["set", n]); }, clearAppBadge: async () => { log.badge.push(["clear"]); } } : {};
  const fakeSelf = {
    addEventListener: (n, f) => { listeners[n] = f; }, location: { origin: "https://hespulse.test" }, skipWaiting() {}, clients: { claim() {} },
    registration: { showNotification: async () => { log.shown += 1; } }, navigator: nav,
  };
  const fakeCaches = { open: async () => ({ put: async () => {}, match: async () => null }), keys: async () => [], delete: async () => true };
  new Function("self", "caches", "clients", "Response", "URL", "fetch", src)(
    fakeSelf, fakeCaches, { matchAll: async () => [], openWindow: async () => {}, claim() {} }, Response, URL, async () => { throw new Error("offline"); });
  const event = { data: { json: () => payload }, waitUntil(p) { this.p = p; } };
  listeners.push(event);
  await event.p;
  return log;
}

(async () => {
  const base = { title: "t", body: "b", url: "/smc" };
  console.log(JSON.stringify({
    three: await scenario({ ...base, badge: 3 }, true),
    zero: await scenario({ ...base, badge: 0 }, true),
    none: await scenario(base, true),
    noApi: await scenario({ ...base, badge: 2 }, false),
  }));
})();
