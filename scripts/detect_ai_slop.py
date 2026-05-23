#!/usr/bin/env python3
"""
AI Slop Detector - Detects common AI-generated code patterns.

Detects:
- Emojis in code (🚀, ✅, etc.)
- Em dashes (—) often used by AI
- Other configurable patterns

Usage:
    python scripts/detect_ai_slop.py [PATH] [--fix] [--ci]

Exit codes:
    0: No issues found
    1: Issues found (for CI)
"""

import argparse
import os
import re
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Dict, List


@dataclass
class SlopMatch:
    """Represents a detected AI slop pattern."""

    file_path: str
    line_number: int
    line_content: str
    pattern_type: str
    matched_text: str


class AISlopDetector:
    """Detects AI-generated code patterns."""

    # Patterns that indicate AI-generated code
    PATTERNS = {
        "emoji": {
            "regex": r"[\U0001F300-\U0001F9FF]|[\u2600-\u26FF]|[\u2700-\u27BF]",
            "description": "Emoji characters",
            "severity": "warning",
            "file_extensions": None,  # None = all file types
        },
        "em_dash": {
            "regex": r" — ",
            "description": "Em dash (often used by AI)",
            "severity": "warning",
            "file_extensions": {".md"},  # Only check markdown files
        },
        # Add more patterns as needed
        # 'todo_ai': {
        #     'regex': r'(?i)(as an ai|I cannot|I\'m unable to)',
        #     'description': 'AI response artifacts',
        #     'severity': 'error',
        #     'file_extensions': None,
        # },
    }

    # Directories to skip
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

    # File extensions to check
    CHECK_EXTENSIONS = {".py", ".js", ".ts", ".jsx", ".tsx", ".md"}

    def __init__(self, base_path: str = "."):
        self.base_path = Path(base_path).resolve()
        self.compiled_patterns = {
            name: re.compile(config["regex"], re.UNICODE)
            for name, config in self.PATTERNS.items()
        }

    def should_check_file(self, file_path: Path) -> bool:
        """Check if file should be scanned."""
        return file_path.suffix in self.CHECK_EXTENSIONS

    def should_skip_dir(self, dir_name: str) -> bool:
        """Check if directory should be skipped."""
        return dir_name in self.SKIP_DIRS

    def scan_file(self, file_path: Path) -> List[SlopMatch]:
        """Scan a single file for AI slop patterns."""
        matches = []

        try:
            with open(file_path, "r", encoding="utf-8", errors="ignore") as f:
                for line_num, line in enumerate(f, 1):
                    for pattern_name, pattern in self.compiled_patterns.items():
                        # Check if pattern applies to this file type
                        pattern_config = self.PATTERNS[pattern_name]
                        if pattern_config.get("file_extensions") is not None:
                            if (
                                file_path.suffix
                                not in pattern_config["file_extensions"]
                            ):
                                continue

                        found = pattern.findall(line)
                        if found:
                            # Use absolute path for display, or relative if possible
                            try:
                                display_path = str(
                                    file_path.relative_to(self.base_path)
                                )
                            except ValueError:
                                display_path = str(file_path)

                            matches.append(
                                SlopMatch(
                                    file_path=display_path,
                                    line_number=line_num,
                                    line_content=line.rstrip(),
                                    pattern_type=pattern_name,
                                    matched_text=", ".join(set(found)),
                                )
                            )
        except Exception as e:
            print(f"Warning: Could not read {file_path}: {e}", file=sys.stderr)

        return matches

    def scan_directory(self, target_dir: str = None) -> List[SlopMatch]:
        """Scan directory recursively for AI slop patterns."""
        scan_path = Path(target_dir) if target_dir else self.base_path
        all_matches = []

        for root, dirs, files in os.walk(scan_path):
            # Filter out directories to skip
            dirs[:] = [d for d in dirs if not self.should_skip_dir(d)]

            for filename in files:
                file_path = Path(root) / filename
                if self.should_check_file(file_path):
                    matches = self.scan_file(file_path)
                    all_matches.extend(matches)

        return all_matches

    def print_results(self, matches: List[SlopMatch], verbose: bool = True) -> None:
        """Print results in a formatted way."""
        if not matches:
            print("[OK] No AI slop patterns detected.")
            return

        # Group by file
        by_file: Dict[str, List[SlopMatch]] = {}
        for match in matches:
            if match.file_path not in by_file:
                by_file[match.file_path] = []
            by_file[match.file_path].append(match)

        print(f"\n{'='*60}")
        print(
            f"[WARN] Found {len(matches)} AI slop pattern(s) in {len(by_file)} file(s)"
        )
        print(f"{'='*60}\n")

        for file_path, file_matches in sorted(by_file.items()):
            print(f"FILE {file_path}")
            for match in file_matches:
                severity = self.PATTERNS[match.pattern_type]["severity"]
                symbol = "[ERROR]" if severity == "error" else "[WARN]"
                print(
                    f"  {symbol} Line {match.line_number}: [{match.pattern_type}] {match.matched_text}"
                )
                if verbose:
                    print(f"     {match.line_content[:100]}")
            print()

        # Summary by pattern type
        print(f"\n{'─'*60}")
        print("Summary by pattern type:")
        by_pattern: Dict[str, int] = {}
        for match in matches:
            by_pattern[match.pattern_type] = by_pattern.get(match.pattern_type, 0) + 1

        for pattern_type, count in sorted(by_pattern.items(), key=lambda x: -x[1]):
            desc = self.PATTERNS[pattern_type]["description"]
            print(f"  - {pattern_type}: {count} occurrences ({desc})")
        print(f"{'─'*60}")
        print()
        print("To replace emojis with plain-text tags, run:")
        print("  python scripts/fix_emojis.py --dry-run   # preview")
        print("  python scripts/fix_emojis.py             # apply")
        print("  (Edit scripts/emoji_map.py to add new mappings.)")
        print(f"{'─'*60}\n")

    def generate_report(
        self, matches: List[SlopMatch], output_format: str = "json"
    ) -> str:
        """Generate a report in JSON or Markdown format."""
        import json
        from datetime import datetime

        # Group by file
        by_file: Dict[str, List[SlopMatch]] = {}
        for match in matches:
            if match.file_path not in by_file:
                by_file[match.file_path] = []
            by_file[match.file_path].append(match)

        # Summary by pattern type
        by_pattern: Dict[str, int] = {}
        for match in matches:
            by_pattern[match.pattern_type] = by_pattern.get(match.pattern_type, 0) + 1

        if output_format == "json":
            report = {
                "timestamp": datetime.now().isoformat(),
                "summary": {
                    "total_issues": len(matches),
                    "files_affected": len(by_file),
                    "by_pattern": by_pattern,
                },
                "issues": [
                    {
                        "file": match.file_path,
                        "line": match.line_number,
                        "pattern_type": match.pattern_type,
                        "matched_text": match.matched_text,
                        "line_content": match.line_content,
                        "severity": self.PATTERNS[match.pattern_type]["severity"],
                    }
                    for match in matches
                ],
            }
            return json.dumps(report, indent=2)

        elif output_format == "markdown":
            lines = [
                "# AI Slop Detection Report",
                "",
                f"**Generated:** {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}",
                "",
                "## Summary",
                "",
                f"- **Total Issues:** {len(matches)}",
                f"- **Files Affected:** {len(by_file)}",
                "",
                "## How to Fix",
                "",
                "Emoji replacements are defined in `scripts/emoji_map.py`.",
                "Run the fixer to apply them automatically:",
                "",
                "```bash",
                "python scripts/fix_emojis.py --dry-run   # preview changes",
                "python scripts/fix_emojis.py             # apply changes",
                "```",
                "",
                "To add new mappings, edit `scripts/emoji_map.py` and re-run.",
                "",
                "### Issues by Pattern Type",
                "",
            ]

            for pattern_type, count in sorted(by_pattern.items(), key=lambda x: -x[1]):
                desc = self.PATTERNS[pattern_type]["description"]
                lines.append(f"- **{pattern_type}**: {count} occurrences ({desc})")

            lines.extend(
                [
                    f"",
                    f"## Files Requiring Attention",
                    f"",
                ]
            )

            for file_path, file_matches in sorted(by_file.items()):
                lines.append(f"### `{file_path}`")
                lines.append(f"")
                lines.append(f"| Line | Pattern | Matched | Severity |")
                lines.append(f"|------|---------|---------|----------|")

                for match in file_matches:
                    severity = self.PATTERNS[match.pattern_type]["severity"]
                    lines.append(
                        f"| {match.line_number} | {match.pattern_type} | {match.matched_text} | {severity} |"
                    )

                lines.append(f"")

            return "\n".join(lines)

        return ""


