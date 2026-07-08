(function () {
  const STORAGE_SESSION = "cortex_session_key";
  const LEGACY_STORAGE_SESSION = "cortex_session_id";
  const LEGACY_STORAGE_TOKEN = "cortex_auth_token";
  const LEGACY_STORAGE_CONNECTION = "cortex_connection_meta";

  const CONFIG_KEYS = {
    openaiApiKey: "cortex_openai_api_key",
    openaiModel: "cortex_openai_model",
    openaiBaseUrl: "cortex_openai_base_url",
    mcpSwaggerUrl: "cortex_mcp_swagger_url",
    mcpBaseUrl: "cortex_mcp_base_url",
    mcpAuthScheme: "cortex_mcp_auth_scheme",
    mcpToken: "cortex_mcp_token",
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
    sessionId: document.getElementById("session-id"),
    newSession: document.getElementById("new-session"),
    streamMode: document.getElementById("stream-mode"),
    showTools: document.getElementById("show-tools"),
    status: document.getElementById("status"),
    routeBadge: document.getElementById("route-badge"),
    connectWarning: document.getElementById("connect-warning"),
    connectBtn: document.getElementById("connect-btn"),
    configStatus: document.getElementById("config-status"),
    connectDetail: document.getElementById("connect-detail"),
    openaiApiKey: document.getElementById("openai-api-key"),
    openaiModel: document.getElementById("openai-model"),
    openaiBaseUrl: document.getElementById("openai-base-url"),
    mcpSwaggerUrl: document.getElementById("mcp-swagger-url"),
    mcpBaseUrl: document.getElementById("mcp-base-url"),
    mcpAuthScheme: document.getElementById("mcp-auth-scheme"),
    mcpToken: document.getElementById("mcp-token"),
  };

  let busy = false;
  let swaggerConnected = false;
  let connectState = "idle";

  const CHAT_PLACEHOLDER_CONNECTED = "输入消息，Enter 发送，Shift+Enter 换行";
  const CHAT_PLACEHOLDER_DISCONNECTED = "请先连接 Swagger 后再开始对话";

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

  function uuid() {
    if (crypto.randomUUID) return crypto.randomUUID();
    return "sess-" + Date.now().toString(36);
  }

  function normalizeSessionKey(value) {
    const trimmed = (value || "").trim();
    if (!trimmed) return "";
    if (trimmed.startsWith("mem:") && trimmed.endsWith(":default")) {
      return trimmed.slice(4, -":default".length);
    }
    return trimmed;
  }

  function newSessionKey() {
    return "web-" + uuid();
  }

  function loadSettings() {
    let sid =
      localStorage.getItem(STORAGE_SESSION) ||
      localStorage.getItem(LEGACY_STORAGE_SESSION);
    if (sid) els.sessionId.value = normalizeSessionKey(sid);

    const legacyToken = localStorage.getItem(LEGACY_STORAGE_TOKEN);
    const fields = {
      openaiApiKey: els.openaiApiKey,
      openaiModel: els.openaiModel,
      openaiBaseUrl: els.openaiBaseUrl,
      mcpSwaggerUrl: els.mcpSwaggerUrl,
      mcpBaseUrl: els.mcpBaseUrl,
      mcpAuthScheme: els.mcpAuthScheme,
      mcpToken: els.mcpToken,
    };
    for (const [key, el] of Object.entries(fields)) {
      if (!el) continue;
      let value = localStorage.getItem(CONFIG_KEYS[key]);
      if (!value && key === "mcpToken" && legacyToken) value = legacyToken;
      if (value) el.value = value;
    }
    if (!els.mcpAuthScheme.value.trim()) {
      els.mcpAuthScheme.value = "Bearer";
    }
    localStorage.removeItem(LEGACY_STORAGE_CONNECTION);
    setConnectStatus("idle", "未连接", "");
  }

  function formatConnectDetail(data) {
    const parts = [];
    if (data.group_count != null && data.tool_count != null) {
      parts.push(data.group_count + " 个分组 · " + data.tool_count + " 个接口");
    }
    if (data.base_url) parts.push("API " + data.base_url);
    if (data.swagger_url) parts.push(data.swagger_url);
    return parts.join("\n");
  }

  function markConfigStale() {
    setConnectStatus("idle", "未连接", "配置已变更，请重新连接");
  }

  function saveSettings() {
    localStorage.setItem(
      STORAGE_SESSION,
      normalizeSessionKey(els.sessionId.value)
    );
    localStorage.removeItem(LEGACY_STORAGE_SESSION);

    const fields = {
      openaiApiKey: els.openaiApiKey,
      openaiModel: els.openaiModel,
      openaiBaseUrl: els.openaiBaseUrl,
      mcpSwaggerUrl: els.mcpSwaggerUrl,
      mcpBaseUrl: els.mcpBaseUrl,
      mcpAuthScheme: els.mcpAuthScheme,
      mcpToken: els.mcpToken,
    };
    for (const [key, el] of Object.entries(fields)) {
      if (!el) continue;
      localStorage.setItem(CONFIG_KEYS[key], el.value.trim());
    }
  }

  function configPayload() {
    return {
      openai_model: els.openaiModel && els.openaiModel.value.trim(),
      openai_base_url: els.openaiBaseUrl && els.openaiBaseUrl.value.trim(),
      mcp_swagger_url: els.mcpSwaggerUrl && els.mcpSwaggerUrl.value.trim(),
      mcp_base_url: els.mcpBaseUrl && els.mcpBaseUrl.value.trim(),
      mcp_auth_scheme: els.mcpAuthScheme && els.mcpAuthScheme.value.trim(),
    };
  }

  async function applyConfig() {
    const res = await fetch("/v1/config/apply", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(configPayload()),
    });

    if (!res.ok) {
      let message = "HTTP " + res.status;
      try {
        const data = await res.json();
        message = data.detail || message;
      } catch (_) {
        message = (await res.text()) || message;
      }
      throw new Error(message);
    }

    return await res.json();
  }

  function setPill(pillEl, state, text) {
    if (!pillEl) return;
    pillEl.setAttribute("data-state", state);
    pillEl.querySelector(".pill-text").textContent = text;
  }

  function setConnectDetail(text) {
    if (!els.connectDetail) return;
    const value = (text || "").trim();
    if (!value) {
      els.connectDetail.textContent = "";
      els.connectDetail.classList.add("hidden");
      return;
    }
    els.connectDetail.textContent = value;
    els.connectDetail.classList.remove("hidden");
  }

  function connectWarningText() {
    if (connectState === "loading") return "正在连接 Swagger…";
    if (connectState === "error") return "Swagger 连接失败，请重新连接";
    return "未连接 Swagger，请先在左侧完成连接";
  }

  function setConnectStatus(state, pillText, detail) {
    setPill(els.configStatus, state, pillText);
    setConnectDetail(detail);
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
    if (els.connectWarning) {
      if (swaggerConnected) {
        els.connectWarning.classList.add("hidden");
      } else {
        els.connectWarning.textContent = connectWarningText();
        els.connectWarning.setAttribute("data-state", connectState);
        els.connectWarning.classList.remove("hidden");
      }
    }
    refreshEmptyState();
  }

  function setConnectButtonBusy(connecting) {
    if (!els.connectBtn) return;
    els.connectBtn.disabled = connecting;
    els.connectBtn.textContent = connecting ? "连接中…" : "连接 Swagger";
  }

  async function onConnect() {
    saveSettings();
    setConnectButtonBusy(true);
    setConnectStatus("loading", "连接中…", "正在加载 Swagger 并重建 MCP…");
    setStatus("正在连接 Swagger…");

    try {
      const data = await applyConfig();
      const meta = {
        swagger_url: data.swagger_url || "",
        base_url: data.base_url || "",
        group_count: data.group_count,
        tool_count: data.tool_count,
      };
      setConnectStatus("ok", "已连接", formatConnectDetail(meta));
      setStatus("Swagger 已连接，可以开始对话");
    } catch (err) {
      const message = String(err.message || err);
      setConnectStatus("error", "连接失败", message);
      setStatus(message);
    } finally {
      setConnectButtonBusy(false);
    }
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
        '<p class="empty-desc">用自然语言查询、操作已接入的 API。</p>' +
        '<p class="empty-hint">例如：「你能帮我做什么？」「查询某条记录」' +
        "「帮我完成一个需要填参数的操作」</p>"
      );
    }
    return (
      '<p class="empty-title">请先连接 Swagger</p>' +
      '<p class="empty-desc">在左侧填写模型与 API 接入配置，点击「连接 Swagger」后即可开始对话。</p>'
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
    const sessionKey = normalizeSessionKey(els.sessionId.value);
    if (!sessionKey) {
      clearMessages();
      ensureEmptyState();
      return;
    }

    clearMessages();
    setStatus("加载历史…");

    try {
      const url =
        "/v1/chat/history?session_id=" + encodeURIComponent(sessionKey);
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

  function buildToolInline(title, body) {
    const details = document.createElement("details");
    details.className = "tool-inline";
    details.open = false;
    const summary = document.createElement("summary");
    summary.textContent = title;
    const pre = document.createElement("pre");
    pre.textContent = body;
    details.appendChild(summary);
    details.appendChild(pre);
    return details;
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
        toolHost.appendChild(buildToolInline(title, item.body || ""));
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

    function appendToolBlock(title, body) {
      if (!els.showTools.checked) return;
      showThoughtPanel();
      if (currentState !== "replying") setAgentState("thinking");
      toolHost.appendChild(buildToolInline(title, body));
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
      beginReply,
      appendAnswerDelta,
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

    const swaggerUrl = els.mcpSwaggerUrl && els.mcpSwaggerUrl.value.trim();
    if (swaggerUrl) headers["X-MCP-Swagger-Url"] = swaggerUrl;
    const mcpBaseUrl = els.mcpBaseUrl && els.mcpBaseUrl.value.trim();
    if (mcpBaseUrl) headers["X-MCP-Base-Url"] = mcpBaseUrl;

    const token = els.mcpToken && els.mcpToken.value.trim();
    const scheme =
      (els.mcpAuthScheme && els.mcpAuthScheme.value.trim()) || "Bearer";
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
    const res = await fetch("/v1/chat", {
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
          turn.appendToolBlock(
            "调用 · " + toolName,
            JSON.stringify(data.args || {}, null, 2)
          );
        } else if (event === "tool_result") {
          const toolName = data.tool_name || "tool";
          turn.appendToolBlock(
            (data.is_error ? "失败 · " : "返回 · ") + toolName,
            data.result || ""
          );
        } else if (event === "turn_complete") {
          turn.finalize(data.final_message || "", data.route || "");
        } else if (event === "error") {
          throw new Error(data.error || "未知错误");
        }
      }
    }
  }

  async function chatOnce(message, sessionKey) {
    const res = await fetch("/v1/chat", {
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
    const sessionKey = normalizeSessionKey(els.sessionId.value);

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

  els.newSession.addEventListener("click", () => {
    els.sessionId.value = newSessionKey();
    saveSettings();
    clearMessages();
    ensureEmptyState();
    setRoute("");
    setStatus("已创建新会话");
  });

  els.sessionId.addEventListener("change", () => {
    saveSettings();
    loadHistory();
  });
  if (els.connectBtn) {
    els.connectBtn.addEventListener("click", onConnect);
  }

  [
    els.openaiApiKey,
    els.openaiModel,
    els.openaiBaseUrl,
    els.mcpSwaggerUrl,
    els.mcpBaseUrl,
    els.mcpAuthScheme,
    els.mcpToken,
  ].forEach(function (el) {
    if (!el) return;
    el.addEventListener("change", function () {
      saveSettings();
      if (
        el === els.mcpSwaggerUrl ||
        el === els.mcpBaseUrl ||
        el === els.mcpAuthScheme
      ) {
        markConfigStale();
      }
    });
  });

  loadSettings();
  if (!els.sessionId.value.trim()) {
    els.sessionId.value = newSessionKey();
    saveSettings();
  }
  setupScrollbarReveal();
  loadHistory();
  updateChatInputState();
  if (swaggerConnected) els.input.focus();
})();
