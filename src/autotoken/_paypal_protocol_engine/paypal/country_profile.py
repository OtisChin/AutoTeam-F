from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class CountryProfile:
    country: str
    locale: str
    language: str
    phone_country_code: str
    timezone: str
    timezone_offset_minutes: int
    kyc_fields: tuple[str, ...] = ()
    collect_card_product_class: bool = False
    card_dob_required: bool = False

    @property
    def content_language(self) -> str:
        return self.language.split('-', 1)[0].lower()

COUNTRY_PROFILES: dict[str, CountryProfile] = {
    "US": CountryProfile("US", "en_US", "en-US", "1", "America/Los_Angeles", 420, (), False, False),
    "CA": CountryProfile("CA", "en_CA", "en-CA", "1", "America/Toronto", 240, (), False, False),
    "GB": CountryProfile("GB", "en_GB", "en-GB", "44", "Europe/London", -60, ("DateOfBirth", "Nationality"), False, False),
    "ID": CountryProfile("ID", "id_ID", "id-ID", "62", "Asia/Jakarta", -420, (), False, False),
    "JP": CountryProfile("JP", "ja_JP", "ja-JP", "81", "Asia/Tokyo", -540, (), False, False),
    "MX": CountryProfile("MX", "es_MX", "es-MX", "52", "America/Mexico_City", 360, (), False, False),
    "PH": CountryProfile("PH", "en_PH", "en-PH", "63", "Asia/Manila", -480, (), False, False),
    "TH": CountryProfile("TH", "th_TH", "th-TH", "66", "Asia/Bangkok", -420, (), False, False),
    "NL": CountryProfile("NL", "nl_NL", "nl-NL", "31", "Europe/Amsterdam", -120, (), False, False),
    "BR": CountryProfile("BR", "pt_BR", "pt-BR", "55", "America/Sao_Paulo", 180, ("DateOfBirth", "IdentityDocumentType", "IdentityDocumentNumber"), True, True),
}

def get_country_profile(country: str | None) -> CountryProfile:
    return COUNTRY_PROFILES.get((country or "BR").upper(), COUNTRY_PROFILES["BR"])
