// Laadt stale.js zonder DOM en toetst de pure toestandsfunctie.
const fs = require("fs"), vm = require("vm");
const ctx = {};
vm.createContext(ctx);
vm.runInContext(fs.readFileSync(process.argv[2], "utf8"), ctx);
const s = ctx.hesStaleState;
console.log(JSON.stringify({ unknown: s(null, 1000, 120000), fresh: s(0, 120000, 120000), stale: s(0, 120001, 120000) }));
