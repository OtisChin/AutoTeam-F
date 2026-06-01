import {createServer} from "node:http";
import {spawn} from "node:child_process";
import {existsSync} from "node:fs";
import {mkdir, readFile, readdir, rename, stat, writeFile} from "node:fs/promises";
import path from "node:path";
import {fileURLToPath} from "node:url";
import crypto from "node:crypto";

const __filename = fileURLToPath(import.meta.url);
const WEB_DIR = path.dirname(__filename);
const ROOT = path.resolve(WEB_DIR, "..");
const PUBLIC_DIR = path.join(WEB_DIR, "public");
const DATA_DIR = path.join(WEB_DIR, "data");
const IMPORT_DIR = path.join(DATA_DIR, "imports");
const TASK_LOG_DIR = path.join(DATA_DIR, "task-logs");
const AUTOTEAM_ROOT = process.env.AUTOTEAM_F_ROOT || "D:\\code\\OpenSource\\AutoTeam-F";
const PORT = Number(process.env.CNGOPAY_WEB_PORT || 8765);
const HOST = process.env.CNGOPAY_WEB_HOST || "127.0.0.1";

const tasks = new Map();

const paths = {
  config: path.join(ROOT, "config.json"),
  state: path.join(ROOT, "runs", "pool", "state.json"),
  numbers: path.join(ROOT, "pool_numbers.txt"),
  tokens: path.join(ROOT, "pool_tokens.txt"),
};

const allowedSlotStates = new Set([
  "EMPTY",
  "GOPAY_REGISTERING",
  "WALLET_WAITING",
  "WALLET_READY",
  "PLUS_PAYING",
  "NO_TRIAL",
  "PLUS_DONE",
  "REBINDING",
  "RELEASED",
  "FAILED",
]);

async function ensureDirs() {
  await mkdir(IMPORT_DIR, {recursive: true});
  await mkdir(TASK_LOG_DIR, {recursive: true});
}

function jsonResponse(res, status, body) {
  const payload = JSON.stringify(body);
  res.writeHead(status, {
    "Content-Type": "application/json; charset=utf-8",
    "Content-Length": Buffer.byteLength(payload),
    "Cache-Control": "no-store",
  });
  res.end(payload);
}

function textResponse(res, status, body, contentType = "text/plain; charset=utf-8") {
  res.writeHead(status, {
    "Content-Type": contentType,
    "Content-Length": Buffer.byteLength(body),
  });
  res.end(body);
}

async function readJsonFile(file, fallback) {
  try {
    return JSON.parse(await readFile(file, "utf8"));
  } catch {
    return fallback;
  }
}

async function readLines(file) {
  try {
    return (await readFile(file, "utf8")).split(/\r?\n/);
  } catch {
    return [];
  }
}

function activeLines(lines) {
  return lines.map((line) => line.trim()).filter((line) => line && !line.startsWith("#"));
}

function maskPhone(value) {
  const text = String(value || "");
  if (text.length <= 7) return text;
  return `${text.slice(0, 5)}****${text.slice(-3)}`;
}

function maskToken(value) {
  const text = String(value || "");
  if (text.length <= 16) return text;
  return `${text.slice(0, 10)}...${text.slice(-6)}`;
}

function safeSlug(value, fallback = "auth") {
  const slug = String(value || "")
    .trim()
    .toLowerCase()
    .replace(/[^a-z0-9@._-]+/g, "-")
    .replace(/^-+|-+$/g, "");
  return slug || fallback;
}

function decodeJwtPayload(token) {
  const parts = String(token || "").split(".");
  if (parts.length < 2) return {};
  try {
    const padded = parts[1].replace(/-/g, "+").replace(/_/g, "/") + "=".repeat((4 - (parts[1].length % 4)) % 4);
    return JSON.parse(Buffer.from(padded, "base64").toString("utf8"));
  } catch {
    return {};
  }
}

function extractAuthItems(value, filename = "pasted.json") {
  const out = [];
  const visit = (node, name) => {
    if (!node) return;
    if (Array.isArray(node)) {
      node.forEach((item, index) => visit(item, `${name}#${index + 1}`));
      return;
    }
    if (typeof node !== "object") return;
    if (node.auth_data && typeof node.auth_data === "object") {
      visit(node.auth_data, node.filename || node.name || name);
      return;
    }
    if (node.codex_auth && typeof node.codex_auth === "object") {
      visit(node.codex_auth, node.filename || node.name || name);
      return;
    }
    if (Array.isArray(node.auths)) {
      node.auths.forEach((item, index) => {
        const itemName = item?.filename || item?.name || `${name}#auth${index + 1}`;
        visit(item?.data || item, itemName);
      });
      return;
    }
    if (node.access_token || node.accessToken || node.refresh_token || node.refreshToken) {
      out.push({name, data: node});
    }
  };
  visit(value, filename);
  return out;
}

