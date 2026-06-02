"""
Documentation generator for the Metadata Architect project.

Reads every substantive Python source file, extracts module docstring,
classes, functions, and constants, then writes:
  docs/reference/<module_path>.md
  docs/reference/<module_path>.html

Run from the project root:
  python scripts/generate_docs.py
"""

from __future__ import annotations

import ast
import html
import os
import re
import textwrap
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

ROOT = Path(__file__).parent.parent
SRC_ROOT = ROOT / "src" / "metadata_architect"
DOCS_OUT = ROOT / "docs" / "reference"

# Modules with only trivial content (empty __init__.py files)
_SKIP_EMPTY = True

PROJECT_VERSION = "0.1.0"
PROJECT_NAME = "Metadata Architect AI Agent"
GENERATED_AT = datetime.now(timezone.utc).strftime("%Y-%m-%d")

# ---------------------------------------------------------------------------
# Module metadata registry — human descriptions per module
# ---------------------------------------------------------------------------

MODULE_DESCRIPTIONS: dict[str, str] = {
    "config": "Application settings loaded from environment variables via pydantic-settings.",
    "database": "Async SQLAlchemy engine, session factory, and FastAPI dependency for DB access.",
    "agents.claude_client": "Low-level Anthropic API wrapper with prompt caching and exponential-backoff retry.",
    "agents.jargon_scrubber": "Claude-powered ISO 24495-1 plain-language violation detector.",
    "agents.reading_level": "Flesch-Kincaid reading-level validator with Claude semantic fallback.",
    "agents.soi_drafter": "Primary AI agent that drafts Statements of Intent from DDL schemas.",
    "api.main": "FastAPI application factory — middleware, routers, startup hooks.",
    "api.routers.assets": "Asset Registry CRUD endpoints (create, read, update, delete, parse, transition).",
    "api.routers.batch": "Batch ingestion endpoint — register up to 200 assets in one request.",
    "api.routers.gates": "CI/CD gate endpoints: Context-First (Gate 1) and Jargon Scrubber (Gate 2).",
    "api.routers.workflows": "SME HITL review portal — approve, edit, reject, list, and get workflows.",
    "auth.tokens": "JWT one-time review token creation and verification for SME email links.",
    "catalog.push_adapter": "DataHub GMS and Collibra REST adapters for post-approval metadata push.",
    "middleware.rate_limit": "Sliding-window rate limiter (per API key) for the CI/CD gate endpoints.",
    "middleware.request_id": "X-Request-ID propagation middleware with structlog context binding.",
    "models.asset_registry": "SQLAlchemy ORM models: Asset, SoIDraft, SmeWorkflow, TdkScoreLog and state machine.",
    "notifications.base": "Abstract notification adapter interface, payload schema, and type enum.",
    "notifications.dispatcher": "Concurrent notification dispatcher — sends to all enabled adapters.",
    "notifications.sendgrid_adapter": "SendGrid HTML email adapter for Verification Pulse and Orphan Notices.",
    "notifications.slack_adapter": "Slack Block Kit adapter with TDK score bar visualisation.",
    "observability.logging": "Structured logging setup — JSON (production) or console (development).",
    "observability.tracing": "OpenTelemetry TracerProvider setup with OTLP/gRPC export and no-op fallback.",
    "parsers.schema_parser": "sqlglot-based DDL parser — extracts columns, PKs, FKs from 20+ SQL dialects.",
    "policy.emitter": "YAML Policy-as-Code emitter (ruamel.yaml) and async MinIO uploader.",
    "prompts.jargon_scrubber": "System prompt blocks for the ISO 24495-1 jargon scrubber agent.",
    "prompts.reading_level": "System prompt blocks for the reading-level semantic validation agent.",
    "prompts.soi_drafter": "Cacheable system prompt blocks and user template for the SoI drafter agent.",
    "schemas.asset_schemas": "Pydantic request/response schemas for the Asset Registry API.",
    "scoring.tdk_calculator": "TDK composite score calculator: clarity (60%) × ownership (40%) formula.",
    "workers.celery_app": "Celery application factory — queues, Beat schedule, and worker settings.",
    "workers.tasks": "Celery tasks: draft pipeline, SLA monitor, orphan notice, edit analysis.",
}


