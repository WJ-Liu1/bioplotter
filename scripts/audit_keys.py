"""Static audit of session_state key naming for the 5 migrated modules.

Enforces architecture §8.2:

* every widget key starts with the module prefix
  (``bubble_`` / ``gmp_`` / ``circle_`` / ``cbar_`` / ``genvar_``),
* every ``st.color_picker`` key contains the ``color`` substring (so
  ``reset_module_colors()`` can find it),
* **no other** widget key contains a ``reset_module_colors()`` filter substring
  (``color`` / ``fill`` / ``edge`` / ``line`` / ``bg`` / ``reg``).

    .venv\\Scripts\\python.exe scripts/audit_keys.py
"""

from __future__ import annotations

import ast
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]

MODULE_PREFIX: dict[str, str] = {
    "bubble": "bubble_",
    "grouped_matrix": "gmp_",
    "circle_viz": "circle_",
    "circular_bar": "cbar_",
    "genomic_variation": "genvar_",
    "volcano": "volcano_",
    "pca": "pca_",
    "heatmap": "heatmap_",
    "upset": "upset_",
    "kaplan_meier": "km_",
    "manhattan": "manhattan_",
    "paired_tree": "pt_",
}

FORBIDDEN = ("color", "fill", "edge", "line", "bg", "reg")

# Keys created outside a widget call (plain session_state writes) that are still
# part of the module contract; checked with the same rules.
EXTRA_KEYS: dict[str, list[str]] = {
    "bubble": ["_bubble_mapped_for"],
    "grouped_matrix": [],
    "circle_viz": [],
    "circular_bar": [],
    "genomic_variation": ["_genvar_bounds", "genvar_override_table", "_genvar_override_editor"],
    "volcano": [],
    "pca": [],
    "heatmap": [],
    "upset": [],
    "kaplan_meier": [],
    "manhattan": [],
    "paired_tree": [],
}

INTERNAL_PREFIXES = ("_",)


def _const_strings(node: ast.AST, constants: dict[str, list[str]] | None = None) -> list[str]:
    """Resolve a key argument to every string it can take."""
    constants = constants or {}
    if isinstance(node, ast.Constant) and isinstance(node.value, str):
        return [node.value]
    if isinstance(node, ast.JoinedStr):
        parts: list[str] = []
        for value in node.values:
            if isinstance(value, ast.Constant):
                parts.append(str(value.value))
            else:
                parts.append("<x>")
        return ["".join(parts)]
    if isinstance(node, ast.Subscript) and isinstance(node.value, ast.Name):
        # ``CAT_COLOR_KEYS[index]`` → every member of the tuple
        return list(constants.get(node.value.id, ["<dynamic>"]))
    if isinstance(node, ast.Name):
        return list(constants.get(node.id, [f"<name:{node.id}>"]))
    return ["<dynamic>"]


def _assignments(tree: ast.AST):
    """Yield ``(target_name, value_node)`` for ``x =`` and ``x: T =`` statements."""
    for node in ast.walk(tree):
        if isinstance(node, ast.Assign):
            for target in node.targets:
                if isinstance(target, ast.Name):
                    yield target.id, node.value
        elif isinstance(node, ast.AnnAssign) and isinstance(node.target, ast.Name) and node.value is not None:
            yield node.target.id, node.value


def _string_sequence(value: ast.AST) -> list[str] | None:
    """Return the members of a literal tuple/list/set made only of strings."""
    if not isinstance(value, (ast.Tuple, ast.List, ast.Set)):
        return None
    members: list[str] = []
    for element in value.elts:
        if not (isinstance(element, ast.Constant) and isinstance(element.value, str)):
            return None
        members.append(element.value)
    return members


def _module_constant_strings(tree: ast.AST) -> dict[str, list[str]]:
    """Collect module-level string sequences, e.g. ``CAT_COLOR_KEYS = ("gmp_...")``."""
    found: dict[str, list[str]] = {}
    for target_id, value in _assignments(tree):
        members = _string_sequence(value)
        if members:
            found.setdefault(target_id, members)
    return found


