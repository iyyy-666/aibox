"use strict";

const RADAR_MAX_DISTANCE_MM = 8000;
const RADAR_DETECTION_REGION = { angleMin: 180, angleMax: 240, distanceMin: 300, distanceMax: 2000 };

const appState = {
  modules: [],
  active: null,
  socket: null,
  socketGeneration: 0,
  socketReconnectTimer: null,
  socketReconnectAttempt: 0,
  frameTimer: null,
  frameRequest: null,
  frameGeneration: 0,
  frameSequence: null,
  toastTimer: null,
  commandRequestPending: false,
  lifecycleControlsDisabled: false,
  radarScan: { points: [], valid: false, latestAngle: null, region: RADAR_DETECTION_REGION },
  radarDataReady: false,
  radarBaselineReady: false,
  radarError: null,
};

let radarResizeObserver = null;
let radarWindowResizeHandler = null;
let radarDprMediaQuery = null;
let radarDprChangeHandler = null;

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
  radar_detection: "scan",
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
  radar: "雷达",
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
  build_baseline: "建立基准",
  start_detection: "开始检测",
  stop_detection: "停止检测",
  transfer: "搬运",
};

const secondaryCommands = new Set(["stop_listening", "interrupt", "pause_sorting", "stop_sorting", "stop_tracking", "stop_motion", "stop_playback"]);
const preemptiveCommands = new Set(["stop_listening", "interrupt", "stop_sorting", "stop_tracking", "stop_motion", "stop_playback"]);
const nurseryPayloads = { twinkle: { song_id: "twinkle" }, two_tigers: { song_id: "two_tigers" } };

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
  if (module.visual) renderVisualActions(module);
  else renderCommandWorkspace(module, accent, soft);
  document.querySelector("[data-stage-error]").hidden = true;
}