# ---------------------------------------------------------------------------
# AST extraction
# ---------------------------------------------------------------------------

@dataclass
class ParamInfo:
    name: str
    annotation: str = ""
    default: str = ""


@dataclass
class FuncInfo:
    name: str
    docstring: str
    params: list[ParamInfo] = field(default_factory=list)
    returns: str = ""
    is_async: bool = False
    decorators: list[str] = field(default_factory=list)
    lineno: int = 0


@dataclass
class ClassInfo:
    name: str
    docstring: str
    bases: list[str] = field(default_factory=list)
    methods: list[FuncInfo] = field(default_factory=list)
    lineno: int = 0


@dataclass
class ConstantInfo:
    name: str
    value_repr: str
    lineno: int = 0


@dataclass
class ModuleDoc:
    module_path: str          # e.g. "agents.claude_client"
    file_path: Path
    docstring: str
    description: str          # from MODULE_DESCRIPTIONS registry
    classes: list[ClassInfo] = field(default_factory=list)
    functions: list[FuncInfo] = field(default_factory=list)
    constants: list[ConstantInfo] = field(default_factory=list)
    imports: list[str] = field(default_factory=list)


def _ann_to_str(node) -> str:
    if node is None:
        return ""
    return ast.unparse(node)


def _extract_func(node: ast.FunctionDef | ast.AsyncFunctionDef) -> FuncInfo:
    doc = ast.get_docstring(node) or ""
    params = []
    args = node.args
    # Positional args
    for i, arg in enumerate(args.args):
        if arg.arg == "self" or arg.arg == "cls":
            continue
        ann = _ann_to_str(arg.annotation)
        # Default: args.defaults is aligned to the end of args.args
        offset = len(args.args) - len(args.defaults)
        default = ""
        if i >= offset:
            default = ast.unparse(args.defaults[i - offset])
        params.append(ParamInfo(name=arg.arg, annotation=ann, default=default))
    # *args
    if args.vararg:
        params.append(ParamInfo(name=f"*{args.vararg.arg}", annotation=_ann_to_str(args.vararg.annotation)))
    # keyword-only args
    for kw, dflt in zip(args.kwonlyargs, args.kw_defaults):
        params.append(ParamInfo(
            name=kw.arg,
            annotation=_ann_to_str(kw.annotation),
            default=ast.unparse(dflt) if dflt else "",
        ))
    # **kwargs
    if args.kwarg:
        params.append(ParamInfo(name=f"**{args.kwarg.arg}", annotation=_ann_to_str(args.kwarg.annotation)))

    returns = _ann_to_str(node.returns)
    decorators = [ast.unparse(d) for d in node.decorator_list]
    return FuncInfo(
        name=node.name,
        docstring=doc,
        params=params,
        returns=returns,
        is_async=isinstance(node, ast.AsyncFunctionDef),
        decorators=decorators,
        lineno=node.lineno,
    )


def _extract_class(node: ast.ClassDef) -> ClassInfo:
    doc = ast.get_docstring(node) or ""
    bases = [ast.unparse(b) for b in node.bases]
    methods = []
    for item in node.body:
        if isinstance(item, (ast.FunctionDef, ast.AsyncFunctionDef)):
            if not item.name.startswith("__") or item.name in ("__init__", "__call__"):
                methods.append(_extract_func(item))
    return ClassInfo(name=node.name, docstring=doc, bases=bases, methods=methods, lineno=node.lineno)


