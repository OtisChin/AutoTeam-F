import {readFileSync} from "node:fs";
import path from "node:path";

export type MailProviderName = "2925" | "gmail" | "proxiedmail" | "cloudflare" | "hotmail" | "gptmail";
export type SmsProviderName = "hero_sms" | "oasis";

interface AppConfigFile {
    provider?: unknown;
    smsProvider?: unknown;
    defaultPassword?: unknown;
    loopDelayMs?: unknown;
    gmailAccessToken?: unknown;
    gmailEmailAddress?: unknown;
    gptMailApiKey?: unknown;
    gptMailDomain?: unknown;
    "2925EmailAddress"?: unknown;
    "2925Password"?: unknown;
    cloudflareEmailDomain?: unknown;
    cloudflareApiBaseUrl?: unknown;
    cloudflareApiKey?: unknown;
    defaultProxyUrl?: unknown;
    heroSMSApiKey?: unknown;
    heroSMSCountry?: unknown;
    heroSMSMaxPrice?: unknown;
    heroSMSPriceTiers?: unknown;
    heroSMSPollAttempts?: unknown;
    heroSMSPollIntervalMs?: unknown;
    oasisSMSBaseUrl?: unknown;
    oasisSMSCdks?: unknown;
    oasisSMSCdkFile?: unknown;
    oasisSMSPollAttempts?: unknown;
    oasisSMSPollIntervalMs?: unknown;
    oasisSMSAccountMapFile?: unknown;
    cliproxyApiAutoUploadAuth?: unknown;
    cliproxyApiBaseUrl?: unknown;
    cliproxyApiManagementKey?: unknown;
}

export interface AppConfig {
    provider: MailProviderName;
    smsProvider: SmsProviderName;
    defaultPassword: string;
    loopDelayMs: number;
    gmailAccessToken: string;
    gmailEmailAddress: string;
    gptMailApiKey: string;
    gptMailDomain: string;
    ["2925EmailAddress"]: string;
    ["2925Password"]: string;
    cloudflareEmailDomain: string;
    cloudflareApiBaseUrl: string;
    cloudflareApiKey: string;
    defaultProxyUrl: string;
    heroSMSApiKey?: string;
    heroSMSCountry: number;
    heroSMSMaxPrice: number;
    heroSMSPriceTiers?: number[];
    heroSMSPollAttempts: number;
    heroSMSPollIntervalMs: number;
    oasisSMSBaseUrl: string;
    oasisSMSCdks: string[];
    oasisSMSCdkFile: string;
    oasisSMSPollAttempts: number;
    oasisSMSPollIntervalMs: number;
    oasisSMSAccountMapFile: string;
    cliproxyApiAutoUploadAuth: boolean;
    cliproxyApiBaseUrl: string;
    cliproxyApiManagementKey: string;
}

const DEFAULT_CONFIG: AppConfig = {
    provider: "proxiedmail",
    smsProvider: "hero_sms",
    defaultPassword: "kuaileshifu88",
    loopDelayMs: 120000,
    gmailAccessToken: "",
    gmailEmailAddress: "",
    gptMailApiKey: "",
    gptMailDomain: "",
    "2925EmailAddress": "",
    "2925Password": "",
    cloudflareEmailDomain: "",
    cloudflareApiBaseUrl: "",
    cloudflareApiKey: "",
    defaultProxyUrl: "http://127.0.0.1:10808",
    heroSMSApiKey: undefined,
    heroSMSCountry: 52,
    heroSMSMaxPrice: 0.05,
    heroSMSPollAttempts: 10,
    heroSMSPollIntervalMs: 3000,
    oasisSMSBaseUrl: "https://sms.oapi.vip",
    oasisSMSCdks: [],
    oasisSMSCdkFile: "",
    oasisSMSPollAttempts: 24,
    oasisSMSPollIntervalMs: 5000,
    oasisSMSAccountMapFile: "oasis-cdk-accounts.jsonl",
    cliproxyApiAutoUploadAuth: false,
    cliproxyApiBaseUrl: "http://localhost:8317",
    cliproxyApiManagementKey: "",
};

