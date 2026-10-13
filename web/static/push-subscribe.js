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

  // Ook gebruikt door de banner (push-banner.js): een aanmeldroute, zodat een fix voor iOS op beide plekken geldt.
  async function subscribe(onStatus) {
    const showStatus = function (text) {
      if (onStatus) onStatus(text);
      report(text);
    };

    report("subscribe() gestart, klik geregistreerd");

    try {
      if (!("serviceWorker" in navigator) || !("PushManager" in window)) {
        showStatus("Pushmeldingen vereisen een geïnstalleerde app (voeg toe aan beginscherm).");
        return false;
      }
      report("serviceWorker + PushManager aanwezig");

      const permission = await Notification.requestPermission();
      report("Notification.requestPermission() -> " + permission);
      if (permission !== "granted") {
        showStatus("Toestemming niet gegeven, geen pushmeldingen mogelijk.");
        return false;
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
      if (!subResp.ok) {
        showStatus("Kon meldingen niet opslaan, probeer het opnieuw.");
        return false;
      }

      showStatus("Meldingen staan aan op dit apparaat.");
      document.dispatchEvent(new CustomEvent("hespush:subscribed"));
      return true;
    } catch (err) {
      showStatus("Kon meldingen niet aanzetten: " + err.name + ": " + err.message);
      return false;
    }
  }

  window.hesPushSubscribe = subscribe;

  const btn = document.getElementById("push-subscribe-btn");
  if (btn) {
    const statusEl = document.getElementById("push-subscribe-status");
    btn.addEventListener("click", function () {
      subscribe(function (text) {
        if (statusEl) {
          statusEl.hidden = false;
          statusEl.textContent = text;
        }
      });
    });
    report("push-subscribe.js geladen, knop-listener gekoppeld");
  }
})();
