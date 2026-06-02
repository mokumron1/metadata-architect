"""
Unit tests for SchemaParser.

Covers:
- Column extraction (name, type, nullable, PK, FK, default, constraints)
- Table-level PK and FK detection
- Multi-dialect support (Postgres, Snowflake, BigQuery)
- Error cases (empty DDL, multiple CREATE statements, unsupported dialect)
- parse_many() for multi-statement DDL files
"""

import pytest

from metadata_architect.parsers.schema_parser import (
    ColumnMetadata,
    ParsedSchema,
    SchemaParseError,
    SchemaParser,
)


# ---------------------------------------------------------------------------
# Postgres — basic revenue table
# ---------------------------------------------------------------------------

class TestPostgresRevenueTable:
    @pytest.fixture(autouse=True)
    def parsed(self, postgres_revenue_ddl: str) -> None:
        parser = SchemaParser(dialect="postgres")
        self.schema: ParsedSchema = parser.parse(postgres_revenue_ddl)

    def test_asset_name(self):
        assert "global_revenue_agg_v1" in self.schema.asset_name

    def test_column_count(self):
        assert len(self.schema.columns) == 8

    def test_primary_key_column(self):
        pk_cols = [c for c in self.schema.columns if c.is_primary_key]
        assert len(pk_cols) >= 1
        assert pk_cols[0].name == "id"

    def test_pk_not_nullable(self):
        id_col = next(c for c in self.schema.columns if c.name == "id")
        assert id_col.nullable is False

    def test_not_null_columns(self):
        not_null = {c.name for c in self.schema.columns if not c.nullable}
        assert "report_date" in not_null
        assert "region_code" in not_null
        assert "revenue" in not_null

    def test_nullable_columns(self):
        nullable = {c.name for c in self.schema.columns if c.nullable}
        assert "cost" in nullable

    def test_default_value_on_revenue(self):
        revenue_col = next(c for c in self.schema.columns if c.name == "revenue")
        assert revenue_col.default_value is not None
        assert "0" in revenue_col.default_value

    def test_default_value_on_created_at(self):
        col = next(c for c in self.schema.columns if c.name == "created_at")
        assert col.default_value is not None

    def test_no_foreign_keys(self):
        assert not any(c.is_foreign_key for c in self.schema.columns)

    def test_ddl_hash_is_sha256(self):
        assert len(self.schema.ddl_hash) == 64
        assert all(c in "0123456789abcdef" for c in self.schema.ddl_hash)

    def test_dialect_recorded(self):
        assert self.schema.dialect == "postgres"


# ---------------------------------------------------------------------------
# Snowflake — orders table with FK
# ---------------------------------------------------------------------------

class TestSnowflakeOrdersTable:
    @pytest.fixture(autouse=True)
    def parsed(self, snowflake_orders_ddl: str) -> None:
        parser = SchemaParser(dialect="snowflake")
        self.schema: ParsedSchema = parser.parse(snowflake_orders_ddl)

    def test_asset_name(self):
        assert "orders" in self.schema.asset_name.lower()

    def test_column_count(self):
        assert len(self.schema.columns) == 7

    def test_primary_key(self):
        pk_cols = [c for c in self.schema.columns if c.is_primary_key]
        assert len(pk_cols) >= 1
        assert pk_cols[0].name == "order_id"

    def test_foreign_key_detection(self):
        fk_cols = [c for c in self.schema.columns if c.is_foreign_key]
        assert len(fk_cols) >= 1
        fk_names = {c.name for c in fk_cols}
        assert "customer_id" in fk_names

    def test_fk_references(self):
        customer_col = next(c for c in self.schema.columns if c.name == "customer_id")
        assert customer_col.references is not None
        assert "customers" in customer_col.references.lower()

    def test_status_default(self):
        status_col = next(c for c in self.schema.columns if c.name == "status")
        assert status_col.default_value is not None

    def test_nullable_region(self):
        region_col = next(c for c in self.schema.columns if c.name == "region")
        assert region_col.nullable is True

    def test_table_fks_recorded(self):
        assert len(self.schema.foreign_keys) >= 1


# ---------------------------------------------------------------------------
# BigQuery — events table
# ---------------------------------------------------------------------------