def parse_module(file_path: Path, module_path: str) -> ModuleDoc | None:
    source = file_path.read_text(encoding="utf-8")
    try:
        tree = ast.parse(source)
    except SyntaxError:
        return None

    doc = ast.get_docstring(tree) or ""
    classes: list[ClassInfo] = []
    functions: list[FuncInfo] = []
    constants: list[ConstantInfo] = []
    imports: list[str] = []

    for node in tree.body:
        if isinstance(node, ast.ClassDef):
            classes.append(_extract_class(node))
        elif isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            if not node.name.startswith("_"):
                functions.append(_extract_func(node))
        elif isinstance(node, ast.Assign):
            for target in node.targets:
                if isinstance(target, ast.Name) and target.id.isupper():
                    try:
                        val = ast.unparse(node.value)
                        if len(val) > 120:
                            val = val[:117] + "..."
                        constants.append(ConstantInfo(name=target.id, value_repr=val, lineno=node.lineno))
                    except Exception:
                        pass
        elif isinstance(node, (ast.Import, ast.ImportFrom)):
            imports.append(ast.unparse(node))

    if _SKIP_EMPTY and not doc and not classes and not functions and not constants:
        return None

    description = MODULE_DESCRIPTIONS.get(module_path, "")
    return ModuleDoc(
        module_path=module_path,
        file_path=file_path,
        docstring=doc,
        description=description,
        classes=classes,
        functions=functions,
        constants=constants,
        imports=imports,
    )


# ---------------------------------------------------------------------------
# Markdown renderer
# ---------------------------------------------------------------------------

def _md_escape(text: str) -> str:
    return text.replace("|", "\\|").replace("\n", " ")


def render_markdown(mod: ModuleDoc) -> str:
    lines: list[str] = []
    title = f"`metadata_architect.{mod.module_path}`"
    lines.append(f"# {title}\n")
    lines.append(f"**Package:** `metadata_architect`  ")
    lines.append(f"**Module:** `{mod.module_path}`  ")
    lines.append(f"**Source:** `src/metadata_architect/{mod.module_path.replace('.', '/')}.py`  ")
    lines.append(f"**Generated:** {GENERATED_AT}  \n")

    if mod.description:
        lines.append(f"> {mod.description}\n")

    if mod.docstring:
        lines.append("## Overview\n")
        lines.append(mod.docstring + "\n")

    if mod.constants:
        lines.append("## Constants\n")
        lines.append("| Name | Value |")
        lines.append("|---|---|")
        for c in mod.constants:
            lines.append(f"| `{c.name}` | `{_md_escape(c.value_repr)}` |")
        lines.append("")

    if mod.classes:
        lines.append("## Classes\n")
        for cls in mod.classes:
            bases_str = f"({', '.join(cls.bases)})" if cls.bases else ""
            lines.append(f"### `class {cls.name}{bases_str}`\n")
            if cls.docstring:
                lines.append(cls.docstring + "\n")
            if cls.methods:
                lines.append("#### Methods\n")
                for m in cls.methods:
                    _render_func_md(lines, m, indent="")
            lines.append("---\n")

    if mod.functions:
        lines.append("## Functions\n")
        for fn in mod.functions:
            _render_func_md(lines, fn, indent="")

    return "\n".join(lines)


def _render_func_md(lines: list[str], fn: FuncInfo, indent: str) -> None:
    prefix = "async " if fn.is_async else ""
    params_str = ", ".join(
        f"{p.name}: {p.annotation}" + (f" = {p.default}" if p.default else "")
        if p.annotation else p.name + (f" = {p.default}" if p.default else "")
        for p in fn.params
    )
    ret = f" → {fn.returns}" if fn.returns else ""
    sig = f"{prefix}def {fn.name}({params_str}){ret}"

    for dec in fn.decorators:
        lines.append(f"```\n@{dec}\n```")
    lines.append(f"```python\n{sig}\n```\n")
    if fn.docstring:
        lines.append(fn.docstring + "\n")

    if fn.params:
        lines.append("**Parameters:**\n")
        for p in fn.params:
            ann = f" `{p.annotation}`" if p.annotation else ""
            dflt = f" *(default: `{p.default}`)*" if p.default else ""
            lines.append(f"- **`{p.name}`**{ann}{dflt}")
        lines.append("")

    if fn.returns:
        lines.append(f"**Returns:** `{fn.returns}`\n")