function summarizeAuth(name, data) {
  const accessToken = String(data.access_token || data.accessToken || "");
  const refreshToken = String(data.refresh_token || data.refreshToken || "");
  const idToken = String(data.id_token || data.idToken || "");
  const accessClaims = decodeJwtPayload(accessToken);
  const idClaims = decodeJwtPayload(idToken);
  const accessAuth = accessClaims["https://api.openai.com/auth"] || {};
  const idAuth = idClaims["https://api.openai.com/auth"] || {};
  const accessProfile = accessClaims["https://api.openai.com/profile"] || {};
  const idProfile = idClaims["https://api.openai.com/profile"] || {};
  const email = String(data.email || accessProfile.email || idProfile.email || accessClaims.email || idClaims.email || "").toLowerCase();
  const plan = String(data.plan_type || data.chatgpt_plan_type || accessAuth.chatgpt_plan_type || idAuth.chatgpt_plan_type || "").toLowerCase() || "unknown";
  const accountId = String(data.account_id || data.accountId || data.account?.id || accessAuth.chatgpt_account_id || idAuth.chatgpt_account_id || "");
  return {
    id: crypto.randomUUID(),
    filename: name.endsWith(".json") ? path.basename(name) : `${safeSlug(email || name)}.json`,
    email,
    plan,
    accountId,
    accessToken,
    refreshToken,
    idToken,
    tokenPreview: maskToken(accessToken),
    importedAt: Date.now(),
    validForHarvest: Boolean(accessToken),
    validForHub: Boolean(accessToken && refreshToken && idToken && email && accountId),
    data,
  };
}

async function writeJsonAtomic(file, value) {
  const tmp = `${file}.${process.pid}.${Date.now()}.tmp`;
  await mkdir(path.dirname(file), {recursive: true});
  await writeFile(tmp, JSON.stringify(value, null, 2), "utf8");
  await rename(tmp, file);
}

async function listImportedAuths() {
  await ensureDirs();
  const entries = await readdir(IMPORT_DIR, {withFileTypes: true}).catch(() => []);
  const items = [];
  for (const entry of entries) {
    if (!entry.isFile() || !entry.name.endsWith(".json")) continue;
    const file = path.join(IMPORT_DIR, entry.name);
    try {
      const raw = JSON.parse(await readFile(file, "utf8"));
      const {data, accessToken, refreshToken, idToken, ...safe} = raw;
      items.push({...safe, file: entry.name});
    } catch {
      // Ignore broken cache files; imports can be repeated.
    }
  }
  items.sort((a, b) => Number(b.importedAt || 0) - Number(a.importedAt || 0));
  return items;
}

async function loadImportedAuth(id) {
  const file = path.join(IMPORT_DIR, `${id}.json`);
  const raw = JSON.parse(await readFile(file, "utf8"));
  return raw;
}

async function appendUniqueLines(file, incomingLines) {
  const existingLines = await readLines(file);
  const existing = new Set(activeLines(existingLines));
  const additions = [];
  const duplicates = [];
  for (const raw of incomingLines) {
    const line = String(raw || "").trim();
    if (!line || line.startsWith("#")) continue;
    if (existing.has(line)) {
      duplicates.push(line);
      continue;
    }
    existing.add(line);
    additions.push(line);
  }
  if (additions.length) {
    const current = existingLines.join("\n").replace(/\s*$/, "");
    const next = `${current}${current ? "\n" : ""}${additions.join("\n")}\n`;
    await writeFile(file, next, "utf8");
  }
  return {added: additions.length, duplicates: duplicates.length};
}

