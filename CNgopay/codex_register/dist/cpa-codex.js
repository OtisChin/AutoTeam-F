/**
 * CPA management codex OAuth helpers.
 *
 * 注意：这些请求必须**绕过**全局 SOCKS 代理（代理是给 OpenAI 用的美国节点），
 * 直接走默认 dispatcher 才能正常访问 cpa.iceaix.com。
 */
import { Agent, fetch as undiciFetch } from "undici";
const CPA_BASE_DEFAULT = "https://cpa.iceaix.com";
let cachedDispatcher = null;
function getCpaDispatcher() {
    if (!cachedDispatcher) {
        cachedDispatcher = new Agent({ connect: { rejectUnauthorized: false } });
    }
    return cachedDispatcher;
}
function buildHeaders(managementKey) {
    return {
        Accept: "application/json",
        "Content-Type": "application/json",
        Authorization: `Bearer ${managementKey}`,
        "X-Management-Key": managementKey,
    };
}
export async function requestCodexAuthUrl(baseUrl, managementKey, timeoutMs = 20000) {
    const url = `${baseUrl.replace(/\/+$/, "")}/v0/management/codex-auth-url`;
    const controller = new AbortController();
    const timer = setTimeout(() => controller.abort(), timeoutMs);
    try {
        const response = await undiciFetch(url, {
            method: "GET",
            headers: buildHeaders(managementKey),
            signal: controller.signal,
            dispatcher: getCpaDispatcher(),
        });
        if (!response.ok) {
            const body = await response.text().catch(() => "");
            throw new Error(`CPA codex-auth-url 失败: status=${response.status} body=${body.slice(0, 300)}`);
        }
        const data = (await response.json());
        const authorizeUrl = data.url || data.auth_url || data.authUrl
            || data.data?.url || data.data?.auth_url || data.data?.authUrl || "";
        if (!authorizeUrl || !authorizeUrl.startsWith("http")) {
            throw new Error(`CPA codex-auth-url 未返回有效 URL: ${JSON.stringify(data).slice(0, 300)}`);
        }
        let state = data.state || data.auth_state || data.authState
            || data.data?.state || data.data?.auth_state || data.data?.authState || "";
        if (!state) {
            try {
                const u = new URL(authorizeUrl);
                state = u.searchParams.get("state") || "";
            }
            catch (_) { /* ignore */ }
        }
        return { authorizeUrl, state };
    }
    finally {
        clearTimeout(timer);
    }
}
export async function submitOAuthCallback(baseUrl, managementKey, callbackUrl, timeoutMs = 30000) {
    const url = `${baseUrl.replace(/\/+$/, "")}/v0/management/oauth-callback`;
    const controller = new AbortController();
    const timer = setTimeout(() => controller.abort(), timeoutMs);
    try {
        const response = await undiciFetch(url, {
            method: "POST",
            headers: buildHeaders(managementKey),
            body: JSON.stringify({ provider: "codex", redirect_url: callbackUrl }),
            signal: controller.signal,
            dispatcher: getCpaDispatcher(),
        });
        const body = await response.text().catch(() => "");
        return { status: response.status, body };
    }
    finally {
        clearTimeout(timer);
    }
}
export async function listAuthFiles(baseUrl, managementKey, timeoutMs = 20000) {
    const url = `${baseUrl.replace(/\/+$/, "")}/v0/management/auth-files`;
    const controller = new AbortController();
    const timer = setTimeout(() => controller.abort(), timeoutMs);
    try {
        const response = await undiciFetch(url, {
            method: "GET",
            headers: buildHeaders(managementKey),
            signal: controller.signal,
            dispatcher: getCpaDispatcher(),
        });
        const body = await response.text().catch(() => "");
        if (!response.ok) {
            throw new Error(`CPA list auth-files 失败: status=${response.status} body=${body.slice(0, 300)}`);
        }
        const data = JSON.parse(body);
        return Array.isArray(data?.files) ? data.files : [];
    }
    finally {
        clearTimeout(timer);
    }
}
export async function downloadAuthFile(baseUrl, managementKey, name, timeoutMs = 20000) {
    const url = new URL(`${baseUrl.replace(/\/+$/, "")}/v0/management/auth-files/download`);
    url.searchParams.set("name", name);
    const controller = new AbortController();
    const timer = setTimeout(() => controller.abort(), timeoutMs);
    try {
        const response = await undiciFetch(url.toString(), {
            method: "GET",
            headers: buildHeaders(managementKey),
            signal: controller.signal,
            dispatcher: getCpaDispatcher(),
        });
        const body = await response.text().catch(() => "");
        if (!response.ok) {
            throw new Error(`CPA download auth-file 失败: status=${response.status} name=${name} body=${body.slice(0, 300)}`);
        }
        return JSON.parse(body);
    }
    finally {
        clearTimeout(timer);
    }
}
export function getCpaBaseUrl() {
    return process.env.CPA_BASE_URL?.trim() || CPA_BASE_DEFAULT;
}
export function getCpaManagementKey() {
    const key = process.env.CPA_MANAGEMENT_KEY?.trim() || "";
    if (!key) {
        throw new Error("缺少 CPA_MANAGEMENT_KEY 环境变量");
    }
    return key;
}
