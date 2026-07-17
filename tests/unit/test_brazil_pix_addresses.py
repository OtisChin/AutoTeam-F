from __future__ import annotations

import json
from pathlib import Path

from autotoken.payments import brazil_pix


PROJECT_ROOT = Path(__file__).resolve().parents[2]
BACKUP_FILE = PROJECT_ROOT / "docs" / "backups" / "brazil_pix_addresses_2026-07-17.json"


def test_brazil_pix_old_address_pool_is_backed_up():
    data = json.loads(BACKUP_FILE.read_text(encoding="utf-8"))

    assert len(data) == 147
    assert data[0] == {
        "line1": "Avenida Paulista 1578",
        "city": "Sao Paulo",
        "state": "SP",
        "postal_code": "01310-200",
        "ddd": 11,
    }


def test_brazil_pix_address_pool_has_been_replaced_with_valid_real_addresses():
    addresses = brazil_pix.BR_ADDRESSES

    assert len(addresses) >= 120
    assert ("Avenida Paulista 1578", "Sao Paulo", "SP", "01310-200", 11) not in addresses
    assert len(set(addresses)) == len(addresses)
    for line1, city, state, postal_code, ddd in addresses:
        assert line1
        assert city
        assert len(state) == 2
        assert postal_code[:5].isdigit()
        assert postal_code[5:6] == "-"
        assert postal_code[6:].isdigit()
        assert isinstance(ddd, int)


def test_build_pix_dynamic_proxy_refreshes_direct_proxy_sid_marker():
    cfg = brazil_pix.PixJobConfig(
        access_token="token",
        direct_proxies=["socks5h://user:sid-oldsid-t-token@proxy.example:1080"],
    )

    first_url, first_label = brazil_pix.build_pix_dynamic_proxy(cfg, 0)
    second_url, second_label = brazil_pix.build_pix_dynamic_proxy(cfg, 1)

    assert "sid-oldsid-t-" not in first_url
    assert "sid-oldsid-t-" not in second_url
    assert first_url != second_url
    assert first_label.startswith("direct-1 sid=")
    assert second_label.startswith("direct-1 sid=")


def test_build_pix_dynamic_proxy_refreshes_kookeey_style_direct_proxy_sid():
    cfg = brazil_pix.PixJobConfig(
        access_token="token",
        region="BR",
        direct_proxies=["gate.kookeey.info:1000:user:pass-BR-OLDSID1"],
    )

    url, label = brazil_pix.build_pix_dynamic_proxy(cfg, 0)

    assert url.startswith("socks5h://user:pass-BR-")
    assert "OLDSID1" not in url
    assert "@gate.kookeey.info:1000" in url
    assert label.startswith("direct-1 sid=")
