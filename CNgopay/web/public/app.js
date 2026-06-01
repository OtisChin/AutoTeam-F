const state = {
  snapshot: null,
  selectedTaskId: null,
};

const slotStates = [
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
];

const $ = (id) => document.getElementById(id);

function toast(message, type = "info") {
  const host = $("toastHost");
  const el = document.createElement("div");
  el.className = `toast ${type === "error" ? "error" : ""}`;
  el.textContent = message;
  host.appendChild(el);
  setTimeout(() => el.remove(), 4200);
}

async function api(path, options = {}) {
  const res = await fetch(path, {
    ...options,
    headers: {
      "Content-Type": "application/json",
      ...(options.headers || {}),
    },
  });
  const body = await res.json().catch(() => ({}));
  if (!res.ok) {
    const detail = typeof body.detail === "string" ? body.detail : "";
    throw new Error(body.error || detail || `HTTP ${res.status}`);
  }
  return body;
}

function statusClass(value) {
  const text = String(value || "").toLowerCase();
  if (text.includes("ready") || text.includes("released")) return "ready";
  if (text.includes("plus_done") || text === "plus") return "plus";
  if (text.includes("register") || text.includes("paying") || text.includes("waiting") || text.includes("rebind")) return "running";
  if (text.includes("fail") || text.includes("no_trial")) return "fail";
  return "";
}

function renderMetrics(data) {
  $("numberCount").textContent = data.counts.numbers;
  $("tokenCount").textContent = data.counts.tokens;
  $("slotCount").textContent = data.slots.length;
  $("plusImportCount").textContent = data.counts.plusImports;
  $("rootPath").textContent = data.root;
  $("autoteamPath").textContent = data.autoteamRoot;
  const summary = Object.entries(data.stateCounts)
    .map(([key, count]) => `${key}: ${count}`)
    .join(" / ");
  $("stateSummary").textContent = summary || "暂无 slot 状态";
}

function renderSlots(slots) {
  const tbody = $("slotTable");
  tbody.innerHTML = "";
  if (!slots.length) {
    tbody.innerHTML = '<tr><td colspan="7" class="empty">暂无 slot 数据</td></tr>';
    return;
  }
  for (const slot of slots) {
    const tr = document.createElement("tr");
    const options = slotStates
      .map((item) => `<option value="${item}" ${item === slot.state ? "selected" : ""}>${item}</option>`)
      .join("");
    tr.innerHTML = `
      <td class="mono">${slot.id || ""}</td>
      <td>
        <select class="slot-state" data-slot-state="${slot.id}">
          ${options}
        </select>
      </td>
      <td class="mono">${slot.displayPhone || "-"}</td>
      <td>${slot.last_balance_idr ?? "-"}</td>
      <td class="mono">${slot.account_id || "-"}</td>
      <td><div class="error-text" title="${slot.error || ""}">${slot.error || "-"}</div></td>
      <td>
        <div class="slot-actions">
          <button data-slot-action="save" data-slot="${slot.id}">保存</button>
          <button data-slot-action="clear-error" data-slot="${slot.id}">清错</button>
          <button data-slot-action="delete" data-slot="${slot.id}">删除</button>
        </div>
      </td>
    `;
    tbody.appendChild(tr);
  }
}

function renderImports(imports) {
  const list = $("importList");
  list.innerHTML = "";
  if (!imports.length) {
    list.innerHTML = '<div class="empty">还没有导入 CPA JSON</div>';
    return;
  }
  for (const item of imports.slice(0, 20)) {
    const div = document.createElement("div");
    div.className = "import-item";
    div.innerHTML = `
      <input type="checkbox" class="import-check" value="${item.id}" ${item.plan === "plus" ? "checked" : ""} />
      <div>
        <strong>${item.email || item.filename || "unknown"}</strong>
        <small>${item.filename || ""} · token ${item.tokenPreview || "-"} · ${item.validForHub ? "Hub 可用" : "缺少 id/refresh/account"}</small>
      </div>
      <span class="pill ${statusClass(item.plan)}">${item.plan || "unknown"}</span>
    `;
    list.appendChild(div);
  }
}

function formatTime(ts) {
  if (!ts) return "-";
  return new Date(ts).toLocaleTimeString();
}

