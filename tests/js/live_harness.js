// Laadt live.js en stale.js zonder DOM en toetst de versheid per coin: één coin die tikt, maakt een andere coin niet vers.
const fs = require("fs"), vm = require("vm"), path = require("path");
const ctx = {};
vm.createContext(ctx);
vm.runInContext(fs.readFileSync(process.argv[2], "utf8"), ctx);
vm.runInContext(fs.readFileSync(path.join(path.dirname(process.argv[2]), "stale.js"), "utf8"), ctx);
const now = 100000, by = { BTC: now - 1000, ETH: now - 20000 }, coins = ["BTC", "ETH"];
const f = ctx.hesLiveFreshAt, shown = ctx.hesShownAt;
console.log(JSON.stringify({
  btc: f(by, coins, now, "BTC"),
  eth: f(by, coins, now, "ETH"),
  sol: f(by, coins, now, "SOL"),
  all: f(by, coins, now),
  allFresh: f({ BTC: now - 1000, ETH: now - 2000 }, coins, now),
  none: f({}, coins, now),
  shownStalest: shown(null, by, coins),
  shownPollHelps: shown(now - 5000, by, coins),
  shownOnlyPoll: shown(now - 7000, {}, coins),
  shownNothing: shown(null, {}, []),
}));
