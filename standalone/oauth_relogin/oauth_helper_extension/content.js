(function () {
  const CONFIG_KEY = "oauth_relogin_config";
  let lastAction = "";
  let lastActionAt = 0;

  function parseFragment() {
    const raw = window.location.hash || "";
    if (!raw.includes("oauth_relogin_token=")) return null;
    const params = new URLSearchParams(raw.slice(1));
    const token = params.get("oauth_relogin_token") || "";
    const port = params.get("oauth_relogin_port") || "";
    const authUrl = params.get("oauth_relogin_auth") || "";
    if (!token || !port) return null;
    const config = { token, port, authUrl };
    try {
      window.localStorage.setItem(CONFIG_KEY, JSON.stringify(config));
    } catch (e) {}
    if (authUrl) {
      setTimeout(() => window.location.replace(authUrl), 200);
    }
    return config;
  }

  function loadConfig() {
    const parsed = parseFragment();
    if (parsed) return parsed;
    try {
      const raw = window.localStorage.getItem(CONFIG_KEY) || "";
      return raw ? JSON.parse(raw) : null;
    } catch (e) {
      return null;
    }
  }

  function endpoint(config, path) {
    return `http://127.0.0.1:${config.port}${path}?token=${encodeURIComponent(config.token)}`;
  }

  async function fetchState(config) {
    const response = await fetch(endpoint(config, "/state"), { cache: "no-store" });
    return response.json();
  }

  async function postEvent(config, payload) {
    try {
      await fetch(endpoint(config, "/event"), {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          url: window.location.href,
          title: document.title || "",
          body: ((document.body && document.body.innerText) || "").slice(0, 1500),
          ...payload
        })
      });
    } catch (e) {}
  }

  function visible(el) {
    if (!el) return false;
    const style = window.getComputedStyle(el);
    const rect = el.getBoundingClientRect();
    return style.visibility !== "hidden" && style.display !== "none" && rect.width > 0 && rect.height > 0;
  }

  function queryFirst(selectors) {
    for (const selector of selectors) {
      for (const el of Array.from(document.querySelectorAll(selector))) {
        if (visible(el)) return el;
      }
    }
    return null;
  }

  function setNativeValue(el, value) {
    const proto = el instanceof HTMLTextAreaElement ? HTMLTextAreaElement.prototype : HTMLInputElement.prototype;
    const descriptor = Object.getOwnPropertyDescriptor(proto, "value");
    el.focus();
    if (descriptor && descriptor.set) descriptor.set.call(el, value);
    else el.value = value;
    el.dispatchEvent(new InputEvent("input", { bubbles: true, inputType: "insertText", data: value }));
    el.dispatchEvent(new Event("change", { bubbles: true }));
  }

  function clickButtonNear(field, labels) {
    const labelSet = labels.map((label) => String(label).trim().toLowerCase());
    const form = field && field.closest("form");
    const scopes = [form, document].filter(Boolean);
    for (const scope of scopes) {
      const targets = Array.from(scope.querySelectorAll("button, input[type='submit'], a, [role='button']"));
      for (const el of targets) {
        if (!visible(el) || el.disabled || el.getAttribute("aria-disabled") === "true") continue;
        const text = String(el.innerText || el.value || el.getAttribute("aria-label") || "").replace(/\s+/g, " ").trim().toLowerCase();
        if (!text) continue;
        if (labelSet.some((label) => text === label || text.includes(label))) {
          el.click();
          return text;
        }
      }
    }
    return "";
  }

  function clickAny(labels) {
    const labelSet = labels.map((label) => String(label).trim().toLowerCase());
    for (const el of Array.from(document.querySelectorAll("button, input[type='submit'], a, [role='button']"))) {
      if (!visible(el) || el.disabled || el.getAttribute("aria-disabled") === "true") continue;
      const text = String(el.innerText || el.value || el.getAttribute("aria-label") || "").replace(/\s+/g, " ").trim().toLowerCase();
      if (!text) continue;
      if (labelSet.some((label) => text === label || text.includes(label))) {
        el.click();
        return text;
      }
    }
    return "";
  }

  function throttle(action) {
    const now = Date.now();
    if (lastAction === action && now - lastActionAt < 2500) return false;
    lastAction = action;
    lastActionAt = now;
    return true;
  }

  function fillCode(code) {
    code = String(code || "").trim();
    if (!code) return false;
    const selectors = [
      "input[name='code']",
      "input[autocomplete='one-time-code']",
      "input[inputmode='numeric']",
      "input[placeholder*='code' i]",
      "input[placeholder*='验证码']"
    ];
    const inputs = [];
    for (const selector of selectors) {
      for (const el of Array.from(document.querySelectorAll(selector))) {
        if (visible(el) && !el.disabled && !el.readOnly && !inputs.includes(el)) inputs.push(el);
      }
    }
    if (!inputs.length) return false;
    const oneChar = inputs.filter((el) => Number(el.maxLength || 0) === 1 || el.getAttribute("aria-label"));
    if (oneChar.length >= code.length && code.length > 1) {
      for (let i = 0; i < code.length; i++) setNativeValue(oneChar[i], code[i]);
      return oneChar.slice(0, code.length).every((el) => String(el.value || "").trim());
    }
    setNativeValue(inputs[0], code);
    return String(inputs[0].value || "").trim().length > 0;
  }

  function hasVisibleCodeInput() {
    return Boolean(queryFirst([
      "input[name='code']",
      "input[autocomplete='one-time-code']",
      "input[inputmode='numeric']",
      "input[placeholder*='code' i]",
      "input[placeholder*='验证码']"
    ]));
  }

  function fillPhone(phone) {
    phone = String(phone || "").trim();
    if (!phone) return false;
    const phoneInput = queryFirst([
      "input[name='phone']",
      "input[name='phone_number']",
      "input[name='phoneNumber']",
      "input[type='tel']",
      "input[autocomplete='tel']",
      "input[id*='phone' i]",
      "input[placeholder*='phone' i]",
      "input[placeholder*='手机号']",
      "input[placeholder*='手机号码']",
      "input[aria-label*='phone' i]",
      "input[aria-label*='手机号']"
    ]);
    if (!phoneInput || phoneInput.disabled || phoneInput.readOnly) return false;
    setNativeValue(phoneInput, phone);
    return String(phoneInput.value || "").replace(/\D+/g, "").length > 3;
  }

  function codeInputFilled() {
    const selectors = [
      "input[name='code']",
      "input[autocomplete='one-time-code']",
      "input[inputmode='numeric']",
      "input[placeholder*='code' i]",
      "input[placeholder*='验证码']"
    ];
    return selectors.some((selector) =>
      Array.from(document.querySelectorAll(selector)).some((el) => visible(el) && !el.disabled && String(el.value || "").trim())
    );
  }

  async function tick() {
    const config = loadConfig();
    if (!config) return;

    if (window.location.href.includes("/auth/callback")) {
      await postEvent(config, { type: "callback" });
      return;
    }

    const body = ((document.body && document.body.innerText) || "").toLowerCase();
    let state = null;
    try {
      state = await fetchState(config);
    } catch (e) {
      return;
    }
    if (!state || !state.email) return;

    if (window.location.href.includes("/add-phone") || body.includes("add phone") || body.includes("phone verification") || body.includes("手机号")) {
      await postEvent(config, { type: "phone_required" });
      if (state.phone && throttle(`phone_${state.phone}`) && fillPhone(state.phone)) {
        await postEvent(config, { type: "phone_filled" });
        setTimeout(() => clickAny(["continue", "继续", "send code", "发送验证码", "verify", "验证"]), 300);
      }
      return;
    }

    const emailInput = queryFirst([
      "input[name='email']",
      "input[name='username']",
      "input[id*='email' i]",
      "input[type='email']",
      "input[placeholder*='email' i]",
      "input[placeholder*='邮箱']",
      "input[aria-label*='email' i]",
      "input[autocomplete='email']",
      "input[autocomplete='username']"
    ]);
    if (emailInput && !emailInput.disabled && !emailInput.readOnly && throttle("email")) {
      setNativeValue(emailInput, state.email);
      await postEvent(config, { type: "email_filled" });
      setTimeout(() => clickButtonNear(emailInput, ["continue", "继续", "log in", "登录"]), 300);
      return;
    }

    const passwordInput = queryFirst(["input[name='password']", "input[type='password']"]);
    if (passwordInput && throttle("switch_otp")) {
      const clicked = clickAny([
        "一次性验证码", "邮箱验证码", "验证码登录", "验证码登陆", "使用验证码登录", "使用验证码登陆",
        "email login", "email code", "continue with email code", "login with code", "sign in with code", "one-time", "otp"
      ]);
      if (clicked) {
        await postEvent(config, { type: "otp_login_clicked", clicked });
        return;
      }
    }

    if (passwordInput && !passwordInput.disabled && !passwordInput.readOnly && state.password && throttle("password")) {
      setNativeValue(passwordInput, state.password);
      await postEvent(config, { type: "password_filled" });
      setTimeout(() => clickButtonNear(passwordInput, ["continue", "继续", "log in", "登录"]), 300);
      return;
    }

    if (state.otp && throttle(`otp_${state.otp}`) && fillCode(String(state.otp))) {
      await postEvent(config, { type: "otp_filled" });
      setTimeout(() => {
        if (codeInputFilled()) clickAny(["continue", "继续", "verify", "验证"]);
      }, 300);
      return;
    }

    if (hasVisibleCodeInput() && !codeInputFilled()) {
      if (throttle("otp_empty_wait")) await postEvent(config, { type: "otp_empty_wait" });
      return;
    }

    if (throttle("continue")) {
      const clicked = clickAny(["continue", "继续", "allow", "authorize", "授权", "confirm", "确认"]);
      if (clicked) await postEvent(config, { type: "continue_clicked", clicked });
    }
  }

  setInterval(tick, 1000);
  tick();
})();