# ---------------------------------------------------------------------------
# HTML renderer
# ---------------------------------------------------------------------------

_HTML_TEMPLATE = """\
<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="UTF-8">
  <meta name="viewport" content="width=device-width, initial-scale=1.0">
  <title>{title} — {project}</title>
  <style>
    :root {{
      --bg: #0f1117;
      --surface: #1a1d2e;
      --surface2: #252840;
      --accent: #7c6af7;
      --accent2: #56c2e6;
      --text: #e2e4f0;
      --muted: #8b90b0;
      --code-bg: #12141f;
      --border: #2e3157;
      --green: #4ade80;
      --yellow: #facc15;
    }}
    * {{ box-sizing: border-box; margin: 0; padding: 0; }}
    body {{
      background: var(--bg);
      color: var(--text);
      font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, sans-serif;
      font-size: 15px;
      line-height: 1.7;
    }}
    a {{ color: var(--accent2); text-decoration: none; }}
    a:hover {{ text-decoration: underline; }}

    /* Layout */
    .page {{ display: flex; min-height: 100vh; }}
    nav {{
      width: 260px;
      min-width: 260px;
      background: var(--surface);
      border-right: 1px solid var(--border);
      padding: 24px 0;
      position: sticky;
      top: 0;
      height: 100vh;
      overflow-y: auto;
    }}
    nav .logo {{
      padding: 0 20px 20px;
      border-bottom: 1px solid var(--border);
      margin-bottom: 16px;
    }}
    nav .logo h2 {{ font-size: 14px; color: var(--accent); font-weight: 700; }}
    nav .logo p {{ font-size: 11px; color: var(--muted); margin-top: 2px; }}
    nav ul {{ list-style: none; padding: 0 8px; }}
    nav ul li a {{
      display: block;
      padding: 5px 12px;
      border-radius: 6px;
      font-size: 13px;
      color: var(--muted);
    }}
    nav ul li a:hover, nav ul li a.active {{
      background: var(--surface2);
      color: var(--text);
      text-decoration: none;
    }}
    nav .nav-group {{ padding: 12px 12px 4px; font-size: 11px; font-weight: 700;
                      color: var(--accent); text-transform: uppercase; letter-spacing: 0.08em; }}

    main {{
      flex: 1;
      padding: 48px 56px;
      max-width: 960px;
    }}

    /* Header */
    .mod-header {{ margin-bottom: 40px; }}
    .mod-header h1 {{ font-size: 26px; font-weight: 700; color: var(--text); margin-bottom: 8px; }}
    .mod-header .module-name {{
      font-family: "SF Mono", "Fira Code", monospace;
      font-size: 13px;
      background: var(--surface2);
      border: 1px solid var(--border);
      border-radius: 6px;
      padding: 2px 8px;
      color: var(--accent2);
    }}
    .meta {{ font-size: 13px; color: var(--muted); margin-top: 10px; }}
    .meta span {{ margin-right: 20px; }}
    .meta .label {{ color: var(--muted); }}
    .meta .val {{ color: var(--text); font-family: monospace; }}
    .description-box {{
      background: var(--surface);
      border-left: 3px solid var(--accent);
      border-radius: 0 8px 8px 0;
      padding: 14px 20px;
      margin: 20px 0;
      font-size: 14px;
      color: var(--text);
    }}

    /* Sections */
    h2 {{
      font-size: 19px;
      font-weight: 600;
      color: var(--text);
      margin: 40px 0 16px;
      padding-bottom: 8px;
      border-bottom: 1px solid var(--border);
    }}
    h3 {{
      font-size: 16px;
      font-weight: 600;
      color: var(--accent2);
      margin: 28px 0 10px;
    }}
    h4 {{ font-size: 14px; font-weight: 600; color: var(--muted); margin: 20px 0 8px; text-transform: uppercase; letter-spacing: 0.06em; }}

    /* Code */
    pre {{
      background: var(--code-bg);
      border: 1px solid var(--border);
      border-radius: 8px;
      padding: 16px 20px;
      overflow-x: auto;
      font-family: "SF Mono", "Fira Code", "Cascadia Code", monospace;
      font-size: 13px;
      line-height: 1.6;
      color: var(--accent2);
      margin: 8px 0 16px;
    }}
    code {{
      background: var(--code-bg);
      border: 1px solid var(--border);
      border-radius: 4px;
      padding: 1px 6px;
      font-family: "SF Mono", "Fira Code", monospace;
      font-size: 12px;
      color: var(--accent2);
    }}
    pre code {{ background: none; border: none; padding: 0; font-size: inherit; }}

    /* Overview */
    .overview {{
      background: var(--surface);
      border-radius: 8px;
      padding: 20px 24px;
      margin-bottom: 16px;
      white-space: pre-wrap;
      font-size: 14px;
      color: var(--muted);
      border: 1px solid var(--border);
    }}

    /* Class card */
    .class-card {{
      background: var(--surface);
      border: 1px solid var(--border);
      border-radius: 10px;
      padding: 24px 28px;
      margin-bottom: 24px;
    }}
    .class-card h3 {{ margin-top: 0; }}
    .class-bases {{
      font-size: 12px;
      color: var(--muted);
      margin-bottom: 10px;
    }}
    .class-doc {{
      font-size: 14px;
      color: var(--muted);
      margin-bottom: 20px;
      white-space: pre-wrap;
    }}

    /* Method */
    .method {{
      border-top: 1px solid var(--border);
      padding-top: 16px;
      margin-top: 16px;
    }}
    .method-sig {{
      font-family: "SF Mono", "Fira Code", monospace;
      font-size: 13px;
      color: var(--accent2);
    }}
    .async-badge {{
      display: inline-block;
      background: #1e3a5f;
      color: #60b4f0;
      font-size: 10px;
      font-weight: 700;
      border-radius: 4px;
      padding: 1px 6px;
      margin-right: 6px;
      vertical-align: middle;
    }}
    .method-doc {{ font-size: 13px; color: var(--muted); margin: 8px 0; white-space: pre-wrap; }}

    /* Params table */
    .params-table {{ width: 100%; border-collapse: collapse; margin: 10px 0 16px; font-size: 13px; }}
    .params-table th {{
      text-align: left;
      padding: 6px 12px;
      background: var(--surface2);
      color: var(--muted);
      font-size: 11px;
      font-weight: 700;
      text-transform: uppercase;
      letter-spacing: 0.05em;
    }}
    .params-table td {{ padding: 7px 12px; border-bottom: 1px solid var(--border); vertical-align: top; }}
    .params-table tr:last-child td {{ border-bottom: none; }}
    .param-name {{ color: var(--accent2); font-family: monospace; }}
    .param-type {{ color: var(--green); font-family: monospace; font-size: 12px; }}
    .param-default {{ color: var(--yellow); font-family: monospace; font-size: 12px; }}
    .returns-badge {{
      display: inline-block;
      background: #1a3a2a;
      color: var(--green);
      border-radius: 4px;
      padding: 2px 8px;
      font-family: monospace;
      font-size: 12px;
      margin-top: 4px;
    }}

    /* Constants table */
    .const-table {{ width: 100%; border-collapse: collapse; margin: 0 0 24px; font-size: 13px; }}
    .const-table th {{
      text-align: left; padding: 8px 14px;
      background: var(--surface2); color: var(--muted);
      font-size: 11px; font-weight: 700; text-transform: uppercase; letter-spacing: 0.05em;
    }}
    .const-table td {{ padding: 8px 14px; border-bottom: 1px solid var(--border); }}
    .const-table tr:last-child td {{ border-bottom: none; }}

    /* Function card */
    .func-card {{
      border: 1px solid var(--border);
      border-radius: 8px;
      padding: 18px 22px;
      margin-bottom: 16px;
    }}
    .func-card h3 {{ margin-top: 0; font-size: 15px; }}

    /* Decorator */
    .decorator {{ color: #c084fc; font-size: 12px; font-family: monospace; }}

    /* Footer */
    footer {{
      margin-top: 60px;
      padding-top: 20px;
      border-top: 1px solid var(--border);
      font-size: 12px;
      color: var(--muted);
    }}
  </style>
</head>
<body>
<div class="page">
{nav}
<main>
{content}
<footer>
  Generated by <strong>generate_docs.py</strong> · {project} v{version} · {date}
</footer>
</main>
</div>
</body>
</html>
"""