async function getStatus() {
  const [config, state, numberLines, tokenLines, imports] = await Promise.all([
    readJsonFile(paths.config, {}),
    readJsonFile(paths.state, {slots: {}}),
    readLines(paths.numbers),
    readLines(paths.tokens),
    listImportedAuths(),
  ]);
  const slots = Object.values(state.slots || {}).map((slot) => ({
    ...slot,
    displayPhone: maskPhone(slot.full_phone || slot.phone || ""),
  }));
  const stateCounts = slots.reduce((acc, slot) => {
    const key = String(slot.state || "UNKNOWN");
    acc[key] = (acc[key] || 0) + 1;
    return acc;
  }, {});
  return {
    root: ROOT,
    autoteamRoot: AUTOTEAM_ROOT,
    config: {
      slots: config?.pool?.slots || 0,
      concurrency: config?.pool?.concurrency || 0,
      gptMode: config?.pool?.gpt_mode || "",
      numberPoolFile: config?.pool?.number_pool_file || "pool_numbers.txt",
      tokenFile: config?.pool?.provided_tokens_file || "pool_tokens.txt",
    },
    counts: {
      numbers: activeLines(numberLines).length,
      tokens: activeLines(tokenLines).length,
      imported: imports.length,
      plusImports: imports.filter((item) => item.plan === "plus").length,
      hubReadyImports: imports.filter((item) => item.validForHub).length,
    },
    slots,
    stateCounts,
    imports,
    tasks: Array.from(tasks.values()).sort((a, b) => b.startedAt - a.startedAt),
  };
}

async function readRequestBody(req) {
  const chunks = [];
  for await (const chunk of req) chunks.push(chunk);
  const raw = Buffer.concat(chunks).toString("utf8");
  if (!raw.trim()) return {};
  return JSON.parse(raw);
}

function startScriptTask(kind) {
  const scripts = {
    register: "reg.cmd",
    harvest: "harvest.cmd",
    rebind: "rebind.cmd",
    status: "status.cmd",
  };
  const script = scripts[kind];
  if (!script) throw new Error(`未知任务: ${kind}`);
  const scriptPath = path.join(ROOT, script);
  if (!existsSync(scriptPath)) throw new Error(`脚本不存在: ${script}`);
  const id = `${kind}-${Date.now()}`;
  const logPath = path.join(TASK_LOG_DIR, `${id}.log`);
  const task = {
    id,
    kind,
    script,
    status: "running",
    startedAt: Date.now(),
    finishedAt: null,
    exitCode: null,
    log: "",
  };
  tasks.set(id, task);
  const child = spawn("cmd.exe", ["/c", scriptPath], {cwd: ROOT, windowsHide: true});
  const writeLog = async () => {
    await writeFile(logPath, task.log, "utf8").catch(() => {});
  };
  child.stdout.on("data", (chunk) => {
    task.log += chunk.toString("utf8");
    task.log = task.log.slice(-20000);
  });
  child.stderr.on("data", (chunk) => {
    task.log += chunk.toString("utf8");
    task.log = task.log.slice(-20000);
  });
  child.on("error", (error) => {
    task.status = "failed";
    task.finishedAt = Date.now();
    task.log += `\n[server] ${error.message}\n`;
    writeLog();
  });
  child.on("close", (code) => {
    task.status = code === 0 ? "completed" : "failed";
    task.finishedAt = Date.now();
    task.exitCode = code;
    writeLog();
  });
  return task;
}

