(function () {
  const STORAGE = {
    token: "transport_demo_token",
    user: "transport_demo_user",
    swaggerUrl: "transport_mcp_swagger_url",
    baseUrl: "transport_mcp_base_url",
    authScheme: "transport_mcp_auth_scheme",
  };

  const form = document.getElementById("login-form");
  const errorEl = document.getElementById("error");
  const submitBtn = document.getElementById("submit-btn");

  function setError(message) {
    errorEl.textContent = message || "";
  }

  function saveSession(data) {
    const origin = window.location.origin;
    sessionStorage.setItem(STORAGE.token, data.token);
    sessionStorage.setItem(STORAGE.user, JSON.stringify(data.user || {}));
    sessionStorage.setItem(STORAGE.swaggerUrl, origin + "/openapi.json");
    sessionStorage.setItem(STORAGE.baseUrl, origin);
    sessionStorage.setItem(STORAGE.authScheme, "Bearer");
  }

  form.addEventListener("submit", async function (event) {
    event.preventDefault();
    setError("");
    submitBtn.disabled = true;
    submitBtn.textContent = "登录中…";

    const username = document.getElementById("username").value.trim();
    const password = document.getElementById("password").value;

    try {
      const response = await fetch("/auth/login", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ username, password }),
      });

      if (!response.ok) {
        let message = "登录失败，请检查账号或密码";
        try {
          const payload = await response.json();
          if (payload.detail) {
            message =
              typeof payload.detail === "string"
                ? payload.detail
                : JSON.stringify(payload.detail);
          }
        } catch (_) {
          message = (await response.text()) || message;
        }
        throw new Error(message);
      }

      const data = await response.json();
      saveSession(data);
      window.location.href = "/chat";
    } catch (err) {
      setError(err.message || "无法连接交通服务");
      submitBtn.disabled = false;
      submitBtn.textContent = "登录";
    }
  });
})();
