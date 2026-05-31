"""Check Alembic migration chain integrity.

Usage:
    python scripts/check_alembic_chain.py

Validates:
- All down_revision references point to existing revisions
- No orphaned revisions
- Single head (or explicit merge migrations)
"""

import re
import sys
from pathlib import Path

MIGRATIONS_DIR = Path(__file__).parent.parent / "migrations" / "versions"

REVISION_PATTERN = re.compile(r'^revision(?::\s*[^=]+)?\s*=\s*["\']([^"\']+)["\']', re.MULTILINE)
DOWN_REVISION_PATTERN = re.compile(
    r'^down_revision(?::\s*[^=]+)?\s*=\s*["\']([^"\']+)["\']', re.MULTILINE
)
DOWN_REVISION_NONE_PATTERN = re.compile(
    r'^down_revision(?::\s*[^=]+)?\s*=\s*None', re.MULTILINE
)


def parse_migration(file_path: Path) -> tuple[str | None, str | None]:
    """Extract revision and down_revision from a migration file."""
    content = file_path.read_text(encoding="utf-8")

    revision_match = REVISION_PATTERN.search(content)
    revision = revision_match.group(1) if revision_match else None

    down_match = DOWN_REVISION_PATTERN.search(content)
    down_none = DOWN_REVISION_NONE_PATTERN.search(content)

    if down_match:
        down_revision = down_match.group(1)
    elif down_none:
        down_revision = None
    else:
        down_revision = "UNKNOWN"

    return revision, down_revision


def main() -> int:
    if not MIGRATIONS_DIR.exists():
        print(f"ERROR: Migrations directory not found: {MIGRATIONS_DIR}")
        return 1

    files = sorted(MIGRATIONS_DIR.glob("*.py"))
    if not files:
        print("ERROR: No migration files found")
        return 1

    revisions: dict[str, Path] = {}
    down_revisions: dict[str, str | None] = {}
    errors: list[str] = []

    for file_path in files:
        revision, down_revision = parse_migration(file_path)

        if revision is None:
            errors.append(f"{file_path.name}: missing revision")
            continue

        if revision in revisions:
            errors.append(
                f"{file_path.name}: duplicate revision '{revision}' "
                f"(also in {revisions[revision].name})"
            )
            continue

        revisions[revision] = file_path
        down_revisions[revision] = down_revision

    for revision, down_rev in down_revisions.items():
        if down_rev is None:
            continue
        if down_rev == "UNKNOWN":
            errors.append(f"{revisions[revision].name}: cannot parse down_revision")
            continue
        if down_rev not in revisions:
            errors.append(
                f"{revisions[revision].name}: down_revision '{down_rev}' not found"
            )

    heads = set(revisions.keys()) - set(down_revisions.values())
    heads = {h for h in heads if down_revisions.get(h) != "UNKNOWN"}

    if errors:
        print("ALEMBIC CHAIN ERRORS:")
        for error in errors:
            print(f"  - {error}")
        print(f"\nTotal: {len(errors)} error(s)")
        return 1

    print(f"OK: {len(revisions)} migrations, chain is valid")
    print(f"Heads: {', '.join(sorted(heads))}")

    if len(heads) > 1:
        print(f"WARNING: Multiple heads detected ({len(heads)})")
        print("Consider creating a merge migration")

    return 0


if __name__ == "__main__":
    sys.exit(main())
