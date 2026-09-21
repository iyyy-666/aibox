"use strict";

const appState = {
  modules: [],
  active: null,
  socket: null,
  frameTimer: null,
  toastTimer: null,
};

const iconByModule = {
  ai_assistant: "bot",
  object_sorting: "boxes",
  plate_recognition: "scan",
  palm_recognition: "hand",
  palm_tracking: "target",
  voice_input_test: "mic",
  fruit_recognition: "fruit",
  color_recognition: "palette",
  face_detection: "face",
  robot_button: "sliders",
  nursery_rhyme: "music",
  shape_recognition: "shapes",
  voice_robot_arm: "audio",
};

const accentByCategory = {
  "人工智能": ["#6755b5", "#eeebff"],
  "视觉识别": ["#278761", "#e8f6f0"],
  "语音交互": ["#16849b", "#e4f5f8"],
  "机械臂": ["#c76a24", "#fff0e4"],
};

const resourceLabels = {
  camera: "摄像头",
  microphone: "麦克风",
  speaker: "扬声器",
  robot: "机械臂",
  gimbal: "云台",
  asr: "语音识别",
  llm: "AI 模型",
  tts: "语音合成",
};

const commandLabels = {
  ask: "发送问题",
  start_listening: "开始识别",
  stop_listening: "停止识别",
  interrupt: "停止回答",
  prepare: "准备机械臂",
  start_sorting: "开始分拣",
  pause_sorting: "暂停分拣",
  stop_sorting: "停止分拣",
  save_snapshot: "保存画面",
  start_tracking: "开始跟踪",
  stop_tracking: "停止跟踪",
  pose: "执行姿态",
  sequence: "执行动作组",
  joint_step: "关节步进",
  gripper: "夹爪控制",
  stop_motion: "停止动作",
  play: "播放儿歌",
  stop_playback: "停止播放",
};

const secondaryCommands = new Set(["stop_listening", "interrupt", "pause_sorting", "stop_sorting", "stop_tracking", "stop_motion", "stop_playback"]);

function iconMarkup(name) {
  return `<svg aria-hidden="true"><use href="#icon-${name}"></use></svg>`;
}

async function requestJson(url, options = {}) {
  const response = await fetch(url, {
    headers: { "Content-Type": "application/json", ...(options.headers || {}) },
    ...options,
  });
  const payload = response.status === 204 ? null : await response.json().catch(() => ({}));
  if (!response.ok) {
    throw new Error(payload?.detail || "请求失败，请检查设备连接。");
  }
  return payload;
}

async function loadModules() {
  const grid = document.querySelector("[data-module-grid]");
  const message = document.querySelector("[data-home-message]");
  try {
    const payload = await requestJson("/api/modules");
    appState.modules = payload.modules;
    document.querySelector("[data-module-count]").textContent = String(appState.modules.length);
    renderModuleCards(grid);
    grid.setAttribute("aria-busy", "false");
  } catch (error) {
    grid.replaceChildren();
    grid.setAttribute("aria-busy", "false");
    message.textContent = `无法加载功能列表：${error.message}`;
    message.hidden = false;
  }
}

async function openModule(moduleId) {
  const module = appState.modules.find((item) => item.module_id === moduleId);
  if (!module || appState.active) return;
  appState.active = module;
  renderModuleShell(module);
  showModuleView();
  updateLifecycle({ state: "starting", message: "正在加载模型并连接所需设备…" });
  setControlsDisabled(true);
  try {
    const snapshot = await requestJson(`/api/modules/${moduleId}/start`, { method: "POST", body: "{}" });
    updateLifecycle(snapshot);
    if (snapshot.state === "running") {
      setControlsDisabled(false);
      connectStatusSocket(moduleId);
      if (module.visual) startFrameUpdates(moduleId);
    } else if (snapshot.state === "failed" || snapshot.state === "cleanup_failed") {
      showStageError(snapshot.message);
    }
  } catch (error) {
    updateLifecycle({ state: "failed", message: error.message });
    showStageError(error.message);
  }
}

function renderModuleCards(grid) {
  const fragment = document.createDocumentFragment();
  for (const module of appState.modules) {
    const [accent, soft] = accentByCategory[module.category] || ["#2468d8", "#e6f0ff"];
    const article = document.createElement("article");
    article.className = "module-card";
    article.style.setProperty("--card-accent", accent);
    article.style.setProperty("--card-soft", soft);

    const head = document.createElement("div");
    head.className = "card-head";
    const icon = document.createElement("span");
    icon.className = "card-icon";
    icon.innerHTML = iconMarkup(iconByModule[module.module_id] || "spark");
    const titleBlock = document.createElement("div");
    const category = document.createElement("span");
    category.className = "card-category";
    category.textContent = module.category;
    const title = document.createElement("h3");
    title.textContent = module.name;
    titleBlock.append(category, title);
    head.append(icon, titleBlock);

    const description = document.createElement("p");
    description.textContent = module.description;
    const button = document.createElement("button");
    button.className = "start-button";
    button.type = "button";
    button.dataset.moduleId = module.module_id;
    button.innerHTML = `<span>开始演示</span>${iconMarkup("arrow")}`;
    button.addEventListener("click", () => openModule(module.module_id));
    article.append(head, description, button);
    fragment.append(article);
  }
  grid.replaceChildren(fragment);
}