def _h(text: str) -> str:
    """HTML-escape text."""
    return html.escape(str(text))


def _code(text: str) -> str:
    return f"<code>{_h(text)}</code>"


def _pre(text: str) -> str:
    return f"<pre><code>{_h(text)}</code></pre>"


def render_html_content(mod: ModuleDoc) -> str:
    parts: list[str] = []

    # Header
    parts.append('<div class="mod-header">')
    parts.append(f'<h1><span class="module-name">metadata_architect.{_h(mod.module_path)}</span></h1>')
    parts.append(f'<div class="meta">')
    parts.append(f'<span><span class="label">Source: </span><span class="val">src/metadata_architect/{_h(mod.module_path.replace(".", "/"))}.py</span></span>')
    parts.append(f'<span><span class="label">Generated: </span><span class="val">{GENERATED_AT}</span></span>')
    parts.append('</div>')
    if mod.description:
        parts.append(f'<div class="description-box">{_h(mod.description)}</div>')
    parts.append('</div>')

    if mod.docstring:
        parts.append('<h2>Overview</h2>')
        parts.append(f'<div class="overview">{_h(mod.docstring)}</div>')

    if mod.constants:
        parts.append('<h2>Constants</h2>')
        parts.append('<table class="const-table"><thead><tr><th>Name</th><th>Value</th></tr></thead><tbody>')
        for c in mod.constants:
            parts.append(f'<tr><td>{_code(c.name)}</td><td>{_code(c.value_repr)}</td></tr>')
        parts.append('</tbody></table>')

    if mod.classes:
        parts.append('<h2>Classes</h2>')
        for cls in mod.classes:
            parts.append('<div class="class-card">')
            bases_str = f"({', '.join(cls.bases)})" if cls.bases else ""
            parts.append(f'<h3>{_code(f"class {cls.name}{bases_str}")}</h3>')
            if cls.bases:
                parts.append(f'<div class="class-bases">Inherits from: {", ".join(_code(b) for b in cls.bases)}</div>')
            if cls.docstring:
                parts.append(f'<div class="class-doc">{_h(cls.docstring)}</div>')
            if cls.methods:
                parts.append('<h4>Methods</h4>')
                for m in cls.methods:
                    parts.extend(_render_func_html(m))
            parts.append('</div>')

    if mod.functions:
        parts.append('<h2>Functions</h2>')
        for fn in mod.functions:
            parts.append('<div class="func-card">')
            parts.extend(_render_func_html(fn))
            parts.append('</div>')

    return "\n".join(parts)


