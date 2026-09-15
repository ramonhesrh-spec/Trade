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

  async function subscribe() {
    const statusEl = document.getElementById("push-subscribe-status");
    const showStatus = function (text) {
      statusEl.hidden = false;
      statusEl.textContent = text;
    };

    if (!("serviceWorker" in navigator) || !("PushManager" in window)) {
      showStatus("Pushmeldingen vereisen een geïnstalleerde app (voeg toe aan beginscherm).");
      return;
    }

    const permission = await Notification.requestPermission();
    if (permission !== "granted") {
      showStatus("Toestemming niet gegeven, geen pushmeldingen mogelijk.");
      return;
    }

    try {
      const reg = await navigator.serviceWorker.ready;
      const keyResp = await fetch("/api/push/vapid-public-key");
      const { key } = await keyResp.json();
      const subscription = await reg.pushManager.subscribe({
        userVisibleOnly: true,
        applicationServerKey: urlBase64ToUint8Array(key),
      });
      await fetch("/api/push/subscribe", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(Object.assign(subscription.toJSON(), { device_label: navigator.userAgent.slice(0, 60) })),
      });
      showStatus("Meldingen staan aan op dit apparaat.");
    } catch (err) {
      showStatus("Kon meldingen niet aanzetten: " + err.message);
    }
  }

  const btn = document.getElementById("push-subscribe-btn");
  if (btn) btn.addEventListener("click", subscribe);
})();
