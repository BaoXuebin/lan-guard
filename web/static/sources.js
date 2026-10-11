/* 注册推送源页：生成证书与推流页二维码，轮询推送源在线状态 */
"use strict";

const $ = (id) => document.getElementById(id);
const token = localStorage.getItem("bm_token") || "";

function makeQR(el, text) {
  el.innerHTML = "";
  new QRCode(el, { text, width: 160, height: 160, correctLevel: QRCode.CorrectLevel.M });
}

async function init() {
  const cfg = await fetch(`/api/config?token=${encodeURIComponent(token)}`)
    .then((r) => { if (r.status === 401) { location.href = "/"; throw new Error("auth"); } return r.json(); });

  makeQR($("qr-ca"), cfg.ca_url);
  makeQR($("qr-push"), cfg.push_url);
  $("ca-url").textContent = "或手动访问: " + cfg.ca_url;
  $("push-url").textContent = "或手动访问: " + cfg.push_url;
  if (!cfg.https_enabled) {
    $("push-url").textContent += "（⚠️ HTTPS 未启用，iPhone 无法推流，请先生成证书）";
  }

  pollStatus();
}

async function pollStatus() {
  try {
    const s = await fetch(`/api/status?token=${encodeURIComponent(token)}`).then((r) => r.json());
    const b = $("stream-banner");
    if (s.stream_ok) {
      b.className = "banner ok";
      b.textContent = "🟢 已有推送源在线，可在监控页查看画面";
    } else {
      b.className = "banner warn";
      b.textContent = "⚪ 暂无推送源在线——用 iPhone 扫下方二维码开始推流";
    }
  } catch (e) { /* ignore */ }
  setTimeout(pollStatus, 3000);
}

init();
