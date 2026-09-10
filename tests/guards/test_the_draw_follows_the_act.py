"""The draw follows the act, outside it, and a failed draw is not a failed act (A1, A7).

Every `GraphController` write commits its act in one `transaction.atomic()` and
then draws under `_draw_after`, which logs a failure, leaves the outbox row and
returns — the payload says `pending`. Two orderings are held here by reading the
source: the draw block is never inside the transaction (a claim that fails to
write must fail the mutation), and no drawing happens outside the block (a draw
that raised would surface as a failed mutation for a durable act).

History: the draw ran bare after the commit. A projector error propagated to the
client as a failed mutation while the log, the outbox and the subscription all
said the act happened, and nothing recorded why.
"""

import ast
import pathlib

CONTROLLER = pathlib.Path(__file__).resolve().parents[2] / "graph_engine" / "controller.py"

DRAW_NAMES = {"reproject_refs", "project", "project_edges", "project_refs", "project_from_structures", "unproject", "converge", "rebuild_projection"}
DRAW_PREFIXES = ("_reproject_", "project_")


def _calls(node: ast.AST):
    for sub in ast.walk(node):
        if isinstance(sub, ast.Call):
            yield sub


def _name(call: ast.Call) -> str:
    func = call.func
    if isinstance(func, ast.Attribute):
        return func.attr
    if isinstance(func, ast.Name):
        return func.id
    return ""


def _is_draw(call: ast.Call) -> bool:
    name = _name(call)
    return name in DRAW_NAMES or name.startswith(DRAW_PREFIXES)


def _with_items(node: ast.With) -> list[str]:
    names = []
    for item in node.items:
        expr = item.context_expr
        if isinstance(expr, ast.Call):
            names.append(_name(expr))
    return names


def _writes() -> list[ast.FunctionDef]:
    tree = ast.parse(CONTROLLER.read_text())
    controller = next(n for n in tree.body if isinstance(n, ast.ClassDef) and n.name == "GraphController")
    return [f for f in controller.body if isinstance(f, ast.FunctionDef) and any(_name(c) == "_create_assertion" for c in _calls(f))]


def test_every_write_draws_after_its_act_and_never_inside_it() -> None:
    writes = _writes()
    assert len(writes) >= 20, "the controller's writes are the population under test"
    for fn in writes:
        atomic_blocks = [w for w in ast.walk(fn) if isinstance(w, ast.With) and "atomic" in _with_items(w)]
        draw_blocks = [w for w in ast.walk(fn) if isinstance(w, ast.With) and "_draw_after" in _with_items(w)]
        assert atomic_blocks, f"{fn.name}: the act is one transaction"

        for block in atomic_blocks:
            assert not any(isinstance(w, ast.With) and "_draw_after" in _with_items(w) for w in ast.walk(block)), f"{fn.name}: the draw block sits inside the transaction — a claim that fails to write would be reported as pending instead of failing"

        inside = {id(c) for block in draw_blocks for c in _calls(block)}
        stray = [_name(c) for c in _calls(fn) if _is_draw(c) and id(c) not in inside]
        assert not stray, f"{fn.name}: draws outside `_draw_after`: {stray}"

        settles = [c for c in _calls(fn) if _name(c) == "_settle"]
        if any(_is_draw(c) for c in _calls(fn)):
            assert not settles, f"{fn.name}: `_settle` is `_draw_after`'s to call once the drawing succeeded"
            assert draw_blocks, f"{fn.name}: draws, but not under `_draw_after`"
        else:
            assert settles or draw_blocks, f"{fn.name}: an act that draws nothing still settles its outbox row"
