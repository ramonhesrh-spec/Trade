(function () {
  "use strict";

  function urlBase64ToUint8Array(base64String) {
    const padding = "=".repeat((4 - (base64String.length % 4)) % 4);
    const base64 = (base64String + padding).replace(/-/g, "+").replace(/_/g, "/");
    const rawData = window.atob(base64);
    const outputArray = new Uint8Array(rawData.length);
    for (let i = 0; i < rawData.length; i++) outputArray[i] = rawData.charCodeAt(i);
    return outputArray;
  }

  // Tijdelijk: op iOS is er geen console te zien zonder Mac + Safari Web
  // Inspector, dus rapporteert elke stap hierheen in plaats van er alleen
  // op te vertrouwen dat de gebruiker de tekst onder de knop leest.
  // Belandt in journalctl -u crypto-web. Weer verwijderen zodra de bug
  // gevonden is.
  function report(message) {
    try {
      fetch("/api/push/debug-log", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ message: message }),
      }).catch(function () {});
    } catch (e) {}
  }

  async function subscribe() {
    const statusEl = document.getElementById("push-subscribe-status");
    const showStatus = function (text) {
      if (statusEl) {
        statusEl.hidden = false;
        statusEl.textContent = text;
      }
      report(text);
    };

    report("subscribe() gestart, klik geregistreerd");

    try {
      if (!("serviceWorker" in navigator) || !("PushManager" in window)) {
        showStatus("Pushmeldingen vereisen een geïnstalleerde app (voeg toe aan beginscherm).");
        return;
      }
      report("serviceWorker + PushManager aanwezig");

      const permission = await Notification.requestPermission();
      report("Notification.requestPermission() -> " + permission);
      if (permission !== "granted") {
        showStatus("Toestemming niet gegeven, geen pushmeldingen mogelijk.");
        return;
      }

      const reg = await navigator.serviceWorker.ready;
      report("serviceWorker.ready opgelost, scope: " + reg.scope);

      const keyResp = await fetch("/api/push/vapid-public-key");
      report("vapid-public-key response status: " + keyResp.status);
      const { key } = await keyResp.json();
      report("vapid key ontvangen, lengte: " + (key ? key.length : 0));

      const subscription = await reg.pushManager.subscribe({
        userVisibleOnly: true,
        applicationServerKey: urlBase64ToUint8Array(key),
      });
      report("pushManager.subscribe() gelukt, endpoint: " + subscription.endpoint.slice(0, 60));

      const subResp = await fetch("/api/push/subscribe", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(Object.assign(subscription.toJSON(), { device_label: navigator.userAgent.slice(0, 60) })),
      });
      report("api/push/subscribe response status: " + subResp.status);

      showStatus("Meldingen staan aan op dit apparaat.");
    } catch (err) {
      showStatus("Kon meldingen niet aanzetten: " + err.name + ": " + err.message);
    }
  }

  const btn = document.getElementById("push-subscribe-btn");
  if (btn) {
    btn.addEventListener("click", subscribe);
    report("push-subscribe.js geladen, knop-listener gekoppeld");
  } else {
    report("push-subscribe.js geladen, MAAR push-subscribe-btn niet gevonden in de pagina");
  }
})();