def _render_func_html(fn: FuncInfo) -> list[str]:
    parts: list[str] = []
    badge = '<span class="async-badge">async</span>' if fn.is_async else ''
    params_str = ", ".join(
        f"{p.name}: {p.annotation}" + (f" = {p.default}" if p.default else "")
        if p.annotation else p.name + (f" = {p.default}" if p.default else "")
        for p in fn.params
    )
    ret = f" → {fn.returns}" if fn.returns else ""
    sig = f"def {fn.name}({params_str}){ret}"

    for dec in fn.decorators:
        parts.append(f'<div class="decorator">@{_h(dec)}</div>')

    parts.append(f'<div class="method">')
    parts.append(f'<div class="method-sig">{badge}{_code(sig)}</div>')
    if fn.docstring:
        parts.append(f'<div class="method-doc">{_h(fn.docstring)}</div>')

    if fn.params:
        parts.append('<table class="params-table"><thead><tr><th>Parameter</th><th>Type</th><th>Default</th></tr></thead><tbody>')
        for p in fn.params:
            parts.append(
                f'<tr>'
                f'<td><span class="param-name">{_h(p.name)}</span></td>'
                f'<td><span class="param-type">{_h(p.annotation)}</span></td>'
                f'<td><span class="param-default">{_h(p.default)}</span></td>'
                f'</tr>'
            )
        parts.append('</tbody></table>')

    if fn.returns:
        parts.append(f'<div>Returns: <span class="returns-badge">{_h(fn.returns)}</span></div>')

    parts.append('</div>')
    return parts


