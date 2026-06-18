import {appendFile, mkdir, readFile} from "node:fs/promises";
import {readFileSync} from "node:fs";
import path from "node:path";
import {Agent, fetch as undiciFetch, type Dispatcher} from "undici";
import {ActivationBroker, type ISMSActivationBroker} from "./activation-broker.js";
import type {SmsActivation, SmsProvider, SmsVerificationCode} from "./provider.js";

const OASIS_DEFAULT_BASE_URL = "https://sms.oapi.vip";
const OASIS_DEFAULT_POLL_ATTEMPTS = 24;
const OASIS_DEFAULT_POLL_INTERVAL_MS = 5000;

export interface OasisSmsBrokerConfig {
  baseUrl?: string;
  cdks?: string[];
  cdkFile?: string;
  pollAttempts?: number;
  pollIntervalMs?: number;
  accountMapFile?: string;
}

export interface OasisSmsActivation extends SmsActivation {
  activationId: string;
  phoneNumber: string;
  cdk: string;
  remaining?: number;
  allowChange?: number;
}

export interface OasisSmsVerificationCode extends SmsVerificationCode {
  code: string;
  source: "oasis";
  text?: string;
  rawStatus: unknown;
}

export interface OasisAccountMapping {
  mode?: string;
  account?: string;
  phone?: string;
  email?: string;
  password?: string;
  authFile?: string;
  accessTokenFile?: string;
  extra?: Record<string, unknown>;
}

interface OasisApiResponse {
  ok?: boolean;
  error?: string;
  retry_after?: number;
  timeout?: boolean;
  code?: string;
  sms?: string;
  phone?: string;
  remaining?: number;
  allow_change?: number;
  cdk?: {
    remaining?: number;
    allow_change?: number;
  };
  session?: {
    phone_number?: string;
  };
}

interface OasisBrokerWithState extends ISMSActivationBroker {
  getState?: () => {
    currentActivation?: SmsActivation | null;
    lastReleasedUsage?: {
      activationId?: string;
      phoneNumber?: string;
    } | null;
  };
}

const oasisProviderByBroker = new WeakMap<object, OasisSmsProvider>();

function normalizeCdks(values: Iterable<unknown>): string[] {
  const cdks: string[] = [];
  const seen = new Set<string>();
  for (const value of values) {
    const raw = String(value ?? "");
    for (const item of raw.split(/[\s,;]+/)) {
      const cdk = item.trim();
      if (!cdk || seen.has(cdk)) {
        continue;
      }
      seen.add(cdk);
      cdks.push(cdk);
    }
  }
  return cdks;
}

function loadCdksFromFile(filePath?: string): string[] {
  const normalized = String(filePath ?? "").trim();
  if (!normalized) {
    return [];
  }

  const resolved = path.resolve(process.cwd(), normalized);
  const raw = readFileSync(resolved, "utf8");
  return normalizeCdks([raw]);
}

function normalizeBaseUrl(value?: string): string {
  const baseUrl = String(value ?? OASIS_DEFAULT_BASE_URL).trim().replace(/\/+$/, "");
  if (!baseUrl) {
    throw new Error("Oasis SMS baseUrl 未配置");
  }
  return baseUrl;
}

function normalizePollAttempts(value?: number): number {
  return value && Number.isFinite(value) && value > 0
    ? Math.floor(value)
    : OASIS_DEFAULT_POLL_ATTEMPTS;
}

function normalizePollIntervalMs(value?: number): number {
  return value && Number.isFinite(value) && value > 0
    ? Math.floor(value)
    : OASIS_DEFAULT_POLL_INTERVAL_MS;
}

function delay(ms: number): Promise<void> {
  return new Promise((resolve) => {
    setTimeout(resolve, ms);
  });
}

function formatPayload(payload: unknown): string {
  if (typeof payload === "string") {
    return payload;
  }
  try {
    return JSON.stringify(payload);
  } catch {
    return String(payload);
  }
}

function normalizePhoneNumber(phone: unknown): string {
  const normalized = String(phone ?? "").trim();
  if (!normalized) {
    return "";
  }
  return normalized.startsWith("+") ? normalized.slice(1) : normalized;
}

