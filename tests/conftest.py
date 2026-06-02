from pathlib import Path
import pytest


FIXTURE_DDL_DIR = Path(__file__).parent / "fixtures" / "ddl"


def load_ddl(filename: str) -> str:
    return (FIXTURE_DDL_DIR / filename).read_text(encoding="utf-8")


@pytest.fixture
def postgres_revenue_ddl() -> str:
    return load_ddl("postgres_revenue.sql")


@pytest.fixture
def snowflake_orders_ddl() -> str:
    return load_ddl("snowflake_orders.sql")


@pytest.fixture
def bigquery_events_ddl() -> str:
    return load_ddl("bigquery_events.sql")


@pytest.fixture
def postgres_fk_ddl() -> str:
    return load_ddl("postgres_fk_table.sql")
