"""`make docs-check` — anti-drift mechanism (CLAUDE.md, "Context Engineering").

Every ALL_CAPS token shaped like a rule id (ends in _GUARD/_CAP/_FLOOR/_WINDOW/
_HOURS/_DEFER/_CLASS/_SWITCH/_DOWN) cited in a markdown file must actually exist in
rules.yaml. Catches the dominant drift class cheaply: a doc referencing a rule that
was renamed or removed.
"""

from __future__ import annotations

import re
import sys
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parent.parent
RULES_PATH = ROOT / "agent" / "policy" / "rules.yaml"
DOC_GLOBS = ["*.md", "eval/*.md", "research/*.md"]

RULE_LIKE = re.compile(r"\b([A-Z][A-Z_]{3,})\b")
RULE_SUFFIXES = (
    "_GUARD", "_CAP", "_FLOOR", "_WINDOW", "_HOURS", "_DEFER", "_CLASS", "_SWITCH", "_DOWN",
)


def known_rule_ids() -> set[str]:
    raw = yaml.safe_load(RULES_PATH.read_text(encoding="utf-8"))
    return {r["id"] for r in raw["rules"]}


def main() -> int:
    known = known_rule_ids()
    problems: list[str] = []
    for pattern in DOC_GLOBS:
        for path in ROOT.glob(pattern):
            text = path.read_text(encoding="utf-8")
            for m in RULE_LIKE.finditer(text):
                token = m.group(1)
                if token.endswith(RULE_SUFFIXES) and token not in known:
                    problems.append(f"{path.relative_to(ROOT)}: cites unknown rule id '{token}'")
    if problems:
        for p in problems:
            print(f"docs-check: {p}", file=sys.stderr)
        return 1
    print(f"docs-check: OK ({len(known)} known rule ids)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
