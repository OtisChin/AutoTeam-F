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
    "BR": CountryProfile("BR", "pt_BR", "pt-BR", "55", "America/Sao_Paulo", 180, ("DateOfBirth", "IdentityDocumentType", "IdentityDocumentNumber"), True, True),
}

def get_country_profile(country: str | None) -> CountryProfile:
    return COUNTRY_PROFILES.get((country or "BR").upper(), COUNTRY_PROFILES["BR"])
