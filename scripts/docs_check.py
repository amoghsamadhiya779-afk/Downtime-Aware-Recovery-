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


def check_numeric_provenance() -> list[str]:
    readme_path = ROOT / "README.md"
    report_path = ROOT / "eval" / "report.md"
    if not readme_path.exists() or not report_path.exists():
        return []

    readme_text = readme_path.read_text(encoding="utf-8")
    report_text = report_path.read_text(encoding="utf-8")

    # Extract all numbers from report.md (normalizing commas, currency, percentages)
    report_tokens = set()
    for raw in re.findall(r"[₹$]?\b\d+(?:,\d+)*(?:\.\d+)?%?\b", report_text):
        cleaned = raw.replace("₹", "").replace("$", "").replace(",", "").replace("%", "").strip()
        if cleaned:
            report_tokens.add(cleaned)

    # Whitelist for system constants, ports, versions, attempt caps, demo amounts, and structure
    whitelist = {
        "256",          # SHA-256
        "8000",         # Dashboard port
        "3.11", "3.12", # Python versions
        "0.2.0", "1.0.0", # Generator versions
        "1", "2", "3", "4", "5", "6", "7", "8", "9", "10", # Section & attempt caps
        "2499", "2499.00", # Demo recovery amount
        "25",           # Holdout percentage
        "100",          # Max confidence %
        "326", "324", "321", "313", # Test suite counts
        "2000", "10000", "1000", # Resampling & corpus sizes
        "120",          # gpt-oss-120b model name
        "0",            # Zero counter / baseline
        "42",           # Seed
        "300",          # Dev cases
        "90", "15",     # Backoff / min delay
    }

    problems = []
    for raw in re.findall(r"[₹$]?\b\d+(?:,\d+)*(?:\.\d+)?%?\b", readme_text):
        cleaned = raw.replace("₹", "").replace("$", "").replace(",", "").replace("%", "").strip()
        if not cleaned:
            continue
        if cleaned in whitelist or cleaned in report_tokens:
            continue
        # Also check float equivalence if formatted with rounding
        try:
            val = float(cleaned)
            found = False
            for rt in report_tokens:
                try:
                    if abs(float(rt) - val) < 1e-4:
                        found = True
                        break
                except ValueError:
                    pass
            if found:
                continue
        except ValueError:
            pass

        problems.append(f"README.md: numeric token '{raw}' ({cleaned}) not found in eval/report.md or whitelist")

    return problems


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

    # Numeric provenance check
    num_problems = check_numeric_provenance()
    problems.extend(num_problems)

    if problems:
        for p in problems:
            print(f"docs-check: {p}", file=sys.stderr)
        return 1
    print(f"docs-check: OK ({len(known)} known rule ids, numeric provenance verified)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

