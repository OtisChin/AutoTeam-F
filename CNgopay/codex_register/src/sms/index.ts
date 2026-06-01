import { ActivationBroker } from "./activation-broker.js";
import { createHeroSmsProvider } from "./heroSMS.js";
import type { HeroSmsActivation, HeroSmsProvider, HeroSmsVerificationCode } from "./heroSMS.js";

type HeroSMSBrokerOption = {
  apiKey: string;
  country: number;
  maxPrice: number;
  pollAttempts: number;
  pollIntervalMs: number;
  // 新增：价格阶梯（从低到高）。如果没设置，就用 maxPrice 单点
  priceTiers?: number[];
}

/**
 * 阶梯价格 broker。第一次取号用最低价，遇到 NO_NUMBERS 就升一档。
 * 一旦取到号，就缓存当前 priceTier 给后续 requestActivation 用。
 */
export const createSMSBroker = (option: HeroSMSBrokerOption) => {
  const tiers = (option.priceTiers && option.priceTiers.length)
    ? [...option.priceTiers].sort((a, b) => a - b)
    : [option.maxPrice];

  const heroProvider = createHeroSmsProvider({
    apiKey: option.apiKey,
    defaultRequestOptions: {
      service: "dr",
      country: option.country,
      maxPrice: tiers[0],
      fixedPrice: true,
    },
    defaultWaitForCodeOptions: {
      markReady: false,
      completeOnCode: false,
      pollAttempts: option.pollAttempts,
      pollIntervalMs: option.pollIntervalMs,
    },
  });

  // wrap requestActivation：从 tiers[0] 开始，遇到 NO_NUMBERS 阶梯升级
  // fixedPrice=false → maxPrice 表示上限，能捕捉到 0.04 ~ 0.0499 之间所有号
  let currentTierIndex = 0;
  const wrappedProvider: HeroSmsProvider = {
    ...heroProvider,
    async requestActivation(): Promise<HeroSmsActivation> {
      let lastErr: unknown = null;
      for (let i = currentTierIndex; i < tiers.length; i += 1) {
        const tier = tiers[i];
        try {
          console.log(`[heroSMS] 尝试取号 maxPrice<=${tier} (tier ${i + 1}/${tiers.length})`);
          const activation = await heroProvider.requestPhoneNumber({
            service: "dr",
            country: option.country,
            maxPrice: tier,
            fixedPrice: false,
          });
          currentTierIndex = i; // 下次直接从这一档开始
          console.log(`[heroSMS] 取号成功 phone=+${activation.phoneNumber} cost=${activation.activationCost ?? '?'}`);
          return activation;
        } catch (err) {
          lastErr = err;
          const msg = String((err as Error)?.message ?? err).toUpperCase();
          // NO_NUMBERS / NO_NUMBER / NO_BALANCE 等都尝试升档
          if (msg.includes("NO_NUMBERS") || msg.includes("NO_NUMBER") || msg.includes("BAD_PRICE")) {
            console.warn(`[heroSMS] tier=${tier} 无可用号码，升档继续`);
            continue;
          }
          throw err;
        }
      }
      throw lastErr ?? new Error("HeroSMS 所有价位都没号");
    },
  };

  return new ActivationBroker(wrappedProvider);
};
