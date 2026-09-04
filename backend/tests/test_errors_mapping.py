"""A failure in our own infrastructure must not be blamed on the user's network.

Regression test for a real incident: Supabase's pooler closed a connection
partway through a download, and the user was told "Could not reach YouTube.
Check the connection and retry." over a fault that was entirely ours.
"""

import psycopg
import pytest
from sqlalchemy.exc import OperationalError

from app.core.errors import to_friendly


def _dropped_connection() -> OperationalError:
    """The exact shape seen in the wild."""
    inner = psycopg.OperationalError(
        "consuming input failed: server closed the connection unexpectedly"
    )
    return OperationalError("SELECT 1", {}, inner)


def test_dropped_database_connection_is_not_reported_as_a_youtube_problem() -> None:
    friendly = to_friendly(_dropped_connection())
    assert friendly.code == "server_error"
    assert "our side" in friendly.message
    assert "YouTube" not in friendly.message
    # The old message sent people to check their own internet. Never again.
    assert "check the connection" not in friendly.message.lower()


def test_database_error_wrapped_in_another_exception_is_still_ours() -> None:
    try:
        try:
            raise _dropped_connection()
        except OperationalError as exc:
            raise RuntimeError("job failed") from exc
    except RuntimeError as outer:
        assert to_friendly(outer).code == "server_error"


@pytest.mark.parametrize(
    ("message", "code"),
    [
        ("ERROR: unable to download webpage: getaddrinfo failed", "network"),
        ("ERROR: [youtube] abc: Private video", "private"),
        ("Sign in to confirm you're not a bot", "bot_check"),
        ("ERROR: Video unavailable", "unavailable"),
    ],
)
def test_genuine_download_failures_still_map_as_before(message: str, code: str) -> None:
    assert to_friendly(RuntimeError(message)).code == code
