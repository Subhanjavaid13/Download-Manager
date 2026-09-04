"""Is this email address worth creating an account for?

Three cheap checks run before Supabase ever sees the sign-up:
1. syntax          obvious typos and garbage
2. disposable      throwaway domains (10minutemail and ~4,000 friends)
3. mx              the domain can actually receive mail

The result is stored on the profile as `email_risk` so the dashboard can show
verified vs unverified vs disposable sign-ups over time.
"""

from __future__ import annotations

import logging
import re
from dataclasses import dataclass
from functools import lru_cache

log = logging.getLogger(__name__)

_EMAIL = re.compile(r"^[A-Za-z0-9.!#$%&'*+/=?^_`{|}~-]+@([A-Za-z0-9-]+\.)+[A-Za-z]{2,}$")


@dataclass(frozen=True)
class EmailCheck:
    ok: bool
    risk: str  # ok | invalid | disposable | no_mx | unknown
    message: str | None = None


@lru_cache
def _disposable_domains() -> frozenset[str]:
    try:
        from disposable_email_domains import blocklist

        return frozenset(d.lower() for d in blocklist)
    except ImportError:  # pragma: no cover - dependency is declared, but stay safe
        log.warning("disposable-email-domains not installed; skipping that check")
        return frozenset()


def is_disposable(domain: str) -> bool:
    domain = domain.lower()
    domains = _disposable_domains()
    # Also catch subdomains of a listed domain (mail.tempmail.com).
    parts = domain.split(".")
    return any(".".join(parts[i:]) in domains for i in range(len(parts) - 1))


def has_mx(domain: str, timeout: float = 3.0) -> bool | None:
    """True/False when DNS answered; None when DNS itself failed (do not block on that)."""
    try:
        import dns.resolver

        resolver = dns.resolver.Resolver()
        resolver.lifetime = timeout
        try:
            answers = resolver.resolve(domain, "MX")
            return len(list(answers)) > 0
        except dns.resolver.NoAnswer:
            # No MX record: mail may still be delivered to an A record (rare, legacy).
            try:
                resolver.resolve(domain, "A")
                return True
            except Exception:  # noqa: BLE001
                return False
        except dns.resolver.NXDOMAIN:
            return False
    except Exception:  # noqa: BLE001 - resolver outage, offline CI, etc.
        log.info("MX lookup failed for %s", domain, exc_info=True)
        return None


def check_email(email: str, *, check_disposable: bool = True, check_mx: bool = True) -> EmailCheck:
    email = (email or "").strip()
    if not _EMAIL.match(email) or len(email) > 254:
        return EmailCheck(False, "invalid", "That email address does not look right.")
    domain = email.rsplit("@", 1)[1].lower()

    if check_disposable and is_disposable(domain):
        return EmailCheck(
            False,
            "disposable",
            "Temporary email addresses are not accepted. Use an address you keep.",
        )
    if check_mx:
        mx = has_mx(domain)
        if mx is False:
            return EmailCheck(
                False, "no_mx", "That email domain cannot receive mail. Check for a typo."
            )
        if mx is None:
            return EmailCheck(True, "unknown")
    return EmailCheck(True, "ok")