function isNoPhoneResponse(payload: OasisApiResponse): boolean {
  const error = String(payload.error ?? "").toLowerCase();
  return (
    error.includes("no available phone") ||
    error.includes("暂无可用") ||
    error.includes("号池暂无") ||
    error.includes("无可用")
  );
}

function buildDispatcher(): Dispatcher {
  return new Agent({
    connect: {rejectUnauthorized: false},
  });
}

class OasisSmsProvider implements SmsProvider<OasisSmsActivation, OasisSmsVerificationCode> {
  private readonly baseUrl: string;
  private readonly cdks: string[];
  private readonly pollAttempts: number;
  private readonly pollIntervalMs: number;
  private readonly accountMapFile: string;
  private readonly usedCdks = new Set<string>();

  constructor(config: OasisSmsBrokerConfig) {
    this.baseUrl = normalizeBaseUrl(config.baseUrl);
    this.cdks = normalizeCdks([
      ...(config.cdks ?? []),
      ...loadCdksFromFile(config.cdkFile),
    ]);
    this.pollAttempts = normalizePollAttempts(config.pollAttempts);
    this.pollIntervalMs = normalizePollIntervalMs(config.pollIntervalMs);
    this.accountMapFile = path.resolve(
      process.cwd(),
      String(config.accountMapFile ?? "oasis-cdk-accounts.jsonl").trim() ||
        "oasis-cdk-accounts.jsonl",
    );
  }

  async requestActivation(): Promise<OasisSmsActivation> {
    if (!this.cdks.length) {
      throw new Error("Oasis SMS CDK 池为空，请配置 oasisSMSCdks 或 oasisSMSCdkFile");
    }

    const errors: string[] = [];
    for (const cdk of this.cdks) {
      if (this.usedCdks.has(cdk)) {
        continue;
      }

      const payload = await this.requestApi("check_cdk", {code: cdk});
      if (!payload.ok) {
        errors.push(`${cdk}: ${payload.error || formatPayload(payload)}`);
        if (isNoPhoneResponse(payload)) {
          continue;
        }
        this.usedCdks.add(cdk);
        continue;
      }

      const phoneNumber = normalizePhoneNumber(payload.session?.phone_number ?? payload.phone);
      if (!phoneNumber) {
        errors.push(`${cdk}: 未返回手机号`);
        continue;
      }

      this.usedCdks.add(cdk);
      console.log(`[oasisSMS] CDK=${cdk} 兑换到号码 +${phoneNumber}`);
      return {
        activationId: cdk,
        cdk,
        phoneNumber,
        canRequestAnotherSms: false,
        remaining: payload.remaining ?? payload.cdk?.remaining,
        allowChange: payload.allow_change ?? payload.cdk?.allow_change,
      };
    }

    throw new Error(`Oasis SMS 没有可用 CDK/手机号: ${errors.join(" | ")}`);
  }

  async requestAnotherSms(_activationId: string): Promise<string> {
    throw new Error("Oasis SMS 一个 CDK 只对应一个验证码，不能复用同一 activation 请求第二条短信");
  }

  async waitForVerificationCode(activationId: string): Promise<OasisSmsVerificationCode> {
    const cdk = this.normalizeActivationId(activationId);
    let lastStatus: unknown;

    for (let attempt = 1; attempt <= this.pollAttempts; attempt += 1) {
      console.log(`[oasisSMS] 等待验证码 attempt=${attempt}/${this.pollAttempts} cdk=${cdk}`);
      const payload = await this.requestApi("get_sms", {code: cdk});
      lastStatus = payload;

      if (payload.ok && payload.code) {
        return {
          code: String(payload.code).trim(),
          source: "oasis",
          text: payload.sms,
          rawStatus: payload,
        };
      }

      if (payload.timeout) {
        throw new Error(`Oasis SMS 会话超时: cdk=${cdk} error=${payload.error ?? ""}`);
      }

      const retryAfter = Number(payload.retry_after ?? 0);
      const waitMs = retryAfter > 0 ? retryAfter * 1000 : this.pollIntervalMs;
      if (attempt < this.pollAttempts) {
        await delay(waitMs);
      }
    }

    throw new Error(
      `Oasis SMS 长时间未收到验证码: cdk=${cdk} lastStatus=${formatPayload(lastStatus)}`,
    );
  }

