/* 推流端逻辑：getUserMedia → WHIP(WebRTC) 推到 MediaMTX；Wake Lock 保持屏幕常亮 */
"use strict";

const $ = (id) => document.getElementById(id);
const video = $("video");

let pc = null;
let localStream = null;
let wakeLock = null;
let facing = "environment"; // 宝宝床位置决定用哪颗摄像头，可翻转
let startTime = null;
let statsTimer = null;

/* ---------------- Wake Lock（屏幕常亮） ---------------- */

async function requestWakeLock() {
  try {
    if ("wakeLock" in navigator) {
      wakeLock = await navigator.wakeLock.request("screen");
      $("st-wakelock").textContent = "已保持常亮 ✅";
      wakeLock.addEventListener("release", () => {
        $("st-wakelock").textContent = "已被系统释放";
      });
    } else {
      $("st-wakelock").textContent = "此浏览器不支持，请设置自动锁定=永不";
    }
  } catch (e) {
    $("st-wakelock").textContent = "获取失败：" + e.message;
  }
}

document.addEventListener("visibilitychange", () => {
  // iOS 切后台会释放 Wake Lock；回前台且仍在推流时重新申请
  if (document.visibilityState === "visible" && pc && wakeLock === null) {
    requestWakeLock();
  }
});

/* ---------------- WHIP 推流 ---------------- */

/* ---------------- WHIP 推流 ---------------- */

// 预检：确认电脑端服务与 MediaMTX 可达（SDP 经后端同源代理转发，无需跨端口证书信任）
async function preflight() {
  try {
    const resp = await fetch("/proxy/whip", { method: "GET", cache: "no-store" });
    return resp.status < 500; // MediaMTX 对 GET 返回 405 即为可达
  } catch (e) {
    return false;
  }
}

async function startPush() {
  if (!navigator.mediaDevices?.getUserMedia) {
    setState("❌ 需要 HTTPS 访问才允许使用摄像头（请用 https://地址打开本页）");
    return;
  }
  setState("1/4 检查服务连接…");
  if (!(await preflight())) {
    setState("❌ 连不上电脑端服务：请确认电脑已运行 start-windows.bat，且手机与电脑在同一 Wi-Fi");
    return;
  }
  setState("2/4 请求摄像头…");
  try {
    localStream = await navigator.mediaDevices.getUserMedia({
      audio: { echoCancellation: false, noiseSuppression: false, autoGainControl: false },
      video: {
        facingMode: facing,
        width: { ideal: 1280 }, height: { ideal: 720 }, frameRate: { ideal: 15 },
      },
    });
  } catch (e) {
    setState("❌ 无法获取摄像头/麦克风：" + e.message +
      "（若曾拒绝过授权，请到 iOS 设置 → Safari → 相机/麦克风 改为允许）");
    return;
  }
  video.srcObject = localStream;
  video.play().catch(() => {});
  setState("3/4 建立推流连接…");

  pc = new RTCPeerConnection();
  localStream.getTracks().forEach((t) => pc.addTrack(t, localStream));
  pc.onconnectionstatechange = onPcState;

  const offer = await pc.createOffer();
  await pc.setLocalDescription(offer);
  await new Promise((resolve) => {
    if (pc.iceGatheringState === "complete") return resolve();
    const t = setTimeout(resolve, 2000);
    pc.onicegatheringstatechange = () =>
      pc.iceGatheringState === "complete" && (clearTimeout(t), resolve());
  });

  const whipUrl = "/proxy/whip";
  try {
    const resp = await fetch(whipUrl, {
      method: "POST",
      headers: { "Content-Type": "application/sdp" },
      body: pc.localDescription.sdp,
    });
    if (!resp.ok) throw new Error(`WHIP ${resp.status}（请确认电脑端 MediaMTX 已启动）`);
    await pc.setRemoteDescription({ type: "answer", sdp: await resp.text() });
  } catch (e) {
    stopPush();
    setState("❌ 推流失败：" + e.message);
    return;
  }

  setState("4/4 等待推流确认…");
  startTime = Date.now();
  $("btn-start").style.display = "none";
  $("btn-stop").style.display = "block";
  $("video-status").textContent = "";
  requestWakeLock();
  statsTimer = setInterval(updateDuration, 1000);
}

function onPcState() {
  if (!pc) return;
  const s = pc.connectionState;
  if (s === "connected") setState("🟢 推流中");
  else if (s === "connecting") setState("连接中…");
  else if (s === "failed" || s === "disconnected") {
    setState("⚠️ 连接断开，5 秒后自动重试…");
    setTimeout(() => { if (pc) { stopPush(); startPush(); } }, 5000);
  }
}

function stopPush() {
  if (statsTimer) { clearInterval(statsTimer); statsTimer = null; }
  if (pc) { pc.close(); pc = null; }
  if (localStream) { localStream.getTracks().forEach((t) => t.stop()); localStream = null; }
  if (wakeLock) { try { wakeLock.release(); } catch (e) {} wakeLock = null; }
  startTime = null;
  $("st-duration").textContent = "--";
  $("st-wakelock").textContent = "--";
  $("btn-start").style.display = "block";
  $("btn-stop").style.display = "none";
  $("video-status").textContent = "已停止推流";
}

function setState(text) {
  $("st-state").textContent = text;
}

function updateDuration() {
  if (!startTime) return;
  const sec = Math.floor((Date.now() - startTime) / 1000);
  const h = Math.floor(sec / 3600), m = Math.floor((sec % 3600) / 60);
  $("st-duration").textContent = h > 0 ? `${h} 小时 ${m} 分` : `${m} 分 ${sec % 60} 秒`;
}

/* ---------------- 事件 ---------------- */

$("btn-start").onclick = startPush;
$("btn-stop").onclick = () => { stopPush(); setState("未推流"); };
$("btn-flip").onclick = async () => {
  facing = facing === "environment" ? "user" : "environment";
  if (pc) { stopPush(); startPush(); }
};

/* ---------------- 启动 ---------------- */

(async function init() {
  try {
    const resp = await fetch(`/api/health`);
    if (!resp.ok) throw new Error("bad status");
    $("conn-dot").className = "dot online";
    if (!window.isSecureContext) {
      setState("⚠️ 当前非 HTTPS，iOS 将无法使用摄像头");
    }
  } catch (e) {
    setState("❌ 服务未启动，请先在电脑端运行 start-windows.bat");
  }
})();
