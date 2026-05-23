#!/usr/bin/env python3
"""
Generate comprehensive linting reports for the entire project.

Runs all detection scripts and generates combined reports in multiple formats.
"""

import argparse
import json
import sys
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List

# Add scripts directory to path
sys.path.insert(0, str(Path(__file__).parent))

from detect_ai_slop import AISlopDetector
from detect_hardcoded_colors import CSSColorDetector


def generate_combined_report(
    ai_slop_matches: List[Any],
    color_matches: List[Any],
    output_format: str = "markdown",
) -> str:
    """Generate a combined report from all detectors."""

    timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")

    # Calculate totals
    total_ai_slop = len(ai_slop_matches)
    total_colors = len(color_matches)
    total_issues = total_ai_slop + total_colors

    # Count files affected
    ai_slop_files = (
        len(set(m.file_path for m in ai_slop_matches)) if ai_slop_matches else 0
    )
    color_files = len(set(m.file_path for m in color_matches)) if color_matches else 0

    if output_format == "json":
        report = {
            "timestamp": timestamp,
            "summary": {
                "total_issues": total_issues,
                "ai_slop": {"total": total_ai_slop, "files_affected": ai_slop_files},
                "hardcoded_colors": {
                    "total": total_colors,
                    "files_affected": color_files,
                },
            },
            "ai_slop_issues": [
                {
                    "file": m.file_path,
                    "line": m.line_number,
                    "pattern_type": m.pattern_type,
                    "matched_text": m.matched_text,
                    "line_content": m.line_content,
                }
                for m in ai_slop_matches
            ],
            "color_issues": [
                {
                    "file": m.file_path,
                    "line": m.line_number,
                    "color_type": m.color_type,
                    "color_value": m.color_value,
                    "line_content": m.line_content,
                }
                for m in color_matches
            ],
        }
        return json.dumps(report, indent=2)

    elif output_format == "markdown":
        lines = [
            f"# Code Quality Report",
            f"",
            f"**Generated:** {timestamp}",
            f"",
            f"## Executive Summary",
            f"",
            f"| Category | Issues | Files Affected |",
            f"|----------|--------|----------------|",
            f"| AI Slop Patterns | {total_ai_slop} | {ai_slop_files} |",
            f"| Hard-coded Colors | {total_colors} | {color_files} |",
            f"| **Total** | **{total_issues}** | **{ai_slop_files + color_files}** |",
            f"",
        ]

        # AI Slop Section
        if ai_slop_matches:
            lines.extend(
                [
                    f"## AI Slop Detection",
                    f"",
                    f"Found **{total_ai_slop}** AI-generated code patterns in **{ai_slop_files}** files.",
                    f"",
                ]
            )

            # Group by pattern type
            by_pattern: Dict[str, int] = {}
            for m in ai_slop_matches:
                by_pattern[m.pattern_type] = by_pattern.get(m.pattern_type, 0) + 1

            lines.append("### Issues by Pattern Type")
            lines.append("")
            for pattern_type, count in sorted(by_pattern.items(), key=lambda x: -x[1]):
                lines.append(f"- **{pattern_type}**: {count} occurrences")

            lines.append("")
            lines.append("### All Files with Issues")
            lines.append("")

            # Group by file for detailed listing
            by_file_detailed: Dict[str, List[Any]] = {}
            for m in ai_slop_matches:
                if m.file_path not in by_file_detailed:
                    by_file_detailed[m.file_path] = []
                by_file_detailed[m.file_path].append(m)

            # Show all files with clickable file:line format
            for file_path, matches in sorted(by_file_detailed.items()):
                lines.append(f"#### `{file_path}` ({len(matches)} issues)")
                lines.append("")
                for match in sorted(matches, key=lambda x: x.line_number):
                    # Escape pipe characters in matched text
                    matched_text = match.matched_text.replace("|", "\\|")
                    lines.append(
                        f"- `{file_path}:{match.line_number}` - {match.pattern_type}: `{matched_text}`"
                    )
                lines.append("")

        # Hard-coded Colors Section
        if color_matches:
            lines.extend(
                [
                    f"## Hard-coded Colors Detection",
                    f"",
                    f"Found **{total_colors}** hard-coded colors in **{color_files}** CSS files.",
                    f"",
                ]
            )

            # Group by color type
            by_type: Dict[str, int] = {}
            for m in color_matches:
                by_type[m.color_type] = by_type.get(m.color_type, 0) + 1

            lines.append("### Issues by Color Type")
            lines.append("")
            for color_type, count in sorted(by_type.items(), key=lambda x: -x[1]):
                lines.append(f"- **{color_type}**: {count} occurrences")

            lines.append("")
            lines.append("### All Files with Issues")
            lines.append("")

            # Group by file for detailed listing
            by_file_detailed: Dict[str, List[Any]] = {}
            for m in color_matches:
                if m.file_path not in by_file_detailed:
                    by_file_detailed[m.file_path] = []
                by_file_detailed[m.file_path].append(m)

            # Show all files with clickable file:line format
            for file_path, matches in sorted(by_file_detailed.items()):
                lines.append(f"#### `{file_path}` ({len(matches)} issues)")
                lines.append("")
                for match in sorted(matches, key=lambda x: x.line_number):
                    # Escape pipe characters in color value
                    color_value = match.color_value.replace("|", "\\|")
                    lines.append(
                        f"- `{file_path}:{match.line_number}` - {match.color_type}: `{color_value}`"
                    )
                lines.append("")

        # Recommendations
        lines.extend(
            [
                f"## Recommendations",
                f"",
                f"### Immediate Actions (High Priority)",
                f"",
            ]
        )

        if total_ai_slop > 100:
            lines.append(
                f"1. **AI Slop Cleanup**: Focus on removing emojis from production code"
            )

        if total_colors > 50:
            lines.append(
                f"2. **CSS Variables Migration**: Replace hard-coded colors with CSS variables"
            )

        lines.extend(
            [
                f"",
                f"### Gradual Improvements",
                f"",
                f"- Run `pre-commit run --all-files` to auto-fix formatting issues",
                f"- Review and fix issues in test files (lower priority)",
                f"- Update CI/CD to enforce quality checks",
                f"",
                f"## Resources",
                f"",
                f"- [AI Slop Detection Guide](docs/ai-slop-detection.md)",
                f"- [CSS Variables Documentation](frontend/src/styles/variables.css)",
                f"- [Pre-commit Configuration](.pre-commit-config.yaml)",
                f"",
                f"---",
                f"*Generated by Code Quality Reporter*",
            ]
        )

        return "\n".join(lines)

    return ""


