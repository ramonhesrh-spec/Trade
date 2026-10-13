// Laadt levelchart.js zonder grafiekbibliotheek en zonder kaarten en toetst de pure functie die de vlakken bepaalt.
const fs = require("fs"), vm = require("vm");
const ctx = { window: {}, document: { querySelectorAll: () => [], documentElement: {} }, getComputedStyle: () => ({ getPropertyValue: () => "" }) };
vm.createContext(ctx);
vm.runInContext(fs.readFileSync(process.argv[2], "utf8"), ctx);
const areas = ctx.window.hesLevelChart.areas;
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
}));
