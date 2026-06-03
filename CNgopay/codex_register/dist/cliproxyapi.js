import { appConfig } from "./config.js";
function normalizeBaseUrl(value) {
    return String(value ?? "").trim().replace(/\/+$/, "");
}
function getCLIProxyAPIConfig() {
    const baseUrl = normalizeBaseUrl(appConfig.cliproxyApiBaseUrl);
    const managementKey = String(appConfig.cliproxyApiManagementKey ?? "").trim();
    if (!baseUrl) {
        throw new Error("cliproxyApiBaseUrl 未配置");
    }
    if (!managementKey) {
        throw new Error("cliproxyApiManagementKey 未配置");
    }
    return {
        baseUrl,
        managementKey,
    };
}
function createManagementHeaders(extraHeaders = {}) {
    const { managementKey } = getCLIProxyAPIConfig();
    return {
        Authorization: `Bearer ${managementKey}`,
        Accept: "application/json",
        ...extraHeaders,
    };
}
export function shouldAutoUploadAuthToCLIProxyAPI() {
    return appConfig.cliproxyApiAutoUploadAuth;
}
export async function listAuthFilesFromCLIProxyAPI() {
    const { baseUrl } = getCLIProxyAPIConfig();
    const response = await fetch(`${baseUrl}/v0/management/auth-files`, {
        method: "GET",
        headers: createManagementHeaders(),
    });
    const rawBody = await response.text();
    if (!response.ok) {
        throw new Error(`CLIProxyAPI 获取 auth 列表失败: ${response.status} body=${rawBody}`);
    }
    const payload = JSON.parse(rawBody);
    return Array.isArray(payload?.files)
        ? payload.files
            .map((item) => ({
            ...item,
            name: String(item?.name ?? "").trim(),
            type: typeof item?.type === "string" ? item.type.trim() : undefined,
        }))
            .filter((item) => item.name)
        : [];
}
export async function downloadAuthFileJsonObjectFromCLIProxyAPI(name) {
    const { baseUrl } = getCLIProxyAPIConfig();
    const url = new URL(`${baseUrl}/v0/management/auth-files/download`);
    url.searchParams.set("name", name);
    const response = await fetch(url, {
        method: "GET",
        headers: createManagementHeaders(),
    });
    const rawBody = await response.text();
    if (!response.ok) {
        throw new Error(`CLIProxyAPI 下载 auth 失败: ${response.status} name=${name} body=${rawBody}`);
    }
    const payload = JSON.parse(rawBody);
    if (!payload || typeof payload !== "object" || Array.isArray(payload)) {
        throw new Error(`CLIProxyAPI auth 内容不是合法 JSON 对象: ${name}`);
    }
    return payload;
}
export async function saveAuthFileJsonObjectToCLIProxyAPI(fileName, record) {
    const { baseUrl } = getCLIProxyAPIConfig();
    if (!fileName.toLowerCase().endsWith(".json")) {
        throw new Error(`上传到 CLIProxyAPI 的 auth 文件名必须是 .json: ${fileName}`);
    }
    const url = new URL(`${baseUrl}/v0/management/auth-files`);
    url.searchParams.set("name", fileName);
    const response = await fetch(url, {
        method: "POST",
        headers: createManagementHeaders({
            "Content-Type": "application/json",
        }),
        body: JSON.stringify(record, null, 2),
    });
    const rawBody = await response.text();
    if (!response.ok) {
        throw new Error(`CLIProxyAPI 上传 auth 失败: ${response.status} body=${rawBody}`);
    }
}
export async function deleteAuthFileFromCLIProxyAPI(fileName) {
    const { baseUrl } = getCLIProxyAPIConfig();
    const response = await fetch(`${baseUrl}/v0/management/auth-files`, {
        method: "DELETE",
        headers: createManagementHeaders({
            "Content-Type": "application/json",
        }),
        body: JSON.stringify({
            names: [fileName],
        }),
    });
    const rawBody = await response.text();
    if (!response.ok) {
        throw new Error(`CLIProxyAPI 删除 auth 失败: ${response.status} body=${rawBody}`);
    }
}
export async function setAuthFileDisabledStatusToCLIProxyAPI(fileName, disabled) {
    const { baseUrl } = getCLIProxyAPIConfig();
    const response = await fetch(`${baseUrl}/v0/management/auth-files/status`, {
        method: "PATCH",
        headers: createManagementHeaders({
            "Content-Type": "application/json",
        }),
        body: JSON.stringify({
            name: fileName,
            disabled,
        }),
    });
    const rawBody = await response.text();
    if (!response.ok) {
        throw new Error(`CLIProxyAPI 更新 auth 状态失败: ${response.status} body=${rawBody}`);
    }
}
export async function uploadAuthFileToCLIProxyAPI(fileName, record) {
    if (!appConfig.cliproxyApiAutoUploadAuth) {
        return;
    }
    await saveAuthFileJsonObjectToCLIProxyAPI(fileName, record);
}
