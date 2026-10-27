// Laadt ladder.js zonder DOM en geeft de pure maths terug, zodat de test ze naast app/ladder.py kan leggen.
const fs = require("fs"), vm = require("vm");
const ctx = {};
vm.createContext(ctx);
vm.runInContext(fs.readFileSync(process.argv[2], "utf8"), ctx);
const m = ctx.hesLadderMath;
const ys = [[107.5, 110, 100], [130, 110, 100], [90, 110, 100], [80800, 81300, 80000]].map(a => m.y(a[0], a[1], a[2]));
const ds = [["short", 100, 98], ["long", 100, 102], ["short", 80774.8, 80537]].map(a => m.distance(a[0], a[1], a[2]));
const nls = [80774.8, 102, 0.1702, 2.5].map(v => m.nl(v));
const gap = m.gap(101, 102, null, 99, 110, 90);
const inZone = m.gap(101, 102, null, 101.5, 110, 90);
const noZone = m.gap(null, null, 100, 104, 110, 90);
console.log(JSON.stringify({ ys, ds, nls, gap, inZone, noZone, stale: [m.stale(null), m.stale(30), m.stale(45), m.stale(150), m.stale(7300)] }));