# ---------------------------------------------------------------------------
# Navigation builder
# ---------------------------------------------------------------------------

_NAV_GROUPS: dict[str, list[str]] = {
    "Core": ["config", "database"],
    "API": ["api.main", "api.routers.assets", "api.routers.batch", "api.routers.gates", "api.routers.workflows"],
    "Agents": ["agents.claude_client", "agents.soi_drafter", "agents.jargon_scrubber", "agents.reading_level"],
    "Intelligence": ["scoring.tdk_calculator", "parsers.schema_parser", "policy.emitter"],
    "Prompts": ["prompts.soi_drafter", "prompts.jargon_scrubber", "prompts.reading_level"],
    "Workflow": ["auth.tokens", "models.asset_registry", "schemas.asset_schemas"],
    "Notifications": ["notifications.base", "notifications.dispatcher", "notifications.sendgrid_adapter", "notifications.slack_adapter"],
    "Workers": ["workers.celery_app", "workers.tasks"],
    "Catalog": ["catalog.push_adapter"],
    "Observability": ["observability.tracing", "observability.logging"],
    "Middleware": ["middleware.request_id", "middleware.rate_limit"],
}


def build_nav(current_module: str) -> str:
    parts = ['<nav>']
    parts.append('<div class="logo">')
    parts.append(f'<h2>{html.escape(PROJECT_NAME)}</h2>')
    parts.append(f'<p>API Reference v{PROJECT_VERSION}</p>')
    parts.append('</div>')
    parts.append('<ul>')

    for group, modules in _NAV_GROUPS.items():
        parts.append(f'<li><div class="nav-group">{_h(group)}</div></li>')
        for mod in modules:
            active = 'active' if mod == current_module else ''
            label = mod.split(".")[-1].replace("_", " ")
            href = f"{mod}.html"
            parts.append(f'<li><a href="{href}" class="{active}">{_h(label)}</a></li>')

    parts.append('</ul></nav>')
    return "\n".join(parts)


# ---------------------------------------------------------------------------
# Index page
# ---------------------------------------------------------------------------