class TestBigQueryEventsTable:
    @pytest.fixture(autouse=True)
    def parsed(self, bigquery_events_ddl: str) -> None:
        parser = SchemaParser(dialect="bigquery")
        self.schema: ParsedSchema = parser.parse(bigquery_events_ddl)

    def test_asset_name(self):
        assert "user_events" in self.schema.asset_name.lower()

    def test_column_count(self):
        assert len(self.schema.columns) == 7

    def test_nullable_json_column(self):
        props_col = next(c for c in self.schema.columns if c.name == "properties")
        assert props_col.nullable is True

    def test_not_null_required_columns(self):
        required = {"event_id", "user_id", "event_type", "event_ts"}
        not_null = {c.name for c in self.schema.columns if not c.nullable}
        assert required.issubset(not_null)


# ---------------------------------------------------------------------------
# Postgres FK table — order_lines with two FKs
# ---------------------------------------------------------------------------

class TestPostgresFKTable:
    @pytest.fixture(autouse=True)
    def parsed(self, postgres_fk_ddl: str) -> None:
        parser = SchemaParser(dialect="postgres")
        self.schema: ParsedSchema = parser.parse(postgres_fk_ddl)

    def test_two_foreign_keys(self):
        fk_cols = [c for c in self.schema.columns if c.is_foreign_key]
        assert len(fk_cols) == 2

    def test_fk_column_names(self):
        fk_names = {c.name for c in self.schema.columns if c.is_foreign_key}
        assert fk_names == {"order_id", "product_id"}

    def test_pk_is_line_id(self):
        pk_cols = [c for c in self.schema.columns if c.is_primary_key]
        assert any(c.name == "line_id" for c in pk_cols)

    def test_quantity_default(self):
        qty = next(c for c in self.schema.columns if c.name == "quantity")
        assert qty.default_value is not None

    def test_discount_nullable(self):
        discount = next(c for c in self.schema.columns if c.name == "discount")
        assert discount.nullable is True


# ---------------------------------------------------------------------------
# parse_many() — multi-statement DDL
# ---------------------------------------------------------------------------

class TestParseMany:
    def test_parses_two_tables(self, postgres_revenue_ddl, postgres_fk_ddl):
        combined = postgres_revenue_ddl + "\n\n" + postgres_fk_ddl
        parser = SchemaParser(dialect="postgres")
        schemas = parser.parse_many(combined)
        assert len(schemas) == 2
        names = {s.asset_name for s in schemas}
        assert any("global_revenue_agg_v1" in n for n in names)

    def test_empty_returns_empty_list(self):
        parser = SchemaParser(dialect="postgres")
        # A pure comment — no CREATE statements
        schemas = parser.parse_many("-- nothing here")
        assert schemas == []


# ---------------------------------------------------------------------------
# Error cases
# ---------------------------------------------------------------------------

class TestSchemaParserErrors:
    def test_empty_ddl_raises(self):
        parser = SchemaParser(dialect="postgres")
        with pytest.raises(SchemaParseError, match="Empty DDL"):
            parser.parse("   ")

    def test_no_create_statement_raises(self):
        parser = SchemaParser(dialect="postgres")
        with pytest.raises(SchemaParseError, match="No CREATE"):
            parser.parse("SELECT 1;")

    def test_multiple_creates_raises(self, postgres_revenue_ddl, postgres_fk_ddl):
        parser = SchemaParser(dialect="postgres")
        combined = postgres_revenue_ddl + "\n\n" + postgres_fk_ddl
        with pytest.raises(SchemaParseError, match="Multiple CREATE"):
            parser.parse(combined)

    def test_unsupported_dialect_raises(self):
        with pytest.raises(ValueError, match="Unsupported dialect"):
            SchemaParser(dialect="oracle")

    def test_postgres_alias_accepted(self):
        parser = SchemaParser(dialect="postgresql")
        assert parser.dialect == "postgresql"


# ---------------------------------------------------------------------------
# ColumnMetadata dataclass completeness
# ---------------------------------------------------------------------------

class TestColumnMetadataFields:
    def test_all_fields_present(self, postgres_revenue_ddl):
        parser = SchemaParser(dialect="postgres")
        schema = parser.parse(postgres_revenue_ddl)
        col = schema.columns[0]
        assert isinstance(col, ColumnMetadata)
        # All required fields exist (not AttributeError)
        _ = col.name, col.data_type, col.nullable, col.is_primary_key
        _ = col.is_foreign_key, col.references, col.default_value
        _ = col.constraints, col.comment

    def test_constraints_is_list(self, postgres_revenue_ddl):
        parser = SchemaParser(dialect="postgres")
        schema = parser.parse(postgres_revenue_ddl)
        for col in schema.columns:
            assert isinstance(col.constraints, list)
