from pathlib import Path

ROOT = Path(__file__).parents[1]


def test_maintenance_page_is_standalone_and_retries():
    page = (ROOT / "apps/web/public/maintenance.html").read_text(encoding="utf-8")
    assert '<meta http-equiv="refresh" content="30"' in page
    assert "temporarily unavailable" in page
    assert "Warren Buffett" in page
    assert "https://" not in page
    assert "<script" not in page


def test_gateway_returns_maintenance_page_for_web_outages():
    config = (ROOT / "infrastructure/nginx.conf").read_text(encoding="utf-8")
    assert "proxy_intercept_errors on;" in config
    assert "error_page 502 503 504 =503 /maintenance.html;" in config
    assert 'add_header Retry-After "30" always;' in config


def test_gateway_owns_public_port_while_web_is_internal():
    compose = (ROOT / "compose.yaml").read_text(encoding="utf-8")
    web = compose.split("  web:\n", 1)[1].split("  gateway:\n", 1)[0]
    gateway = compose.split("  gateway:\n", 1)[1].split("volumes:\n", 1)[0]
    assert 'expose: ["3000"]' in web
    assert 'ports: ["127.0.0.1:3000:3000"]' not in web
    assert 'ports: ["127.0.0.1:3000:3000"]' in gateway
    assert "http://127.0.0.1:3000/gateway-health" in gateway
