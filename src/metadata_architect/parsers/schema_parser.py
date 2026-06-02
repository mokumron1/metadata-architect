"""
DDL → structured column metadata using sqlglot.

Supports: BigQuery, Snowflake, Redshift, Postgres, Databricks, DuckDB, MySQL, TSQL.
Returns a ParsedSchema containing a list of ColumnMetadata — the context packet
fed into the SoI Drafter in Phase 2.
"""

import hashlib
from dataclasses import dataclass, field

import sqlglot
import sqlglot.expressions as exp


@dataclass
class ColumnMetadata:
    name: str
    data_type: str
    nullable: bool
    is_primary_key: bool
    is_foreign_key: bool
    references: str | None        # "schema.table.column" if FK
    default_value: str | None
    constraints: list[str]        # e.g. ["UNIQUE", "CHECK (val > 0)"]
    comment: str | None           # inline COMMENT if present in DDL


@dataclass
class ParsedSchema:
    asset_name: str               # fully-qualified if schema prefix present
    dialect: str
    raw_ddl: str
    ddl_hash: str                 # SHA-256 hex
    columns: list[ColumnMetadata] = field(default_factory=list)
    primary_keys: list[str] = field(default_factory=list)   # table-level PKs
    foreign_keys: list[dict] = field(default_factory=list)  # table-level FKs
    table_options: dict = field(default_factory=dict)       # PARTITION BY, CLUSTER BY, etc.


class SchemaParseError(Exception):
    pass


