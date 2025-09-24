import re
from typing import Any, Dict, Tuple, Optional
from jinja2 import Environment, BaseLoader, StrictUndefined, pass_context

# ---------- config you can tweak ----------
ALLOWED_SORT_FIELDS = {"label", "title", "created_at", "age"}
ALLOWED_SORT_DIRS = {"ASC", "DESC"}

# Reject obvious mutators after rendering (belt & suspenders)
MUTATING_TOKENS = re.compile(r"\b(CREATE|MERGE|DELETE|SET|REMOVE|DROP|ALTER|CALL)\b", re.I)

# ---------- internal: preprocesser to allow {% if $search %} ----------
TAG_RE = re.compile(r"({%.*?%}|{{.*?}})", re.S)
DOLLAR_VAR_RE = re.compile(r"\$(\w+)")  # $search -> search


def _strip_dollar_in_jinja_tags(template: str) -> str:
    """
    Replace $var with var *inside Jinja tags only*,
    leaving raw text (e.g., '$search' in Cypher) untouched.
    """
    out = []
    last = 0
    for m in TAG_RE.finditer(template):
        out.append(template[last : m.start()])
        tag = m.group(1)
        tag = DOLLAR_VAR_RE.sub(r"\1", tag)  # allow {% if $x %} etc.
        out.append(tag)
        last = m.end()
    out.append(template[last:])
    return "".join(out)


@pass_context
def search_where(ctx: dict[str, Any], field: str = "external_id", param: str = "$search") -> str:
    """
    Emit a Cypher WHERE clause if `search` is present in the template context.

    Args:
        ctx:    Jinja2 Context object (passed automatically by Jinja).
        field:  The node property to compare (default: "external_id").
        param:  The Cypher parameter placeholder (default: "$search").

    Returns:
        A Cypher WHERE clause string if `search` is set, else "".
    """
    search_val: Any = ctx.get("search")
    if search_val is not None:
        return f"WHERE n.{field} = {param}"
    return ""


@pass_context
def apply_limit(ctx: dict[str, Any], max: int = 100) -> str:
    """
    Emit a Cypher WHERE clause if `search` is present in the template context.

    Args:
        ctx:    Jinja2 Context object (passed automatically by Jinja).
        field:  The node property to compare (default: "external_id").
        param:  The Cypher parameter placeholder (default: "$search").

    Returns:
        A Cypher WHERE clause string if `search` is set, else "".
    """
    limit_vale: Any = ctx.get("limit")

    if limit_vale is not None:
        return f"LIMIT {limit_vale}"
    return ""


@pass_context
def defaults(ctx: dict[str, Any], max: int = 100) -> str:
    """
    Emit a Cypher WHERE clause if `search` is present in the template context.

    Args:
        ctx:    Jinja2 Context object (passed automatically by Jinja).
        field:  The node property to compare (default: "external_id").
        param:  The Cypher parameter placeholder (default: "$search").

    Returns:
        A Cypher WHERE clause string if `search` is set, else "".
    """
    limit_vale: Any = ctx.get("limit")

    if limit_vale is not None:
        return f"LIMIT {limit_vale}"
    return ""


# ---------- main API ----------
def render_cypher_template(
    template_str: str,
    search: Optional[str] = None,
    sort: Optional[Dict[str, str]] = None,
    extra_params: Optional[Dict[str, Any]] = None,
    limit: Optional[int] = 100,
) -> Tuple[str, Dict[str, Any]]:
    """
    Render a Jinja2 Cypher template that may use {% if $search %} etc.
    Validate *after* rendering. Returns (cypher, params).

    sort: {"field": "<whitelisted field>", "dir": "ASC|DESC"}  (optional)
    search: free-text search string (optional)
    extra_params: any other parameters you want to pass through to the DB
    """
    # Step 1: preprocess to support $vars in Jinja tags
    pre = _strip_dollar_in_jinja_tags(template_str)

    # Step 2: render with Jinja2 (strict: undefined -> error)
    env = Environment(
        loader=BaseLoader(),
        undefined=StrictUndefined,
        autoescape=False,  # plain text generation
        trim_blocks=True,
        lstrip_blocks=True,
    )

    env.globals["search_where"] = search_where
    env.globals["apply_limit"] = apply_limit
    env.globals["defaults"] = defaults

    # Everything the template can reference:
    context = {
        # your convenience vars
        "search": search,
        "sort": sort,
        "limit": limit,
        # helper: truthy helper if you like: {% if search %}
        # add more helpers/globals if needed
    }

    tpl = env.from_string(pre)
    rendered = tpl.render(**context)

    # Step 3: validate AFTER rendering
    _validate_no_mutations(rendered)
    _validate_sort(sort)

    # Step 4: build params for the DB (e.g., $search)
    params: Dict[str, Any] = {}
    if search is not None:
        params["search"] = search
    if extra_params:
        params.update(extra_params)

    # Optional: cap/normalize LIMIT in the final text (if template forgot)
    if limit and not re.search(r"\bLIMIT\b", rendered, re.I):
        rendered = f"{rendered.rstrip()}\nLIMIT {int(limit)}"

    return rendered, params


def _validate_no_mutations(cypher_text: str) -> None:
    if MUTATING_TOKENS.search(cypher_text):
        raise ValueError("Rendered query appears to contain mutating clauses; rejected.")


def _validate_sort(sort: Optional[Dict[str, str]]) -> None:
    if not sort:
        return
    field = sort.get("field")
    direction = (sort.get("dir") or "ASC").upper()
    if field not in ALLOWED_SORT_FIELDS:
        raise ValueError(f"Sort field not allowed: {field!r}")
    if direction not in ALLOWED_SORT_DIRS:
        raise ValueError(f"Sort direction must be one of {sorted(ALLOWED_SORT_DIRS)}")
