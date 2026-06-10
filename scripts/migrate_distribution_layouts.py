"""Reassign Distribution Statement layouts across the existing ground truth.

Rewrites ONLY each entry's `layout:` line in
ground_truth/distribution_statements.yml, mapping the 50 entries (in file order)
onto the six layouts round-robin by index. Field values, CASE ids, and
degradation seeds are left byte-for-byte unchanged. The script aborts without
writing if any field value would change.

Usage:
    python scripts/migrate_distribution_layouts.py
"""

import re
from pathlib import Path

import yaml

_GT = Path(__file__).parent.parent / "ground_truth" / "distribution_statements.yml"

DISTRIBUTION_LAYOUTS = [
    "dist_software_navy",
    "dist_software_teal",
    "dist_table_plain",
    "dist_table_ruled",
    "dist_letter_formal",
    "dist_letter_compact",
]

_CASE_RE = re.compile(r"^CASE\d+:\s*$")
_LAYOUT_RE = re.compile(r"^(\s*layout:\s*).*$")


def layout_for_index(index: int) -> str:
    """Deterministic round-robin layout for the Nth entry (0-based)."""
    return DISTRIBUTION_LAYOUTS[index % len(DISTRIBUTION_LAYOUTS)]


def migrate(path: Path = _GT) -> dict[str, str]:
    """Rewrite layout lines in place. Returns {case_id: new_layout}.

    Raises:
        SystemExit: if any field value would change (nothing is written).
    """
    original_text = path.read_text()
    before = yaml.safe_load(original_text)
    before_fields = {cid: e["fields"] for cid, e in before.items()}

    assignments: dict[str, str] = {}
    replaced: set[str] = set()
    current_case: str | None = None
    index = -1
    out: list[str] = []

    for line in original_text.splitlines(keepends=True):
        if _CASE_RE.match(line):
            current_case = line.split(":", 1)[0]
            index += 1
            assignments[current_case] = layout_for_index(index)
            out.append(line)
            continue
        m = _LAYOUT_RE.match(line)
        if m and current_case is not None and current_case not in replaced:
            out.append(f"{m.group(1)}{assignments[current_case]}\n")
            replaced.add(current_case)
            continue
        out.append(line)

    new_text = "".join(out)
    after = yaml.safe_load(new_text)
    after_fields = {cid: e["fields"] for cid, e in after.items()}

    if before_fields != after_fields:
        raise SystemExit("ABORT: field values would change; nothing written.")
    if set(replaced) != set(assignments):
        missing = set(assignments) - set(replaced)
        raise SystemExit(f"ABORT: no layout line found for {sorted(missing)}; nothing written.")

    path.write_text(new_text)
    return assignments


def main() -> None:
    assignments = migrate()
    counts: dict[str, int] = {}
    for layout in assignments.values():
        counts[layout] = counts.get(layout, 0) + 1
    print(f"Reassigned {len(assignments)} entries:")
    for layout in DISTRIBUTION_LAYOUTS:
        print(f"  {layout}: {counts.get(layout, 0)}")


if __name__ == "__main__":
    main()