  async completeActivation(_activationId: string): Promise<string> {
    return "OK";
  }

  async cancelAndWithdraw(activationId: string): Promise<string> {
    return this.cancelActivation(activationId);
  }

  async cancelActivation(_activationId: string): Promise<string> {
    return "OK";
  }

  async recordAccountMapping(
    usage: {activationId?: string; phoneNumber?: string},
    account: OasisAccountMapping,
  ): Promise<boolean> {
    const cdk = this.normalizeActivationId(usage.activationId ?? "");
    const phone = account.phone || (usage.phoneNumber ? `+${normalizePhoneNumber(usage.phoneNumber)}` : "");
    const record = {
      recorded_at: new Date().toISOString(),
      provider: "oasis",
      cdk,
      phone,
      mode: account.mode ?? "",
      account: account.account || account.email || phone,
      email: account.email ?? "",
      password: account.password ?? "",
      auth_file: account.authFile ?? "",
      access_token_file: account.accessTokenFile ?? "",
      ...(account.extra ?? {}),
    };

    await mkdir(path.dirname(this.accountMapFile), {recursive: true});
    if (await this.hasExistingMapping(cdk, record.account)) {
      return false;
    }
    await appendFile(this.accountMapFile, `${JSON.stringify(record)}\n`, "utf8");
    console.log(`[oasisSMS] 已保存 CDK/账号对应关系: ${this.accountMapFile}`);
    return true;
  }

  private async requestApi(action: string, body: Record<string, unknown>): Promise<OasisApiResponse> {
    const url = `${this.baseUrl}/api.php?action=${encodeURIComponent(action)}`;
    const response = await undiciFetch(url, {
      method: "POST",
      dispatcher: buildDispatcher(),
      headers: {
        Accept: "application/json, text/plain;q=0.9, */*;q=0.8",
        "Content-Type": "application/json",
        Origin: this.baseUrl,
        Referer: `${this.baseUrl}/`,
        "User-Agent":
          "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/125 Safari/537.36",
      },
      body: JSON.stringify(body),
    });
    const text = await response.text();
    let payload: unknown;
    try {
      payload = text ? JSON.parse(text) : {};
    } catch {
      payload = text;
    }

    if (!response.ok) {
      throw new Error(`Oasis SMS ${action} 请求失败 status=${response.status}: ${formatPayload(payload)}`);
    }
    if (!payload || typeof payload !== "object") {
      throw new Error(`Oasis SMS ${action} 返回格式异常: ${formatPayload(payload)}`);
    }
    return payload as OasisApiResponse;
  }

  private normalizeActivationId(activationId: string): string {
    const normalized = String(activationId ?? "").trim();
    if (!normalized) {
      throw new Error("Oasis SMS activationId/CDK 不能为空");
    }
    return normalized;
  }

  private async hasExistingMapping(cdk: string, account: string): Promise<boolean> {
    try {
      const raw = await readFile(this.accountMapFile, "utf8");
      return raw.split(/\r?\n/).some((line) => {
        if (!line.trim()) {
          return false;
        }
        try {
          const record = JSON.parse(line) as {cdk?: unknown; account?: unknown};
          return record.cdk === cdk && String(record.account ?? "") === account;
        } catch {
          return false;
        }
      });
    } catch {
      return false;
    }
  }
}

export function createOasisSMSBroker(config: OasisSmsBrokerConfig): ISMSActivationBroker {
  const provider = new OasisSmsProvider(config);
  const broker = new ActivationBroker(provider);
  oasisProviderByBroker.set(broker, provider);
  return broker;
}

export async function recordOasisAccountMapping(
  broker: ISMSActivationBroker | undefined,
  account: OasisAccountMapping,
): Promise<boolean> {
  if (!broker || typeof broker !== "object") {
    return false;
  }

  const provider = oasisProviderByBroker.get(broker);
  if (!provider) {
    return false;
  }

  const state = (broker as OasisBrokerWithState).getState?.();
  const usage =
    state?.currentActivation ??
    state?.lastReleasedUsage ??
    null;
  if (!usage?.activationId) {
    return false;
  }

  return provider.recordAccountMapping(usage, account);
}
