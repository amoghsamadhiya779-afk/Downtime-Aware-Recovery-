"""Invariant 7: agent/ must never import datagen/.

The generator produces the hidden response model (p_organic, p_retry_now, ...) that
the agent is never allowed to see. This makes that a build failure rather than a
code-review hope — static AST check, no need to actually import anything.
"""

from __future__ import annotations

import ast
from pathlib import Path

AGENT_DIR = Path(__file__).resolve().parent.parent / "agent"


def _imports(path: Path) -> set[str]:
    tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
    found: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                found.add(alias.name.split(".")[0])
        elif isinstance(node, ast.ImportFrom) and node.module:
            found.add(node.module.split(".")[0])
    return found


def test_agent_never_imports_datagen():
    offenders = [str(p) for p in AGENT_DIR.rglob("*.py") if "datagen" in _imports(p)]
    assert not offenders, f"agent/ modules importing datagen/: {offenders}"
