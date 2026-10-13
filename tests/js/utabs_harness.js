// Minimale nep-DOM: een tabgroep met twee paneeltabs en twee panelen. Klik op tab 2 en print wat zichtbaar is.
const fs = require("fs"), vm = require("vm");

function classList(el) {
  return {
    toggle(c, on) { const s = el._c; if (on) s.add(c); else s.delete(c); },
    add(c) { el._c.add(c); },
  };
}
function node(attrs) {
  const el = { _c: new Set(), _a: Object.assign({}, attrs), id: (attrs && attrs.id) || "" };
  el.classList = classList(el);
  el.getAttribute = (k) => (k in el._a ? el._a[k] : null);
  el.setAttribute = (k, v) => { el._a[k] = v; };
  return el;
}

const tabA = node({ href: "#tab-a", "aria-selected": "true" });
const tabB = node({ href: "#tab-b", "aria-selected": "false" });
const panelA = node({ id: "tab-a" }), panelB = node({ id: "tab-b" });
const listeners = {};
const group = node({ "data-utabs": "main" });
group.querySelectorAll = () => [tabA, tabB];
group.querySelector = () => null;
group.addEventListener = (type, fn) => { listeners[type] = fn; };
const panels = node({});
panels.querySelectorAll = () => [panelA, panelB];

const ctx = {
  location: { hash: "" },
  history: { replaceState(_s, _t, h) { ctx.location.hash = h; } },
  Event: function (t) { this.type = t; },
  document: {
    querySelector: () => panels,
    querySelectorAll: (sel) => (sel === "[data-utabs]" ? [group] : []),
  },
};
ctx.window = ctx;
ctx.dispatchEvent = () => {};
vm.createContext(ctx);
vm.runInContext(fs.readFileSync(process.argv[2], "utf8"), ctx);

// Zonder hash en met tab B al als actief gemarkeerd (server-rendered): B blijft staan, niet A.
const noHash = (() => {
  tabA._c.delete("is-active"); tabB._c.add("is-active"); ctx.location.hash = "";
  panelA._c.delete("is-shown"); panelB._c.delete("is-shown");
  group.querySelector = (sel) => (sel === ".ut-tab.is-active" ? tabB : null);
  vm.runInContext(fs.readFileSync(process.argv[2], "utf8"), ctx);
  return panelB._c.has("is-shown") && !panelA._c.has("is-shown") ? "tab-b" : "fout";
})();
tabA._c.add("is-active"); tabB._c.delete("is-active");
listeners.click({ target: { closest: () => tabB }, preventDefault() {} });
const shown = [panelA, panelB].filter((p) => p._c.has("is-shown")).map((p) => p.id);
console.log(JSON.stringify({
  shown: shown.length === 1 ? shown[0] : shown,
  selected: [tabA.getAttribute("aria-selected"), tabB.getAttribute("aria-selected")],
  hash: ctx.location.hash,
  noHashActive: noHash,
}));