function renderModuleShell(module) {
  const [accent, soft] = accentByCategory[module.category] || ["#2468d8", "#e6f0ff"];
  const activeIcon = document.querySelector("[data-active-icon]");
  activeIcon.style.setProperty("--card-accent", accent);
  activeIcon.style.setProperty("--card-soft", soft);
  activeIcon.innerHTML = iconMarkup(iconByModule[module.module_id] || "spark");
  document.querySelector("[data-active-name]").textContent = module.name;
  document.querySelector("[data-active-category]").textContent = module.category;
  document.querySelector("[data-active-description]").textContent = module.description;
  document.querySelector("[data-page-title]").textContent = module.name;
  renderInstructions(module);
  renderResources(module.resources);

  const visual = document.querySelector("[data-visual-workspace]");
  const commands = document.querySelector("[data-command-workspace]");
  visual.hidden = !module.visual;
  commands.hidden = module.visual;
  if (!module.visual) renderCommandWorkspace(module, accent, soft);
  document.querySelector("[data-stage-error]").hidden = true;
}

function renderInstructions(module) {
  const steps = module.visual
    ? ["等待摄像头和识别模型就绪", "将目标放入画面中进行识别", "根据结果进行保存、跟踪或分拣", "退出功能后等待资源释放"]
    : ["等待功能和所需设备就绪", "使用右侧控件开始交互", "在实验记录中查看执行结果", "完成后退出并等待资源释放"];
  const list = document.querySelector("[data-instructions]");
  list.replaceChildren(...steps.map((step) => {
    const item = document.createElement("li");
    item.textContent = step;
    return item;
  }));
}

function renderResources(resources) {
  const list = document.querySelector("[data-resources]");
  list.replaceChildren(...resources.map((resource) => {
    const chip = document.createElement("span");
    chip.className = "resource-chip";
    chip.textContent = resourceLabels[resource] || resource;
    return chip;
  }));
}

function renderCommandWorkspace(module, accent, soft) {
  const icon = document.querySelector("[data-interaction-icon]");
  icon.style.setProperty("--card-accent", accent);
  icon.style.setProperty("--card-soft", soft);
  icon.innerHTML = iconMarkup(iconByModule[module.module_id] || "spark");
  document.querySelector("[data-interaction-title]").textContent = module.name;
  document.querySelector("[data-interaction-copy]").textContent = module.description;
  const list = document.querySelector("[data-command-list]");
  const commands = module.commands.filter((name) => !name.startsWith("gimbal_"));
  list.replaceChildren(...commands.map((name) => {
    const button = document.createElement("button");
    button.type = "button";
    button.className = `command-button${secondaryCommands.has(name) ? " is-secondary" : ""}`;
    button.dataset.command = name;
    button.textContent = commandLabels[name] || name;
    return button;
  }));
}

function showModuleView() {
  document.querySelector('[data-view="home"]').hidden = true;
  document.querySelector('[data-view="module"]').hidden = false;
  document.querySelector("[data-global-status]").textContent = "功能正在运行";
  window.scrollTo({ top: 0, behavior: "smooth" });
}

function showHomeView() {
  document.querySelector('[data-view="module"]').hidden = true;
  document.querySelector('[data-view="home"]').hidden = false;
  document.querySelector("[data-page-title]").textContent = "功能演示";
  document.querySelector("[data-global-status]").textContent = "等待选择功能";
  appState.active = null;
  window.scrollTo({ top: 0, behavior: "smooth" });
}

function updateLifecycle(snapshot) {
  const labels = {
    idle: "已停止",
    starting: "正在准备",
    running: "运行中",
    stopping: "正在退出",
    failed: "启动失败",
    cleanup_failed: "释放失败",
  };
  const badge = document.querySelector("[data-state-badge]");
  badge.dataset.state = snapshot.state;
  badge.querySelector("b").textContent = labels[snapshot.state] || "未知状态";
  document.querySelector("[data-status-title]").textContent = labels[snapshot.state] || "状态更新";
  document.querySelector("[data-status-message]").textContent = snapshot.message || "正在更新功能状态…";
  document.querySelector(".status-dot").style.background = snapshot.state === "running" ? "#278761" : snapshot.state.includes("failed") ? "#b94444" : "#c76a24";
  renderWorkerDetails(snapshot.details || {});
}

function renderWorkerDetails(details) {
  const result = details.result || details.text || details.message;
  if (result) {
    const target = appState.active?.visual ? document.querySelector("[data-result-content]") : document.querySelector("[data-activity-log]");
    target.textContent = typeof result === "string" ? result : JSON.stringify(result, null, 2);
    target.classList.remove("result-empty", "activity-empty");
  }
}

