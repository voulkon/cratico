#!/usr/bin/env python3
"""
Emoji Fixer - Replaces emojis in source code with plain-text equivalents.

Workflow:
  1. Scan codebase → collect all unique emojis
  2. Look each one up in EMOJI_MAP (falls back to empty string)
  3. Replace in-place (or preview with --dry-run)

Usage:
    # Preview changes without writing
    python scripts/fix_emojis.py --dry-run

    # Apply fixes
    python scripts/fix_emojis.py

    # List all unique emojis found (no replacements)
    python scripts/fix_emojis.py --list

    # Scan a specific path only
    python scripts/fix_emojis.py backend --dry-run
"""

import argparse
import os
import re
import sys
from pathlib import Path
from typing import Dict, List, Set, Tuple

# Allow  python scripts/fix_emojis.py  to import sibling modules regardless
# of the working directory.
sys.path.insert(0, str(Path(__file__).parent))

# EMOJI_MAP lives in emoji_map.py — the single source of truth.
# Edit that file to add new entries; both this script and detect_ai_slop.py
# will pick up the change automatically.
# See scripts/emoji_map.py for the rationale behind plain-text tags.
from emoji_map import EMOJI_MAP  # noqa: E402

# ---------------------------------------------------------------------------
# File filtering (mirrors detect_ai_slop.py)
# ---------------------------------------------------------------------------
SKIP_DIRS = {
    "__pycache__",
    ".venv",
    "venv",
    "node_modules",
    "migrations",
    ".git",
    "build",
    "dist",
    "egg-info",
    ".pytest_cache",
}

CHECK_EXTENSIONS = {".py", ".js", ".ts", ".jsx", ".tsx", ".md"}

EMOJI_RE = re.compile(
    r"[\U0001F300-\U0001F9FF]|[\u2600-\u26FF]|[\u2700-\u27BF]",
    re.UNICODE,
)

# Matches "EMOJI followed by an optional single space" so the space is consumed
# together with the emoji (avoids leaving a dangling leading space).
EMOJI_WITH_SPACE_RE = re.compile(
    r"([\U0001F300-\U0001F9FF]|[\u2600-\u26FF]|[\u2700-\u27BF]) ?",
    re.UNICODE,
)


def should_skip_dir(name: str) -> bool:
    return name in SKIP_DIRS


def should_check_file(path: Path) -> bool:
    return path.suffix in CHECK_EXTENSIONS


# ---------------------------------------------------------------------------
# Core replacement logic
# ---------------------------------------------------------------------------


def replace_emojis_in_text(text: str, emoji_map: Dict[str, str]) -> Tuple[str, int]:
    """Replace all mapped emojis in *text*.

    For each emoji:
      - If mapped to a non-empty string: emoji → replacement (space NOT consumed)
      - If mapped to empty string: emoji + optional trailing space → "" (space consumed)

    Returns (new_text, replacement_count).
    """
    count = 0

    def replacer(m: re.Match) -> str:
        nonlocal count
        emoji_char = m.group(1)  # just the emoji, without the optional space
        full_match = m.group(0)  # emoji + possibly a space

        replacement = emoji_map.get(emoji_char)
        if replacement is None:
            # Not in map → leave untouched
            return full_match

        count += 1
        if replacement == "":
            # Consume the emoji and the trailing space (if any)
            return ""
        else:
            # Keep the space if there was one; prepend the replacement text
            had_space = full_match != emoji_char
            return replacement + (" " if had_space else "")

    new_text = EMOJI_WITH_SPACE_RE.sub(replacer, text)
    return new_text, count


def collect_unique_emojis(
    scan_paths: List[str],
) -> Dict[str, List[Tuple[str, int, str]]]:
    """Return {emoji: [(file, line_number, line_content), ...]}."""
    result: Dict[str, List] = {}

    for scan_path in scan_paths:
        for root, dirs, files in os.walk(scan_path):
            dirs[:] = [d for d in dirs if not should_skip_dir(d)]
            for filename in files:
                fp = Path(root) / filename
                if not should_check_file(fp):
                    continue
                try:
                    with open(fp, encoding="utf-8", errors="ignore") as fh:
                        for lineno, line in enumerate(fh, 1):
                            for emoji in EMOJI_RE.findall(line):
                                result.setdefault(emoji, []).append(
                                    (str(fp), lineno, line.rstrip())
                                )
                except OSError as exc:
                    print(f"Warning: cannot read {fp}: {exc}", file=sys.stderr)

    return result