def main():
    parser = argparse.ArgumentParser(
        description="Detect AI-generated code patterns (emojis, em dashes, etc.)",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
    # Scan current directory
    python scripts/detect_ai_slop.py

    # Scan specific directory
    python scripts/detect_ai_slop.py backend

    # Run in CI mode (exit with error code if issues found)
    python scripts/detect_ai_slop.py --ci

    # Scan multiple directories
    python scripts/detect_ai_slop.py backend frontend
        """,
    )
    parser.add_argument(
        "paths",
        nargs="*",
        default=["."],
        help="Paths to scan (default: current directory)",
    )
    parser.add_argument(
        "--ci", action="store_true", help="CI mode: exit with code 1 if issues found"
    )
    parser.add_argument(
        "--quiet", action="store_true", help="Only show summary, not individual lines"
    )
    parser.add_argument(
        "--pattern",
        choices=["emoji", "em_dash", "all"],
        default="all",
        help="Which pattern to check (default: all)",
    )
    parser.add_argument(
        "--report",
        metavar="FORMAT",
        choices=["json", "markdown"],
        help="Generate report in specified format (json or markdown)",
    )
    parser.add_argument(
        "--output", metavar="FILE", help="Output file for report (default: stdout)"
    )

    args = parser.parse_args()

    # Initialize detector
    detector = AISlopDetector()

    # Filter patterns if specific one requested
    if args.pattern != "all":
        patterns_to_keep = {args.pattern: detector.PATTERNS[args.pattern]}
        detector.PATTERNS = patterns_to_keep
        detector.compiled_patterns = {
            name: re.compile(config["regex"], re.UNICODE)
            for name, config in patterns_to_keep.items()
        }

    # Scan all specified paths
    all_matches = []
    for path in args.paths:
        matches = detector.scan_directory(path)
        all_matches.extend(matches)

    # Generate report if requested
    if args.report:
        report = detector.generate_report(all_matches, args.report)

        if args.output:
            with open(args.output, "w", encoding="utf-8") as f:
                f.write(report)
            print(f"[OK] Report saved to {args.output}")
        else:
            print(report)
    else:
        detector.print_results(all_matches, verbose=not args.quiet)

    # Exit with appropriate code
    if args.ci and all_matches:
        sys.exit(1)

    sys.exit(0)


if __name__ == "__main__":
    main()