async function handleApi(req, res, url) {
  try {
    if (req.method === "GET" && url.pathname === "/api/status") {
      return jsonResponse(res, 200, await getStatus());
    }

    if (req.method === "POST" && url.pathname === "/api/numbers") {
      const body = await readRequestBody(req);
      const lines = String(body.text || "").split(/\r?\n/);
      const invalid = lines
        .map((line) => line.trim())
        .filter((line) => line && !line.startsWith("#") && !line.includes("----"));
      if (invalid.length) {
        return jsonResponse(res, 400, {error: "稳定号格式需要包含 ---- 接码记录 URL", invalid});
      }
      return jsonResponse(res, 200, await appendUniqueLines(paths.numbers, lines));
    }

    if (req.method === "POST" && url.pathname === "/api/import-cpa") {
      const body = await readRequestBody(req);
      const parsed = JSON.parse(String(body.text || "{}"));
      const items = extractAuthItems(parsed, body.filename || "pasted.json").map((item) => summarizeAuth(item.name, item.data));
      if (!items.length) {
        return jsonResponse(res, 400, {error: "没有识别到 CPA/Codex auth JSON"});
      }
      let tokensAdded = 0;
      for (const item of items) {
        await writeJsonAtomic(path.join(IMPORT_DIR, `${item.id}.json`), item);
        if (item.accessToken) {
          const result = await appendUniqueLines(paths.tokens, [item.accessToken]);
          tokensAdded += result.added;
        }
      }
      return jsonResponse(res, 200, {
        imported: items.map((item) => ({...item, data: undefined, accessToken: undefined, refreshToken: undefined, idToken: undefined})),
        tokensAdded,
      });
    }

    if (req.method === "POST" && url.pathname === "/api/task") {
      await ensureDirs();
      const body = await readRequestBody(req);
      const task = startScriptTask(String(body.kind || ""));
      return jsonResponse(res, 200, task);
    }

    if (req.method === "POST" && url.pathname === "/api/slot") {
      const body = await readRequestBody(req);
      const id = String(body.id || "").trim();
      const action = String(body.action || "").trim();
      const state = await readJsonFile(paths.state, {slots: {}});
      if (!id || !state.slots?.[id]) return jsonResponse(res, 404, {error: "slot 不存在"});
      if (action === "set-state") {
        const nextState = String(body.state || "").trim();
        if (!allowedSlotStates.has(nextState)) return jsonResponse(res, 400, {error: "状态不合法"});
        state.slots[id].state = nextState;
        state.slots[id].updated_at = Math.floor(Date.now() / 1000);
      } else if (action === "clear-error") {
        delete state.slots[id].error;
        state.slots[id].updated_at = Math.floor(Date.now() / 1000);
      } else if (action === "delete") {
        delete state.slots[id];
      } else {
        return jsonResponse(res, 400, {error: "未知 slot 动作"});
      }
      await writeJsonAtomic(paths.state, state);
      return jsonResponse(res, 200, {ok: true});
    }

    if (req.method === "POST" && url.pathname === "/api/upload-hub") {
      const body = await readRequestBody(req);
      const ids = Array.isArray(body.ids) ? body.ids.map(String) : [];
      const forcePlus = body.forcePlus !== false;
      const selected = ids.length ? ids : (await listImportedAuths()).filter((item) => item.plan === "plus").map((item) => item.id);
      const auths = [];
      for (const id of selected) {
        const item = await loadImportedAuth(id);
        if (!item.validForHub) continue;
        if (forcePlus || item.plan === "plus") {
          auths.push({
            filename: item.filename,
            data: item.data,
            force_plus: forcePlus || item.plan === "plus",
          });
        }
      }
      if (!auths.length) {
        return jsonResponse(res, 400, {error: "没有可上传的 Plus CPA JSON"});
      }
      const payloadPath = path.join(DATA_DIR, `autoteam-upload-${Date.now()}.json`);
      await writeJsonAtomic(payloadPath, {auths});
      const script = path.join(WEB_DIR, "tools", "import-to-autoteam.py");
      const py = process.env.PYTHON || "python";
      const result = await new Promise((resolve) => {
        const child = spawn(py, [script, AUTOTEAM_ROOT, payloadPath], {cwd: ROOT, windowsHide: true});
        let stdout = "";
        let stderr = "";
        child.stdout.on("data", (chunk) => (stdout += chunk.toString("utf8")));
        child.stderr.on("data", (chunk) => (stderr += chunk.toString("utf8")));
        child.on("close", (code) => resolve({code, stdout, stderr}));
        child.on("error", (error) => resolve({code: -1, stdout, stderr: error.message}));
      });
      if (result.code !== 0) {
        return jsonResponse(res, 500, {error: "导入 AutoTeam-F 失败", detail: result.stderr || result.stdout});
      }
      const lastLine = result.stdout.trim().split(/\r?\n/).filter(Boolean).at(-1) || "{}";
      return jsonResponse(res, 200, JSON.parse(lastLine));
    }

    return jsonResponse(res, 404, {error: "not found"});
  } catch (error) {
    return jsonResponse(res, 500, {error: error.message || String(error)});
  }
}

async function serveStatic(res, url) {
  const requested = url.pathname === "/" ? "/index.html" : url.pathname;
  const file = path.resolve(PUBLIC_DIR, `.${requested}`);
  if (!file.startsWith(PUBLIC_DIR)) return textResponse(res, 403, "Forbidden");
  try {
    const info = await stat(file);
    if (!info.isFile()) throw new Error("not file");
    const body = await readFile(file);
    const ext = path.extname(file).toLowerCase();
    const types = {
      ".html": "text/html; charset=utf-8",
      ".css": "text/css; charset=utf-8",
      ".js": "text/javascript; charset=utf-8",
      ".svg": "image/svg+xml",
    };
    res.writeHead(200, {"Content-Type": types[ext] || "application/octet-stream"});
    res.end(body);
  } catch {
    textResponse(res, 404, "Not found");
  }
}

await ensureDirs();

createServer(async (req, res) => {
  const url = new URL(req.url || "/", `http://${req.headers.host || `${HOST}:${PORT}`}`);
  if (url.pathname.startsWith("/api/")) {
    await handleApi(req, res, url);
    return;
  }
  await serveStatic(res, url);
}).listen(PORT, HOST, () => {
  console.log(`CNgopay console: http://${HOST}:${PORT}`);
});