class SchemaParser:
    """
    Parse raw DDL strings into structured ParsedSchema objects.

    Usage:
        parser = SchemaParser(dialect="snowflake")
        schema = parser.parse(ddl_string)
    """

    SUPPORTED_DIALECTS = {
        "bigquery", "snowflake", "redshift", "postgres", "postgresql",
        "databricks", "spark", "duckdb", "mysql", "tsql",
    }

    def __init__(self, dialect: str = "postgres") -> None:
        dialect = dialect.lower()
        if dialect not in self.SUPPORTED_DIALECTS:
            raise ValueError(
                f"Unsupported dialect '{dialect}'. Supported: {sorted(self.SUPPORTED_DIALECTS)}"
            )
        self.dialect = dialect

    def parse(self, ddl: str) -> ParsedSchema:
        """
        Parse a single CREATE TABLE / CREATE VIEW statement.

        Raises SchemaParseError if the DDL cannot be parsed or contains no
        recognisable table/view definition.
        """
        ddl = ddl.strip()
        if not ddl:
            raise SchemaParseError("Empty DDL string.")

        try:
            statements = sqlglot.parse(ddl, dialect=self.dialect, error_level=sqlglot.ErrorLevel.RAISE)
        except sqlglot.errors.ParseError as exc:
            raise SchemaParseError(f"sqlglot parse error: {exc}") from exc

        create_stmts = [s for s in statements if isinstance(s, exp.Create)]
        if not create_stmts:
            raise SchemaParseError("No CREATE TABLE / CREATE VIEW statement found in DDL.")
        if len(create_stmts) > 1:
            raise SchemaParseError(
                "Multiple CREATE statements found. Parse one asset at a time."
            )

        stmt = create_stmts[0]
        return self._extract(stmt, ddl)

    def parse_many(self, ddl: str) -> list[ParsedSchema]:
        """
        Parse a DDL file containing multiple CREATE statements.
        Returns one ParsedSchema per CREATE TABLE / CREATE VIEW.
        """
        try:
            statements = sqlglot.parse(ddl, dialect=self.dialect, error_level=sqlglot.ErrorLevel.RAISE)
        except sqlglot.errors.ParseError as exc:
            raise SchemaParseError(f"sqlglot parse error: {exc}") from exc

        results = []
        for stmt in statements:
            if isinstance(stmt, exp.Create):
                single_ddl = stmt.sql(dialect=self.dialect)
                results.append(self._extract(stmt, single_ddl))
        return results

    # ------------------------------------------------------------------
    # Internal extraction helpers
    # ------------------------------------------------------------------

    def _extract(self, stmt: exp.Create, raw_ddl: str) -> ParsedSchema:
        asset_name = self._extract_table_name(stmt)
        ddl_hash = hashlib.sha256(raw_ddl.encode()).hexdigest()

        schema = ParsedSchema(
            asset_name=asset_name,
            dialect=self.dialect,
            raw_ddl=raw_ddl,
            ddl_hash=ddl_hash,
        )

        table_def = stmt.find(exp.Schema)
        if table_def is None:
            # VIEW with no column list — record minimal metadata
            return schema

        # Collect table-level PK and FK constraints first so column-level
        # metadata can cross-reference them.
        schema.primary_keys = self._extract_table_pks(table_def)
        schema.foreign_keys = self._extract_table_fks(table_def)

        fk_columns: set[str] = {fk["column"] for fk in schema.foreign_keys}
        fk_lookup: dict[str, dict] = {fk["column"]: fk for fk in schema.foreign_keys}

        for col_def in table_def.find_all(exp.ColumnDef):
            col = self._extract_column(col_def, schema.primary_keys, fk_columns, fk_lookup)
            schema.columns.append(col)

        schema.table_options = self._extract_table_options(stmt)
        return schema

    def _extract_table_name(self, stmt: exp.Create) -> str:
        table = stmt.find(exp.Table)
        if table is None:
            return "unknown"
        parts = [p for p in [table.args.get("db"), table.args.get("name")] if p]
        return ".".join(str(p) for p in parts) if len(parts) > 1 else str(table.name)

    def _extract_table_pks(self, table_def: exp.Schema) -> list[str]:
        pks: list[str] = []
        for constraint in table_def.find_all(exp.PrimaryKeyColumnConstraint):
            # column-level PK — handled per-column
            pass
        for pk in table_def.find_all(exp.PrimaryKey):
            # table-level PK constraint
            for col in pk.find_all(exp.Column):
                pks.append(col.name)
        return pks

    def _extract_table_fks(self, table_def: exp.Schema) -> list[dict]:
        fks: list[dict] = []
        for fk in table_def.find_all(exp.ForeignKey):
            # fk.expressions → local column Identifiers
            local_cols = [e.name for e in fk.args.get("expressions", [])]
            ref = fk.args.get("reference")
            ref_table_name = ""
            ref_col_names: list[str] = []
            if ref:
                ref_schema_node = ref.find(exp.Schema)
                ref_table_node = ref.find(exp.Table)
                if ref_table_node:
                    ref_table_name = ref_table_node.name
                if ref_schema_node:
                    # Schema.expressions are the referenced column Identifiers
                    ref_col_names = [e.name for e in ref_schema_node.expressions]
            for col in local_cols:
                fks.append({
                    "column": col,
                    "references_table": ref_table_name,
                    "references_columns": ref_col_names,
                })
        return fks

    def _extract_column(
        self,
        col_def: exp.ColumnDef,
        table_pks: list[str],
        fk_columns: set[str],
        fk_lookup: dict[str, dict],
    ) -> ColumnMetadata:
        name = col_def.name
        data_type = self._safe_type_str(col_def)
        constraints: list[str] = []
        nullable = True
        is_primary_key = name in table_pks
        default_value: str | None = None
        comment: str | None = None
        references: str | None = None

        for constraint in col_def.find_all(exp.ColumnConstraint):
            kind = constraint.args.get("kind")
            if isinstance(kind, exp.NotNullColumnConstraint):
                nullable = False
            elif isinstance(kind, exp.PrimaryKeyColumnConstraint):
                is_primary_key = True
                nullable = False
            elif isinstance(kind, exp.UniqueColumnConstraint):
                constraints.append("UNIQUE")
            elif isinstance(kind, exp.DefaultColumnConstraint):
                default_value = kind.this.sql(dialect=self.dialect) if kind.this else None
            elif isinstance(kind, exp.CommentColumnConstraint):
                comment = str(kind.this).strip("'\"") if kind.this else None
            elif isinstance(kind, exp.CheckColumnConstraint):
                constraints.append(f"CHECK ({kind.this.sql(dialect=self.dialect)})")
            elif isinstance(kind, exp.GeneratedAsIdentityColumnConstraint):
                constraints.append("IDENTITY")

        if name in fk_columns:
            fk = fk_lookup[name]
            ref_cols = ", ".join(fk["references_columns"])
            references = f"{fk['references_table']}({ref_cols})"

        return ColumnMetadata(
            name=name,
            data_type=data_type,
            nullable=nullable,
            is_primary_key=is_primary_key,
            is_foreign_key=name in fk_columns,
            references=references,
            default_value=default_value,
            constraints=constraints,
            comment=comment,
        )

    def _safe_type_str(self, col_def: exp.ColumnDef) -> str:
        dtype = col_def.args.get("kind")
        if dtype is None:
            return "UNKNOWN"
        try:
            return dtype.sql(dialect=self.dialect).upper()
        except Exception:
            return str(dtype)

    def _extract_table_options(self, stmt: exp.Create) -> dict:
        options: dict = {}
        prop_block = stmt.args.get("properties")
        if prop_block is None:
            return options
        for prop in prop_block.find_all(exp.Property):
            key = prop.name or prop.__class__.__name__
            val = prop.args.get("value")
            options[key] = val.sql(dialect=self.dialect) if val else None
        return options
