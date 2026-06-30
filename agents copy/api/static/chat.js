(function () {
  const STORAGE_SESSION = "cortex_session_key";
  const STORAGE_TOKEN = "cortex_auth_token";
  const LEGACY_STORAGE_SESSION = "cortex_session_id";

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

  /** 从旧版 mem:xxx:default 还原为裸 session 键；已是裸键则原样返回。 */
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
    els.routeBadge.textContent = route;
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

  function appendThinkingBubble() {
    removeEmptyState();
    const div = document.createElement("div");
    div.className = "msg assistant thinking";
    div.setAttribute("aria-busy", "true");
    div.setAttribute("aria-label", "Agent 思考中");

    const label = document.createElement("span");
    label.className = "thinking-text";
    label.textContent = "思考中";

    const dots = document.createElement("span");
    dots.className = "thinking-dots";
    dots.setAttribute("aria-hidden", "true");
    dots.innerHTML =
      '<span class="dot"></span><span class="dot"></span><span class="dot"></span>';

    div.appendChild(label);
    div.appendChild(dots);
    els.messages.appendChild(div);
    scrollToBottom();
    return div;
  }

  function clearThinkingState(assistantEl) {
    if (!assistantEl.classList.contains("thinking")) return;
    assistantEl.classList.remove("thinking");
    assistantEl.removeAttribute("aria-busy");
    assistantEl.removeAttribute("aria-label");
    assistantEl.textContent = "";
  }

  function setThinkingLabel(assistantEl, text) {
    if (!assistantEl.classList.contains("thinking")) return;
    const label = assistantEl.querySelector(".thinking-text");
    if (label && text) label.textContent = text;
  }

  function phaseStatusText(phase) {
    const map = {
      react: "思考中…",
      plan: "规划中…",
      reflection: "审查中…",
      revision: "修订中…",
    };
    return map[phase] || "思考中…";
  }

  function appendToolBlock(title, body) {
    if (!els.showTools.checked) return;
    removeEmptyState();
    const details = document.createElement("details");
    details.className = "msg tool-block";
    details.open = false;
    const summary = document.createElement("summary");
    summary.textContent = title;
    const pre = document.createElement("pre");
    pre.textContent = body;
    details.appendChild(summary);
    details.appendChild(pre);
    els.messages.appendChild(details);
    scrollToBottom();
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

  async function chatStream(message, sessionKey, assistantEl) {
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
    let streamText = "";
    let started = false;

    while (true) {
      const { done, value } = await reader.read();
      if (done) break;
      buffer += decoder.decode(value, { stream: true });
      const parsed = parseSseChunk(buffer);
      buffer = parsed.rest;

      for (const { event, data } of parsed.events) {
        if (event === "text_delta" && data.delta) {
          if (!started) {
            clearThinkingState(assistantEl);
            assistantEl.classList.add("typing");
            started = true;
          }
          streamText += data.delta;
          assistantEl.textContent = streamText;
          scrollToBottom();
        } else if (event === "tool_call") {
          const toolName = data.tool_name || "tool";
          setThinkingLabel(assistantEl, "调用工具 · " + toolName);
          appendToolBlock(
            "调用 · " + toolName,
            JSON.stringify(data.args || {}, null, 2)
          );
        } else if (event === "tool_result") {
          const toolName = data.tool_name || "tool";
          setThinkingLabel(
            assistantEl,
            data.is_error ? "工具失败 · " + toolName : "整理回复中"
          );
          appendToolBlock(
            (data.is_error ? "失败 · " : "返回 · ") + toolName,
            data.result || ""
          );
        } else if (event === "phase") {
          const phase = (data.phase || "").trim();
          setStatus(phaseStatusText(phase));
        } else if (event === "turn_complete") {
          clearThinkingState(assistantEl);
          assistantEl.classList.remove("typing");
          const final = (data.final_message || "").trim();
          if (final) {
            assistantEl.textContent = final;
            streamText = final;
            started = true;
          }
          setRoute(data.route || "");
        } else if (event === "error") {
          throw new Error(data.error || "未知错误");
        }
      }
    }

    assistantEl.classList.remove("typing");
    if (assistantEl.classList.contains("thinking")) {
      clearThinkingState(assistantEl);
    }
    if (!streamText.trim() && !assistantEl.textContent.trim()) {
      assistantEl.textContent = "（无文本回复）";
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

    const data = await res.json();
    setRoute(data.route || "");
    return (data.final_message || data.user_reply || "").trim() || "（空）";
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
    setStatus("思考中…");
    setRoute("");

    appendMessage("user", message);
    els.input.value = "";

    const assistantEl = appendThinkingBubble();
    await waitForPaint();

    try {
      if (els.streamMode.checked) {
        await chatStream(message, sessionKey, assistantEl);
      } else {
        const text = await chatOnce(message, sessionKey);
        clearThinkingState(assistantEl);
        assistantEl.textContent = text;
      }
      setStatus("就绪");
    } catch (err) {
      assistantEl.classList.remove("typing", "thinking");
      assistantEl.remove();
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
