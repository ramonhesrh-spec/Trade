// Laadt live.js zonder DOM en toetst welke koersstromen de browser opent: perps op fstream met de symboolkaart (1000PEPE / 1000), een coin
// die terugviel op spot op de spotstroom, en met CANDLE_MARKET=spot alles op de spotstroom.
const fs = require("fs"), vm = require("vm");
const ctx = {};
vm.createContext(ctx);
vm.runInContext(fs.readFileSync(process.argv[2], "utf8"), ctx);
const s = ctx.hesLiveStreams;
const map = { PEPE: ["1000PEPEUSDT", 1000, "perp"], NOPERP: ["NOPERPUSDT", 1, "spot"] };
console.log(JSON.stringify({
  perp: s(["BTC", "PEPE", "NOPERP"], "perp", map, "usdt"),
  spot: s(["BTC", "PEPE"], "spot", {}, "usdt"),
  onlyPerp: s(["ETH"], "perp", {}, "usdt"),
}));