def _local_aliases(tree: ast.AST, constants: dict[str, list[str]]) -> dict[str, list[str]]:
    """Resolve ``symbol_key = CAT_SYMBOL_KEYS[index]`` style local aliases."""
    aliases: dict[str, list[str]] = {}
    for target_id, source in _assignments(tree):
        if isinstance(source, ast.Subscript):
            source = source.value
        if isinstance(source, ast.Name) and source.id in constants:
            aliases[target_id] = constants[source.id]
    return aliases


def _helper_params(tree: ast.AST) -> set[str]:
    """Names that are parameters of the module's own helper functions."""
    params: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            params.update(argument.arg for argument in node.args.args)
            params.update(argument.arg for argument in node.args.kwonlyargs)
    return params


def _widget_name(func: ast.AST) -> str | None:
    """Return the ``st.<widget>`` name for an ``st.xxx(...)`` call, else ``None``."""
    if isinstance(func, ast.Attribute) and isinstance(func.value, ast.Name) and func.value.id == "st":
        return func.attr
    return None


def audit_module(name: str) -> list[str]:
    path = PROJECT_ROOT / "app" / "modules" / f"{name}.py"
    tree = ast.parse(path.read_text(encoding="utf-8"))
    prefix = MODULE_PREFIX[name]
    constants = _module_constant_strings(tree)
    aliases = _local_aliases(tree, constants)
    helper_params = _helper_params(tree)
    # A helper parameter (``key``) must not inherit a same-named local alias from
    # elsewhere in the module; its real values are validated at the call sites.
    resolver = {
        name: values
        for name, values in {**constants, **aliases}.items()
        if name not in helper_params
    }
    problems: list[str] = []

    widget_keys: list[tuple[str, str]] = []
    for node in ast.walk(tree):
        if not isinstance(node, ast.Call):
            continue
        widget = _widget_name(node.func)
        func = node.func

        # Local wrappers (``_pick`` / ``_select_option``) take the key as the
        # third positional argument.
        helper = func.attr if isinstance(func, ast.Attribute) else (func.id if isinstance(func, ast.Name) else "")
        if helper in {"_pick", "_select_option"} and len(node.args) >= 3:
            for key in _const_strings(node.args[2], resolver):
                widget_keys.append(("selectbox", key))
            continue

        if widget is None:
            continue
        for keyword in node.keywords:
            if keyword.arg != "key":
                continue
            for key in _const_strings(keyword.value, resolver):
                widget_keys.append((widget, key))

    for widget, key in widget_keys:
        if key.startswith("<name:"):
            # Forwarded through a helper parameter → validated at the call site.
            if key[6:-1] in helper_params:
                continue
            problems.append(f"{widget}: cannot resolve key {key!r}")
            continue
        if key.startswith("<"):
            problems.append(f"{widget}: cannot resolve key {key!r}")
            continue
        _check(widget, key, prefix, problems)

    for key in EXTRA_KEYS.get(name, []):
        if key.startswith(INTERNAL_PREFIXES):
            continue
        _check("session", key, prefix, problems)

    return problems


def _check(widget: str, key: str, prefix: str, problems: list[str]) -> None:
    if not key.startswith(prefix):
        problems.append(f"{widget}: key {key!r} does not start with {prefix!r}")
        return
    lowered = key.lower()
    if widget == "color_picker":
        if "color" not in lowered:
            problems.append(f"color_picker: key {key!r} must contain 'color'")
        return
    for token in FORBIDDEN:
        if token in lowered:
            problems.append(f"{widget}: non-colour key {key!r} contains forbidden {token!r}")


def main() -> int:
    total = 0
    for name in MODULE_PREFIX:
        problems = audit_module(name)
        if problems:
            total += len(problems)
            print(f"[FAIL] {name}")
            for problem in sorted(set(problems)):
                print(f"       - {problem}")
        else:
            print(f"[PASS] {name}: key naming clean")

    print()
    print(f"audit: {total} problem(s)")
    return 0 if total == 0 else 1


if __name__ == "__main__":
    raise SystemExit(main())
