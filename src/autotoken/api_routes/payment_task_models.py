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


class PayPalTaskParams(BaseModel):
    runner_mode: str = Field("", validation_alias=AliasChoices("runner_mode", "runnerMode"))
    email: str = ""
    account_emails: list[str] = Field(
        default_factory=list, validation_alias=AliasChoices("account_emails", "accountEmails")
    )
    checkout_url: str = Field("", validation_alias=AliasChoices("checkout_url", "checkoutUrl"))
    bind_link_payload: dict = Field(
        default_factory=dict, validation_alias=AliasChoices("bind_link_payload", "bindLinkPayload")
    )
    proxy_url: str | None = Field(None, validation_alias=AliasChoices("proxy_url", "proxyUrl"))
    proxy_pool: list[str] = Field(default_factory=list, validation_alias=AliasChoices("proxy_pool", "proxyPool"))
    proxy_pool_text: str = Field("", validation_alias=AliasChoices("proxy_pool_text", "proxyPoolText"))
    proxy_api_url: str = Field("", validation_alias=AliasChoices("proxy_api_url", "proxyApiUrl"))
    proxy_api_provider: str = Field("", validation_alias=AliasChoices("proxy_api_provider", "proxyApiProvider"))
    proxy_label: str = Field("", validation_alias=AliasChoices("proxy_label", "proxyLabel"))
    proxy_bypass: str | None = Field(None, validation_alias=AliasChoices("proxy_bypass", "proxyBypass"))
    paypal_browser: str = Field("chromium", validation_alias=AliasChoices("paypal_browser", "paypalBrowser"))
    paypal_fallback_browser: str = Field(
        "",
        validation_alias=AliasChoices("paypal_fallback_browser", "paypalFallbackBrowser"),
    )
    roxybrowser_workspace_id: str = Field(
        "",
        validation_alias=AliasChoices("roxybrowser_workspace_id", "roxybrowserWorkspaceId"),
    )
    roxybrowser_profile_id: str = Field(
        "",
        validation_alias=AliasChoices(
            "roxybrowser_profile_id", "roxybrowserProfileId", "roxybrowser_dir_id", "roxybrowserDirId"
        ),
    )
    roxybrowser_auto_create_profile: bool = Field(
        False,
        validation_alias=AliasChoices("roxybrowser_auto_create_profile", "roxybrowserAutoCreateProfile"),
    )
    manual_confirm: bool = Field(True, validation_alias=AliasChoices("manual_confirm", "manualConfirm"))
    paypal_mode: str = Field("existing_account", validation_alias=AliasChoices("paypal_mode", "paypalMode"))
    paypal_email: str = Field("", validation_alias=AliasChoices("paypal_email", "paypalEmail"))
    paypal_password: str = Field("", validation_alias=AliasChoices("paypal_password", "paypalPassword"))
    paypal_approve_url: str = Field("", validation_alias=AliasChoices("paypal_approve_url", "paypalApproveUrl"))
    paypal_ba_token: str = Field("", validation_alias=AliasChoices("paypal_ba_token", "paypalBaToken"))
    paypal_checkout_session_id: str = Field(
        "",
        validation_alias=AliasChoices("paypal_checkout_session_id", "paypalCheckoutSessionId"),
    )
    paypal_checkout_url: str = Field("", validation_alias=AliasChoices("paypal_checkout_url", "paypalCheckoutUrl"))
    paypal_hosted_checkout_url: str = Field(
        "",
        validation_alias=AliasChoices("paypal_hosted_checkout_url", "paypalHostedCheckoutUrl"),
    )
    paypal_payment_method_id: str = Field(
        "",
        validation_alias=AliasChoices("paypal_payment_method_id", "paypalPaymentMethodId"),
    )
    paypal_ba_mode: str = Field("eu", validation_alias=AliasChoices("paypal_ba_mode", "paypalBaMode"))
    phone_accounts: list[GoPayPhoneAccountParams] = Field(
        default_factory=list,
        validation_alias=AliasChoices("phone_accounts", "phoneAccounts"),
    )
    sms_url: str = Field("", validation_alias=AliasChoices("sms_url", "smsUrl"))
    otp_channel: str = Field("sms", validation_alias=AliasChoices("otp_channel", "otpChannel"))
    paypal_card_number: str = Field("", validation_alias=AliasChoices("paypal_card_number", "paypalCardNumber"))
    paypal_card_expiry: str = Field("", validation_alias=AliasChoices("paypal_card_expiry", "paypalCardExpiry"))
    paypal_card_cvv: str = Field("", validation_alias=AliasChoices("paypal_card_cvv", "paypalCardCvv"))
    paypal_region: str = Field("", validation_alias=AliasChoices("paypal_region", "paypalRegion"))
    paypal_country: str = Field("US", validation_alias=AliasChoices("paypal_country", "paypalCountry"))
    paypal_lang: str = Field("", validation_alias=AliasChoices("paypal_lang", "paypalLang"))
    autofill_enabled: bool = Field(False, validation_alias=AliasChoices("autofill_enabled", "autofillEnabled"))
    billing_name: str = Field("", validation_alias=AliasChoices("billing_name", "billingName"))
    billing_email: str = Field("", validation_alias=AliasChoices("billing_email", "billingEmail"))
    billing_phone: str = Field("", validation_alias=AliasChoices("billing_phone", "billingPhone"))
    billing_country: str = Field("US", validation_alias=AliasChoices("billing_country", "billingCountry"))
    billing_state: str = Field("", validation_alias=AliasChoices("billing_state", "billingState"))
    billing_city: str = Field("", validation_alias=AliasChoices("billing_city", "billingCity"))
    billing_zip: str = Field("", validation_alias=AliasChoices("billing_zip", "billingZip"))
    billing_address1: str = Field("", validation_alias=AliasChoices("billing_address1", "billingAddress1"))
    billing_address2: str = Field("", validation_alias=AliasChoices("billing_address2", "billingAddress2"))
    timeout_seconds: int = Field(0, validation_alias=AliasChoices("timeout_seconds", "timeoutSeconds"))
    auto_oauth_after_success: bool = Field(
        False,
        validation_alias=AliasChoices("auto_oauth_after_success", "autoOauthAfterSuccess"),
    )
    pending_retry_attempts: int = Field(
        1,
        validation_alias=AliasChoices("pending_retry_attempts", "pendingRetryAttempts"),
    )
    paypal_concurrency: int = Field(
        1,
        validation_alias=AliasChoices("paypal_concurrency", "paypalConcurrency"),
    )
