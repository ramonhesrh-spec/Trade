// Deelt een kans als nette afbeelding (PNG) voor een groepschat: titel, de grafiek en de drie stappen, zonder menu of bedragen van jezelf.
// Zonder bestanden delen (navigator.share met files) valt het terug op een download.
(function () {
  var W = 720, PAD = 28;
  var STYLE_PROPS = ["fill", "stroke", "stroke-width", "stroke-dasharray", "opacity", "fill-opacity", "stroke-opacity", "font-family", "font-size", "font-weight", "text-anchor"];

  function inlineStyles(src, dst) {
    var cs = window.getComputedStyle(src);
    var css = "";
    STYLE_PROPS.forEach(function (p) { css += p + ":" + cs.getPropertyValue(p) + ";"; });
    dst.setAttribute("style", css);
    for (var i = 0; i < src.children.length; i++) inlineStyles(src.children[i], dst.children[i]);
  }

  function wrap(str, max) {
    var out = [], cur = "";
    str.split(" ").forEach(function (word) {
      if ((cur + " " + word).trim().length > max) { out.push(cur); cur = "   " + word; } else { cur = (cur + " " + word).trim(); }
    });
    if (cur) out.push(cur);
    return out;
  }

  function esc(s) { return String(s).replace(/&/g, "&amp;").replace(/</g, "&lt;").replace(/>/g, "&gt;"); }

  // De strook is HTML (past zich aan de breedte aan); voor de afbeelding tekenen we dezelfde balk en prijzen als SVG uit de data-attributen.
  function stripSvg(el, css) {
    var g = function (n) { return el.getAttribute(n); };
    var w = 320, x0 = 10, bw = w - 20, hasBar = g("data-bar") === "1";
    var out = "";
    var colors = { stop: css.red, instap: css.accent, take: css.green };
    if (hasBar) {
      var ip = parseFloat(g("data-instap-pos")), at = function (p) { return x0 + bw * p / 100; };
      out += '<rect x="' + x0 + '" y="30" width="' + (at(ip) - x0) + '" height="10" rx="5" fill="' + css.red + '" fill-opacity="0.55"/>' +
        '<rect x="' + at(ip) + '" y="30" width="' + (x0 + bw - at(ip)) + '" height="10" rx="5" fill="' + css.green + '" fill-opacity="0.55"/>' +
        '<rect x="' + (at(ip) - 1.5) + '" y="25" width="3" height="20" fill="' + css.accent + '"/>';
      if (g("data-dot")) {
        var dp = parseFloat(g("data-dot")), anchor = dp > 70 ? "end" : dp < 30 ? "start" : "middle";
        out += '<circle cx="' + at(dp) + '" cy="35" r="7" fill="' + css.text + '" stroke="' + css.bg + '" stroke-width="2"/>' +
          '<text x="' + at(dp) + '" y="16" text-anchor="' + anchor + '" fill="' + css.text + '" font-size="13" font-weight="600">' + esc(g("data-now")) + "</text>";
      }
    }
    var top = hasBar ? 62 : 6;
    [["stop", "Stop", g("data-stop")], ["instap", "Instap", g("data-instap")], ["take", "Doel", g("data-take")]].forEach(function (b, i) {
      var cx = 10 + i * 100;
      out += '<rect x="' + cx + '" y="' + top + '" width="96" height="52" rx="3" fill="' + css.panel + '"/>' +
        '<rect x="' + cx + '" y="' + top + '" width="96" height="2" fill="' + colors[b[0]] + '"/>' +
        '<text x="' + (cx + 8) + '" y="' + (top + 20) + '" fill="' + css.muted + '" font-size="10">' + b[1].toUpperCase() + "</text>" +
        '<text x="' + (cx + 8) + '" y="' + (top + 40) + '" fill="' + colors[b[0]] + '" font-size="14" font-weight="600">' + esc(b[2]) + "</text>";
    });
    return '<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 ' + w + " " + (top + 58) + '" font-family="ui-monospace, Consolas, monospace">' + out + "</svg>";
  }

  function build(card, data) {
    var chart = card.querySelector("svg.sc, .trade-strip, svg[data-share-chart]");
    var rootStyle = window.getComputedStyle(document.documentElement);
    var bg = rootStyle.getPropertyValue("--bg").trim() || "#0a0e0f";
    var text = rootStyle.getPropertyValue("--text").trim() || "#e8eeee";
    var accent = rootStyle.getPropertyValue("--accent").trim() || "#2dd4bf";
    var chartH = 0, chartMarkup = "";
    var cv = function (n, d) { return rootStyle.getPropertyValue(n).trim() || d; };
    if (chart && chart.classList.contains("trade-strip")) {
      var holder = document.createElement("div");
      holder.innerHTML = stripSvg(chart, { bg: bg, text: text, accent: accent, red: cv("--red", "#f2685c"), green: cv("--green", "#33d69f"), muted: cv("--muted", "#7d8c8a"), panel: cv("--panel", "#131a1b") });
      chart = holder.firstElementChild;
      var stripSvgEl = chart;
    }
    if (chart) {
      var vb = chart.viewBox.baseVal;
      var scale = (W - 2 * PAD) / vb.width;
      chartH = vb.height * scale;
      var clone = chart.cloneNode(true);
      if (!stripSvgEl) inlineStyles(chart, clone);
      clone.setAttribute("width", W - 2 * PAD);
      clone.setAttribute("height", chartH);
      clone.setAttribute("x", PAD);
      clone.setAttribute("y", 78);
      chartMarkup = new XMLSerializer().serializeToString(clone);
    }
    var y = 78 + chartH + 36;
    var lines = "";
    (data.lines || []).forEach(function (line, i) {
      wrap((i + 1) + ". " + line, 46).forEach(function (part) {
        lines += '<text x="' + PAD + '" y="' + y + '" fill="' + text + '" font-size="20" font-weight="600">' + esc(part) + "</text>";
        y += 28;
      });
      y += 8;
    });
    var H = y + 20;
    var svg = '<svg xmlns="http://www.w3.org/2000/svg" width="' + W + '" height="' + H + '" viewBox="0 0 ' + W + " " + H + '" font-family="system-ui, -apple-system, sans-serif">' +
      '<rect width="100%" height="100%" fill="' + bg + '"/>' +
      '<text x="' + PAD + '" y="50" fill="' + text + '" font-size="34" font-weight="700">' + esc(data.title) + "</text>" +
      '<text x="' + (W - PAD) + '" y="50" fill="' + accent + '" font-size="20" text-anchor="end" font-weight="700">HesPulse</text>' +
      chartMarkup + lines + "</svg>";
    return { svg: svg, w: W, h: H };
  }

  function toPng(built) {
    return new Promise(function (resolve, reject) {
      var img = new Image();
      img.onload = function () {
        var canvas = document.createElement("canvas");
        canvas.width = built.w * 2; canvas.height = built.h * 2;
        var ctx = canvas.getContext("2d");
        ctx.scale(2, 2);
        ctx.drawImage(img, 0, 0);
        canvas.toBlob(function (blob) { blob ? resolve(blob) : reject(new Error("geen afbeelding")); }, "image/png");
      };
      img.onerror = reject;
      img.src = "data:image/svg+xml;charset=utf-8," + encodeURIComponent(built.svg);
    });
  }

  document.addEventListener("click", function (e) {
    var btn = e.target.closest("[data-share-card]");
    if (!btn) return;
    var card = btn.closest(".setup-card, .radar-card, .vd-scenario, .kans-card, .week-card");
    if (!card) return;
    var data;
    try { data = JSON.parse(btn.getAttribute("data-share-card")); } catch (err) { return; }
    toPng(build(card, data)).then(function (blob) {
      var file = new File([blob], "hespulse-kans.png", { type: "image/png" });
      if (navigator.canShare && navigator.canShare({ files: [file] })) {
        return navigator.share({ files: [file], title: data.title });
      }
      var a = document.createElement("a");
      a.href = URL.createObjectURL(blob);
      a.download = "hespulse-kans.png";
      document.body.appendChild(a); a.click(); a.remove();
    }).catch(function (err) { if (window.console) console.error("deel mislukt", err && err.message); });
  });
})();