def fix_file(
    fp: Path, emoji_map: Dict[str, str], dry_run: bool
) -> Tuple[int, List[str]]:
    """Process one file. Returns (total_replacements, diff_lines)."""
    try:
        original = fp.read_text(encoding="utf-8", errors="ignore")
    except OSError as exc:
        print(f"Warning: cannot read {fp}: {exc}", file=sys.stderr)
        return 0, []

    fixed, count = replace_emojis_in_text(original, emoji_map)
    if count == 0:
        return 0, []

    diff_lines: List[str] = []
    if dry_run:
        orig_lines = original.splitlines()
        fixed_lines = fixed.splitlines()
        for i, (old, new) in enumerate(zip(orig_lines, fixed_lines), 1):
            if old != new:
                diff_lines.append(f"  line {i}:")
                diff_lines.append(f"  - {old.rstrip()}")
                diff_lines.append(f"  + {new.rstrip()}")
    else:
        fp.write_text(fixed, encoding="utf-8")

    return count, diff_lines


def scan_and_fix(
    scan_paths: List[str],
    emoji_map: Dict[str, str],
    dry_run: bool,
    verbose: bool,
) -> int:
    """Walk paths, fix emojis. Returns total replacement count."""
    total_replacements = 0
    total_files = 0

    for scan_path in scan_paths:
        for root, dirs, files in os.walk(scan_path):
            dirs[:] = [d for d in dirs if not should_skip_dir(d)]
            for filename in files:
                fp = Path(root) / filename
                if not should_check_file(fp):
                    continue

                count, diff = fix_file(fp, emoji_map, dry_run)
                if count:
                    total_files += 1
                    total_replacements += count
                    action = "Would fix" if dry_run else "Fixed"
                    print(f"{action}: {fp}  ({count} replacement(s))")
                    if verbose and diff:
                        print("\n".join(diff))

    mode = "[DRY RUN] " if dry_run else ""
    print(
        f"\n{mode}Total: {total_replacements} replacement(s) in {total_files} file(s)"
    )
    return total_replacements


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------


def cmd_list(scan_paths: List[str]) -> None:
    """Print all unique emojis found, with mapping status."""
    found = collect_unique_emojis(scan_paths)
    if not found:
        print("No emojis found.")
        return

    mapped = {e for e in found if e in EMOJI_MAP}
    unmapped = {e for e in found if e not in EMOJI_MAP}

    print(f"\nFound {len(found)} unique emoji(s) across the codebase:\n")
    print(f"{'EMOJI':<6}  {'MAPPED TO':<20}  {'OCCURRENCES'}")
    print("-" * 50)
    for emoji in sorted(found):
        occ = len(found[emoji])
        if emoji in EMOJI_MAP:
            rep = repr(EMOJI_MAP[emoji]) if EMOJI_MAP[emoji] else '""  (removed)'
            print(f"  {emoji}    {rep:<20}  {occ}")
        else:
            print(f"  {emoji}    {'(NOT IN MAP)':<20}  {occ}  ← add to EMOJI_MAP")

    print(f"\nMapped: {len(mapped)}   Unmapped: {len(unmapped)}")
    if unmapped:
        print("\nUnmapped emojis — add entries to EMOJI_MAP in this script:")
        for e in sorted(unmapped):
            print(f'    "{e}": "",')


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Replace emojis in source code with plain-text equivalents.",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
    python scripts/fix_emojis.py --list            # discover emojis, show mapping
    python scripts/fix_emojis.py --dry-run         # preview replacements
    python scripts/fix_emojis.py                   # apply fixes
    python scripts/fix_emojis.py backend --dry-run # scope to backend/
        """,
    )
    parser.add_argument(
        "paths",
        nargs="*",
        default=["."],
        help="Directories to scan (default: current directory)",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Preview changes without modifying any files",
    )
    parser.add_argument(
        "--list",
        action="store_true",
        help="List unique emojis found and their mapping status, then exit",
    )
    parser.add_argument(
        "--verbose",
        "-v",
        action="store_true",
        help="Show before/after diff for each changed line",
    )

    args = parser.parse_args()

    if args.list:
        cmd_list(args.paths)
        return

    unmapped_warning: Set[str] = set()
    found_emojis = collect_unique_emojis(args.paths)
    for emoji in found_emojis:
        if emoji not in EMOJI_MAP:
            unmapped_warning.add(emoji)

    if unmapped_warning:
        print(
            f"Warning: {len(unmapped_warning)} emoji(s) not in EMOJI_MAP "
            f"(will be left unchanged): " + " ".join(sorted(unmapped_warning)),
            file=sys.stderr,
        )

    scan_and_fix(args.paths, EMOJI_MAP, dry_run=args.dry_run, verbose=args.verbose)


if __name__ == "__main__":
    main()