function renderVisualActions(module) {
  const list = document.querySelector("[data-visual-actions]");
  const commands = module.commands.filter((name) => !name.startsWith("gimbal_"));
  list.replaceChildren(...commands.map((name) => {
    const button = document.createElement("button");
    button.type = "button";
    button.className = `command-button${secondaryCommands.has(name) ? " is-secondary" : ""}`;
    if (name === "save_snapshot") button.dataset.localAction = "save_snapshot";
    else button.dataset.command = name;
    button.textContent = commandLabels[name] || name;
    return button;
  }));
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
  stopRadarResizeTracking();
  const workspace = document.querySelector("[data-command-workspace]");
  const icon = document.querySelector("[data-interaction-icon]");
  workspace.classList.toggle("radar-workspace", module.module_id === "radar_detection");
  document.querySelector("[data-interaction-panel]").classList.toggle("radar-mode", module.module_id === "radar_detection");
  icon.style.setProperty("--card-accent", accent);
  icon.style.setProperty("--card-soft", soft);
  icon.innerHTML = iconMarkup(iconByModule[module.module_id] || "spark");
  document.querySelector("[data-interaction-title]").textContent = module.name;
  document.querySelector("[data-interaction-copy]").textContent = module.description;
  const list = document.querySelector("[data-command-list]");
  if (["ai_assistant", "voice_input_test", "nursery_rhyme", "robot_button", "voice_robot_arm", "radar_detection"].includes(module.module_id)) {
    list.classList.add("nonvisual-controls");
    if (module.module_id === "radar_detection") {
      resetRadarState();
    }
    list.innerHTML = nonVisualControls(module.module_id);
    if (module.module_id === "radar_detection") {
      updateCommandControls();
      window.requestAnimationFrame(() => startRadarResizeTracking());
    }
    return;
  }
  list.classList.remove("nonvisual-controls");
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

function nonVisualControls(moduleId) {
  const button = (command, label, extra = "", secondary = false) => `<button type="button" class="command-button${secondary ? " is-secondary" : ""}" data-command="${command}" ${extra}>${label}</button>`;
  const listening = () => `<div class="command-row" aria-label="语音监听控制">${button("start_listening", "开始监听")}${button("stop_listening", "停止监听", "", true)}</div>`;
  if (moduleId === "radar_detection") return `<fieldset class="control-group radar-controls"><legend>雷达检测</legend><div class="radar-console"><div class="radar-screen"><canvas data-radar-canvas aria-label="实时雷达扫描图，零度朝上，角度顺时针增加，最大距离八米"></canvas><span class="radar-screen-label">实时扫描 · 8 m</span></div><div class="radar-control-column"><div class="radar-result-strip" aria-live="polite"><strong data-radar-result>雷达数据无效</strong><span data-radar-data-status>等待有效扫描数据</span></div><dl class="radar-status-grid"><div><dt>雷达状态</dt><dd data-radar-connection>未连接</dd></div><div><dt>扫描就绪</dt><dd data-radar-readiness>有效扫描 0/5</dd></div><div><dt>基准状态</dt><dd data-radar-baseline>未建立</dd></div><div><dt>检测状态</dt><dd data-radar-detection>未开始</dd></div><div><dt>传输速率</dt><dd data-radar-byte-rate>0 B/s</dd></div><div><dt>测距点率</dt><dd data-radar-point-rate>0 点/s</dd></div><div><dt>旋转速度</dt><dd data-radar-rotation-rate>0 Hz / 0 RPM</dd></div><div><dt>最近一帧</dt><dd data-radar-last-frame>0 点 / -- ms</dd></div></dl><div class="command-row">${button("build_baseline", "建立基准")}${button("start_detection", "开始检测")}${button("stop_detection", "停止检测", "", true)}${button("transfer", "搬运")}</div><section class="worker-output radar-details"><h3>检测参数</h3><dl><div><dt>固定位置</dt><dd data-radar-location>等待检测</dd></div><div><dt>检测区域</dt><dd><span data-radar-angle>180° ~ 240°</span> / <span data-radar-distance>300 ~ 2000 mm</span></dd></div><div><dt>当前变化程度</dt><dd data-radar-change>0%</dd></div><div><dt>变化阈值</dt><dd data-radar-threshold>35%</dd></div><div><dt>连续确认</dt><dd data-radar-confirmation>0 / 3</dd></div></dl></section></div></div></fieldset>`;
  if (moduleId === "ai_assistant") return `<fieldset class="control-group"><legend>文字与语音对话</legend><label for="assistant-prompt">请输入问题</label><textarea id="assistant-prompt" data-assistant-text rows="3" maxlength="500" aria-describedby="assistant-hint" placeholder="例如：什么是图像识别？"></textarea><p id="assistant-hint" class="control-hint">支持文字输入，也可开启语音监听。</p><div class="command-row">${button("ask", "发送问题")}${button("interrupt", "停止回答", "", true)}</div>${listening()}<section class="worker-output" aria-labelledby="dialogue-title"><h3 id="dialogue-title">对话记录</h3><div data-dialogue role="log" aria-live="polite">等待提问。</div></section></fieldset>`;
  if (moduleId === "voice_input_test") return `<fieldset class="control-group"><legend>语音输入测试</legend>${listening()}<section class="worker-output" aria-live="polite"><h3>识别结果</h3><dl><div><dt>原始文本</dt><dd data-raw>等待语音输入。</dd></div><div><dt>规范文本</dt><dd data-normalized>等待语音输入。</dd></div></dl></section></fieldset>`;
  if (moduleId === "nursery_rhyme") return `<fieldset class="control-group"><legend>儿歌播放</legend><div class="command-row" aria-label="选择儿歌">${button("play", "播放小星星", 'data-song-id="twinkle"')}${button("play", "播放两只老虎", 'data-song-id="two_tigers"')}${button("stop_playback", "停止播放", "", true)}</div>${listening()}<section class="worker-output" aria-live="polite"><h3>当前播放</h3><p data-current-song>尚未选择儿歌。</p><div data-lyrics>歌词将在播放时显示。</div></section></fieldset>`;
  if (moduleId === "robot_button") return `<fieldset class="control-group"><legend>机械臂动作</legend><div class="control-section"><h3>预设动作</h3><div class="command-row">${button("pose", "直立", 'data-pose="直立"')}${button("pose", "放平", 'data-pose="放平"')}${button("sequence", "抓取", 'data-sequence="抓取"')}${button("sequence", "搬运", 'data-sequence="搬运"')}</div></div><div class="control-section"><h3>关节微调</h3><div class="joint-controls">${[0,1,2,3,4,5].map((id) => `<div class="joint-row"><span>关节 ${id + 1}</span>${button("joint_step", "减小", `data-servo-id="${id}" data-delta="-30"`, true)}${button("joint_step", "增大", `data-servo-id="${id}" data-delta="30"`)}</div>`).join("")}</div></div><div class="control-section"><h3>夹爪控制</h3><div class="command-row">${button("gripper", "张开", 'data-gripper="open"')}${button("gripper", "半开", 'data-gripper="half"')}${button("gripper", "闭合", 'data-gripper="close"')}${button("stop_motion", "停止动作", "", true)}</div></div></fieldset>`;
  return `<fieldset class="control-group"><legend>语音控制机械臂</legend>${listening()}<div class="command-row">${button("stop_motion", "紧急停止", "", true)}</div><section class="worker-output" aria-live="polite"><h3>语音执行结果</h3><div data-voice-result>等待语音指令。</div></section></fieldset>`;
}

function showModuleView() {
  document.querySelector('[data-view="home"]').hidden = true;
  document.querySelector('[data-view="module"]').hidden = false;
  document.querySelector("[data-global-status]").textContent = "功能正在运行";
  window.scrollTo({ top: 0, behavior: "smooth" });
}

function showHomeView() {
  stopRadarResizeTracking();
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

function drawRadarScan(scan = appState.radarScan) {
  const canvas = document.querySelector("[data-radar-canvas]");
  if (!canvas) return;
  const rect = canvas.getBoundingClientRect();
  const size = Math.max(1, Math.floor(Math.min(rect.width || 460, rect.height || rect.width || 460)));
  const ratio = window.devicePixelRatio || 1;
  const backingSize = Math.round(size * ratio);
  if (canvas.width !== backingSize || canvas.height !== backingSize) {
    canvas.width = backingSize;
    canvas.height = backingSize;
  }
  const context = canvas.getContext("2d");
  context.setTransform(ratio, 0, 0, ratio, 0, 0);
  const centerX = size / 2;
  const centerY = size / 2;
  const plotRadius = Math.max(1, centerX - 34);
  context.clearRect(0, 0, size, size);
  context.fillStyle = "#000000";
  context.fillRect(0, 0, size, size);
  context.strokeStyle = "rgba(89, 183, 196, .28)";
  context.lineWidth = 1;
  for (let ring = 1; ring <= 4; ring += 1) {
    context.beginPath();
    context.arc(centerX, centerY, plotRadius * ring / 4, 0, Math.PI * 2);
    context.stroke();
    context.fillStyle = "rgba(189, 218, 222, .72)";
    context.font = "10px sans-serif";
    context.fillText(`${ring * 2000} mm`, centerX + 4, centerY - plotRadius * ring / 4 + 12);
  }
  for (let angle = 0; angle < 360; angle += 30) {
    const angleRad = angle * Math.PI / 180;
    const x = centerX + Math.sin(angleRad) * plotRadius;
    const y = centerY + -Math.cos(angleRad) * plotRadius;
    context.beginPath();
    context.moveTo(centerX, centerY);
    context.lineTo(x, y);
    context.stroke();
    context.fillStyle = "rgba(189, 218, 222, .82)";
    context.fillText(`${angle}°`, centerX + Math.sin(angleRad) * (plotRadius + 15) - 8, centerY - Math.cos(angleRad) * (plotRadius + 15) + 4);
  }

  const region = scan.region || RADAR_DETECTION_REGION;
  const regionStart = region.angleMin * Math.PI / 180;
  const regionEnd = region.angleMax * Math.PI / 180;
  const arcStart = regionStart - Math.PI / 2;
  const arcEnd = regionEnd - Math.PI / 2;
  const innerRadius = Math.min(region.distanceMin, RADAR_MAX_DISTANCE_MM) / RADAR_MAX_DISTANCE_MM * plotRadius;
  const outerRadius = Math.min(region.distanceMax, RADAR_MAX_DISTANCE_MM) / RADAR_MAX_DISTANCE_MM * plotRadius;
  context.strokeStyle = "rgba(255, 190, 72, .9)";
  context.lineWidth = 1.5;
  context.beginPath();
  context.arc(centerX, centerY, outerRadius, arcStart, arcEnd);
  context.lineTo(centerX + Math.sin(regionEnd) * innerRadius, centerY + -Math.cos(regionEnd) * innerRadius);
  context.arc(centerX, centerY, innerRadius, arcEnd, arcStart, true);
  context.closePath();
  context.stroke();

  if (scan.valid) {
    context.fillStyle = "#33ddf2";
    for (const point of scan.points) {
      if (!Number.isFinite(point.angle_deg) || !Number.isFinite(point.distance_mm) || point.distance_mm <= 0) continue;
      const angleRad = point.angle_deg * Math.PI / 180;
      const radius = Math.min(point.distance_mm, RADAR_MAX_DISTANCE_MM) / RADAR_MAX_DISTANCE_MM * plotRadius;
      const x = centerX + Math.sin(angleRad) * radius;
      const y = centerY + -Math.cos(angleRad) * radius;
      context.beginPath();
      context.arc(x, y, 1.8, 0, Math.PI * 2);
      context.fill();
    }
  }
  if (Number.isFinite(scan.latestAngle)) {
    const angleRad = scan.latestAngle * Math.PI / 180;
    context.strokeStyle = "rgba(255, 255, 255, .78)";
    context.lineWidth = 1;
    context.beginPath();
    context.moveTo(centerX, centerY);
    context.lineTo(centerX + Math.sin(angleRad) * plotRadius, centerY + -Math.cos(angleRad) * plotRadius);
    context.stroke();
  }
}

function resetRadarState() {
  appState.radarScan = { points: [], valid: false, latestAngle: null, region: RADAR_DETECTION_REGION };
  appState.radarDataReady = false;
  appState.radarBaselineReady = false;
  appState.radarError = null;
}

function watchRadarDpr(redraw) {
  if (radarDprMediaQuery && radarDprChangeHandler) {
    radarDprMediaQuery.removeEventListener("change", radarDprChangeHandler);
  }
  radarDprMediaQuery = window.matchMedia?.(`(resolution: ${window.devicePixelRatio || 1}dppx)`) || null;
  radarDprChangeHandler = radarDprMediaQuery ? () => {
    redraw();
    watchRadarDpr(redraw);
  } : null;
  radarDprMediaQuery?.addEventListener("change", radarDprChangeHandler);
}

function startRadarResizeTracking() {
  stopRadarResizeTracking();
  const canvas = document.querySelector("[data-radar-canvas]");
  if (!canvas) return;
  const redraw = () => drawRadarScan(appState.radarScan);
  if (typeof ResizeObserver !== "undefined") {
    radarResizeObserver = new ResizeObserver(redraw);
    radarResizeObserver.observe(canvas);
  }
  radarWindowResizeHandler = redraw;
  window.addEventListener("resize", radarWindowResizeHandler);
  watchRadarDpr(redraw);
  redraw();
}

function stopRadarResizeTracking() {
  radarResizeObserver?.disconnect();
  radarResizeObserver = null;
  if (radarWindowResizeHandler) window.removeEventListener("resize", radarWindowResizeHandler);
  radarWindowResizeHandler = null;
  if (radarDprMediaQuery && radarDprChangeHandler) {
    radarDprMediaQuery.removeEventListener("change", radarDprChangeHandler);
  }
  radarDprMediaQuery = null;
  radarDprChangeHandler = null;
}

function updateRadarScan(details) {
  if (!document.querySelector("[data-radar-canvas]")) return;
  const previousRegion = appState.radarScan.region || RADAR_DETECTION_REGION;
  const incomingRegion = details.detection_region || {};
  const region = {
    angleMin: Number(incomingRegion.angle_min_deg ?? previousRegion.angleMin),
    angleMax: Number(incomingRegion.angle_max_deg ?? previousRegion.angleMax),
    distanceMin: Number(incomingRegion.distance_min_mm ?? previousRegion.distanceMin),
    distanceMax: Number(incomingRegion.distance_max_mm ?? previousRegion.distanceMax),
  };
  if (!Array.isArray(details.points)) {
    if (!details.detection_region) return;
    appState.radarScan = { ...appState.radarScan, region };
    drawRadarScan();
    return;
  }
  const valid = details.radar_data_valid === true && details.points.length > 0;
  const points = valid ? details.points : [];
  appState.radarScan = {
    points,
    valid,
    latestAngle: points.length ? points[points.length - 1].angle_deg : appState.radarScan.latestAngle,
    region,
  };
  drawRadarScan();
  const status = document.querySelector("[data-radar-data-status]");
  if (status) status.textContent = valid ? `${details.points.length} 个有效测距点` : "等待有效扫描数据";
}

function formatPlateResults(items) {
  const validItems = items.filter((item) => item && typeof item === "object" && !Array.isArray(item));
  if (!validItems.length) return "暂未识别到车牌";
  const colorNames = { "Blue Plate": "蓝色", "Green Plate": "绿色", Blue: "蓝色", Green: "绿色" };
  const vehicleNames = { "Fuel Vehicle": "燃油车", "Electric Vehicle": "新能源车" };
  return validItems.map((item, index) => {
    const safeText = (value) => typeof value === "string" ? value.trim() : "";
    const plate = safeText(item.plate);
    const color = safeText(item.color);
    const vehicleType = safeText(item.vehicle_type);
    const confidence = typeof item.confidence === "number" ? item.confidence : Number.NaN;
    const confidenceText = Number.isFinite(confidence) && confidence >= 0 && confidence <= 100
      ? `${Math.round(confidence <= 1 ? confidence * 100 : confidence)}%`
      : "--";
    const lines = [
      `车牌号码：${plate || "未读取"}`,
      `车牌颜色：${colorNames[color] || color || "未知"}`,
      `车辆类型：${vehicleNames[vehicleType] || vehicleType || "未知"}`,
      `置信度：${confidenceText}`,
    ];
    return validItems.length > 1 ? `${index + 1}. ${lines.join("\n   ")}` : lines.join("\n");
  }).join("\n\n");
}

const visualNameMaps = {
  fruit_recognition: {
    apple: "苹果", banana: "香蕉", watermelon: "西瓜", pineapple: "菠萝",
    strawberry: "草莓", orange: "橙子", grape: "葡萄", pear: "梨", peach: "桃子",
  },
  color_recognition: {
    Red: "红色", Orange: "橙色", Yellow: "黄色", Green: "绿色",
    Cyan: "青色", Blue: "蓝色", Purple: "紫色", Pink: "粉色",
  },
  shape_recognition: {
    Triangle: "三角形", Square: "正方形", Rectangle: "矩形", Circle: "圆形",
    Ellipse: "椭圆形", Pentagon: "五边形", Hexagon: "六边形", Star: "星形", Polygon: "多边形",
  },
};

const emptyVisualMessages = {
  object_sorting: "暂未检测到可分拣货物",
  plate_recognition: "暂未识别到车牌",
  palm_recognition: "暂未识别到手势",
  palm_tracking: "暂未检测到手掌",
  fruit_recognition: "暂未识别到水果",
  color_recognition: "暂未识别到颜色",
  face_detection: "暂未检测到人脸",
  shape_recognition: "暂未识别到形状",
};

function confidenceSuffix(value) {
  const confidence = Number(value);
  if (!Number.isFinite(confidence) || confidence < 0) return "";
  const percentage = confidence <= 1 ? confidence * 100 : confidence;
  return `（置信度 ${Math.round(Math.min(100, percentage))}%）`;
}

function mappedName(moduleId, value) {
  const text = typeof value === "string" ? value.trim() : "";
  if (!text) return "";
  const names = visualNameMaps[moduleId] || {};
  const normalized = text.toLowerCase();
  const match = Object.entries(names).find(([key]) => key.toLowerCase() === normalized);
  return names[text] || match?.[1] || "";
}

function formatVisualResults(moduleId, result) {
  if (moduleId === "plate_recognition") return formatPlateResults(Array.isArray(result) ? result : []);
  const items = Array.isArray(result) ? result.filter(Boolean) : (result ? [result] : []);
  if (!items.length) return emptyVisualMessages[moduleId] || "暂无识别结果";

  if (moduleId === "object_sorting") {
    const rawColor = typeof items[0] === "string" ? items[0] : items[0]?.color || items[0]?.name;
    const color = mappedName("color_recognition", rawColor);
    return color ? `检测到${color}货物` : "检测到可分拣货物";
  }
  if (moduleId === "face_detection") return `检测到 ${items.length} 张人脸`;
  if (moduleId === "palm_tracking") return "检测到手掌，正在跟踪";
  if (moduleId === "palm_recognition") {
    const gestureNames = { rock: "石头", scissors: "剪刀", paper: "布" };
    return items.map((item) => {
      const value = typeof item === "string" ? item : item.gesture || item.name || item.label;
      return gestureNames[value] || value || "检测到手势";
    }).join("\n");
  }
  if (visualNameMaps[moduleId]) {
    const genericNames = {
      fruit_recognition: "检测到水果",
      color_recognition: "检测到颜色",
      shape_recognition: "检测到形状",
    };
    return items.map((item) => {
      const rawName = typeof item === "string" ? item : item.name_en || item.name || item.name_cn || item.label;
      const name = mappedName(moduleId, rawName) || genericNames[moduleId] || "已识别";
      return `${name}${confidenceSuffix(item?.confidence)}`;
    }).join("\n");
  }
  if (typeof result === "string") return result;
  return `检测到 ${items.length} 个目标`;
}

function renderWorkerDetails(details) {
  const setDetail = (selector, value) => {
    const target = document.querySelector(selector);
    if (!target || value === undefined || value === null || value === "") return;
    target.textContent = typeof value === "string" ? value : JSON.stringify(value, null, 2);
  };
  setDetail("[data-raw]", details.raw);
  setDetail("[data-normalized]", details.normalized);
  setDetail("[data-dialogue]", details.dialogue || (details.type === "assistant_reply" ? { turn: details.turn, text: details.text } : null));
  setDetail("[data-current-song]", details.song);
  setDetail("[data-lyrics]", Array.isArray(details.lyrics) ? details.lyrics.join("\n") : details.lyrics);
  setDetail("[data-voice-result]", details.voice_result || (details.type === "speech" ? details.normalized : details.result));
  setDetail("[data-radar-connection]", details.connected === true ? "已连接" : details.connected === false ? "未连接" : undefined);
  if (details.data_ready !== undefined) appState.radarDataReady = details.data_ready === true;
  if (details.baseline_ready !== undefined) appState.radarBaselineReady = details.baseline_ready === true;
  setDetail("[data-radar-readiness]", details.valid_rotations !== undefined || details.required_rotations !== undefined ? `有效扫描 ${details.valid_rotations || 0}/${details.required_rotations || 5}` : undefined);
  setDetail("[data-radar-byte-rate]", details.bytes_per_second !== undefined ? `${Number(details.bytes_per_second).toFixed(1)} B/s` : undefined);
  setDetail("[data-radar-point-rate]", details.points_per_second !== undefined ? `${Number(details.points_per_second).toFixed(1)} 点/s` : undefined);
  setDetail("[data-radar-rotation-rate]", details.rotations_per_second !== undefined ? `${Number(details.rotations_per_second).toFixed(2)} Hz / ${(Number(details.rotations_per_second) * 60).toFixed(1)} RPM` : undefined);
  setDetail("[data-radar-last-frame]", details.last_rotation_points !== undefined || details.last_rotation_age_ms !== undefined ? `${details.last_rotation_points || 0} 点 / ${details.last_rotation_age_ms ?? "--"} ms` : undefined);
  setDetail("[data-radar-baseline]", details.baseline_ready === true ? "已建立" : details.baseline_ready === false ? "未建立" : undefined);
  setDetail("[data-radar-detection]", details.detecting === true ? "检测中" : details.detecting === false ? "已停止" : undefined);
  updateRadarScan(details);
  if (details.type === "error" || details.ok === false) {
    appState.radarError = details.message || "雷达运行错误";
    setDetail("[data-radar-result]", appState.radarError);
  } else if (appState.radarError && details.radar_data_valid !== true) {
    setDetail("[data-radar-result]", appState.radarError);
  } else if (details.radar_data_valid === false) {
    setDetail("[data-radar-result]", "雷达数据无效");
  } else if (details.result === "有物块") {
    appState.radarError = null;
    setDetail("[data-radar-result]", "固定位置存在物块");
  } else if (details.result === "无物块") {
    appState.radarError = null;
    setDetail("[data-radar-result]", "固定位置不存在物块");
  } else if (details.radar_data_valid === true) {
    appState.radarError = null;
    setDetail("[data-radar-result]", "雷达数据有效");
  } else {
    setDetail("[data-radar-result]", details.result);
  }
  if (details.result === "有物块" || details.result === "无物块") {
    setDetail("[data-radar-location]", details.result === "有物块" ? "存在物块" : "不存在物块");
  }
  if (details.change_ratio !== undefined) setDetail("[data-radar-change]", `${Math.round(Number(details.change_ratio) * 100)}%`);
  if (details.threshold !== undefined) setDetail("[data-radar-threshold]", `${Math.round(Number(details.threshold) * 100)}%`);
  if (details.confirmation !== undefined || details.confirmation_required !== undefined) setDetail("[data-radar-confirmation]", `${details.confirmation || 0} / ${details.confirmation_required || 0}`);
  updateCommandControls();
  const hasResult = Object.prototype.hasOwnProperty.call(details, "result");
  const result = appState.active?.visual && hasResult
    ? formatVisualResults(appState.active.module_id, details.result)
    : details.result || details.text || details.message;
  if (result !== undefined && result !== null && result !== "") {
    const target = appState.active?.visual ? document.querySelector("[data-result-content]") : document.querySelector("[data-activity-log]");
    target.textContent = typeof result === "string" ? result : JSON.stringify(result, null, 2);
    const emptyVisualResult = appState.active?.visual
      && hasResult
      && Array.isArray(details.result)
      && details.result.length === 0;
    if (emptyVisualResult) target.classList.add("result-empty");
    else target.classList.remove("result-empty", "activity-empty");
  }
}

function connectStatusSocket(moduleId, generation = null) {
  if (generation === null) {
    closeStatusSocket();
    generation = appState.socketGeneration;
  }
  if (appState.active?.module_id !== moduleId || generation !== appState.socketGeneration) return;
  const protocol = location.protocol === "https:" ? "wss" : "ws";
  const socket = new WebSocket(`${protocol}://${location.host}/ws/modules/${moduleId}`);
  appState.socket = socket;
  socket.addEventListener("open", () => { appState.socketReconnectAttempt = 0; });
  socket.addEventListener("message", (event) => {
    try { updateLifecycle(JSON.parse(event.data)); } catch (_error) { showToast("收到了无法读取的状态信息。"); }
  });
  socket.addEventListener("close", () => {
    if (appState.socket === socket) appState.socket = null;
    if (appState.active?.module_id !== moduleId || generation !== appState.socketGeneration) return;
    document.querySelector("[data-status-message]").textContent = "状态连接已断开，正在重新连接。";
    const delays = [250, 500, 1000, 2000];
    const delay = delays[Math.min(appState.socketReconnectAttempt, delays.length - 1)];
    appState.socketReconnectAttempt += 1;
    appState.socketReconnectTimer = window.setTimeout(
      () => connectStatusSocket(moduleId, generation),
      delay,
    );
  });
}

function closeStatusSocket() {
  appState.socketGeneration += 1;
  if (appState.socketReconnectTimer) window.clearTimeout(appState.socketReconnectTimer);
  appState.socketReconnectTimer = null;
  appState.socketReconnectAttempt = 0;
  if (appState.socket) appState.socket.close();
  appState.socket = null;
}

function startFrameUpdates(moduleId) {
  stopFrameUpdates();
  const generation = appState.frameGeneration;
  refreshFrame(moduleId, generation);
}

function frameRefreshDelay(moduleId) {
  if (document.hidden) return 500;
  return moduleId === "fruit_recognition" ? 50 : 80;
}

async function refreshFrame(moduleId, generation) {
  const image = document.querySelector("[data-camera-frame]");
  const empty = document.querySelector("[data-frame-empty]");
  const controller = new AbortController();
  appState.frameRequest = controller;
  try {
    const response = await fetch(`/api/modules/${moduleId}/frame`, {
      cache: "no-store",
      signal: controller.signal,
    });
    if (response.status === 200) {
      const sequence = response.headers.get("X-Frame-Sequence");
      if (sequence !== appState.frameSequence) {
        const blob = await response.blob();
        const nextUrl = URL.createObjectURL(blob);
        if (image.dataset.objectUrl) URL.revokeObjectURL(image.dataset.objectUrl);
        image.dataset.objectUrl = nextUrl;
        image.src = nextUrl;
        appState.frameSequence = sequence;
        image.hidden = false;
        empty.hidden = true;
      }
    }
  } catch (error) {
    if (error.name !== "AbortError") {
      empty.querySelector("span").textContent = "画面暂时中断，正在继续尝试。";
    }
  } finally {
    if (appState.frameRequest === controller) appState.frameRequest = null;
    if (generation === appState.frameGeneration && appState.active?.module_id === moduleId) {
      appState.frameTimer = window.setTimeout(
        () => refreshFrame(moduleId, generation),
        frameRefreshDelay(moduleId),
      );
    }
  }
}

function stopFrameUpdates() {
  appState.frameGeneration += 1;
  if (appState.frameTimer) window.clearTimeout(appState.frameTimer);
  appState.frameTimer = null;
  if (appState.frameRequest) appState.frameRequest.abort();
  appState.frameRequest = null;
  appState.frameSequence = null;
  const image = document.querySelector("[data-camera-frame]");
  if (image.dataset.objectUrl) URL.revokeObjectURL(image.dataset.objectUrl);
  image.removeAttribute("src");
  image.removeAttribute("data-object-url");
  image.hidden = true;
  document.querySelector("[data-frame-empty]").hidden = false;
}

function saveSnapshot() {
  const image = document.querySelector("[data-camera-frame]");
  if (image.hidden || !image.src) {
    showToast("当前没有可保存的画面。", true);
    return;
  }
  const link = document.createElement("a");
  link.href = image.src;
  link.download = `${appState.active.module_id}-${Date.now()}.jpg`;
  link.click();
}

async function sendCommand(command, control) {
  if (!appState.active) return;
  const assistantText = command === "ask" ? document.querySelector("[data-assistant-text]") : null;
  if (assistantText && !assistantText.value.trim()) {
    showToast("请输入要发送的问题。", true);
    assistantText.focus();
    return;
  }
  if (!control || control.disabled) return;
  const payload = command.startsWith("gimbal_")
    ? { amount: Number(document.querySelector("[data-gimbal-amount]").value) }
    : command === "ask" ? { text: assistantText.value.trim() }
    : command === "play" ? nurseryPayloads[control.dataset.songId]
    : command === "pose" ? { name: control.dataset.pose }
    : command === "sequence" ? { name: control.dataset.sequence }
    : command === "joint_step" ? { servo_id: Number(control.dataset.servoId), delta: Number(control.dataset.delta) }
    : command === "gripper" ? { action: control.dataset.gripper }
    : {};
  const preemptive = preemptiveCommands.has(command);
  if (!preemptive) {
    appState.commandRequestPending = true;
    updateCommandControls();
  }
  try {
    const result = await requestJson(`/api/modules/${appState.active.module_id}/commands/${command}`, { method: "POST", body: JSON.stringify(payload) });
    if (result?.ok === false) {
      throw new Error(result.message || "操作执行失败。");
    }
    showToast(`${commandLabels[command] || "操作"}已发送。`);
    renderWorkerDetails(result || {});
    if (assistantText) assistantText.value = "";
  } catch (error) {
    showToast(error.message, true);
    if (appState.active?.module_id === "radar_detection") {
      renderWorkerDetails({ type: "error", message: error.message });
    }
  } finally {
    if (!preemptive) {
      appState.commandRequestPending = false;
      updateCommandControls();
    }
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
  closeStatusSocket();
  stopFrameUpdates();
  try {
    const snapshot = await requestJson(`/api/modules/${appState.active.module_id}/stop`, { method: "POST", body: "{}" });
    updateLifecycle(snapshot);
    if (snapshot.state === "idle") {
      showHomeView();
      showToast("功能已停止，设备资源已释放。");
      return;
    }
    setControlsDisabled(false);
    connectStatusSocket(appState.active.module_id);
    if (appState.active.visual) startFrameUpdates(appState.active.module_id);
    showToast(snapshot.message || "资源未能完全释放。", true);
  } catch (error) {
    updateLifecycle({ state: "cleanup_failed", message: error.message });
    setControlsDisabled(false);
    connectStatusSocket(appState.active.module_id);
    if (appState.active.visual) startFrameUpdates(appState.active.module_id);
    showToast(error.message, true);
  }
}

function showStageError(message) {
  stopRadarResizeTracking();
  document.querySelector("[data-visual-workspace]").hidden = true;
  document.querySelector("[data-command-workspace]").hidden = true;
  const panel = document.querySelector("[data-stage-error]");
  panel.querySelector("p").textContent = `${message} 请检查相关设备或服务后返回。`;
  panel.hidden = false;
}

function setControlsDisabled(disabled) {
  appState.lifecycleControlsDisabled = disabled;
  updateCommandControls();
}

function updateCommandControls() {
  document.querySelectorAll("[data-command]").forEach((control) => {
    control.disabled = appState.lifecycleControlsDisabled || (
      appState.commandRequestPending && !preemptiveCommands.has(control.dataset.command)
    ) || (control.dataset.command === "build_baseline" && !appState.radarDataReady)
      || (control.dataset.command === "start_detection" && !appState.radarBaselineReady);
  });
  document.querySelectorAll("[data-local-action]").forEach((control) => {
    control.disabled = appState.lifecycleControlsDisabled;
  });
}

function showToast(message, isError = false) {
  const toast = document.querySelector("[data-toast]");
  toast.textContent = message;
  toast.style.background = isError ? "#8f3636" : "#263e52";
  toast.hidden = false;
  window.clearTimeout(appState.toastTimer);
  appState.toastTimer = window.setTimeout(() => { toast.hidden = true; }, 3200);
}

function handleDocumentClick(event) {
  const localAction = event.target.closest("[data-local-action]")?.dataset.localAction;
  if (localAction === "save_snapshot") {
    saveSnapshot();
    return;
  }
  const command = event.target.closest("[data-command]")?.dataset.command;
  if (command) sendCommand(command, event.target.closest("[data-command]"));
}

if (globalThis.__FEATURE_DEMO_TEST__) {
  globalThis.__featureDemoTestHooks = {
    appState,
    handleDocumentClick,
    sendCommand,
    renderCommandWorkspace,
    renderWorkerDetails,
    resetRadarState,
    showHomeView,
    startRadarResizeTracking,
    stopRadarResizeTracking,
    updateCommandControls,
  };
} else {
  document.addEventListener("click", handleDocumentClick);
  document.querySelector('[data-action="exit-module"]').addEventListener("click", requestExit);
  document.querySelector('[data-action="continue-module"]').addEventListener("click", () => document.querySelector("[data-exit-dialog]").close());
  document.querySelector('[data-action="confirm-exit"]').addEventListener("click", confirmExit);
  document.querySelector('[data-action="error-exit"]').addEventListener("click", confirmExit);
  document.querySelector('[data-nav="feature-demo"]').addEventListener("click", () => { if (appState.active) requestExit(); });
  window.addEventListener("beforeunload", () => { closeStatusSocket(); stopFrameUpdates(); stopRadarResizeTracking(); });
  loadModules();
}
