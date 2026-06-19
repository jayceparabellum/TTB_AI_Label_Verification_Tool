"""Security hardening: response headers + upload size limit (PR #2 spec)."""

from fastapi.testclient import TestClient

from app.main import app, _MAX_FILE_BYTES

client = TestClient(app)


def test_security_headers_present_on_every_response():
    h = client.get("/").headers
    assert h["X-Content-Type-Options"] == "nosniff"
    assert h["X-Frame-Options"] == "DENY"
    assert h["Referrer-Policy"] == "strict-origin-when-cross-origin"
    assert "camera=()" in h["Permissions-Policy"]
    csp = h["Content-Security-Policy"]
    assert "default-src 'self'" in csp
    assert "script-src 'self'" in csp            # no 'unsafe-inline' for scripts
    assert "object-src 'none'" in csp


def test_headers_present_on_error_responses_too():
    # The middleware wraps every response, including 404s.
    r = client.post("/verify-sample/does-not-exist")
    assert r.status_code == 404
    assert r.headers["X-Content-Type-Options"] == "nosniff"


def test_oversized_upload_is_rejected_413():
    big = b"\x89PNG" + b"0" * (_MAX_FILE_BYTES + 1)   # just over the 10 MB cap
    r = client.post("/verify",
                    files={"label_image": ("big.png", big, "image/png")},
                    data={"brand": "X", "alcohol_content": "5.0"})
    assert r.status_code == 413
    assert "10 MB" in r.text


def test_upload_at_limit_is_not_rejected_for_size():
    # A small valid-ish payload under the cap must not 413 (it may be "unreadable",
    # but that's a 200 result, not a size rejection).
    r = client.post("/verify",
                    files={"label_image": ("ok.png", b"not really a png", "image/png")},
                    data={"brand": "X", "alcohol_content": "5.0"})
    assert r.status_code != 413