function normalizeNumber(value: unknown, fallback: number): number {
    if (typeof value !== "number" || !Number.isFinite(value)) {
        return fallback;
    }
    return value;
}

function normalizeProvider(value: unknown): MailProviderName {
    if (value === "2925" || value === "gmail" || value === "proxiedmail" || value === "cloudflare" || value === "hotmail" || value === "gptmail") {
        return value;
    }
    return DEFAULT_CONFIG.provider;
}

function normalizeSmsProvider(value: unknown): SmsProviderName {
    if (value === "hero_sms" || value === "oasis") {
        return value;
    }
    return DEFAULT_CONFIG.smsProvider;
}

function normalizeStringArray(value: unknown): string[] {
    const values = Array.isArray(value) ? value : [value];
    const items: string[] = [];
    const seen = new Set<string>();
    for (const raw of values) {
        const text = String(raw ?? "");
        for (const item of text.split(/[\s,;]+/)) {
            const normalized = item.trim();
            if (!normalized || seen.has(normalized)) {
                continue;
            }
            seen.add(normalized);
            items.push(normalized);
        }
    }
    return items;
}

function normalizeBoolean(value: unknown, fallback: boolean): boolean {
    if (typeof value === "boolean") {
        return value;
    }
    if (typeof value === "string") {
        const normalized = value.trim().toLowerCase();
        if (["true", "1", "yes", "on"].includes(normalized)) {
            return true;
        }
        if (["false", "0", "no", "off"].includes(normalized)) {
            return false;
        }
    }
    return fallback;
}

