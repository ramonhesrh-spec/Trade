// Laadt install.js met kale stubs en vraagt per apparaat welke installatiehulp hij kiest.
const fs = require("fs"), vm = require("vm");
const ctx = {
  window: { addEventListener() {}, matchMedia: () => ({ matches: false }) },
  navigator: {}, document: { readyState: "loading", addEventListener() {}, querySelectorAll: () => [] },
};
vm.createContext(ctx);
vm.runInContext(fs.readFileSync(process.argv[2], "utf8"), ctx);
const mode = ctx.window.HPInstall.mode;
const IPHONE = "Mozilla/5.0 (iPhone; CPU iPhone OS 18_0 like Mac OS X) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/18.0 Mobile/15E148 Safari/604.1";
const IPAD = "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/18.0 Safari/605.1.15";
const ANDROID = "Mozilla/5.0 (Linux; Android 14; Pixel 8) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/129.0 Mobile Safari/537.36";
const MAC = IPAD;
console.log(JSON.stringify({
  iphone: mode({ ua: IPHONE, platform: "iPhone", maxTouchPoints: 5 }),
  ipadDesktopUa: mode({ ua: IPAD, platform: "MacIntel", maxTouchPoints: 5 }),
  mac: mode({ ua: MAC, platform: "MacIntel", maxTouchPoints: 0 }),
  androidPrompt: mode({ ua: ANDROID, platform: "Linux armv8l", maxTouchPoints: 5, hasPrompt: true }),
  androidNoPrompt: mode({ ua: ANDROID, platform: "Linux armv8l", maxTouchPoints: 5 }),
  standalone: mode({ ua: ANDROID, standalone: true, hasPrompt: true }),
  iosStandalone: mode({ ua: IPHONE, platform: "iPhone", maxTouchPoints: 5, standalone: true }),
  dismissed: mode({ ua: IPHONE, platform: "iPhone", maxTouchPoints: 5, dismissed: true }),
  dismissedInstalled: mode({ ua: IPHONE, platform: "iPhone", standalone: true, dismissed: true }),
}));
