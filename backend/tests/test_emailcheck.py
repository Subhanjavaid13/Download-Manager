import pytest

from app.services import emailcheck
from app.services.emailcheck import check_email, is_disposable


@pytest.mark.parametrize("bad", ["", "nope", "a@b", "a@@b.com", "a b@example.com"])
def test_invalid_syntax(bad: str) -> None:
    result = check_email(bad, check_mx=False)
    assert result.ok is False
    assert result.risk == "invalid"


def test_disposable_domains_are_refused() -> None:
    assert is_disposable("mailinator.com")
    assert is_disposable("MAILINATOR.COM")
    assert is_disposable("sub.mailinator.com")
    assert not is_disposable("gmail.com")
    result = check_email("x@mailinator.com", check_mx=False)
    assert result.ok is False
    assert result.risk == "disposable"
    assert "Temporary" in (result.message or "")


def test_mx_missing_is_refused(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(emailcheck, "has_mx", lambda domain, timeout=3.0: False)
    result = check_email("x@no-such-domain-xyz.example")
    assert result.ok is False
    assert result.risk == "no_mx"


def test_dns_outage_does_not_block(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(emailcheck, "has_mx", lambda domain, timeout=3.0: None)
    result = check_email("x@gmail.com")
    assert result.ok is True
    assert result.risk == "unknown"


def test_good_email(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(emailcheck, "has_mx", lambda domain, timeout=3.0: True)
    result = check_email("Someone@Gmail.com")
    assert result.ok is True
    assert result.risk == "ok"


def test_real_mx_lookup_for_gmail_when_online() -> None:
    # Skips quietly if DNS is unavailable (offline CI).
    mx = emailcheck.has_mx("gmail.com")
    if mx is None:
        pytest.skip("no DNS")
    assert mx is True
