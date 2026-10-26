"use strict";

(() => {
  const $ = (id) => document.getElementById(id);
  const state = { characters: [], character: null, phase: null, gesture: "all", action: "", search: "", scope: "", toastTimer: null };
  const gestureNames = { click: "短按", tap: "短按", hold: "长按", longpress: "长按", drag: "拖拽", swipe: "拖拽", automatic: "自动触发", auto: "自动触发", wait: "等待" };
  const gestureSymbols = { click: "·", hold: "◷", drag: "↝", automatic: "✧", unknown: "?" };
  const avatarColors = [["#efe5ef", "#916687"], ["#e9ecee", "#718391"], ["#f4e8df", "#ad866b"], ["#e7eeea", "#78927e"], ["#eee5ed", "#9a7193"], ["#f1e7e8", "#a97581"]];

  function text(value) {
    if (value == null) return "";
    if (typeof value === "string" || typeof value === "number") return String(value).trim();
    return "";
  }
  function words(value) {
    if (!Array.isArray(value)) return text(value) ? [text(value)] : [];
    return value.map((item) => text(item) || text(item?.description) || text(item?.text)).filter(Boolean);
  }
  function element(tag, className, value) {
    const node = document.createElement(tag);
    if (className) node.className = className;
    if (value !== undefined) node.textContent = value;
    return node;
  }
  function replace(id, nodes) { $(id).replaceChildren(...nodes.filter(Boolean)); }
  function empty(message) { return element("p", "empty-state", message); }
  function verificationLabel(value) { return text(value?.label) || text(value) || "说明待核对"; }
  function isVerified(value) { return ["verified", "live-verified", "live-tested", "current-live-verified"].includes(text(value?.level)); }
  function gestureKey(action) {
    const raw = text(action.gesture).toLowerCase();
    if (["click", "tap", "短按", "点击", "单击"].includes(raw)) return "click";
    if (["hold", "longpress", "长按"].includes(raw)) return "hold";
    if (["drag", "swipe", "拖拽", "滑动", "拖动"].includes(raw)) return "drag";
    if (["automatic", "auto", "自动触发", "自动"].includes(raw)) return "automatic";
    return "unknown";
  }
  function gestureLabel(action) {
    const key = gestureKey(action);
    let label = gestureNames[key] || text(action.gesture) || "操作待核对";
    if (key === "hold" && Number.isFinite(Number(action.holdSeconds)) && Number(action.holdSeconds) > 0) label += ` ${Number(action.holdSeconds)} 秒`;
    return label;
  }
  function normalizeCharacters(document) {
    if (!Array.isArray(document.characters) || document.characters.length === 0) throw new Error("角色目录为空，请等待资料更新后重试。");
    const used = new Set();
    return document.characters.map((raw, index) => {
      const id = text(raw.id) || `entry-${index + 1}`;
      if (used.has(id)) throw new Error("角色目录存在重复标识，暂时无法显示。");
      used.add(id);
      const phases = Array.isArray(raw.phases) ? raw.phases.map((phase, phaseIndex) => ({
        ...phase,
        id: text(phase.id) || String(phaseIndex + 1),
        name: text(phase.name) || `阶段 ${phaseIndex + 1}`,
        actions: Array.isArray(phase.actions) ? phase.actions.map((action, actionIndex) => ({ ...action, id: text(action.id) || `action-${actionIndex + 1}`, name: text(action.name) || text(action.location) || "互动位置待核对" })) : [],
        combos: Array.isArray(phase.combos) ? phase.combos.filter((combo) => Array.isArray(combo.steps) && combo.steps.length >= 2) : [],
        gaugeRules: Array.isArray(phase.gaugeRules) ? phase.gaugeRules : [],
        transitions: Array.isArray(phase.transitions) ? phase.transitions : []
      })) : [];
      return { ...raw, id, name: text(raw.name) || "角色名称待核对", costume: text(raw.costume) || "服装名称待核对", phases, sortIndex: index };
    });
  }
  function currentHash(characterId, phaseId, actionId = "") {
    const params = new URLSearchParams({ character: characterId, stage: phaseId });
    if (actionId) params.set("action", actionId);
    return `#${params.toString()}`;
  }
  function initialPhase(character) { return character.phases.find((phase) => phase.id === text(character.initialPhaseId)) || character.phases[0] || null; }
  function route(characterId, phaseId, actionId = "", options = {}) {
    const hash = currentHash(characterId, phaseId, actionId);
    if (options.replace) history.replaceState(null, "", hash);
    else if (location.hash !== hash) history.pushState(null, "", hash);
    applyHash(options.scroll !== false);
  }
  function applyHash(scroll = false) {
    if (!state.characters.length) return;
    const params = new URLSearchParams(location.hash.slice(1));
    const character = state.characters.find((item) => item.id === params.get("character")) || state.characters[0];
    const phase = character.phases.find((item) => item.id === params.get("stage")) || initialPhase(character);
    const action = text(params.get("action"));
    const different = state.character?.id !== character.id || state.phase?.id !== phase?.id;
    state.character = character;
    state.phase = phase;
    state.action = action;
    if (different) { state.gesture = "all"; renderGuide(); }
    renderCharacters();
    if (!phase) return;
    if (action) {
      if (state.gesture !== "all") { state.gesture = "all"; renderActions(); }
      highlightAction(action, scroll);
    } else if (scroll && different) $("guide").scrollIntoView({ block: "start" });
  }
  function actionDomId(actionId) { return `action-${encodeURIComponent(state.character.id)}-${encodeURIComponent(state.phase.id)}-${encodeURIComponent(actionId)}`; }
  function navigateAction(actionId) { route(state.character.id, state.phase.id, text(actionId), { scroll: true }); }
  function highlightAction(actionId, scroll) {
    document.querySelectorAll(".action-card.is-highlighted").forEach((node) => node.classList.remove("is-highlighted"));
    const node = document.getElementById(actionDomId(actionId));
    if (!node) return;
    node.classList.add("is-highlighted");
    if (scroll) requestAnimationFrame(() => { node.scrollIntoView({ block: "start" }); node.focus({ preventScroll: true }); });
  }

  function renderCharacters() {
    const query = state.search.trim().toLocaleLowerCase("zh-CN");
    const visible = state.characters.filter((item) => `${item.name} ${item.costume} ${words(item.aliases).join(' ')}`.toLocaleLowerCase("zh-CN").includes(query));
    $("character-count").textContent = String(state.characters.length);
    $("list-caption").textContent = query ? `找到 ${visible.length} 套服装` : `${new Set(state.characters.map((item) => item.name)).size} 位角色 · ${state.characters.length} 套服装`;
    const nodes = visible.map((character) => {
      const button = element("button", "character-button");
      button.type = "button";
      button.setAttribute("aria-current", String(character.id === state.character?.id));
      button.setAttribute("aria-label", `${character.name}，${character.costume}`);
      const colors = avatarColors[character.sortIndex % avatarColors.length];
      button.style.setProperty("--avatar-bg", colors[0]);
      button.style.setProperty("--avatar-ink", colors[1]);
      const avatar = element("span", "character-avatar", [...character.name].slice(0, 1).join(""));
      avatar.setAttribute("aria-hidden", "true");
      const copy = element("span", "character-list-copy");
      copy.append(element("strong", "", character.name), element("small", "", character.costume));
      button.append(avatar, copy);
      if (character.id === state.character?.id) { const flower = element("span", "active-flower", "✿"); flower.setAttribute("aria-hidden", "true"); button.append(flower); }
      button.addEventListener("click", (event) => {
        route(character.id, initialPhase(character)?.id || "", "", { scroll: matchMedia("(max-width:800px)").matches });
        if (event.detail === 0) $("character-list").querySelector('[aria-current="true"]')?.focus({ preventScroll: true });
      });
      return button;
    });
    replace("character-list", nodes.length ? nodes : [element("p", "character-empty", "没有找到这位角色。换个名字或服装关键词试试。")]);
  }

  function renderGuide() {
    const character = state.character;
    $("guide-content").hidden = false;
    $("character-name").textContent = character.name;
    $("costume-name").textContent = character.costume;
    $("character-mark").textContent = [...character.name].slice(0, 2).join("");
    $("character-summary").textContent = text(character.summary) || "跟着当前姿态，一步一步找到可以互动的部位。";
    $("scope-note").hidden = !state.scope;
    $("scope-note").textContent = state.scope ? `收录范围：${state.scope}` : "";
    document.title = `${character.name} · ${character.costume} — BD2有缘之客互动图鉴`;
    const verification = element("span", `badge ${isVerified(character.verification) ? "verified" : "pending"}`, verificationLabel(character.verification));
    const badges = [element("span", "badge", `${character.phases.length} 个阶段`), verification];
    const availability = text(character.availability?.label) || text(character.availability);
    if (availability) badges.push(element("span", "badge", availability));
    replace("character-badges", badges);
    const note = text(character.verification?.note);
    $("verification-note").hidden = !note;
    $("verification-note").textContent = note;
    renderCostumes();
    renderPhases();
    renderNotes();
    $("full-route").open = false;
    if (!state.phase) {
      $("phase-content").hidden = true;
      $("phase-empty").hidden = false;
      $("phase-empty").textContent = "这套服装的阶段路线尚未整理，暂不提供未经核对的操作步骤。";
      ["instruction-section", "combo-section", "gauge-section", "transition-section"].forEach((className) => document.querySelector(`.${className}`).hidden = true);
      $("full-route").hidden = true;
      $("previous-stage").disabled = $("next-stage").disabled = true;
      return;
    }
    $("phase-content").hidden = false;
    $("phase-empty").hidden = true;
    ["instruction-section", "combo-section", "gauge-section", "transition-section"].forEach((className) => document.querySelector(`.${className}`).hidden = false);
    renderPhase();
  }
  function renderCostumes() {
    const matches = state.characters.filter((item) => item.name === state.character.name);
    $("costume-switcher").hidden = matches.length < 2;
    const nodes = [element("span", "", "同角色服装")];
    matches.forEach((character) => {
      const button = element("button", "", character.costume);
      button.type = "button";
      button.setAttribute("aria-pressed", String(character.id === state.character.id));
      button.addEventListener("click", (event) => {
        route(character.id, initialPhase(character)?.id || "");
        if (event.detail === 0) $("costume-switcher").querySelector('[aria-pressed="true"]')?.focus({ preventScroll: true });
      });
      nodes.push(button);
    });
    replace("costume-switcher", nodes);
  }
  function renderPhases() {
    const phases = state.character.phases;
    $("stage-count").textContent = `${phases.length} 个阶段 · 手动浏览`;
    replace("phase-tabs", phases.map((phase, index) => {
      const label = /^阶段\s*\d+$/.test(phase.name) ? `阶段 ${index + 1}` : `${index + 1} · ${phase.name}`;
      const button = element("button", "phase-tab", label);
      button.id = `phase-tab-${encodeURIComponent(phase.id)}`;
      button.type = "button";
      button.setAttribute("role", "tab");
      button.setAttribute("aria-selected", String(phase.id === state.phase?.id));
      button.setAttribute("aria-controls", "phase-content");
      button.tabIndex = phase.id === state.phase?.id ? 0 : -1;
      button.title = phase.name;
      button.addEventListener("click", (event) => {
        route(state.character.id, phase.id);
        if (event.detail === 0) document.getElementById(`phase-tab-${encodeURIComponent(phase.id)}`)?.focus({ preventScroll: true });
      });
      button.addEventListener("keydown", (event) => {
        let next = index;
        if (event.key === "ArrowRight") next = (index + 1) % phases.length;
        else if (event.key === "ArrowLeft") next = (index + phases.length - 1) % phases.length;
        else if (event.key === "Home") next = 0;
        else if (event.key === "End") next = phases.length - 1;
        else return;
        event.preventDefault();
        route(state.character.id, phases[next].id, "", { scroll: false });
        document.getElementById(`phase-tab-${encodeURIComponent(phases[next].id)}`)?.focus();
      });
      return button;
    }));
    if (state.phase) $("phase-content").setAttribute("aria-labelledby", `phase-tab-${encodeURIComponent(state.phase.id)}`);
  }
  function renderPhase() {
    const phase = state.phase;
    const index = state.character.phases.indexOf(phase);
    $("phase-number").textContent = String(index + 1).padStart(2, "0");
    $("phase-name").textContent = phase.name;
    $("phase-summary").textContent = text(phase.summary) || "先完成想看的本阶段动作，再按阶段变化说明向前。";
    document.querySelector('.viewing-label').textContent = text(state.character.initialPhaseId) === phase.id ? "初始姿态" : "正在查看";
    renderSwimlane();
    renderActions();
    renderCombos();
    renderGauge();
    renderTransitions();
    renderOtherPhases();
    $("previous-stage").disabled = index <= 0;
    $("next-stage").disabled = index >= state.character.phases.length - 1;
  }

  function lane(label, caption, content) {
    const row = element("section", "lane");
    const heading = element("div", "lane-label");
    heading.append(element("strong", "", label), element("small", "", caption));
    const body = element("div", "lane-content");
    body.append(...content);
    row.append(heading, body);
    return row;
  }
  function renderSwimlane() {
    const phase = state.phase;
    const actions = element("div", "lane-action-grid");
    phase.actions.forEach((action) => {
      const node = element("a", `flow-node${action.nextStage != null && text(action.nextStage) ? " is-transition" : ""}`);
      node.href = currentHash(state.character.id, phase.id, action.id);
      node.append(element("strong", "", action.name), element("small", "", `${gestureLabel(action)}${text(action.location) ? ` · ${text(action.location)}` : ""}`));
      node.addEventListener("click", (event) => { event.preventDefault(); navigateAction(action.id); });
      actions.append(node);
    });
    const normal = actions.childElementCount ? [actions] : [element("p", "lane-empty", "本阶段尚未收录可确认的独立操作。")];
    const comboNodes = phase.combos.map((combo) => {
      const group = element("div", "flow-combination");
      group.append(element("p", "flow-combination-name", text(combo.name) || "连续组合"));
      const routeNode = element("div", "flow-route");
      combo.steps.forEach((step, index) => {
        if (index) routeNode.append(element("span", "route-arrow", "→"));
        const chip = element("span", "route-step");
        const action = findAction(step?.actionId)?.action;
        const part = action ? action.name.split(/[·｜|]/)[0].trim() : "";
        const label = stepLabel(step);
        chip.append(element("span", "step-number", String(index + 1)), element("span", "", part && !label.includes(part) ? `${part} · ${label}` : label));
        routeNode.append(chip);
      });
      group.append(routeNode);
      return group;
    });
    const ruleNodes = phase.gaugeRules.map((rule) => {
      const card = element("div", "flow-rule");
      card.append(element("span", "rule-dot"));
      const copy = element("div");
      copy.append(element("strong", "", text(rule?.title) || "进度条条件"));
      const description = text(rule?.trigger) || text(rule?.description) || text(rule);
      if (description) copy.append(element("small", "", description));
      card.append(copy);
      return card;
    });
    const transitions = phase.transitions.map((transition) => {
      const card = element("div", "flow-transition");
      const reversible = transition?.reversible === true;
      card.append(element("span", "transition-symbol", reversible ? "⇄" : "⇢"));
      const copy = element("div");
      copy.append(element("strong", "", text(transition?.label) || text(transition) || "阶段变化待核对"));
      const destination = phaseLabel(transition?.to);
      const detail = [destination ? `前往 ${destination}` : "", reversible ? "可逆切换" : "单向变化", text(transition?.condition)].filter(Boolean).join(" · ");
      copy.append(element("small", "", detail));
      card.append(copy);
      return card;
    });
    replace("swimlane", [
      lane("独立互动", "并列，分别操作", normal),
      lane("连续组合", "依次，连贯完成", comboNodes.length ? comboNodes : [element("p", "lane-empty", "当前阶段未收录可确认的连续组合。")]),
      lane("进度条条件", "先满足，再触发", ruleNodes.length ? ruleNodes : [element("p", "lane-empty", "当前阶段没有已确认的进度条操作说明。")]),
      lane("阶段流转", "看清方向，再向前", transitions.length ? transitions : [element("p", "lane-empty", "未收录下一阶段入口；可先查看游戏当前提示。")])
    ]);
  }

  function defaultInstructions(action) {
    const location = text(action.location) || "当前提示标记的部位";
    const key = gestureKey(action);
    if (key === "click") return [`在${location}短按一次后松开，等待对应动作结束。`];
    if (key === "hold") {
      const duration = Number(action.holdSeconds);
      return [Number.isFinite(duration) && duration > 0 ? `在${location}按住至少 ${duration} 秒，再按本条说明松开。` : `在${location}长按；准确时长尚待核对，请按游戏当前提示操作。`];
    }
    if (key === "drag") {
      const direction = text(action.drag?.direction);
      const destination = text(action.drag?.destination) || text(action.drag?.to);
      return [`从${location}按住并拖动${direction ? `，方向：${direction}` : "；拖拽方向待核对"}${destination ? `，终点：${destination}` : "；终点以游戏提示为准"}。`];
    }
    if (key === "automatic") return ["满足本条前置条件后由游戏自动触发，不要为了重复触发而连续点击。"];
    return ["准确操作方式尚待核对，请先查看本条条件和游戏提示。"];
  }
  function renderActions() {
    const actions = state.phase.actions;
    $("action-count").textContent = `${actions.length} 条操作说明`;
    const options = [["all", "全部"], ["click", "短按"], ["hold", "长按"], ["drag", "拖拽"], ["automatic", "自动触发"], ["unknown", "待核对"]];
    replace("gesture-filters", options.filter(([key]) => key === "all" || actions.some((action) => gestureKey(action) === key)).map(([key, label]) => {
      const count = key === "all" ? actions.length : actions.filter((action) => gestureKey(action) === key).length;
      const button = element("button", "filter-chip", label);
      button.type = "button";
      button.append(element("span", "", String(count)));
      button.setAttribute("aria-pressed", String(state.gesture === key));
      button.addEventListener("click", () => { state.gesture = key; state.action = ""; renderActions(); });
      return button;
    }));
    const visible = actions.filter((action) => state.gesture === "all" || gestureKey(action) === state.gesture);
    replace("action-grid", visible.length ? visible.map(renderAction) : [empty("当前筛选下没有收录动作。请选择其他操作方式。")]);
  }
  function renderAction(action) {
    const card = element("article", "action-card");
    card.id = actionDomId(action.id);
    card.tabIndex = -1;
    const header = element("div", "action-top");
    const key = gestureKey(action);
    header.append(element("h3", "", action.name), element("span", `gesture-badge ${key}`, `${gestureSymbols[key] || "?"} ${gestureLabel(action)}`));
    const location = element("p", "action-location");
    location.append(element("span", "location-symbol", "⌖"), element("strong", "", text(action.location) || "准确部位待核对，请结合游戏提示标记。"));
    const instructions = words(action.instructions);
    const ordered = element("ol", "instruction-lines");
    (instructions.length ? instructions : defaultInstructions(action)).forEach((line) => ordered.append(element("li", "", line)));
    card.append(header, location, ordered);
    const conditions = words(action.conditions);
    if (conditions.length) card.append(element("p", "action-condition", `前置条件：${conditions.join("；")}`));
    const note = text(action.note);
    if (note) card.append(element("p", "action-note", note));
    if (key === "drag" && action.drag?.verified === false) card.append(element("p", "action-verification", "拖拽落点尚待实机核对，请优先使用游戏内提示。"));
    const verification = text(action.verification?.note) || text(action.verification?.label) || (typeof action.verification === "string" ? action.verification : "");
    if (verification) card.append(element("p", "action-verification", verification));
    else if (action.verified === false) card.append(element("p", "action-verification", "此条操作尚待现场核对，请结合游戏当前提示。"));
    if (action.nextStage != null && text(action.nextStage)) card.append(element("p", "action-next", `⇢ 执行后前往${phaseLabel(action.nextStage) || "下一阶段"}，操作前先确认本阶段想看的动作已完成。`));
    return card;
  }
  function findAction(actionId) {
    const phases = [state.phase, ...state.character.phases.filter(phase => phase.id !== state.phase?.id)].filter(Boolean);
    for (const phase of phases) {
      const action = phase.actions.find((item) => item.id === text(actionId));
      if (action) return { phase, action };
    }
    return null;
  }
  function stepLabel(step) { return text(step?.label) || text(step?.name) || text(step) || findAction(step?.actionId)?.action.name || "按本步说明操作"; }
  function renderCombos() {
    const combos = state.phase.combos;
    $("combo-count").textContent = `${combos.length} 套连续操作`;
    replace("combo-list", combos.length ? combos.map((combo) => {
      const card = element("article", "combo-card");
      const heading = element("div", "combo-card-heading");
      heading.append(element("h3", "", text(combo.name) || "连续组合"));
      const seconds = Number(combo.windowSeconds);
      if (Number.isFinite(seconds) && seconds > 0) heading.append(element("span", "combo-duration", `操作窗口 ${seconds} 秒`));
      const steps = element("ol", "combo-steps");
      combo.steps.forEach((step, index) => {
        const li = element("li", "combo-step");
        li.append(element("span", "combo-step-number", String(index + 1).padStart(2, "0")));
        const match = findAction(step?.actionId);
        const title = match ? element("a", "", stepLabel(step)) : element("strong", "", stepLabel(step));
        if (match) { title.href = currentHash(state.character.id, match.phase.id, match.action.id); title.addEventListener("click", (event) => { event.preventDefault(); route(state.character.id, match.phase.id, match.action.id); }); }
        li.append(title);
        const detail = text(step?.instruction) || text(step?.note);
        if (detail) li.append(element("p", "", detail));
        else if (match) li.append(element("p", "", `${gestureLabel(match.action)} · ${text(match.action.location) || "部位见该动作说明"}`));
        steps.append(li);
      });
      card.append(heading, steps);
      const details = [...words(combo.conditions), text(combo.note)].filter(Boolean);
      if (details.length) card.append(element("p", "combo-note", details.join("；")));
      return card;
    }) : [empty("当前阶段未收录可确认的连续组合。独立点击、长按或一段完整拖拽仍可在“逐项操作”中查看。")]);
  }
  function renderGauge() {
    const rules = state.phase.gaugeRules;
    replace("gauge-list", rules.length ? rules.map((rule) => {
      const card = element("article", "gauge-card");
      card.append(element("span", "gauge-icon", "◔"));
      const copy = element("div");
      const heading = element("h3", "", text(rule?.title) || "进度条操作");
      if (rule?.automatic === true) heading.append(element("span", "automatic-label", "游戏自动触发"));
      copy.append(heading, element("p", "", text(rule?.description) || text(rule) || "具体触发方式待核对。"));
      if (text(rule?.trigger)) copy.append(element("span", "gauge-trigger", text(rule.trigger)));
      const conditions = words(rule?.conditions);
      if (conditions.length) copy.append(element("p", "", `前置条件：${conditions.join("；")}`));
      card.append(copy);
      return card;
    }) : [empty("当前阶段没有已确认的进度条触发说明。不要据此推断该服装没有进度条，以游戏内实际显示为准。")]);
  }
  function phaseLabel(id) {
    const index = state.character.phases.findIndex((phase) => phase.id === text(id));
    return index >= 0 ? `阶段 ${index + 1} · ${state.character.phases[index].name}` : "";
  }
  function renderTransitions() {
    replace("transition-list", state.phase.transitions.length ? state.phase.transitions.map((transition) => {
      const card = element("article", "transition-card");
      card.append(element("span", "big-arrow", transition?.reversible === true ? "⇄" : "⇢"));
      const copy = element("div");
      copy.append(element("h3", "", text(transition?.label) || text(transition) || "阶段变化"));
      const description = [text(transition?.condition), ...words(transition?.notes)].filter(Boolean);
      if (transition?.reversible === true) description.push("这是可逆切换，可按游戏当前开放的反向入口返回。");
      else description.push("按单向路线处理；继续前先完成本阶段想看的动作。");
      if (text(transition?.actionId)) {
        const match = findAction(transition.actionId);
        if (match) description.unshift(`入口：${match.action.name}，${text(match.action.location) || "具体位置见逐项操作"}。`);
      }
      copy.append(element("p", "", description.join(" ")));
      card.append(copy);
      const destination = state.character.phases.find((phase) => phase.id === text(transition?.to));
      if (destination) {
        const button = element("button", "", "查看目标阶段 →");
        button.type = "button";
        button.addEventListener("click", () => route(state.character.id, destination.id));
        card.append(button);
      }
      return card;
    }) : [empty("未收录当前阶段的切换入口。需要重新开始时，请使用游戏右上角的初始化，并以当前开放的动作提示为准。")]);
  }
  function renderOtherPhases() {
    const others = state.character.phases.filter((phase) => phase.id !== state.phase.id);
    $("full-route").hidden = others.length === 0;
    replace("other-phases", others.map((phase) => {
      const card = element("article", "other-phase-card");
      const index = state.character.phases.indexOf(phase);
      card.append(element("h3", "", `阶段 ${index + 1} · ${phase.name}`));
      if (text(phase.summary)) card.append(element("p", "", phase.summary));
      const tags = element("div", "other-phase-tags");
      phase.actions.forEach((action) => tags.append(element("span", "", `${action.name} · ${gestureLabel(action)}`)));
      card.append(tags);
      const button = element("button", "", "展开这个阶段的完整操作 →");
      button.type = "button";
      button.addEventListener("click", () => route(state.character.id, phase.id));
      card.append(button);
      return card;
    }));
  }
  function renderNotes() {
    const notes = [...words(state.character.notes), ...words(state.character.limitations)];
    $("reference-notes").hidden = notes.length === 0;
    replace("reference-notes-content", notes.map((note) => element("p", "", note)));
  }

  async function load() {
    $("loading-panel").hidden = false;
    $("error-panel").hidden = true;
    $("guide-content").hidden = true;
    const timeout = new AbortController();
    const timer = setTimeout(() => timeout.abort(), 15000);
    try {
      const response = await fetch(new URL("./data/characters.json", document.baseURI), { signal: timeout.signal, credentials: "omit", cache: "no-cache" });
      if (!response.ok) throw new Error(`角色资料暂时无法读取（HTTP ${response.status}）。`);
      const data = await response.json();
      if (data.schemaVersion !== 1) throw new Error("角色资料格式尚未支持，请等待网站更新后重试。");
      state.characters = normalizeCharacters(data);
      state.scope = text(data.summary?.scope) || text(data.coverageSummary?.scope);
      state.character = null;
      state.phase = null;
      applyHash(false);
      if (state.phase && !new URLSearchParams(location.hash.slice(1)).has("character")) route(state.character.id, state.phase.id, "", { replace: true, scroll: false });
      $("loading-panel").hidden = true;
    } catch (error) {
      $("loading-panel").hidden = true;
      $("error-panel").hidden = false;
      $("error-message").textContent = error?.name === "AbortError" ? "读取资料超时，请检查网络后重试。" : text(error?.message) || "角色资料暂时无法加载。";
      $("list-caption").textContent = "角色目录暂时不可用";
      $("character-count").textContent = "—";
    } finally { clearTimeout(timer); }
  }
  function toast(message) {
    clearTimeout(state.toastTimer);
    $("toast").textContent = message;
    $("toast").hidden = false;
    state.toastTimer = setTimeout(() => { $("toast").hidden = true; }, 3500);
  }
  $("character-search").addEventListener("input", (event) => { state.search = event.target.value; renderCharacters(); });
  $("choose-character").addEventListener("click", () => { document.querySelector('.character-sidebar').scrollIntoView({ block: 'start' }); $("character-search").focus({ preventScroll: true }); });
  $("retry-button").addEventListener("click", load);
  $("close-share-dialog").addEventListener("click", () => $("share-dialog").close());
  $("print-button").addEventListener("click", () => window.print());
  $("share-button").addEventListener("click", async () => {
    try {
      if (!navigator.clipboard?.writeText) throw new Error("clipboard unavailable");
      await navigator.clipboard.writeText(location.href);
      toast("当前角色与阶段的网址已复制。");
    } catch {
      $("share-url").value = location.href;
      $("share-dialog").showModal();
      $("share-url").select();
    }
  });
  $("previous-stage").addEventListener("click", () => {
    const index = state.character.phases.indexOf(state.phase);
    if (index > 0) route(state.character.id, state.character.phases[index - 1].id);
  });
  $("next-stage").addEventListener("click", () => {
    const index = state.character.phases.indexOf(state.phase);
    if (index + 1 < state.character.phases.length) route(state.character.id, state.character.phases[index + 1].id);
  });
  document.addEventListener("keydown", (event) => {
    const editing = /^(INPUT|TEXTAREA|SELECT)$/.test(document.activeElement?.tagName || "") || document.activeElement?.isContentEditable;
    if (event.key === "/" && !editing && !event.ctrlKey && !event.altKey && !event.metaKey) { event.preventDefault(); $("character-search").focus(); }
  });
  window.addEventListener("hashchange", () => applyHash(false));
  window.addEventListener("popstate", () => applyHash(false));
  load();
})();
