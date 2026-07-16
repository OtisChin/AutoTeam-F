"""Payment and wallet binding task request models."""

from pydantic import AliasChoices, BaseModel, Field


class GoPayPhoneAccountParams(BaseModel):
    country_code: str = Field("", validation_alias=AliasChoices("country_code", "countryCode"))
    phone_number: str = Field("", validation_alias=AliasChoices("phone_number", "phoneNumber"))
    sms_url: str = Field("", validation_alias=AliasChoices("sms_url", "smsUrl"))
    gopay_pin: str = Field("", validation_alias=AliasChoices("gopay_pin", "gopayPin"))
    otp_channel: str = Field("", validation_alias=AliasChoices("otp_channel", "otpChannel"))


class GoPayBindTaskParams(BaseModel):
    email: str = ""
    account_emails: list[str] = Field(default_factory=list)
    auto_register: bool = Field(False, validation_alias=AliasChoices("auto_register", "autoRegister"))
    auto_register_count: int = Field(1, validation_alias=AliasChoices("auto_register_count", "autoRegisterCount"))
    auto_register_protocol: bool = Field(
        False, validation_alias=AliasChoices("auto_register_protocol", "autoRegisterProtocol")
    )
    gopay_auto_signup: bool = Field(False, validation_alias=AliasChoices("gopay_auto_signup", "gopayAutoSignup"))
    gopay_auto_signup_sms_provider: str = Field(
        "",
        validation_alias=AliasChoices("gopay_auto_signup_sms_provider", "gopayAutoSignupSmsProvider"),
    )
    gopay_auto_signup_hero_sms_api_key: str = Field(
        "",
        validation_alias=AliasChoices("gopay_auto_signup_hero_sms_api_key", "gopayAutoSignupHeroSmsApiKey"),
    )
    gopay_auto_signup_hero_sms_base_url: str = Field(
        "",
        validation_alias=AliasChoices("gopay_auto_signup_hero_sms_base_url", "gopayAutoSignupHeroSmsBaseUrl"),
    )
    gopay_auto_signup_hero_sms_country: str = Field(
        "",
        validation_alias=AliasChoices("gopay_auto_signup_hero_sms_country", "gopayAutoSignupHeroSmsCountry"),
    )
    gopay_auto_signup_hero_sms_service: str = Field(
        "",
        validation_alias=AliasChoices("gopay_auto_signup_hero_sms_service", "gopayAutoSignupHeroSmsService"),
    )
    gopay_auto_signup_hero_sms_timeout: str = Field(
        "",
        validation_alias=AliasChoices("gopay_auto_signup_hero_sms_timeout", "gopayAutoSignupHeroSmsTimeout"),
    )
    gopay_auto_signup_hero_sms_min_price: str = Field(
        "",
        validation_alias=AliasChoices("gopay_auto_signup_hero_sms_min_price", "gopayAutoSignupHeroSmsMinPrice"),
    )
    gopay_auto_signup_hero_sms_max_price: str = Field(
        "",
        validation_alias=AliasChoices("gopay_auto_signup_hero_sms_max_price", "gopayAutoSignupHeroSmsMaxPrice"),
    )
    gopay_auto_signup_hero_sms_preferred_price: str = Field(
        "",
        validation_alias=AliasChoices(
            "gopay_auto_signup_hero_sms_preferred_price",
            "gopayAutoSignupHeroSmsPreferredPrice",
            "gopay_auto_signup_hero_sms_price_tier",
            "gopayAutoSignupHeroSmsPriceTier",
        ),
    )
    gopay_auto_signup_smsbower_api_key: str = Field(
        "",
        validation_alias=AliasChoices("gopay_auto_signup_smsbower_api_key", "gopayAutoSignupSmsbowerApiKey"),
    )
    gopay_auto_signup_smsbower_base_url: str = Field(
        "",
        validation_alias=AliasChoices("gopay_auto_signup_smsbower_base_url", "gopayAutoSignupSmsbowerBaseUrl"),
    )
    gopay_auto_signup_smsbower_country: str = Field(
        "",
        validation_alias=AliasChoices("gopay_auto_signup_smsbower_country", "gopayAutoSignupSmsbowerCountry"),
    )
    gopay_auto_signup_smsbower_service: str = Field(
        "",
        validation_alias=AliasChoices("gopay_auto_signup_smsbower_service", "gopayAutoSignupSmsbowerService"),
    )
    gopay_auto_signup_smsbower_timeout: str = Field(
        "",
        validation_alias=AliasChoices("gopay_auto_signup_smsbower_timeout", "gopayAutoSignupSmsbowerTimeout"),
    )
    gopay_auto_signup_smsbower_min_price: str = Field(
        "",
        validation_alias=AliasChoices("gopay_auto_signup_smsbower_min_price", "gopayAutoSignupSmsbowerMinPrice"),
    )
    gopay_auto_signup_smsbower_max_price: str = Field(
        "",
        validation_alias=AliasChoices("gopay_auto_signup_smsbower_max_price", "gopayAutoSignupSmsbowerMaxPrice"),
    )
    gopay_auto_signup_smsbower_preferred_price: str = Field(
        "",
        validation_alias=AliasChoices(
            "gopay_auto_signup_smsbower_preferred_price",
            "gopayAutoSignupSmsbowerPreferredPrice",
            "gopay_auto_signup_smsbower_price_tier",
            "gopayAutoSignupSmsbowerPriceTier",
        ),
    )
    gopay_auto_signup_smscloud_base_url: str = Field(
        "",
        validation_alias=AliasChoices("gopay_auto_signup_smscloud_base_url", "gopayAutoSignupSmscloudBaseUrl"),
    )
    gopay_auto_signup_smscloud_country: str = Field(
        "",
        validation_alias=AliasChoices("gopay_auto_signup_smscloud_country", "gopayAutoSignupSmscloudCountry"),
    )
    gopay_auto_signup_smscloud_service: str = Field(
        "",
        validation_alias=AliasChoices("gopay_auto_signup_smscloud_service", "gopayAutoSignupSmscloudService"),
    )
    gopay_auto_signup_smscloud_max_price: str = Field(
        "",
        validation_alias=AliasChoices("gopay_auto_signup_smscloud_max_price", "gopayAutoSignupSmscloudMaxPrice"),
    )
    gopay_auto_signup_smscloud_timeout: str = Field(
        "",
        validation_alias=AliasChoices("gopay_auto_signup_smscloud_timeout", "gopayAutoSignupSmscloudTimeout"),
    )
    gopay_auto_signup_smscode_api_token: str = Field(
        "",
        validation_alias=AliasChoices("gopay_auto_signup_smscode_api_token", "gopayAutoSignupSmscodeApiToken"),
    )
    gopay_auto_signup_smscode_base_url: str = Field(
        "",
        validation_alias=AliasChoices("gopay_auto_signup_smscode_base_url", "gopayAutoSignupSmscodeBaseUrl"),
    )
    gopay_auto_signup_smscode_country_id: str = Field(
        "",
        validation_alias=AliasChoices("gopay_auto_signup_smscode_country_id", "gopayAutoSignupSmscodeCountryId"),
    )
    gopay_auto_signup_smscode_platform_id: str = Field(
        "",
        validation_alias=AliasChoices("gopay_auto_signup_smscode_platform_id", "gopayAutoSignupSmscodePlatformId"),
    )
    gopay_auto_signup_smscode_platform_query: str = Field(
        "",
        validation_alias=AliasChoices(
            "gopay_auto_signup_smscode_platform_query", "gopayAutoSignupSmscodePlatformQuery"
        ),
    )
    gopay_auto_signup_smscode_product_id: str = Field(
        "",
        validation_alias=AliasChoices("gopay_auto_signup_smscode_product_id", "gopayAutoSignupSmscodeProductId"),
    )
    gopay_auto_signup_smscode_min_price: str = Field(
        "",
        validation_alias=AliasChoices("gopay_auto_signup_smscode_min_price", "gopayAutoSignupSmscodeMinPrice"),
    )
    gopay_auto_signup_smscode_max_price: str = Field(
        "",
        validation_alias=AliasChoices("gopay_auto_signup_smscode_max_price", "gopayAutoSignupSmscodeMaxPrice"),
    )
    gopay_auto_signup_smscode_timeout: str = Field(
        "",
        validation_alias=AliasChoices("gopay_auto_signup_smscode_timeout", "gopayAutoSignupSmscodeTimeout"),
    )
    gopay_auto_signup_mode: str = Field(
        "",
        validation_alias=AliasChoices("gopay_auto_signup_mode", "gopayAutoSignupMode"),
    )
    gopay_appium_url: str = Field(
        "",
        validation_alias=AliasChoices("gopay_appium_url", "gopayAppiumUrl"),
    )
    gopay_appium_adb_serial: str = Field(
        "",
        validation_alias=AliasChoices("gopay_appium_adb_serial", "gopayAppiumAdbSerial"),
    )
    auto_register_mail_provider: str | None = Field(
        None,
        validation_alias=AliasChoices("auto_register_mail_provider", "autoRegisterMailProvider"),
    )
    auto_register_luckmail_email_type: str | None = Field(
        None,
        validation_alias=AliasChoices("auto_register_luckmail_email_type", "autoRegisterLuckmailEmailType"),
    )
    auto_register_luckmail_preferred_domain: str | None = Field(
        None,
        validation_alias=AliasChoices("auto_register_luckmail_preferred_domain", "autoRegisterLuckmailPreferredDomain"),
    )
    auto_register_luckmail_preferred_domains: list[str] = Field(
        default_factory=list,
        validation_alias=AliasChoices(
            "auto_register_luckmail_preferred_domains", "autoRegisterLuckmailPreferredDomains"
        ),
    )
    auto_register_domain: str = Field("", validation_alias=AliasChoices("auto_register_domain", "autoRegisterDomain"))
    auto_register_domains: list[str] = Field(
        default_factory=list,
        validation_alias=AliasChoices("auto_register_domains", "autoRegisterDomains"),
    )
    auto_register_prefix: str = Field("", validation_alias=AliasChoices("auto_register_prefix", "autoRegisterPrefix"))
    auto_register_password: str = Field(
        "", validation_alias=AliasChoices("auto_register_password", "autoRegisterPassword")
    )
    phone_accounts: list[GoPayPhoneAccountParams] = Field(
        default_factory=list,
        validation_alias=AliasChoices("phone_accounts", "phoneAccounts"),
    )
    phone_number: str = ""
    country_code: str = ""
    sms_url: str = ""
    gopay_pin: str = ""
    otp_channel: str = Field("sms", validation_alias=AliasChoices("otp_channel", "otpChannel"))
    billing_name: str = ""
    billing_country: str = "US"
    billing_state: str = ""
    billing_city: str = ""
    billing_zip: str = ""
    billing_address1: str = ""
    billing_address2: str = ""
    checkout_url: str = ""
    checkout_ui_mode: str = "custom"
    proxy_url: str | None = None
    proxy_pool: list[str] = Field(default_factory=list, validation_alias=AliasChoices("proxy_pool", "proxyPool"))
    proxy_pool_text: str = Field("", validation_alias=AliasChoices("proxy_pool_text", "proxyPoolText"))
    proxy_api_provider: str = Field("", validation_alias=AliasChoices("proxy_api_provider", "proxyApiProvider"))
    proxy_api_url: str = Field("", validation_alias=AliasChoices("proxy_api_url", "proxyApiUrl"))
    proxy_label: str = ""
    proxy_bypass: str | None = None
    timeout_seconds: int = 900
    delete_rejected_accounts: bool = False
    auto_oauth_after_success: bool = False
    pending_retry_attempts: int = Field(
        1, validation_alias=AliasChoices("pending_retry_attempts", "pendingRetryAttempts")
    )
    gopay_concurrency: int = Field(1, validation_alias=AliasChoices("gopay_concurrency", "gopayConcurrency"))
    gopay_balance_wait_fallback_transfer: bool = Field(
        False,
        validation_alias=AliasChoices("gopay_balance_wait_fallback_transfer", "gopayBalanceWaitFallbackTransfer"),
    )