def render_index(all_mods: list[ModuleDoc]) -> tuple[str, str]:
    """Returns (markdown, html) for the index page."""
    # Markdown index
    md_lines = [
        f"# {PROJECT_NAME} — API Reference\n",
        f"**Version:** {PROJECT_VERSION}  ",
        f"**Generated:** {GENERATED_AT}  \n",
        "Complete reference documentation for all Python modules in the Metadata Architect AI Agent.\n",
        "## Module Index\n",
    ]
    for group, modules in _NAV_GROUPS.items():
        md_lines.append(f"### {group}\n")
        md_lines.append("| Module | Description |")
        md_lines.append("|---|---|")
        for mod_path in modules:
            desc = MODULE_DESCRIPTIONS.get(mod_path, "")
            md_lines.append(f"| [`{mod_path}`]({mod_path}.md) | {desc} |")
        md_lines.append("")

    md = "\n".join(md_lines)

    # HTML index
    rows = []
    for group, modules in _NAV_GROUPS.items():
        for mod_path in modules:
            desc = MODULE_DESCRIPTIONS.get(mod_path, "")
            rows.append(
                f'<tr>'
                f'<td><a href="{mod_path}.html"><code>metadata_architect.{_h(mod_path)}</code></a></td>'
                f'<td>{_h(group)}</td>'
                f'<td>{_h(desc)}</td>'
                f'</tr>'
            )

    content = f"""
<div class="mod-header">
  <h1>API Reference</h1>
  <div class="meta">
    <span><span class="label">Project: </span><span class="val">{_h(PROJECT_NAME)}</span></span>
    <span><span class="label">Version: </span><span class="val">{PROJECT_VERSION}</span></span>
    <span><span class="label">Generated: </span><span class="val">{GENERATED_AT}</span></span>
  </div>
  <div class="description-box">
    Complete reference documentation for all Python modules in the Metadata Architect AI Agent.
    The system eliminates the "Translation Tax" by auto-drafting 80% of data asset metadata,
    leaving SMEs as Context Editors rather than Data Janitors.
  </div>
</div>
<h2>Module Index</h2>
<table class="const-table">
<thead><tr><th>Module</th><th>Package</th><th>Description</th></tr></thead>
<tbody>{"".join(rows)}</tbody>
</table>
"""
    nav = build_nav("")
    html_out = _HTML_TEMPLATE.format(
        title="API Reference",
        project=PROJECT_NAME,
        version=PROJECT_VERSION,
        date=GENERATED_AT,
        nav=nav,
        content=content,
    )
    return md, html_out


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def _module_path_from_file(file_path: Path) -> str:
    rel = file_path.relative_to(SRC_ROOT)
    parts = list(rel.with_suffix("").parts)
    return ".".join(parts)


def main() -> None:
    DOCS_OUT.mkdir(parents=True, exist_ok=True)

    all_mods: list[ModuleDoc] = []

    for py_file in sorted(SRC_ROOT.rglob("*.py")):
        if py_file.name == "__init__.py":
            continue
        mod_path = _module_path_from_file(py_file)
        mod = parse_module(py_file, mod_path)
        if mod is None:
            continue
        all_mods.append(mod)

    print(f"Parsed {len(all_mods)} modules.")

    for mod in all_mods:
        # Ensure sub-directories exist
        out_dir = DOCS_OUT / Path(*mod.module_path.split(".")[:-1]) if "." in mod.module_path else DOCS_OUT
        out_dir.mkdir(parents=True, exist_ok=True)
        safe_name = mod.module_path  # use dots as-is for flat naming

        # Markdown
        md_content = render_markdown(mod)
        md_path = DOCS_OUT / f"{safe_name}.md"
        md_path.write_text(md_content, encoding="utf-8")

        # HTML
        nav = build_nav(mod.module_path)
        html_content = render_html_content(mod)
        full_html = _HTML_TEMPLATE.format(
            title=f"metadata_architect.{mod.module_path}",
            project=PROJECT_NAME,
            version=PROJECT_VERSION,
            date=GENERATED_AT,
            nav=nav,
            content=html_content,
        )
        html_path = DOCS_OUT / f"{safe_name}.html"
        html_path.write_text(full_html, encoding="utf-8")

        print(f"  OK  {mod.module_path}")

    # Index
    idx_md, idx_html = render_index(all_mods)
    (DOCS_OUT / "index.md").write_text(idx_md, encoding="utf-8")
    (DOCS_OUT / "index.html").write_text(idx_html, encoding="utf-8")
    print(f"  OK  index")
    print(f"\nDone. Output: {DOCS_OUT}")


if __name__ == "__main__":
    main()
