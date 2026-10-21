// Laadt levelchart.js zonder grafiekbibliotheek en zonder kaarten en toetst de pure functie die de vlakken bepaalt.
const fs = require("fs"), vm = require("vm");
const ctx = { window: {}, document: { querySelectorAll: () => [], documentElement: {} }, getComputedStyle: () => ({ getPropertyValue: () => "" }) };
vm.createContext(ctx);
vm.runInContext(fs.readFileSync(process.argv[2], "utf8"), ctx);
const api = ctx.window.hesLevelChart, areas = api.areas;
const zoneSpec = { zone: { tf: "4h", origin: 3600, note: "hier", note_other_tf: "elders", note_outside: "eerder" } };
console.log(JSON.stringify({
  open: areas({ entry: 100, limit: 100, stop: 97, take: 106 }),
  setup: areas({ entry: null, limit: 100, stop: 97, take: 106 }),
  short: areas({ entry: null, limit: 100, stop: 103, take: 94 }),
  noStop: areas({ entry: null, limit: 100, stop: null, take: 106 }),
  wrongSide: areas({ entry: null, limit: 100, stop: 103, take: 106 }),
  longStopAbove: areas({ entry: null, limit: 100, stop: 103, take: 94, direction: "long" }),
  rgbaHex: ctx.window.hesLevelChart.rgba("#f2685c", 0.1),
  rgbaOther: ctx.window.hesLevelChart.rgba("rgb(1,2,3)", 0.1, "rgba(242,104,92,0.1)"),
  rgbaNone: ctx.window.hesLevelChart.rgba("", 0.1),
  nothing: areas({ entry: null, limit: null, stop: 97, take: 106 }),
  limitBase: api.candleLimit("1h", null, 1000000),
  limitOld: api.candleLimit("1h", 1000000 - 150 * 3600, 1000000),
  limitCap: api.candleLimit("4h", 1000000 - 900 * 14400, 1000000),
  limit15: api.candleLimit("15m", 1000000 - 3600, 1000000),
  barSame: api.originBar([0, 3600, 7200], 3600, "1h"),
  barInside: api.originBar([0, 14400, 28800], 18000, "4h"),
  barBefore: api.originBar([3600, 7200], 0, "1h"),
  barAfter: api.originBar([0, 3600], 7200, "1h"),
  barNone: api.originBar([], 3600, "1h"),
  tfZone: api.fullTf({ zone: { tf: "4h" } }),
  tfPlain: api.fullTf({ zone: null }),
  noteSame: api.fullNote(zoneSpec, "4h", 3600),
  noteOther: api.fullNote(zoneSpec, "1h", 3600),
  noteOutside: api.fullNote(zoneSpec, "4h", null),
  noteNoOrigin: api.fullNote({ zone: { tf: "4h", origin: null, note: null } }, "4h", null),
  noteNoZone: api.fullNote({ zone: null }, "1h", null),
}));
