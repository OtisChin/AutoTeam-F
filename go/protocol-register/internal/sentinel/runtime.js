"use strict";

(function (global) {
  function createStorage() {
    const values = new Map();
    return {
      get length() { return values.size; },
      clear() { values.clear(); },
      getItem(key) {
        key = String(key);
        return values.has(key) ? values.get(key) : null;
      },
      setItem(key, value) { values.set(String(key), String(value)); },
      removeItem(key) { values.delete(String(key)); },
      key(index) { return Array.from(values.keys())[Number(index)] || null; },
    };
  }

  function createElement(tagName) {
    const tag = String(tagName || "div").toLowerCase();
    const attributes = new Map();
    const element = {
      nodeType: 1,
      tagName: tag.toUpperCase(),
      nodeName: tag.toUpperCase(),
      style: {},
      dataset: {},
      children: [],
      childNodes: [],
      parentNode: null,
      textContent: "",
      innerHTML: "",
      src: "",
      appendChild(child) {
        if (child) child.parentNode = this;
        this.children.push(child);
        this.childNodes.push(child);
        return child;
      },
      removeChild(child) {
        this.children = this.children.filter((entry) => entry !== child);
        this.childNodes = this.childNodes.filter((entry) => entry !== child);
        if (child) child.parentNode = null;
        return child;
      },
      setAttribute(name, value) {
        attributes.set(String(name), String(value));
        if (String(name).toLowerCase() === "src") this.src = String(value);
      },
      getAttribute(name) {
        name = String(name);
        return attributes.has(name) ? attributes.get(name) : null;
      },
      hasAttribute(name) { return attributes.has(String(name)); },
      addEventListener() {},
      removeEventListener() {},
      dispatchEvent() { return true; },
      querySelector() { return null; },
      querySelectorAll() { return []; },
      getBoundingClientRect() {
        return { x: 0, y: 0, width: 0, height: 0, top: 0, left: 0, right: 0, bottom: 0 };
      },
      getContext() {
        if (tag !== "canvas") return null;
        return {
          fillStyle: "#000000",
          font: "10px sans-serif",
          fillRect() {},
          fillText() {},
          beginPath() {},
          closePath() {},
          stroke() {},
          measureText(text) { return { width: String(text || "").length * 6 }; },
          getImageData() { return { data: new Uint8ClampedArray(4), width: 1, height: 1 }; },
        };
      },
      toDataURL() { return "data:image/png;base64,"; },
    };
    return element;
  }

  function bytesToBase64(bytes) {
    const alphabet = "ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789+/";
    let output = "";
    for (let index = 0; index < bytes.length; index += 3) {
      const a = bytes[index] || 0;
      const b = bytes[index + 1] || 0;
      const c = bytes[index + 2] || 0;
      const value = (a << 16) | (b << 8) | c;
      output += alphabet[(value >>> 18) & 63];
      output += alphabet[(value >>> 12) & 63];
      output += index + 1 < bytes.length ? alphabet[(value >>> 6) & 63] : "=";
      output += index + 2 < bytes.length ? alphabet[value & 63] : "=";
    }
    return output;
  }

  function base64ToBytes(input) {
    const alphabet = "ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789+/";
    const clean = String(input || "").replace(/[^A-Za-z0-9+/=]/g, "");
    const output = [];
    for (let index = 0; index < clean.length; index += 4) {
      const a = alphabet.indexOf(clean[index]);
      const b = alphabet.indexOf(clean[index + 1]);
      const c = alphabet.indexOf(clean[index + 2]);
      const d = alphabet.indexOf(clean[index + 3]);
      const value = ((a & 63) << 18) | ((b & 63) << 12) | (((c < 0 ? 0 : c) & 63) << 6) | ((d < 0 ? 0 : d) & 63);
      output.push((value >>> 16) & 255);
      if (clean[index + 2] !== "=") output.push((value >>> 8) & 255);
      if (clean[index + 3] !== "=") output.push(value & 255);
    }
    return output;
  }

  class URLSearchParamsPolyfill {
    constructor(search) {
      this.pairs = [];
      const raw = String(search || "").replace(/^\?/, "");
      if (!raw) return;
      for (const part of raw.split("&")) {
        if (!part) continue;
        const separator = part.indexOf("=");
        const key = separator < 0 ? part : part.slice(0, separator);
        const value = separator < 0 ? "" : part.slice(separator + 1);
        this.pairs.push([decodeURIComponent(key), decodeURIComponent(value)]);
      }
    }
    append(key, value) { this.pairs.push([String(key), String(value)]); }
    get(key) {
      key = String(key);
      const pair = this.pairs.find((entry) => entry[0] === key);
      return pair ? pair[1] : null;
    }
    keys() { return this.pairs.map((entry) => entry[0])[Symbol.iterator](); }
    entries() { return this.pairs[Symbol.iterator](); }
    toString() {
      return this.pairs.map((entry) => `${encodeURIComponent(entry[0])}=${encodeURIComponent(entry[1])}`).join("&");
    }
    [Symbol.iterator]() { return this.entries(); }
  }

  class URLPolyfill {
    constructor(input, base) {
      const raw = String(input || "");
      if (/^[A-Za-z][A-Za-z0-9+.-]*:\/\//.test(raw)) {
        this.href = raw;
      } else {
        const root = String(base || "https://auth.openai.com/").replace(/\/$/, "");
        this.href = `${root}/${raw.replace(/^\//, "")}`;
      }
      const match = this.href.match(/^([A-Za-z][A-Za-z0-9+.-]*:)\/\/([^/]+)(\/[^?#]*)?(\?[^#]*)?(#.*)?$/);
      this.protocol = match ? match[1] : "https:";
      this.host = match ? match[2] : "auth.openai.com";
      this.hostname = this.host.replace(/:\d+$/, "");
      this.pathname = match && match[3] ? match[3] : "/";
      this.search = match && match[4] ? match[4] : "";
      this.hash = match && match[5] ? match[5] : "";
      this.origin = `${this.protocol}//${this.host}`;
      this.searchParams = new URLSearchParamsPolyfill(this.search);
    }
    toString() { return this.href; }
    toJSON() { return this.href; }
  }

  global.__installSentinelRuntime = function installSentinelRuntime(payload) {
    payload = payload && typeof payload === "object" ? payload : {};
    const width = Number(payload.screen_width || 1366);
    const height = Number(payload.screen_height || 768);
    const language = String(payload.language || "en-US");
    const languages = Array.isArray(payload.languages) && payload.languages.length ? payload.languages.map(String) : [language, "en"];
    const major = String(payload.browser_major || "144");
    const sdkURL = String(payload.sdk_url || "https://sentinel.openai.com/sentinel/sdk.js");
    const scripts = [];
    const documentElement = createElement("html");
    documentElement.clientWidth = width;
    documentElement.clientHeight = height;
    const document = {
      nodeType: 9,
      readyState: "complete",
      hidden: false,
      visibilityState: "visible",
      referrer: "https://auth.openai.com/",
      URL: "https://auth.openai.com/",
      domain: "auth.openai.com",
      characterSet: "UTF-8",
      cookie: `oai-did=${encodeURIComponent(String(payload.device_id || ""))}`,
      scripts,
      currentScript: { src: sdkURL, getAttribute(name) { return name === "src" ? sdkURL : null; } },
      documentElement,
      body: createElement("body"),
      head: createElement("head"),
      createElement(tag) {
        const element = createElement(tag);
        if (String(tag).toLowerCase() === "script") scripts.push(element);
        return element;
      },
      createElementNS(_namespace, tag) { return this.createElement(tag); },
      createTextNode(text) { return { nodeType: 3, nodeName: "#text", textContent: String(text || ""), parentNode: null }; },
      querySelector() { return null; },
      querySelectorAll() { return []; },
      getElementById() { return null; },
      getElementsByTagName(tag) { return String(tag).toLowerCase() === "script" ? scripts : []; },
      addEventListener() {},
      removeEventListener() {},
      dispatchEvent() { return true; },
      hasFocus() { return true; },
    };

    global.window = global;
    global.self = global;
    global.top = global;
    global.parent = global;
    global.document = document;
    global.location = {
      href: "https://auth.openai.com/",
      origin: "https://auth.openai.com",
      protocol: "https:",
      host: "auth.openai.com",
      hostname: "auth.openai.com",
      pathname: "/",
      search: "",
      hash: "",
      toString() { return this.href; },
    };
    global.navigator = {
      userAgent: String(payload.user_agent || "Mozilla/5.0"),
      appVersion: String(payload.user_agent || "Mozilla/5.0").replace(/^Mozilla\//, ""),
      language,
      languages,
      hardwareConcurrency: Number(payload.hardware_concurrency || 12),
      deviceMemory: Number(payload.device_memory || 8),
      platform: "Win32",
      vendor: "Google Inc.",
      product: "Gecko",
      webdriver: false,
      maxTouchPoints: 0,
      cookieEnabled: true,
      doNotTrack: null,
      plugins: [],
      mimeTypes: [],
      connection: { effectiveType: "4g", downlink: 10, rtt: 50, saveData: false },
      permissions: { query() { return Promise.resolve({ state: "prompt", onchange: null }); } },
      userAgentData: {
        brands: [
          { brand: "Not_A Brand", version: "99" },
          { brand: "Chromium", version: major },
          { brand: "Google Chrome", version: major },
        ],
        mobile: false,
        platform: "Windows",
        getHighEntropyValues() {
          return Promise.resolve({ architecture: "x86", bitness: "64", mobile: false, model: "", platform: "Windows", platformVersion: "10.0.0", uaFullVersion: `${major}.0.0.0` });
        },
      },
    };
    global.screen = {
      width,
      height,
      availWidth: width,
      availHeight: height,
      colorDepth: 24,
      pixelDepth: 24,
      orientation: { angle: 0, type: "landscape-primary" },
    };
    global.devicePixelRatio = 1;
    global.innerWidth = width;
    global.innerHeight = height;
    global.outerWidth = width;
    global.outerHeight = height;
    global.performance = {
      now() { return Number(payload.performance_now || 12345.67); },
      timeOrigin: Number(payload.time_origin || 1710000000000),
      memory: { jsHeapSizeLimit: Number(payload.js_heap_size_limit || 4294967296) },
      getEntriesByType() { return []; },
      mark() {},
      measure() {},
    };
    global.localStorage = createStorage();
    global.sessionStorage = createStorage();

    let timerCallbacks = 0;
    const runTimer = (callback, args) => {
      if (typeof callback !== "function") return;
      timerCallbacks += 1;
      if (timerCallbacks > 1024) throw new Error("timer callback limit exceeded");
      callback(...args);
    };
    global.setTimeout = (callback, _delay, ...args) => { runTimer(callback, args); return timerCallbacks; };
    global.clearTimeout = () => {};
    global.setInterval = () => 1;
    global.clearInterval = () => {};
    global.queueMicrotask = (callback) => runTimer(callback, []);
    global.requestAnimationFrame = (callback) => { runTimer(callback, [global.performance.now()]); return timerCallbacks; };
    global.cancelAnimationFrame = () => {};
    global.requestIdleCallback = (callback) => { runTimer(callback, [{ didTimeout: false, timeRemaining() { return 50; } }]); return timerCallbacks; };
    global.cancelIdleCallback = () => {};
    global.addEventListener = () => {};
    global.removeEventListener = () => {};
    global.dispatchEvent = () => true;
    global.postMessage = () => {};

    global.atob = (input) => String.fromCharCode(...base64ToBytes(input));
    global.btoa = (input) => {
      const text = String(input || "");
      const bytes = [];
      for (let index = 0; index < text.length; index += 1) bytes.push(text.charCodeAt(index) & 255);
      return bytesToBase64(bytes);
    };
    global.TextEncoder = class TextEncoder {
      encode(input) { return new Uint8Array(global.__sentinelEncodeUTF8(String(input || ""))); }
    };
    global.TextDecoder = class TextDecoder {
      decode(input) {
        if (input === undefined) return "";
        if (input instanceof ArrayBuffer) {
          return global.__sentinelDecodeUTF8(new Uint8Array(input));
        }
        if (!input || !input.buffer || typeof input.byteLength !== "number") {
          throw new TypeError("text input must be an ArrayBuffer or view");
        }
        return global.__sentinelDecodeUTF8(
          new Uint8Array(input.buffer, Number(input.byteOffset || 0), Number(input.byteLength)),
        );
      }
    };
    global.URL = global.URL || URLPolyfill;
    global.URLSearchParams = global.URLSearchParams || URLSearchParamsPolyfill;
    global.Event = global.Event || class Event { constructor(type) { this.type = String(type || ""); } };
    global.CustomEvent = global.CustomEvent || class CustomEvent extends global.Event {
      constructor(type, init) { super(type); this.detail = init && Object.prototype.hasOwnProperty.call(init, "detail") ? init.detail : null; }
    };
    global.MessageEvent = global.MessageEvent || class MessageEvent extends global.Event {
      constructor(type, init) { super(type); this.data = init ? init.data : undefined; }
    };
    global.MessageChannel = global.MessageChannel || class MessageChannel {
      constructor() {
        this.port1 = { postMessage() {}, addEventListener() {}, removeEventListener() {}, start() {}, close() {} };
        this.port2 = { postMessage() {}, addEventListener() {}, removeEventListener() {}, start() {}, close() {} };
      }
    };
    global.MutationObserver = global.MutationObserver || class MutationObserver { observe() {} disconnect() {} takeRecords() { return []; } };
    global.Image = global.Image || class Image { constructor() { return createElement("img"); } };
    global.matchMedia = () => ({ matches: false, media: "", onchange: null, addListener() {}, removeListener() {}, addEventListener() {}, removeEventListener() {}, dispatchEvent() { return false; } });
    global.getComputedStyle = () => ({ getPropertyValue() { return ""; } });
    global.history = { length: 1, state: null, back() {}, forward() {}, go() {}, pushState() {}, replaceState() {} };
    global.chrome = { runtime: {}, app: {} };
    global.CSS = { supports() { return true; } };
    global.indexedDB = { open() { return { onerror: null, onsuccess: null, onupgradeneeded: null, result: {}, error: null }; }, deleteDatabase() { return {}; } };
    global.fetch = async () => { throw new Error("network access is disabled in Sentinel VM"); };

    global.crypto = {
      getRandomValues(array) {
        if (!array || !array.buffer || typeof array.byteLength !== "number") {
          throw new TypeError("random target must be a typed array");
        }
        const bytes = new Uint8Array(array.buffer, Number(array.byteOffset || 0), Number(array.byteLength));
        global.__sentinelFillRandom(bytes);
        return array;
      },
      randomUUID() {
        const bytes = global.__sentinelFillRandom(new Uint8Array(16));
        bytes[6] = (bytes[6] & 15) | 64;
        bytes[8] = (bytes[8] & 63) | 128;
        const hex = Array.from(bytes, (value) => value.toString(16).padStart(2, "0")).join("");
        return `${hex.slice(0, 8)}-${hex.slice(8, 12)}-${hex.slice(12, 16)}-${hex.slice(16, 20)}-${hex.slice(20)}`;
      },
    };
  };
})(globalThis);

globalThis.__sentinelPayload = JSON.parse(String(globalThis.__sentinelPayloadJSON || "{}"));
globalThis.__installSentinelRuntime(globalThis.__sentinelPayload);

/*__SENTINEL_SDK_SOURCE__*/

globalThis.__sentinelRequirements = async function sentinelRequirements(payload) {
  globalThis.__installSentinelRuntime(payload);
  if (!globalThis.__debugP || typeof globalThis.__debugP.getRequirementsToken !== "function") {
    throw new Error("patched requirements export is unavailable");
  }
  return { request_p: await globalThis.__debugP.getRequirementsToken() };
};

globalThis.__sentinelSolve = async function sentinelSolve(payload) {
  globalThis.__installSentinelRuntime(payload);
  if (!globalThis.__debugP || !globalThis.SentinelSDK) {
    throw new Error("patched solve exports are unavailable");
  }
  const challenge = payload && payload.challenge ? payload.challenge : {};
  const finalP = await globalThis.__debugP.getEnforcementToken(challenge);
  globalThis.SentinelSDK.__debug_bindProof(challenge, payload.request_p);
  const dx = challenge && challenge.turnstile ? challenge.turnstile.dx : null;
  const t = dx ? await globalThis.SentinelSDK.__debug_n(challenge, dx) : "";
  return { final_p: finalP, t };
};
