/* 宝宝睡眠监控 前端逻辑：鉴权、WebRTC 播放、状态刷新、事件、告警响铃 */
"use strict";

const $ = (id) => document.getElementById(id);

let token = localStorage.getItem("bm_token") || "";
let cfgUrls = { webrtc_url: null, hls_url: null };
let ringing = null;
let whepPC = null;
let whepRetryTimer = null;

/* ---------------- API 基础 ---------------- */

async function api(path, opts = {}) {
  const sep = path.includes("?") ? "&" : "?";
  const resp = await fetch(`/api/${path}${sep}token=${encodeURIComponent(token)}`, opts);
  if (resp.status === 401) { showTokenGate(); throw new Error("unauthorized"); }
  if (!resp.ok) throw new Error(`HTTP ${resp.status}`);
  return resp.json();
}

/* ---------------- 口令 ---------------- */

function showTokenGate() {
  $("token-overlay").classList.remove("hidden");
}
$("token-ok").onclick = () => {
  token = $("token-input").value.trim();
  localStorage.setItem("bm_token", token);
  $("token-overlay").classList.add("hidden");
  init();
};

/* ---------------- 视频播放（WebRTC WHEP，失败回退 HLS） ---------------- */

async function playWhep(url) {
  stopWhep();
  const pc = new RTCPeerConnection();
  whepPC = pc;
  pc.addTransceiver("video", { direction: "recvonly" });
  pc.addTransceiver("audio", { direction: "recvonly" });
  pc.ontrack = (ev) => {
    if (video.srcObject !== ev.streams[0]) video.srcObject = ev.streams[0];
  };
  pc.onconnectionstatechange = () => {
    if (pc.connectionState === "failed" || pc.connectionState === "disconnected") {
      scheduleReconnect();
    }
  };
  const offer = await pc.createOffer();
  await pc.setLocalDescription(offer);
  await new Promise((resolve) => {
    if (pc.iceGatheringState === "complete") return resolve();
    const t = setTimeout(resolve, 1500); // 不等 trickle，超时即用当前候选
    pc.onicegatheringstatechange = () => {
      if (pc.iceGatheringState === "complete") { clearTimeout(t); resolve(); }
    };
  });
  const resp = await fetch(url, {
    method: "POST",
    headers: { "Content-Type": "application/sdp" },
    body: pc.localDescription.sdp,
  });
  if (!resp.ok) throw new Error(`WHEP ${resp.status}`);
  await pc.setRemoteDescription({ type: "answer", sdp: await resp.text() });
  $("video-status").textContent = "";
}

function stopWhep() {
  if (whepRetryTimer) { clearTimeout(whepRetryTimer); whepRetryTimer = null; }
  if (whepPC) { whepPC.close(); whepPC = null; }
}

function scheduleReconnect() {
  stopWhep();
  $("video-status").textContent = "视频流中断，正在重连…";
  whepRetryTimer = setTimeout(startVideo, 3000);
}

async function startVideo() {
  const video = $("video");
  if (!cfgUrls.whep_url) return;
  try {
    await playWhep(cfgUrls.whep_url);
  } catch (e) {
    console.warn("WebRTC 失败，尝试 HLS:", e);
    // iOS Safari 原生支持 HLS；其他浏览器需 hls.js（此处仅原生回退）
    video.src = cfgUrls.hls_url;
    video.play().catch(() => {});
    $("video-status").textContent = "使用 HLS 模式（延迟较高）";
    whepRetryTimer = setTimeout(startVideo, 15000);
  }
}

/* ---------------- 状态刷新 ---------------- */

const fmtTs = (ts) => new Date(ts * 1000).toLocaleTimeString("zh-CN", { hour12: false });

