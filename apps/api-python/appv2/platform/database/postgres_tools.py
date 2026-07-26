from __future__ import annotations

from sqlalchemy.engine import URL, make_url


def postgres_cli_connection(database_url: str) -> tuple[str, dict[str, str]]:
    """Return a password-free libpq URL and the minimum secret environment."""
    url = make_url(database_url)
    if url.get_backend_name() != "postgresql":
        raise ValueError("PostgreSQL command-line tools require a PostgreSQL URL")
    password = url.password
    safe_url = URL.create(
        drivername="postgresql",
        username=url.username,
        host=url.host,
        port=url.port,
        database=url.database,
        query=url.query,
    ).render_as_string(hide_password=False)
    environment = {"PGPASSWORD": password} if password is not None else {}
    return safe_url, environment