function renderTasks(tasks) {
  const list = $("taskList");
  list.innerHTML = "";
  if (!tasks.length) {
    list.innerHTML = '<div class="empty">暂无任务</div>';
    $("logBox").textContent = "等待任务启动";
    return;
  }
  if (!state.selectedTaskId || !tasks.some((task) => task.id === state.selectedTaskId)) {
    state.selectedTaskId = tasks[0].id;
  }
  for (const task of tasks.slice(0, 8)) {
    const div = document.createElement("button");
    div.className = "task-item";
    div.dataset.taskId = task.id;
    div.innerHTML = `
      <div>
        <strong>${task.script || task.kind}</strong>
        <small>${formatTime(task.startedAt)} ${task.exitCode === null ? "" : `exit ${task.exitCode}`}</small>
      </div>
      <span class="pill ${task.status === "failed" ? "fail" : task.status === "running" ? "running" : "ready"}">${task.status}</span>
    `;
    list.appendChild(div);
  }
  const selected = tasks.find((task) => task.id === state.selectedTaskId) || tasks[0];
  $("logBox").textContent = selected.log || "任务已启动，等待输出";
}

function render(data) {
  state.snapshot = data;
  renderMetrics(data);
  renderSlots(data.slots);
  renderImports(data.imports);
  renderTasks(data.tasks);
  $("refreshState").textContent = "已连接";
}

async function refresh() {
  try {
    const data = await api("/api/status");
    render(data);
  } catch (error) {
    $("refreshState").textContent = "连接失败";
    toast(error.message, "error");
  }
}

async function startTask(kind) {
  const task = await api("/api/task", {
    method: "POST",
    body: JSON.stringify({kind}),
  });
  state.selectedTaskId = task.id;
  toast(`已启动 ${task.script}`);
  await refresh();
}

async function importCpaText(text, filename = "pasted.json") {
  const result = await api("/api/import-cpa", {
    method: "POST",
    body: JSON.stringify({text, filename}),
  });
  toast(`导入 ${result.imported.length} 个 CPA JSON，新增 ${result.tokensAdded} 个 token`);
  $("cpaText").value = "";
  await refresh();
}

async function importSelectedFiles(files) {
  let imported = 0;
  for (const file of files) {
    const text = await file.text();
    const result = await api("/api/import-cpa", {
      method: "POST",
      body: JSON.stringify({text, filename: file.name}),
    });
    imported += result.imported.length;
  }
  toast(`导入 ${imported} 个 CPA JSON`);
  $("cpaFile").value = "";
  await refresh();
}

async function addNumbers() {
  const text = $("numbersText").value;
  const result = await api("/api/numbers", {
    method: "POST",
    body: JSON.stringify({text}),
  });
  toast(`新增 ${result.added} 个稳定号，跳过 ${result.duplicates} 个重复`);
  $("numbersText").value = "";
  await refresh();
}

async function slotAction(button) {
  const id = button.dataset.slot;
  const action = button.dataset.slotAction;
  let body = {id, action};
  if (action === "save") {
    const select = document.querySelector(`[data-slot-state="${CSS.escape(id)}"]`);
    body = {id, action: "set-state", state: select.value};
  }
  if (action === "delete" && !confirm(`删除 ${id}？`)) return;
  await api("/api/slot", {
    method: "POST",
    body: JSON.stringify(body),
  });
  toast("Slot 已更新");
  await refresh();
}

async function uploadHub() {
  const ids = Array.from(document.querySelectorAll(".import-check:checked")).map((input) => input.value);
  const result = await api("/api/upload-hub", {
    method: "POST",
    body: JSON.stringify({ids, forcePlus: true}),
  });
  const summary = result.result || {};
  toast(`Hub 导入完成：文件 ${summary.imported || 0}/${summary.updated || 0}，Plus ${summary.marked_plus || 0}`);
  await refresh();
}

document.addEventListener("click", async (event) => {
  const taskButton = event.target.closest("[data-task]");
  const slotButton = event.target.closest("[data-slot-action]");
  const taskItem = event.target.closest("[data-task-id]");
  try {
    if (taskButton) {
      await startTask(taskButton.dataset.task);
      return;
    }
    if (slotButton) {
      await slotAction(slotButton);
      return;
    }
    if (taskItem) {
      state.selectedTaskId = taskItem.dataset.taskId;
      renderTasks(state.snapshot?.tasks || []);
    }
  } catch (error) {
    toast(error.message, "error");
  }
});

$("refreshBtn").addEventListener("click", refresh);
$("reloadSlotsBtn").addEventListener("click", refresh);
$("addNumbersBtn").addEventListener("click", () => addNumbers().catch((error) => toast(error.message, "error")));
$("uploadHubBtn").addEventListener("click", () => uploadHub().catch((error) => toast(error.message, "error")));
$("importCpaBtn").addEventListener("click", async () => {
  try {
    const files = $("cpaFile").files;
    if (files && files.length) {
      await importSelectedFiles(files);
      return;
    }
    const text = $("cpaText").value.trim();
    if (!text) {
      toast("请粘贴 CPA JSON 或选择文件", "error");
      return;
    }
    await importCpaText(text);
  } catch (error) {
    toast(error.message, "error");
  }
});

refresh();
setInterval(refresh, 3000);
