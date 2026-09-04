"""Sentry, off unless a DSN is configured.

The DSN comes from the environment (DM_SENTRY_DSN), never from a file in the
repo. Nothing here runs when it is empty, so development and CI are untouched.

Privacy: this app already promises to keep raw IPs and full URLs out of its own
database, and an error tracker must not be the hole in that promise. So
`send_default_pii` is off and every event goes through `scrub_event` before it
leaves the process: credentials, cookies, client addresses, request bodies and
query strings are dropped, and a user is reduced to their id.
"""

from __future__ import annotations

import logging

log = logging.getLogger(__name__)

# Headers that identify or authenticate a person. Compared lower-case.
_SENSITIVE_HEADERS = frozenset(
    {
        "authorization",
        "cookie",
        "set-cookie",
        "proxy-authorization",
        "x-api-key",
        "x-client-id",  # the anonymous browser id: pseudonymous, but still an identifier
        "x-forwarded-for",
        "x-real-ip",
        "cf-connecting-ip",
        "true-client-ip",
    }
)


def scrub_event(event: dict, _hint: dict | None = None) -> dict:
    """Strip personal data from a Sentry event. Safe to call on any event shape."""
    request = event.get("request")
    if isinstance(request, dict):
        headers = request.get("headers")
        if isinstance(headers, dict):
            request["headers"] = {
                k: v for k, v in headers.items() if k.lower() not in _SENSITIVE_HEADERS
            }
        for key in ("cookies", "data", "env", "query_string"):
            request.pop(key, None)
        url = request.get("url")
        if isinstance(url, str) and "?" in url:
            # The query string carries the YouTube link the user pasted.
            request["url"] = url.split("?", 1)[0]

    user = event.get("user")
    if isinstance(user, dict):
        kept = {"id": user["id"]} if user.get("id") else {}
        event["user"] = kept

    event.pop("server_name", None)  # container hostnames are noise, not signal
    return event


def init_sentry(settings) -> bool:  # noqa: ANN001 - avoids importing config here
    """Start Sentry when DM_SENTRY_DSN is set. Returns whether it started."""
    if not settings.sentry_dsn:
        return False
    try:
        import sentry_sdk
    except ImportError:  # pragma: no cover - the package is a normal dependency
        log.warning("DM_SENTRY_DSN is set but sentry-sdk is not installed")
        return False

    sentry_sdk.init(
        dsn=settings.sentry_dsn,
        environment=settings.environment,
        traces_sample_rate=settings.sentry_traces_sample_rate,
        send_default_pii=False,
        max_request_body_size="never",
        before_send=scrub_event,
        before_send_transaction=scrub_event,
    )
    log.info("sentry enabled (environment=%s)", settings.environment)
    return True
