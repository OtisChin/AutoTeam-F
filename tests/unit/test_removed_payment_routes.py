from autotoken import api


def test_removed_payment_routes_are_not_registered():
    paths = {getattr(route, "path", "") for route in api.app.routes}

    assert "/api/tasks/paypal" not in paths
    assert "/api/tasks/paypal/preflight" not in paths
    assert "/api/config/paypal-sms" not in paths
