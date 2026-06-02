# `metadata_architect.parsers.schema_parser`

**Package:** `metadata_architect`  
**Module:** `parsers.schema_parser`  
**Source:** `src/metadata_architect/parsers/schema_parser.py`  
**Generated:** 2026-06-02  

> sqlglot-based DDL parser — extracts columns, PKs, FKs from 20+ SQL dialects.

## Overview

DDL → structured column metadata using sqlglot.

Supports: BigQuery, Snowflake, Redshift, Postgres, Databricks, DuckDB, MySQL, TSQL.
Returns a ParsedSchema containing a list of ColumnMetadata — the context packet
fed into the SoI Drafter in Phase 2.

## Classes

### `class ColumnMetadata`

---

### `class ParsedSchema`

---

### `class SchemaParseError(Exception)`

---

### `class SchemaParser`

Parse raw DDL strings into structured ParsedSchema objects.

Usage:
    parser = SchemaParser(dialect="snowflake")
    schema = parser.parse(ddl_string)

#### Methods

```python
def __init__(dialect: str = 'postgres') → None
```

**Parameters:**

- **`dialect`** `str` *(default: `'postgres'`)*

**Returns:** `None`

```python
def parse(ddl: str) → ParsedSchema
```

Parse a single CREATE TABLE / CREATE VIEW statement.

Raises SchemaParseError if the DDL cannot be parsed or contains no
recognisable table/view definition.

**Parameters:**

- **`ddl`** `str`

**Returns:** `ParsedSchema`

```python
def parse_many(ddl: str) → list[ParsedSchema]
```

Parse a DDL file containing multiple CREATE statements.
Returns one ParsedSchema per CREATE TABLE / CREATE VIEW.

**Parameters:**

- **`ddl`** `str`

**Returns:** `list[ParsedSchema]`

```python
def _extract(stmt: exp.Create, raw_ddl: str) → ParsedSchema
```

**Parameters:**

- **`stmt`** `exp.Create`
- **`raw_ddl`** `str`

**Returns:** `ParsedSchema`

```python
def _extract_table_name(stmt: exp.Create) → str
```

**Parameters:**

- **`stmt`** `exp.Create`

**Returns:** `str`

```python
def _extract_table_pks(table_def: exp.Schema) → list[str]
```

**Parameters:**

- **`table_def`** `exp.Schema`

**Returns:** `list[str]`

```python
def _extract_table_fks(table_def: exp.Schema) → list[dict]
```

**Parameters:**

- **`table_def`** `exp.Schema`

**Returns:** `list[dict]`

```python
def _extract_column(col_def: exp.ColumnDef, table_pks: list[str], fk_columns: set[str], fk_lookup: dict[str, dict]) → ColumnMetadata
```

**Parameters:**

- **`col_def`** `exp.ColumnDef`
- **`table_pks`** `list[str]`
- **`fk_columns`** `set[str]`
- **`fk_lookup`** `dict[str, dict]`

**Returns:** `ColumnMetadata`

```python
def _safe_type_str(col_def: exp.ColumnDef) → str
```

**Parameters:**

- **`col_def`** `exp.ColumnDef`

**Returns:** `str`

```python
def _extract_table_options(stmt: exp.Create) → dict
```

**Parameters:**

- **`stmt`** `exp.Create`

**Returns:** `dict`

---
