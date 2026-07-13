(function () {
  const AUTH_TOKEN = "attraction_demo_token";
  const AUTH_USER = "attraction_demo_user";
  const MCP_SWAGGER = "attraction_mcp_swagger_url";
  const MCP_BASE = "attraction_mcp_base_url";
  const MCP_SCHEME = "attraction_mcp_auth_scheme";

  const CONFIG_KEYS = {
    openaiApiKey: "attraction_openai_api_key",
    openaiModel: "attraction_openai_model",
    openaiBaseUrl: "attraction_openai_base_url",
  };

  /** Agent 对用户可见的三种状态（理解中 → 思考中 → 回复中） */
  const AGENT_STATE = {
    understanding: { label: "理解中", hint: "正在理解你的问题…" },
    thinking: { label: "思考中", hint: "正在推理与调用工具…" },
    replying: { label: "回复中", hint: "正在组织回复…" },
  };

  const els = {
    messages: document.getElementById("messages"),
    form: document.getElementById("chat-form"),
    input: document.getElementById("message-input"),
    sendBtn: document.getElementById("send-btn"),
    streamMode: document.getElementById("stream-mode"),
    showTools: document.getElementById("show-tools"),
    status: document.getElementById("status"),
    routeBadge: document.getElementById("route-badge"),
    openaiApiKey: document.getElementById("openai-api-key"),
    openaiModel: document.getElementById("openai-model"),
    openaiBaseUrl: document.getElementById("openai-base-url"),
  };

  let busy = false;
  let swaggerConnected = false;
  let connectState = "idle";

  const CHAT_PLACEHOLDER_CONNECTED = "输入消息，Enter 发送，Shift+Enter 换行";
  const CHAT_PLACEHOLDER_DISCONNECTED = "正在准备景点助手，请稍候…";

  function requireAuth() {
    const token = sessionStorage.getItem(AUTH_TOKEN);
    if (!token) {
      window.location.replace("/login");
      return false;
    }
    return true;
  }

  function getMcpConfig() {
    return {
      swaggerUrl: sessionStorage.getItem(MCP_SWAGGER) || "",
      baseUrl: sessionStorage.getItem(MCP_BASE) || "",
      authScheme: sessionStorage.getItem(MCP_SCHEME) || "Bearer",
      token: sessionStorage.getItem(AUTH_TOKEN) || "",
    };
  }

  function getSessionKey() {
    try {
      const user = JSON.parse(sessionStorage.getItem(AUTH_USER) || "{}");
      return normalizeSessionKey(user.user_id || user.username || "");
    } catch (_) {
      return "";
    }
  }

  function renderUserLabel() {
    const label = document.getElementById("user-label");
    if (!label) return;
    try {
      const user = JSON.parse(sessionStorage.getItem(AUTH_USER) || "{}");
      const name = user.display_name || user.username || "已登录";
      const id = user.user_id ? "（" + user.user_id + "）" : "";
      label.textContent = name + id;
    } catch (_) {
      label.textContent = "已登录";
    }
  }

  if (typeof marked !== "undefined") {
    marked.use({ breaks: true, gfm: true });
  }

  function renderMarkdown(el, text) {
    if (!text) {
      el.textContent = "";
      el.classList.remove("markdown-body");
      return;
    }
    if (typeof marked === "undefined" || typeof DOMPurify === "undefined") {
      el.textContent = text;
      el.classList.remove("markdown-body");
      return;
    }
    const raw = marked.parse(text);
    el.innerHTML = DOMPurify.sanitize(raw, { USE_PROFILES: { html: true } });
    el.querySelectorAll("a").forEach(function (a) {
      a.setAttribute("target", "_blank");
      a.setAttribute("rel", "noopener noreferrer");
    });
    el.classList.add("markdown-body");
  }

  function normalizeSessionKey(value) {
    const trimmed = (value || "").trim();
    if (!trimmed) return "";
    if (trimmed.startsWith("mem:") && trimmed.endsWith(":default")) {
      return trimmed.slice(4, -":default".length);
    }
    return trimmed;
  }

  function loadSettings() {
    const fields = {
      openaiApiKey: els.openaiApiKey,
      openaiModel: els.openaiModel,
      openaiBaseUrl: els.openaiBaseUrl,
    };
    for (const [key, el] of Object.entries(fields)) {
      if (!el) continue;
      const value = localStorage.getItem(CONFIG_KEYS[key]);
      if (value) el.value = value;
    }
  }

  function saveSettings() {
    const fields = {
      openaiApiKey: els.openaiApiKey,
      openaiModel: els.openaiModel,
      openaiBaseUrl: els.openaiBaseUrl,
    };
    for (const [key, el] of Object.entries(fields)) {
      if (!el) continue;
      localStorage.setItem(CONFIG_KEYS[key], el.value.trim());
    }
  }

  function configPayload() {
    const mcp = getMcpConfig();
    return {
      openai_model: els.openaiModel && els.openaiModel.value.trim(),
      openai_base_url: els.openaiBaseUrl && els.openaiBaseUrl.value.trim(),
      mcp_swagger_url: mcp.swaggerUrl,
      mcp_base_url: mcp.baseUrl,
      mcp_auth_scheme: mcp.authScheme,
      mcp_token: mcp.token,
    };
  }

  async function applyConfig() {
    const res = await fetch("/hubloom/config/apply", {
      method: "POST",
      headers: buildHeaders(getSessionKey()),
      body: JSON.stringify(configPayload()),
    });

    const text = await res.text();
    if (!res.ok) {
      let message = "HTTP " + res.status;
      try {
        const data = JSON.parse(text);
        message = data.detail || message;
      } catch (_) {
        message = text || message;
      }
      throw new Error(message);
    }

    return text ? JSON.parse(text) : {};
  }

  function setConnectState(state) {
    connectState = state;
    swaggerConnected = state === "ok";
    updateChatInputState();
  }

  function updateChatInputState() {
    const canChat = swaggerConnected && !busy;
    if (els.input) {
      els.input.disabled = !canChat;
      els.input.placeholder = swaggerConnected
        ? CHAT_PLACEHOLDER_CONNECTED
        : CHAT_PLACEHOLDER_DISCONNECTED;
    }
    if (els.sendBtn) {
      els.sendBtn.disabled = !canChat;
    }
    if (els.form) {
      els.form.classList.toggle("composer-disabled", !swaggerConnected);
    }
    refreshEmptyState();
  }

  async function autoConnect() {
    saveSettings();
    setConnectState("loading");
    setStatus("正在同步景点 API 配置…");

    try {
      await applyConfig();
      setConnectState("ok");
      setStatus("就绪");
      await loadHistory();
    } catch (err) {
      setConnectState("error");
      setStatus(String(err.message || err));
      ensureEmptyState();
    }

    updateChatInputState();
    if (swaggerConnected) els.input.focus();
  }

  function setStatus(text) {
    els.status.textContent = text;
  }

  function setRoute(route) {
    if (!route) {
      els.routeBadge.classList.add("hidden");
      return;
    }
    const label = route === "thought" ? "深度思考" : route === "chat" ? "快答" : route;
    els.routeBadge.textContent = label;
    els.routeBadge.classList.remove("hidden");
  }

  function scrollToBottom() {
    els.messages.scrollTop = els.messages.scrollHeight;
  }

  function getEmptyStateHtml() {
    if (swaggerConnected) {
      return (
        '<p class="empty-title">开始对话</p>' +
        '<p class="empty-desc">用自然语言查询景区门票、预约时段与订单。</p>' +
        '<p class="empty-hint">例如：「行程 TRIP-5566 的故宫门票状态？」' +
        "「查 HTL-889 订单详情」</p>"
      );
    }
    return (
      '<p class="empty-title">正在准备助手</p>' +
      '<p class="empty-desc">请确认 Hubloom 与景点服务均已启动，并填写 OpenAI API Key。</p>'
    );
  }

  function renderEmptyState(empty) {
    empty.className =
      "empty-state" +
      (swaggerConnected ? " empty-state-ready" : " empty-state-disconnected");
    empty.innerHTML = getEmptyStateHtml();
  }

  function refreshEmptyState() {
    const empty = document.getElementById("empty-state");
    if (empty) {
      renderEmptyState(empty);
      return;
    }
    if (els.messages.children.length === 0) {
      ensureEmptyState();
    }
  }

  function ensureEmptyState() {
    if (els.messages.children.length > 0 && !document.getElementById("empty-state")) {
      return;
    }

    let empty = document.getElementById("empty-state");
    if (!empty) {
      empty = document.createElement("div");
      empty.id = "empty-state";
      els.messages.appendChild(empty);
    }
    renderEmptyState(empty);
  }

  function removeEmptyState() {
    const empty = document.getElementById("empty-state");
    if (empty) empty.remove();
  }

  function clearMessages() {
    els.messages.innerHTML = "";
  }

  async function loadHistory() {
    const sessionKey = getSessionKey();
    if (!sessionKey) {
      clearMessages();
      ensureEmptyState();
      return;
    }

    clearMessages();
    setStatus("加载历史…");

    try {
      const url =
        "/hubloom/chat/history?session_id=" + encodeURIComponent(sessionKey);
      const res = await fetch(url, { headers: buildHeaders(sessionKey) });
      if (!res.ok) {
        const errText = await res.text();
        throw new Error(errText || "HTTP " + res.status);
      }
      const data = await res.json();
      for (const msg of data.messages || []) {
        if (msg.role === "user") {
          const text = (msg.content || "").trim();
          if (text) appendMessage("user", text);
          continue;
        }
        renderAssistantHistory(msg);
      }
      ensureEmptyState();
      setStatus("就绪");
    } catch (err) {
      ensureEmptyState();
      setStatus("历史加载失败");
      console.error(err);
    }
    scrollToBottom();
  }

  function appendMessage(role, text, extraClass) {
    removeEmptyState();
    const div = document.createElement("div");
    div.className = "msg " + role + (extraClass ? " " + extraClass : "");
    if (role === "assistant") {
      renderMarkdown(div, text);
    } else {
      div.textContent = text;
    }
    els.messages.appendChild(div);
    scrollToBottom();
    return div;
  }

  /** call_tool 等元工具在 UI 上展示内部 tool_name */
  function resolveToolDisplayName(toolName, args) {
    const name = (toolName || "").trim() || "tool";
    if (
      name === "call_tool" &&
      args &&
      typeof args.tool_name === "string" &&
      args.tool_name.trim()
    ) {
      return args.tool_name.trim();
    }
    return name;
  }

  function buildToolInline(title, body, opts) {
    const details = document.createElement("details");
    details.className = "tool-inline tool-card";
    details.open = !!(opts && opts.open);
    const summary = document.createElement("summary");
    summary.className = "tool-card-summary";

    const kind = (opts && opts.kind) || "";
    const name = (opts && opts.name) || title;
    if (kind === "call" || kind === "ret" || kind === "fail") {
      const chip = document.createElement("span");
      chip.className =
        "tool-chip " +
        (kind === "call" ? "call" : kind === "fail" ? "fail" : "ret");
      chip.textContent =
        kind === "call" ? "调用" : kind === "fail" ? "失败" : "返回";
      summary.appendChild(chip);
      const nameEl = document.createElement("span");
      nameEl.className = "tool-card-name";
      nameEl.textContent = name;
      summary.appendChild(nameEl);
      if (opts && opts.badge) {
        const badge = document.createElement("span");
        badge.className = "tool-chip badge";
        badge.textContent = opts.badge;
        summary.appendChild(badge);
      }
    } else {
      summary.textContent = title;
    }

    const pre = document.createElement("pre");
    pre.textContent = body || "";
    details.appendChild(summary);
    details.appendChild(pre);
    return details;
  }

  function buildRemoteProcessPanel(agentId) {
    const wrap = document.createElement("div");
    wrap.className = "remote-process is-open";

    const head = document.createElement("div");
    head.className = "remote-process-head";

    const title = document.createElement("div");
    title.className = "remote-process-title";
    const nameSpan = document.createElement("span");
    nameSpan.textContent = "远程过程 · " + (agentId || "Agent");
    const meta = document.createElement("span");
    meta.className = "remote-process-meta";
    if (agentId) meta.textContent = agentId;
    title.appendChild(nameSpan);
    title.appendChild(meta);

    const status = document.createElement("span");
    status.className = "remote-process-status is-live";
    status.textContent = "进行中";

    head.appendChild(title);
    head.appendChild(status);

    const body = document.createElement("div");
    body.className = "remote-process-body";

    const thought = document.createElement("div");
    thought.className = "remote-process-thought";

    const tools = document.createElement("div");
    tools.className = "remote-process-tools";

    body.appendChild(thought);
    body.appendChild(tools);

    head.addEventListener("click", (e) => {
      e.preventDefault();
      wrap.classList.toggle("is-open");
    });

    wrap.appendChild(head);
    wrap.appendChild(body);

    return {
      wrap,
      body,
      status,
      title,
      thought,
      tools,
      buffer: "",
      agentId: agentId || "",
    };
  }

  /** 把 A2A trace 文本拆成：思考文案 + 工具卡片（对齐示意稿） */
  function renderRemoteTrace(panel) {
    const raw = panel.buffer || "";
    const thoughtChunks = [];
    const toolItems = [];

    const re =
      /\[tool_call\]\s+(\S+)(?:\s+(\{[\s\S]*?\}))?(?=\n\[|\s*$)|\[tool_result:(ok|ERROR)\]\s+(\S+)\n?([\s\S]*?)(?=\n\[tool_call\]|\n\[tool_result:|\n\[(?:thinking|replying|working)\]|\s*$)|\[(thinking|replying|working)\][^\n]*/g;

    let last = 0;
    let m;
    while ((m = re.exec(raw)) !== null) {
      if (m.index > last) {
        const gap = raw.slice(last, m.index).trim();
        if (gap) thoughtChunks.push(gap);
      }
      last = m.index + m[0].length;

      if (m[1]) {
        // tool_call
        toolItems.push({
          kind: "call",
          name: m[1],
          body: (m[2] || "").trim(),
        });
      } else if (m[4]) {
        // tool_result
        toolItems.push({
          kind: m[3] === "ERROR" ? "fail" : "ret",
          name: m[4],
          body: (m[5] || "").trim(),
        });
      } else if (m[6]) {
        // phase line — 轻量写入思考区
        const line = m[0].trim();
        if (line) thoughtChunks.push(line);
      }
    }
    if (last < raw.length) {
      const tail = raw.slice(last).trim();
      if (tail) thoughtChunks.push(tail);
    }

    const thoughtText = thoughtChunks.join("\n").trim();
    panel.thought.textContent = thoughtText;
    panel.thought.style.display = thoughtText ? "" : "none";

    panel.tools.innerHTML = "";
    for (const item of toolItems) {
      panel.tools.appendChild(
        buildToolInline("", item.body, {
          kind: item.kind,
          name: item.name,
          open: false,
        })
      );
    }
  }

  /** 从历史记录渲染助手消息（含可折叠思考区） */
  function renderAssistantHistory(msg) {
    const content = (msg.content || "").trim();
    const thought = (msg.thought || "").trim();
    const tools = Array.isArray(msg.tools) ? msg.tools : [];

    if (!thought && !tools.length) {
      if (content) appendMessage("assistant", content);
      return;
    }

    removeEmptyState();
    const root = document.createElement("div");
    root.className = "msg assistant turn history";

    const thoughtPanel = document.createElement("details");
    thoughtPanel.className = "thought-panel";
    thoughtPanel.open = false;
    const thoughtSummary = document.createElement("summary");
    thoughtSummary.className = "thought-summary";
    const thoughtLen = thought.length;
    thoughtSummary.textContent =
      thoughtLen > 0 ? "思考过程（" + thoughtLen + " 字）" : "思考过程";
    const thoughtBody = document.createElement("div");
    thoughtBody.className = "thought-body";
    if (thought) thoughtBody.textContent = thought;
    const toolHost = document.createElement("div");
    toolHost.className = "thought-tools";
    if (els.showTools.checked) {
      for (const item of tools) {
        const title = (item.title || "").trim();
        if (!title) continue;
        if (title.startsWith("远程过程 ·")) {
          const agentId = title.replace(/^远程过程\s*·\s*/, "");
          const panel = buildRemoteProcessPanel(agentId);
          panel.status.textContent = "已完成";
          panel.status.classList.remove("is-live");
          panel.status.classList.add("is-done");
          panel.buffer = item.body || "";
          renderRemoteTrace(panel);
          panel.wrap.classList.add("is-open");
          toolHost.appendChild(panel.wrap);
          continue;
        }
        let kind = "";
        let name = title;
        if (title.startsWith("调用")) {
          kind = "call";
          name = title.replace(/^调用\s*·\s*/, "");
        } else if (title.startsWith("返回")) {
          kind = "ret";
          name = title.replace(/^返回\s*·\s*/, "");
        } else if (title.startsWith("失败")) {
          kind = "fail";
          name = title.replace(/^失败\s*·\s*/, "");
        }
        toolHost.appendChild(
          buildToolInline(title, item.body || "", { kind, name })
        );
      }
    }
    thoughtPanel.appendChild(thoughtSummary);
    thoughtPanel.appendChild(thoughtBody);
    if (toolHost.childElementCount > 0) thoughtPanel.appendChild(toolHost);

    const answerEl = document.createElement("div");
    answerEl.className = "answer-body";
    renderMarkdown(answerEl, content || "（无文本回复）");

    root.appendChild(thoughtPanel);
    root.appendChild(answerEl);
    els.messages.appendChild(root);
    scrollToBottom();
  }

  /** 创建一轮助手回复容器：状态条 + 可折叠思考区 + 正式回复区 */
  function createAssistantTurn() {
    removeEmptyState();
    const root = document.createElement("div");
    root.className = "msg assistant turn";

    const statusBar = document.createElement("div");
    statusBar.className = "agent-status";
    statusBar.setAttribute("data-state", "understanding");
    statusBar.setAttribute("aria-live", "polite");

    const statusLabel = document.createElement("span");
    statusLabel.className = "agent-status-label";
    statusLabel.textContent = AGENT_STATE.understanding.label;

    const statusHint = document.createElement("span");
    statusHint.className = "agent-status-hint";
    statusHint.textContent = AGENT_STATE.understanding.hint;

    const statusDots = document.createElement("span");
    statusDots.className = "agent-status-dots";
    statusDots.setAttribute("aria-hidden", "true");
    statusDots.innerHTML =
      '<span class="dot"></span><span class="dot"></span><span class="dot"></span>';

    statusBar.appendChild(statusLabel);
    statusBar.appendChild(statusHint);
    statusBar.appendChild(statusDots);

    const thoughtPanel = document.createElement("details");
    thoughtPanel.className = "thought-panel hidden";
    const thoughtSummary = document.createElement("summary");
    thoughtSummary.className = "thought-summary";
    thoughtSummary.textContent = "思考过程";
    const thoughtBody = document.createElement("div");
    thoughtBody.className = "thought-body";
    const toolHost = document.createElement("div");
    toolHost.className = "thought-tools";
    thoughtPanel.appendChild(thoughtSummary);
    thoughtPanel.appendChild(thoughtBody);
    thoughtPanel.appendChild(toolHost);

    const answerEl = document.createElement("div");
    answerEl.className = "answer-body hidden";

    root.appendChild(statusBar);
    root.appendChild(thoughtPanel);
    root.appendChild(answerEl);
    els.messages.appendChild(root);
    scrollToBottom();

    let thoughtText = "";
    let answerText = "";
    let currentState = "understanding";
    let hasThought = false;
    /** @type {Map<string, HTMLElement>} */
    const callBlocks = new Map();
    /** @type {Map<string, any>} */
    const remoteByCallId = new Map();

    function updateThoughtSummary() {
      const len = thoughtText.trim().length;
      thoughtSummary.textContent =
        len > 0 ? "思考过程（" + len + " 字）" : "思考过程";
    }

    function setAgentState(state) {
      if (!AGENT_STATE[state]) return;
      currentState = state;
      statusBar.setAttribute("data-state", state);
      statusLabel.textContent = AGENT_STATE[state].label;
      statusHint.textContent = AGENT_STATE[state].hint;
      setStatus(AGENT_STATE[state].label + "…");
    }

    function showThoughtPanel() {
      if (!hasThought) {
        hasThought = true;
        thoughtPanel.classList.remove("hidden");
        thoughtPanel.open = true;
      }
    }

    function appendThoughtDelta(delta) {
      if (!delta) return;
      showThoughtPanel();
      if (currentState !== "replying") setAgentState("thinking");
      thoughtText += delta;
      thoughtBody.textContent = thoughtText;
      updateThoughtSummary();
      scrollToBottom();
    }

    function parseToolTitle(title) {
      const t = (title || "").trim();
      if (t.startsWith("调用 · ") || t.startsWith("调用 ·")) {
        return { kind: "call", name: t.replace(/^调用\s*·\s*/, "") };
      }
      if (t.startsWith("返回 · ") || t.startsWith("返回 ·")) {
        return { kind: "ret", name: t.replace(/^返回\s*·\s*/, "") };
      }
      if (t.startsWith("失败 · ") || t.startsWith("失败 ·")) {
        return { kind: "fail", name: t.replace(/^失败\s*·\s*/, "") };
      }
      return { kind: "", name: t };
    }

    function appendToolBlock(title, body, opts) {
      if (!els.showTools.checked) return null;
      showThoughtPanel();
      if (currentState !== "replying") setAgentState("thinking");
      const parsed = parseToolTitle(title);
      const badge =
        opts && opts.badge
          ? opts.badge
          : parsed.kind === "call" &&
              parsed.name === "delegate_task" &&
              opts &&
              opts.agentId
            ? "→ " + opts.agentId
            : "";
      const block = buildToolInline(title, body, {
        kind: parsed.kind,
        name: parsed.name,
        badge: badge,
        open: !!(opts && opts.open),
      });
      if (opts && opts.callId) {
        block.dataset.callId = opts.callId;
        if (parsed.kind === "call") callBlocks.set(opts.callId, block);
      }
      toolHost.appendChild(block);
      scrollToBottom();
      return block;
    }

    function ensureRemotePanel(callId, agentId) {
      if (!els.showTools.checked) return null;
      if (remoteByCallId.has(callId)) {
        const existing = remoteByCallId.get(callId);
        if (agentId && existing.agentId !== agentId) {
          existing.agentId = agentId;
          const nameSpan = existing.title.firstElementChild;
          if (nameSpan) nameSpan.textContent = "远程过程 · " + agentId;
          const meta = existing.title.querySelector(".remote-process-meta");
          if (meta) meta.textContent = agentId;
        }
        return existing;
      }
      showThoughtPanel();
      const panel = buildRemoteProcessPanel(agentId || "");
      remoteByCallId.set(callId, panel);

      const parent = callBlocks.get(callId);
      if (parent) {
        parent.open = true;
        parent.classList.add("has-remote");
        parent.appendChild(panel.wrap);
      } else {
        toolHost.appendChild(panel.wrap);
      }
      scrollToBottom();
      return panel;
    }

    function appendRemoteDelta(data) {
      const callId = (data && data.call_id) || "";
      if (!callId) return;
      const agentId = (data && data.agent_id) || "";
      const channel = (data && data.channel) || "trace";
      const status = (data && data.status) || "";
      const delta = (data && data.delta) || "";
      const panel = ensureRemotePanel(callId, agentId);
      if (!panel) return;

      if (channel === "status" || status) {
        const st = status || delta;
        if (st === "working" || st === "started") {
          panel.status.textContent = "进行中";
          panel.status.classList.add("is-live");
          panel.status.classList.remove("is-done", "is-fail");
          panel.wrap.classList.add("is-open");
        } else if (st === "completed") {
          panel.status.textContent = "已完成";
          panel.status.classList.remove("is-live", "is-fail");
          panel.status.classList.add("is-done");
        } else if (st === "failed") {
          panel.status.textContent = "失败";
          panel.status.classList.remove("is-live", "is-done");
          panel.status.classList.add("is-fail");
        }
      }

      if (channel === "trace" && delta) {
        panel.buffer += delta;
        renderRemoteTrace(panel);
        panel.wrap.classList.add("is-open");
      }
      scrollToBottom();
    }

    function beginReply() {
      setAgentState("replying");
      answerEl.classList.remove("hidden");
      if (hasThought) thoughtPanel.open = false;
    }

    function appendAnswerDelta(delta) {
      if (!delta) return;
      if (!answerText) beginReply();
      answerText += delta;
      answerEl.textContent = answerText;
      answerEl.classList.add("typing");
      scrollToBottom();
    }

    function appendStreamNotice(message) {
      const text = (message || "").trim();
      if (!text) return;
      let notice = root.querySelector(".stream-notice");
      if (!notice) {
        notice = document.createElement("div");
        notice.className = "stream-notice";
        root.insertBefore(notice, answerEl);
      }
      notice.textContent = text;
      scrollToBottom();
    }

    function finalize(finalText, route) {
      statusBar.classList.add("hidden");
      answerEl.classList.remove("typing");
      const text = (finalText || answerText || "").trim();
      if (text) {
        answerEl.classList.remove("hidden");
        renderMarkdown(answerEl, text);
        answerText = text;
      } else if (!answerText.trim()) {
        answerEl.classList.remove("hidden");
        renderMarkdown(answerEl, "（无文本回复）");
      }
      if (hasThought) {
        thoughtPanel.classList.remove("hidden");
        thoughtPanel.open = false;
        updateThoughtSummary();
      }
      if (route) setRoute(route);
      setStatus("就绪");
      scrollToBottom();
    }

    function remove() {
      root.remove();
    }

    return {
      root,
      setAgentState,
      appendThoughtDelta,
      appendToolBlock,
      appendRemoteDelta,
      ensureRemotePanel,
      beginReply,
      appendAnswerDelta,
      appendStreamNotice,
      finalize,
      remove,
    };
  }

  function phaseStatusText(phase) {
    const map = {
      deliberate: "深度推理",
      execute: "执行工具",
      respond: "组织回复",
      thinking: "思考中",
      replying: "回复中",
    };
    return map[phase] || phase;
  }

  function waitForPaint() {
    return new Promise(function (resolve) {
      requestAnimationFrame(function () {
        requestAnimationFrame(resolve);
      });
    });
  }

  const scrollbarTimers = new WeakMap();
  const SCROLLBAR_REVEAL_MS = 1000;

  function markScrollbarActive(el) {
    if (!(el instanceof Element)) return;
    if (!el.matches(".sidebar, .messages, .thought-body")) return;

    el.classList.add("scrollbar-active");
    const prev = scrollbarTimers.get(el);
    if (prev) clearTimeout(prev);
    scrollbarTimers.set(
      el,
      setTimeout(function () {
        el.classList.remove("scrollbar-active");
        scrollbarTimers.delete(el);
      }, SCROLLBAR_REVEAL_MS)
    );
  }

  function setupScrollbarReveal() {
    document.querySelectorAll(".sidebar, .messages").forEach(function (el) {
      ["scroll", "wheel"].forEach(function (eventName) {
        el.addEventListener(eventName, function () {
          markScrollbarActive(el);
        }, { passive: true });
      });
    });

    document.addEventListener(
      "scroll",
      function (e) {
        markScrollbarActive(e.target);
      },
      true
    );
  }

  function buildHeaders(sessionKey) {
    const headers = { "Content-Type": "application/json" };
    if (sessionKey) headers["X-Session-Id"] = sessionKey;

    const apiKey = els.openaiApiKey && els.openaiApiKey.value.trim();
    if (apiKey) headers["X-OpenAI-Api-Key"] = apiKey;
    const model = els.openaiModel && els.openaiModel.value.trim();
    if (model) headers["X-OpenAI-Model"] = model;
    const baseUrl = els.openaiBaseUrl && els.openaiBaseUrl.value.trim();
    if (baseUrl) headers["X-OpenAI-Base-Url"] = baseUrl;

    const mcp = getMcpConfig();
    if (mcp.swaggerUrl) headers["X-MCP-Swagger-Url"] = mcp.swaggerUrl;
    if (mcp.baseUrl) headers["X-MCP-Base-Url"] = mcp.baseUrl;

    const token = mcp.token;
    const scheme = mcp.authScheme || "Bearer";
    if (scheme) headers["X-MCP-Auth-Scheme"] = scheme;
    if (token) {
      headers["X-MCP-Token"] = token;
      headers["Authorization"] = scheme + " " + token;
    }
    return headers;
  }

  function parseSseChunk(buffer) {
    const events = [];
    const parts = buffer.split("\n\n");
    const rest = parts.pop() || "";
    for (const part of parts) {
      if (!part.trim()) continue;
      let eventName = "message";
      let dataLine = "";
      for (const line of part.split("\n")) {
        if (line.startsWith("event:")) eventName = line.slice(6).trim();
        if (line.startsWith("data:")) dataLine += line.slice(5).trim();
      }
      if (dataLine) {
        try {
          events.push({ event: eventName, data: JSON.parse(dataLine) });
        } catch (_) {
          events.push({ event: eventName, data: { raw: dataLine } });
        }
      }
    }
    return { events, rest };
  }

  async function chatStream(message, sessionKey, turn) {
    const res = await fetch("/hubloom/chat", {
      method: "POST",
      headers: buildHeaders(sessionKey),
      body: JSON.stringify({
        message,
        session_id: sessionKey || null,
        stream: true,
      }),
    });

    if (!res.ok) {
      const errText = await res.text();
      throw new Error(errText || "HTTP " + res.status);
    }

    const reader = res.body.getReader();
    const decoder = new TextDecoder();
    let buffer = "";

    while (true) {
      const { done, value } = await reader.read();
      if (done) break;
      buffer += decoder.decode(value, { stream: true });
      const parsed = parseSseChunk(buffer);
      buffer = parsed.rest;

      for (const { event, data } of parsed.events) {
        if (event === "phase") {
          const phase = (data.phase || "").trim();
          if (phase === "thinking") turn.setAgentState("thinking");
          else if (phase === "replying") turn.beginReply();
          if (data.route) setRoute(data.route);
        } else if (event === "thought_delta") {
          turn.appendThoughtDelta(data.delta || "");
        } else if (event === "text_delta" && data.delta) {
          turn.appendAnswerDelta(data.delta);
        } else if (event === "tool_call") {
          const toolName = resolveToolDisplayName(
            data.tool_name || "tool",
            data.args || {}
          );
          const callId = data.call_id || "";
          const agentId =
            (data.args && (data.args.agent_id || data.args.agentId)) || "";
          turn.appendToolBlock(
            "调用 · " + toolName,
            JSON.stringify(data.args || {}, null, 2),
            {
              callId: callId,
              agentId: agentId,
              open: toolName === "delegate_task",
            }
          );
          if (toolName === "delegate_task" || data.tool_name === "delegate_task") {
            if (callId) turn.ensureRemotePanel(callId, agentId);
          }
        } else if (event === "remote_delta") {
          turn.appendRemoteDelta(data || {});
        } else if (event === "tool_result") {
          const toolName = data.tool_name || "tool";
          turn.appendToolBlock(
            (data.is_error ? "失败 · " : "返回 · ") + toolName,
            data.result || "",
            { callId: data.call_id || "" }
          );
        } else if (event === "turn_complete") {
          turn.finalize(data.final_message || "", data.route || "");
        } else if (event === "error") {
          const msg = data.error || "未知错误";
          if (data.recoverable) {
            turn.appendStreamNotice(msg);
            continue;
          }
          throw new Error(msg);
        }
      }
    }
  }

  async function chatOnce(message, sessionKey) {
    const res = await fetch("/hubloom/chat", {
      method: "POST",
      headers: buildHeaders(sessionKey),
      body: JSON.stringify({
        message,
        session_id: sessionKey || null,
        stream: false,
      }),
    });

    if (!res.ok) {
      const errText = await res.text();
      throw new Error(errText || "HTTP " + res.status);
    }

    return await res.json();
  }

  async function onSubmit(e) {
    e.preventDefault();
    if (busy || !swaggerConnected) return;

    const message = els.input.value.trim();
    if (!message) return;

    saveSettings();
    const sessionKey = getSessionKey();

    busy = true;
    updateChatInputState();
    setRoute("");

    appendMessage("user", message);
    els.input.value = "";

    const turn = createAssistantTurn();
    turn.setAgentState("understanding");
    await waitForPaint();

    try {
      if (els.streamMode.checked) {
        await chatStream(message, sessionKey, turn);
      } else {
        turn.setAgentState("understanding");
        const data = await chatOnce(message, sessionKey);
        turn.finalize(data.final_message || "", data.route || "");
      }
    } catch (err) {
      turn.remove();
      appendMessage("error", String(err.message || err), "error");
      setStatus("出错");
    } finally {
      busy = false;
      updateChatInputState();
      if (swaggerConnected) els.input.focus();
      scrollToBottom();
    }
  }

  els.form.addEventListener("submit", onSubmit);

  els.input.addEventListener("keydown", (e) => {
    if (e.key === "Enter" && !e.shiftKey) {
      e.preventDefault();
      els.form.requestSubmit();
    }
  });

  [
    els.openaiApiKey,
    els.openaiModel,
    els.openaiBaseUrl,
  ].forEach(function (el) {
    if (!el) return;
    el.addEventListener("change", function () {
      saveSettings();
      autoConnect();
    });
  });

  const logoutLink = document.getElementById("logout-link");
  if (logoutLink) {
    logoutLink.addEventListener("click", function () {
      sessionStorage.removeItem(AUTH_TOKEN);
      sessionStorage.removeItem(AUTH_USER);
      sessionStorage.removeItem(MCP_SWAGGER);
      sessionStorage.removeItem(MCP_BASE);
      sessionStorage.removeItem(MCP_SCHEME);
    });
  }

  if (!requireAuth()) return;
  renderUserLabel();
  loadSettings();
  setupScrollbarReveal();
  autoConnect();
})();
