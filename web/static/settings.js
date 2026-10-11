/* 设置页：读取 /api/settings 回填表单，保存时按字段类型提交并处理新口令 */
"use strict";

const $ = (id) => document.getElementById(id);
const NUMERIC = ["stream.sample_interval", "stream.analyze_interval",
  "stream.idle_analyze_interval", "stream.motion_threshold",
  "vision.timeout_sec", "vision.dark_threshold", "audio.sample_rate",
  "audio.cry_threshold_rms", "audio.min_sustain_sec", "audio.baseline_window_sec"];
const BOOLS = ["audio.enabled", "vision.dark_enhance"];

function getCfg(path) {
  return path.split(".").reduce((o, k) => (o || {})[k], window._settings);
}

function fillForm(data) {
  window._settings = data;
  document.querySelectorAll("input[id], select[id]").forEach((el) => {
    if (el.id === "scene") return; // 场景下拉单独处理
    const v = getCfg(el.id);
    if (v === undefined) return;
    if (el.type === "checkbox") el.checked = !!v;
    else el.value = v;
  });
}

async function fillScenes() {
  const { current, scenes } = await api("scenes");
  const sel = $("scene");
  sel.innerHTML = "";
  scenes.forEach((s) => {
    const opt = document.createElement("option");
    opt.value = "scenes/" + s.file;
    opt.textContent = s.name;
    sel.appendChild(opt);
  });
  if (current) sel.value = current;
  if (sel.selectedIndex < 0 && scenes.length) sel.selectedIndex = 0;
  updateSceneDesc();
  sel.onchange = updateSceneDesc;
}

function updateSceneDesc() {
  const opt = $("scene").selectedOptions[0];
  const file = opt ? opt.value : "";
  const item = (window._scenes || []).find((s) => "scenes/" + s.file === file);
  $("scene-desc").textContent = item ? item.description : "";
}

function toast(msg, ok = true) {
  const t = $("toast");
  t.textContent = msg;
  t.style.background = ok ? "var(--green)" : "var(--red)";
  t.style.display = "block";
  setTimeout(() => { t.style.display = "none"; }, 3000);
}

async function api(path, opts = {}) {
  const token = localStorage.getItem("bm_token") || "";
  const sep = path.includes("?") ? "&" : "?";
  const resp = await fetch(`/api/${path}${sep}token=${encodeURIComponent(token)}`, opts);
  if (resp.status === 401) { location.href = "/"; throw new Error("auth"); }
  if (!resp.ok) throw new Error((await resp.json().catch(() => ({}))).detail || resp.status);
  return resp.json();
}

async function save() {
  const payload = {};
  document.querySelectorAll("input[id], select[id]").forEach((el) => {
    if (el.id === "scene") return;
    const [section] = el.id.split(".");
    payload[section] = payload[section] || {};
    if (el.type === "checkbox") payload[section][el.id.split(".")[1]] = el.checked;
    else payload[section][el.id.split(".")[1]] = el.value;
  });
  payload.scene = $("scene").value; // 顶层键，后端单独处理
  try {
    const result = await api("settings", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(payload),
    });
    // 口令可能已变更，更新本地存储
    const newToken = payload.server.access_token;
    if (newToken) localStorage.setItem("bm_token", newToken);
    $("restart-tip").style.display = result.restart_required ? "block" : "none";
    toast("✅ 已保存，配置已生效并持久化到 config.yaml");
  } catch (e) {
    toast("❌ 保存失败：" + e.message, false);
  }
}

(async function init() {
  try {
    fillForm(await api("settings"));
    const { scenes } = await api("scenes");
    window._scenes = scenes;
    await fillScenes();
  } catch (e) {
    if (e.message !== "auth") toast("❌ 无法读取设置：" + e.message, false);
  }
  $("save-btn").onclick = save;
})();
