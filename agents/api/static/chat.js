(function () {
  const STORAGE_SESSION = "cortex_session_key";
  const STORAGE_TOKEN = "cortex_auth_token";
  const LEGACY_STORAGE_SESSION = "cortex_session_id";

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
    authToken: document.getElementById("auth-token"),
    newSession: document.getElementById("new-session"),
    streamMode: document.getElementById("stream-mode"),
    showTools: document.getElementById("show-tools"),
    status: document.getElementById("status"),
    routeBadge: document.getElementById("route-badge"),
  };

  let busy = false;

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
    const tok = localStorage.getItem(STORAGE_TOKEN);
    if (tok) els.authToken.value = tok;
  }

  function saveSettings() {
    localStorage.setItem(
      STORAGE_SESSION,
      normalizeSessionKey(els.sessionId.value)
    );
    localStorage.removeItem(LEGACY_STORAGE_SESSION);
    localStorage.setItem(STORAGE_TOKEN, els.authToken.value.trim());
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

  function ensureEmptyState() {
    if (els.messages.children.length === 0) {
      const empty = document.createElement("div");
      empty.className = "empty-state";
      empty.id = "empty-state";
      empty.innerHTML =
        '<p class="empty-title">开始对话</p>' +
        '<p class="empty-desc">用自然语言与已接入的 REST API 交互。Agent Cortex 会理解意图、' +
        "按需调用 MCP 工具，并支持多轮澄清与流式回复。</p>" +
        '<p class="empty-hint">例如：「你能帮我做什么？」「查询某条记录」' +
        "「帮我完成一个需要填参数的操作」</p>";
      els.messages.appendChild(empty);
    }
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
        const text = (msg.content || "").trim();
        if (!text) continue;
        appendMessage(msg.role === "user" ? "user" : "assistant", text);
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
    div.textContent = text;
    els.messages.appendChild(div);
    scrollToBottom();
    return div;
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
      const details = document.createElement("details");
      details.className = "tool-inline";
      details.open = false;
      const summary = document.createElement("summary");
      summary.textContent = title;
      const pre = document.createElement("pre");
      pre.textContent = body;
      details.appendChild(summary);
      details.appendChild(pre);
      toolHost.appendChild(details);
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
        answerEl.textContent = text;
        answerText = text;
      } else if (!answerText.trim()) {
        answerEl.classList.remove("hidden");
        answerEl.textContent = "（无文本回复）";
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

  function buildHeaders(sessionKey) {
    const headers = { "Content-Type": "application/json" };
    const token = els.authToken.value.trim();
    if (token) headers["Authorization"] = "Bearer " + token;
    if (sessionKey) headers["X-Session-Id"] = sessionKey;
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
          const toolName = data.tool_name || "tool";
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
    if (busy) return;

    const message = els.input.value.trim();
    if (!message) return;

    saveSettings();
    const sessionKey = normalizeSessionKey(els.sessionId.value);

    busy = true;
    els.sendBtn.disabled = true;
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
      els.sendBtn.disabled = false;
      els.input.focus();
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
  els.authToken.addEventListener("change", saveSettings);

  loadSettings();
  if (!els.sessionId.value.trim()) {
    els.sessionId.value = newSessionKey();
    saveSettings();
  }
  loadHistory();
  els.input.focus();
})();