function connectStatusSocket(moduleId) {
  closeStatusSocket();
  const protocol = location.protocol === "https:" ? "wss" : "ws";
  const socket = new WebSocket(`${protocol}://${location.host}/ws/modules/${moduleId}`);
  appState.socket = socket;
  socket.addEventListener("message", (event) => {
    try { updateLifecycle(JSON.parse(event.data)); } catch (_error) { showToast("收到了无法读取的状态信息。"); }
  });
  socket.addEventListener("close", () => {
    if (appState.active?.module_id === moduleId) document.querySelector("[data-status-message]").textContent = "状态连接已断开，正在等待重新连接。";
  });
}

function closeStatusSocket() {
  if (appState.socket) appState.socket.close();
  appState.socket = null;
}

function startFrameUpdates(moduleId) {
  stopFrameUpdates();
  const image = document.querySelector("[data-camera-frame]");
  const empty = document.querySelector("[data-frame-empty]");
  const refresh = async () => {
    try {
      const response = await fetch(`/api/modules/${moduleId}/frame?t=${Date.now()}`, { cache: "no-store" });
      if (response.status === 200) {
        const blob = await response.blob();
        const nextUrl = URL.createObjectURL(blob);
        if (image.dataset.objectUrl) URL.revokeObjectURL(image.dataset.objectUrl);
        image.dataset.objectUrl = nextUrl;
        image.src = nextUrl;
        image.hidden = false;
        empty.hidden = true;
      }
    } catch (_error) {
      empty.querySelector("span").textContent = "画面暂时中断，正在继续尝试。";
    }
  };
  refresh();
  appState.frameTimer = window.setInterval(refresh, 250);
}

function stopFrameUpdates() {
  if (appState.frameTimer) window.clearInterval(appState.frameTimer);
  appState.frameTimer = null;
  const image = document.querySelector("[data-camera-frame]");
  if (image.dataset.objectUrl) URL.revokeObjectURL(image.dataset.objectUrl);
  image.removeAttribute("src");
  image.removeAttribute("data-object-url");
  image.hidden = true;
  document.querySelector("[data-frame-empty]").hidden = false;
}

async function sendCommand(command) {
  if (!appState.active) return;
  const payload = command.startsWith("gimbal_")
    ? { amount: Number(document.querySelector("[data-gimbal-amount]").value) }
    : {};
  try {
    const result = await requestJson(`/api/modules/${appState.active.module_id}/commands/${command}`, { method: "POST", body: JSON.stringify(payload) });
    showToast(`${commandLabels[command] || "操作"}已发送。`);
    renderWorkerDetails(result || {});
  } catch (error) {
    showToast(error.message, true);
  }
}

function requestExit() {
  if (!appState.active) return;
  document.querySelector("[data-exit-dialog]").showModal();
}

async function confirmExit() {
  const dialog = document.querySelector("[data-exit-dialog]");
  dialog.close();
  if (!appState.active) return;
  setControlsDisabled(true);
  updateLifecycle({ state: "stopping", message: "正在停止任务并验证设备资源已释放…" });
  try {
    const snapshot = await requestJson(`/api/modules/${appState.active.module_id}/stop`, { method: "POST", body: "{}" });
    updateLifecycle(snapshot);
    if (snapshot.state === "idle") {
      closeStatusSocket();
      stopFrameUpdates();
      showHomeView();
      showToast("功能已停止，设备资源已释放。");
      return;
    }
    setControlsDisabled(false);
    showToast(snapshot.message || "资源未能完全释放。", true);
  } catch (error) {
    updateLifecycle({ state: "cleanup_failed", message: error.message });
    setControlsDisabled(false);
    showToast(error.message, true);
  }
}

function showStageError(message) {
  document.querySelector("[data-visual-workspace]").hidden = true;
  document.querySelector("[data-command-workspace]").hidden = true;
  const panel = document.querySelector("[data-stage-error]");
  panel.querySelector("p").textContent = `${message} 请检查相关设备或服务后返回。`;
  panel.hidden = false;
}

function setControlsDisabled(disabled) {
  document.querySelectorAll("[data-command]").forEach((control) => { control.disabled = disabled; });
}

function showToast(message, isError = false) {
  const toast = document.querySelector("[data-toast]");
  toast.textContent = message;
  toast.style.background = isError ? "#8f3636" : "#263e52";
  toast.hidden = false;
  window.clearTimeout(appState.toastTimer);
  appState.toastTimer = window.setTimeout(() => { toast.hidden = true; }, 3200);
}

document.addEventListener("click", (event) => {
  const command = event.target.closest("[data-command]")?.dataset.command;
  if (command) sendCommand(command);
});
document.querySelector('[data-action="exit-module"]').addEventListener("click", requestExit);
document.querySelector('[data-action="continue-module"]').addEventListener("click", () => document.querySelector("[data-exit-dialog]").close());
document.querySelector('[data-action="confirm-exit"]').addEventListener("click", confirmExit);
document.querySelector('[data-action="error-exit"]').addEventListener("click", confirmExit);
document.querySelector('[data-nav="feature-demo"]').addEventListener("click", () => { if (appState.active) requestExit(); });
window.addEventListener("beforeunload", () => { closeStatusSocket(); stopFrameUpdates(); });
loadModules();
