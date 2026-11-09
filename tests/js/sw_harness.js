// Draait de notificationclick-regel van de service worker met nagebootste browserobjecten en geeft de waargenomen acties als JSON terug.
const fs = require("fs");
const src = fs.readFileSync(process.argv[2], "utf8");

async function scenario(openClients, focusFails) {
  const listeners = {}, log = { posted: [], opened: [], cached: [], focused: 0, closed: false };
  const cacheStore = {};
  const fakeCaches = {
    open: async () => ({ put: async (k, v) => { log.cached.push([k, JSON.parse(await v.text())]); }, match: async () => null, delete: async () => true }),
    keys: async () => [], delete: async () => true,
  };
  const clientList = openClients.map(() => ({
    focus: async () => { log.focused += 1; if (focusFails) throw new Error("focus"); },
    postMessage: (m) => log.posted.push(m),
  }));
  const fakeSelf = { addEventListener: (n, f) => { listeners[n] = f; }, location: { origin: "https://hespulse.test" }, skipWaiting() {}, clients: { claim() {} }, registration: {} };
  new Function("self", "caches", "clients", "Response", "URL", "fetch", src)(
    fakeSelf, fakeCaches,
    { matchAll: async () => clientList, openWindow: async (u) => { log.opened.push(u); }, claim() {} },
    Response, URL, async () => { throw new Error("offline"); });
  const event = { notification: { close() { log.closed = true; }, data: { url: "/kans/5" } }, waitUntil(p) { this.p = p; } };
  listeners.notificationclick(event);
  await event.p;
  return log;
}

(async () => {
  const out = {};
  out.openApp = await scenario([1], false);
  out.coldStart = await scenario([], false);
  out.focusFails = await scenario([1], true);
  console.log(JSON.stringify(out));
})();