def main():
    parser = argparse.ArgumentParser(
        description="Generate comprehensive code quality reports",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
            Examples:
                # Generate markdown report
                python scripts/generate_quality_report.py

                # Generate JSON report
                python scripts/generate_quality_report.py --format json

                # Save to file
                python scripts/generate_quality_report.py --output reports/quality-report.md

                # Only check specific directories
                python scripts/generate_quality_report.py --ai-slop-paths backend --color-paths frontend
                    """,
    )
    parser.add_argument(
        "--format",
        choices=["json", "markdown"],
        default="markdown",
        help="Report format (default: markdown)",
    )
    parser.add_argument(
        "--output", metavar="FILE", help="Output file for report (default: stdout)"
    )
    parser.add_argument(
        "--ai-slop-paths",
        nargs="+",
        default=["backend"],
        help="Paths to scan for AI slop (default: backend)",
    )
    parser.add_argument(
        "--color-paths",
        nargs="+",
        default=["frontend"],
        help="Paths to scan for hard-coded colors (default: frontend)",
    )
    parser.add_argument(
        "--skip-colors", action="store_true", help="Skip hard-coded color detection"
    )
    parser.add_argument(
        "--skip-ai-slop", action="store_true", help="Skip AI slop detection"
    )

    args = parser.parse_args()

    print("[SCAN] Scanning codebase...", file=sys.stderr)

    # Run AI Slop Detection
    ai_slop_matches = []
    if not args.skip_ai_slop:
        print("  [SCAN] Checking for AI slop patterns...", file=sys.stderr)
        detector = AISlopDetector()
        for path in args.ai_slop_paths:
            matches = detector.scan_directory(path)
            ai_slop_matches.extend(matches)
        print(f"     Found {len(ai_slop_matches)} issues", file=sys.stderr)

    # Run Color Detection
    color_matches = []
    if not args.skip_colors:
        print("  [SCAN] Checking for hard-coded colors...", file=sys.stderr)
        detector = CSSColorDetector()
        for path in args.color_paths:
            matches = detector.scan_directory(path)
            color_matches.extend(matches)
        print(f"     Found {len(color_matches)} issues", file=sys.stderr)

    # Generate report
    print("\n[REPORT] Generating report...", file=sys.stderr)
    report = generate_combined_report(ai_slop_matches, color_matches, args.format)

    # Output report
    if args.output:
        # Create directory if needed
        output_path = Path(args.output)
        output_path.parent.mkdir(parents=True, exist_ok=True)

        with open(args.output, "w", encoding="utf-8") as f:
            f.write(report)
        print(f"\n[OK] Report saved to {args.output}", file=sys.stderr)
    else:
        print("\n" + report)

    # Summary
    total = len(ai_slop_matches) + len(color_matches)
    if total > 0:
        print(f"\n[WARN] Total issues found: {total}", file=sys.stderr)
        print(f"   Review the report above for details.", file=sys.stderr)
    else:
        print(f"\n[OK] No issues found! Code quality is excellent.", file=sys.stderr)


if __name__ == "__main__":
    main()