function renderStatus(s) {
  $("conn-dot").className = "dot online";
  $("scene-title").textContent = s.scene_name ? `· ${s.scene_name}` : "";

  const p = $("st-posture");
  p.textContent = s.state_label || "--";
  p.className = "value " + (s.state === "prone" || s.state === "fallen" ? "bad"
    : (s.state === "left_side" || s.state === "right_side") && s.state_minutes >= 20 ? "warn" : "good");
  $("st-posture-dur").textContent = s.state_minutes > 0
    ? `已持续约 ${Math.floor(s.state_minutes)} 分钟` : "持续 --";

  const awake = $("st-awake");
  awake.textContent = s.awake ? "醒了" : "睡眠中";
  awake.className = "value " + (s.awake ? "warn" : "good");
  $("st-cry").textContent = s.crying ? "检测到哭声！" : "";

  const risky = s.face_covered || s.state === "prone" || s.state === "fallen" || !s.in_frame;
  $("card-risk").classList.toggle("risk-alert", risky);
  const risk = $("st-risk");
  if (s.face_covered) { risk.textContent = "口鼻遮挡"; risk.className = "value bad"; }
  else if (s.state === "prone" || s.state === "fallen") {
    risk.textContent = s.state === "fallen" ? "疑似跌倒" : "趴卧";
    risk.className = "value bad";
  }
  else if (!s.in_frame) { risk.textContent = "不在画面"; risk.className = "value warn"; }
  else { risk.textContent = "正常"; risk.className = "value good"; }
  $("st-inframe").textContent = s.stream_ok ? "" : "视频流未连接";

  $("st-desc").textContent = s.last_description || "等待分析…";
  $("st-last-analysis").textContent = s.last_analysis_ts
    ? `上次分析：${fmtTs(s.last_analysis_ts)}` : "";
}

function renderEvent(ev) {
  const li = document.createElement("li");
  li.className = ev.level;
  li.innerHTML = `<span class="t">${fmtTs(ev.ts)}</span>${escapeHtml(ev.message)}`;
  const list = $("event-list");
  list.querySelector(".empty")?.remove();
  list.prepend(li);
  while (list.children.length > 100) list.lastChild.remove();

  if (ev.level === "alert") showAlert(ev.message);
  else if (ev.level === "warning" && document.hidden) showAlert(ev.message, true);
}

function escapeHtml(s) {
  return s.replace(/[&<>"']/g, (c) =>
    ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));
}

/* ---------------- 告警弹窗 + 响铃 ---------------- */

function showAlert(message, soft = false) {
  $("alert-message").textContent = message;
  $("alert-overlay").classList.remove("hidden");
  startRing(soft);
}

$("alert-ack").onclick = () => {
  $("alert-overlay").classList.add("hidden");
  stopRing();
};

function startRing(soft) {
  if (ringing) return;
  stopRing();
  const ctx = new (window.AudioContext || window.webkitAudioContext)();
  // iOS 上首次需用户手势后才能发声；页面加载时点击"进入"已满足
  const beep = () => {
    const osc = ctx.createOscillator();
    const gain = ctx.createGain();
    osc.type = "sine";
    osc.frequency.value = soft ? 660 : 880;
    gain.gain.setValueAtTime(0.001, ctx.currentTime);
    gain.gain.exponentialRampToValueAtTime(soft ? 0.15 : 0.4, ctx.currentTime + 0.05);
    gain.gain.exponentialRampToValueAtTime(0.001, ctx.currentTime + 0.45);
    osc.connect(gain).connect(ctx.destination);
    osc.start();
    osc.stop(ctx.currentTime + 0.5);
  };
  beep();
  const timer = setInterval(beep, soft ? 2000 : 1000);
  ringing = { ctx, timer };
}

function stopRing() {
  if (!ringing) return;
  clearInterval(ringing.timer);
  ringing.ctx.close();
  ringing = null;
}

/* ---------------- WebSocket 实时推送 ---------------- */

function connectWs() {
  const wsUrl = `${location.protocol === "https:" ? "wss" : "ws"}://${location.host}/ws?token=${encodeURIComponent(token)}`;
  const ws = new WebSocket(wsUrl);
  ws.onmessage = (e) => {
    const msg = JSON.parse(e.data);
    if (msg.type === "status") renderStatus(msg.data);
    else if (msg.type === "event") renderEvent(msg.data);
  };
  ws.onclose = () => {
    $("conn-dot").className = "dot offline";
    setTimeout(connectWs, 3000);
  };
}

/* ---------------- 启动 ---------------- */

async function init() {
  try {
    cfgUrls = await api("config");
    renderStatus(await api("status"));
    (await api("events?limit=30")).slice().reverse().forEach(renderEvent);
    startVideo();
    connectWs();
  } catch (e) {
    if (e.message !== "unauthorized") {
      $("video-status").textContent = "服务连接失败，请确认电脑端服务已启动";
      setTimeout(init, 5000);
    }
  }
}

if (token) init(); else showTokenGate();
