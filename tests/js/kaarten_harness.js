// Laadt kaarten.js zonder blad (de pagina-code stopt dan meteen) en toetst de zin met de tellers, die gelijk moet zijn aan kansen.summary.
const fs = require("fs"), vm = require("vm");
const ctx = { document: { querySelector: () => null, querySelectorAll: () => [] } };
ctx.window = ctx;
vm.createContext(ctx);
vm.runInContext(fs.readFileSync(process.argv[2], "utf8"), ctx);
const s = ctx.hesKansenSummary;
const cases = [[0, 0, 0], [1, 0, 0], [1, 1, 0], [12, 2, 3], [0, 0, 1], [2, 0, 1]];
console.log(JSON.stringify(cases.map((c) => s(c[0], c[1], c[2]))));
