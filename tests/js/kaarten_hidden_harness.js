// Laadt kaarten.js zonder blad en toetst de tekst van de ongedaan-balk en de regel "Verborgen (N)", die gelijk moeten zijn aan app/kansen.py.
const fs = require("fs"), vm = require("vm");
const ctx = { document: { querySelector: () => null, querySelectorAll: () => [] } };
ctx.window = ctx;
vm.createContext(ctx);
vm.runInContext(fs.readFileSync(process.argv[2], "utf8"), ctx);
console.log(JSON.stringify({
  text: [["HYPE short"], ["HYPE short", "ETH long", "SOL long"], ["A", "B"]].map((t) => ctx.hesHiddenText(t)),
  label: [0, 1, 7].map((n) => ctx.hesHiddenLabel(n)),
}));
