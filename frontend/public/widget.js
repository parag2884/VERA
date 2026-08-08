(function () {
  var script = document.currentScript;
  if (!script) return;
  var key =
    script.getAttribute("data-vera-key") ||
    script.getAttribute("data-kite-key");
  if (!key) {
    console.error("[VERA] widget.js missing data-vera-key");
    return;
  }
  var origin =
    script.getAttribute("data-vera-origin") ||
    script.getAttribute("data-kite-origin") ||
    (script.src ? new URL(script.src).origin : window.location.origin);
  var openLabel =
    script.getAttribute("data-vera-label") ||
    script.getAttribute("data-kite-label") ||
    "Chat";
  var accent =
    script.getAttribute("data-vera-accent") ||
    script.getAttribute("data-kite-accent") ||
    "#ff6a3d";

  var btn = document.createElement("button");
  btn.type = "button";
  btn.setAttribute("aria-label", "Open " + openLabel);
  btn.textContent = openLabel;
  btn.style.cssText = [
    "position:fixed",
    "right:20px",
    "bottom:20px",
    "z-index:2147483000",
    "border:0",
    "border-radius:999px",
    "padding:14px 22px",
    "font:600 14px/1 system-ui,Segoe UI,sans-serif",
    "color:#fff",
    "background:" + accent,
    "box-shadow:0 10px 28px rgba(24,36,51,.22)",
    "cursor:pointer",
  ].join(";");

  var panel = document.createElement("div");
  panel.style.cssText = [
    "position:fixed",
    "right:20px",
    "bottom:78px",
    "width:min(400px,calc(100vw - 32px))",
    "height:min(620px,calc(100vh - 110px))",
    "z-index:2147483000",
    "border-radius:18px",
    "overflow:hidden",
    "box-shadow:0 22px 50px rgba(24,36,51,.22)",
    "display:none",
    "background:#fff",
  ].join(";");

  var iframe = document.createElement("iframe");
  iframe.title = "VERA Agent";
  iframe.src = origin.replace(/\/$/, "") + "/embed/" + encodeURIComponent(key);
  iframe.style.cssText = "border:0;width:100%;height:100%;display:block;background:#fff";
  panel.appendChild(iframe);

  var open = false;
  btn.addEventListener("click", function () {
    open = !open;
    panel.style.display = open ? "block" : "none";
    btn.textContent = open ? "Close" : openLabel;
  });

  document.body.appendChild(panel);
  document.body.appendChild(btn);
})();
