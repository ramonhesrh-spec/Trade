// Nep-DOM met één 24u-element zonder minigrafiek (zoals een markt-rij): het script moet toch ophalen en invullen.
const fs = require("fs"), vm = require("vm");

const set = new Set();
const chg = {
  textContent: "",
  classList: { toggle(c, on) { if (on) set.add(c); else set.delete(c); }, add(c) { set.add(c); } },
  getAttribute: (k) => (k === "data-spark-chg" ? "BTC" : null),
  hasAttribute: (k) => k === "data-spark-short",
};
let fetched = null;
const ctx = {
  document: {
    hidden: false,
    querySelectorAll: (sel) => (sel === "[data-spark-chg]" ? [chg] : []),
  },
  fetch: (url) => {
    fetched = decodeURIComponent(url.split("coins=")[1]);
    return Promise.resolve({ ok: true, json: () => Promise.resolve({ BTC: { path: "M0 0", change_pct: -0.9, change_text: "-0,9% 24u" } }) });
  },
  setInterval: () => 0,
};
vm.createContext(ctx);
vm.runInContext(fs.readFileSync(process.argv[2], "utf8"), ctx);
setTimeout(() => console.log(JSON.stringify({ text: chg.textContent, down: set.has("is-down"), fetched })), 20);