function loadConfig(): AppConfig {
    const configPath = path.resolve(process.cwd(), "config.json");
    let raw: string;
    try {
        raw = readFileSync(configPath, "utf8");
    } catch {
        throw new Error("未找到 config.json，请先复制 config.example.json 为 config.json 并按需修改配置");
    }

    const parsed = JSON.parse(raw) as AppConfigFile;
    return {
        provider: normalizeProvider(parsed.provider),
        smsProvider: normalizeSmsProvider(parsed.smsProvider),
        defaultPassword:
            typeof parsed.defaultPassword === "string" && parsed.defaultPassword.trim()
                ? parsed.defaultPassword
                : DEFAULT_CONFIG.defaultPassword,
        loopDelayMs: normalizeNumber(parsed.loopDelayMs, DEFAULT_CONFIG.loopDelayMs),
        gmailAccessToken:
            typeof parsed.gmailAccessToken === "string"
                ? parsed.gmailAccessToken.trim()
                : DEFAULT_CONFIG.gmailAccessToken,
        gmailEmailAddress:
            typeof parsed.gmailEmailAddress === "string"
                ? parsed.gmailEmailAddress.trim()
                : DEFAULT_CONFIG.gmailEmailAddress,
        gptMailApiKey:
            typeof parsed.gptMailApiKey === "string"
                ? parsed.gptMailApiKey.trim()
                : DEFAULT_CONFIG.gptMailApiKey,
        gptMailDomain:
            typeof parsed.gptMailDomain === "string"
                ? parsed.gptMailDomain.trim()
                : DEFAULT_CONFIG.gptMailDomain,
        "2925EmailAddress":
            typeof parsed["2925EmailAddress"] === "string"
                ? parsed["2925EmailAddress"].trim()
                : DEFAULT_CONFIG["2925EmailAddress"],
        "2925Password":
            typeof parsed["2925Password"] === "string"
                ? parsed["2925Password"].trim()
                : DEFAULT_CONFIG["2925Password"],
        cloudflareEmailDomain:
            typeof parsed.cloudflareEmailDomain === "string" && parsed.cloudflareEmailDomain.trim()
                ? parsed.cloudflareEmailDomain.trim()
                : DEFAULT_CONFIG.cloudflareEmailDomain,
        cloudflareApiBaseUrl:
            typeof parsed.cloudflareApiBaseUrl === "string"
                ? parsed.cloudflareApiBaseUrl.trim()
                : DEFAULT_CONFIG.cloudflareApiBaseUrl,
        cloudflareApiKey:
            typeof parsed.cloudflareApiKey === "string"
                ? parsed.cloudflareApiKey.trim()
                : DEFAULT_CONFIG.cloudflareApiKey,
        defaultProxyUrl:
            typeof parsed.defaultProxyUrl === "string"
                ? parsed.defaultProxyUrl.trim()
                : DEFAULT_CONFIG.defaultProxyUrl,
        heroSMSApiKey:
          typeof parsed.heroSMSApiKey === "string"
            ? parsed.heroSMSApiKey.trim()
            : DEFAULT_CONFIG.heroSMSApiKey,
        heroSMSCountry:
          typeof parsed.heroSMSCountry === "number"
            ? parsed.heroSMSCountry
            : DEFAULT_CONFIG.heroSMSCountry,
        heroSMSMaxPrice:
          typeof parsed.heroSMSMaxPrice === "number"
            ? parsed.heroSMSMaxPrice
            : DEFAULT_CONFIG.heroSMSMaxPrice,
        heroSMSPriceTiers:
          Array.isArray(parsed.heroSMSPriceTiers)
            ? (parsed.heroSMSPriceTiers as unknown[])
                .map((v) => Number(v))
                .filter((v) => Number.isFinite(v) && v > 0)
            : undefined,
        heroSMSPollAttempts:
          typeof parsed.heroSMSPollAttempts === "number"
            ? parsed.heroSMSPollAttempts
            : DEFAULT_CONFIG.heroSMSPollAttempts,
        heroSMSPollIntervalMs:
          typeof parsed.heroSMSPollIntervalMs === "number"
            ? parsed.heroSMSPollIntervalMs
            : DEFAULT_CONFIG.heroSMSPollIntervalMs,
        oasisSMSBaseUrl:
            typeof parsed.oasisSMSBaseUrl === "string" && parsed.oasisSMSBaseUrl.trim()
                ? parsed.oasisSMSBaseUrl.trim()
                : DEFAULT_CONFIG.oasisSMSBaseUrl,
        oasisSMSCdks: normalizeStringArray(parsed.oasisSMSCdks),
        oasisSMSCdkFile:
            typeof parsed.oasisSMSCdkFile === "string"
                ? parsed.oasisSMSCdkFile.trim()
                : DEFAULT_CONFIG.oasisSMSCdkFile,
        oasisSMSPollAttempts:
            typeof parsed.oasisSMSPollAttempts === "number"
                ? parsed.oasisSMSPollAttempts
                : DEFAULT_CONFIG.oasisSMSPollAttempts,
        oasisSMSPollIntervalMs:
            typeof parsed.oasisSMSPollIntervalMs === "number"
                ? parsed.oasisSMSPollIntervalMs
                : DEFAULT_CONFIG.oasisSMSPollIntervalMs,
        oasisSMSAccountMapFile:
            typeof parsed.oasisSMSAccountMapFile === "string" && parsed.oasisSMSAccountMapFile.trim()
                ? parsed.oasisSMSAccountMapFile.trim()
                : DEFAULT_CONFIG.oasisSMSAccountMapFile,
        cliproxyApiAutoUploadAuth: normalizeBoolean(
            parsed.cliproxyApiAutoUploadAuth,
            DEFAULT_CONFIG.cliproxyApiAutoUploadAuth,
        ),
        cliproxyApiBaseUrl:
            typeof parsed.cliproxyApiBaseUrl === "string" && parsed.cliproxyApiBaseUrl.trim()
                ? parsed.cliproxyApiBaseUrl.trim()
                : DEFAULT_CONFIG.cliproxyApiBaseUrl,
        cliproxyApiManagementKey:
            typeof parsed.cliproxyApiManagementKey === "string"
                ? parsed.cliproxyApiManagementKey.trim()
                : DEFAULT_CONFIG.cliproxyApiManagementKey,
    };
}

export const appConfig = loadConfig();
