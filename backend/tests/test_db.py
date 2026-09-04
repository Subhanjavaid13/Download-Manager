from app.db import normalize_url


def test_supabase_urls_are_normalized_for_psycopg3() -> None:
    assert (
        normalize_url("postgresql://postgres:pw@db.abc.supabase.co:5432/postgres")
        == "postgresql+psycopg://postgres:pw@db.abc.supabase.co:5432/postgres"
    )
    assert normalize_url("postgres://u:p@h/db") == "postgresql+psycopg://u:p@h/db"
    assert normalize_url("postgresql+psycopg://u:p@h/db") == "postgresql+psycopg://u:p@h/db"
    assert normalize_url("sqlite:///./dm.db") == "sqlite:///./dm.db"
