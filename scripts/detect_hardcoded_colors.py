#!/usr/bin/env python3
"""
CSS Hard-coded Color Detector - Ensures CSS uses variables instead of hard-coded colors.

Detects:
- Hex colors: #fff, #ffffff, #000, etc.
- RGB/RGBA: rgb(255, 255, 255), rgba(0, 0, 0, 0.5)
- HSL/HSLA: hsl(120, 100%, 50%), hsla(120, 100%, 50%, 0.5)
- Named colors: red, blue, green, white, black, etc.

Usage:
    python scripts/detect_hardcoded_colors.py [PATH] [--ci]

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
class ColorMatch:
    """Represents a detected hard-coded color."""

    file_path: str
    line_number: int
    line_content: str
    color_type: str
    color_value: str


class CSSColorDetector:
    """Detects hard-coded colors in CSS files."""

    # CSS color patterns
    PATTERNS = {
        "hex_3": {
            "regex": r"#([0-9a-fA-F]{3})\b(?![0-9a-fA-F])",
            "description": "3-digit hex color (e.g., #fff)",
            "severity": "warning",
        },
        "hex_6": {
            "regex": r"#([0-9a-fA-F]{6})\b",
            "description": "6-digit hex color (e.g., #ffffff)",
            "severity": "warning",
        },
        "rgb": {
            "regex": r"\brgb\(\s*\d{1,3}\s*,\s*\d{1,3}\s*,\s*\d{1,3}\s*\)",
            "description": "RGB color (e.g., rgb(255, 255, 255))",
            "severity": "warning",
        },
        "rgba": {
            "regex": r"\brgba\(\s*\d{1,3}\s*,\s*\d{1,3}\s*,\s*\d{1,3}\s*,\s*[\d.]+\s*\)",
            "description": "RGBA color (e.g., rgba(0, 0, 0, 0.5))",
            "severity": "warning",
        },
        "hsl": {
            "regex": r"\bhsl\(\s*\d{1,3}\s*,\s*\d{1,3}%?\s*,\s*\d{1,3}%?\s*\)",
            "description": "HSL color (e.g., hsl(120, 100%, 50%))",
            "severity": "warning",
        },
        "hsla": {
            "regex": r"\bhsla\(\s*\d{1,3}\s*,\s*\d{1,3}%?\s*,\s*\d{1,3}%?\s*,\s*[\d.]+\s*\)",
            "description": "HSLA color (e.g., hsla(120, 100%, 50%, 0.5))",
            "severity": "warning",
        },
        "named": {
            "regex": r"\b(aliceblue|antiquewhite|aqua|aquamarine|azure|beige|bisque|black|blanchedalmond|blue|blueviolet|brown|burlywood|cadetblue|chartreuse|chocolate|coral|cornflowerblue|cornsilk|crimson|cyan|darkblue|darkcyan|darkgoldenrod|darkgray|darkgreen|darkgrey|darkkhaki|darkmagenta|darkolivegreen|darkorange|darkorchid|darkred|darksalmon|darkseagreen|darkslateblue|darkslategray|darkslategrey|darkturquoise|darkviolet|deeppink|deepskyblue|dimgray|dimgrey|dodgerblue|firebrick|floralwhite|forestgreen|fuchsia|gainsboro|ghostwhite|gold|goldenrod|gray|green|greenyellow|grey|honeydew|hotpink|indianred|indigo|ivory|khaki|lavender|lavenderblush|lawngreen|lemonchiffon|lightblue|lightcoral|lightcyan|lightgoldenrodyellow|lightgray|lightgreen|lightgrey|lightpink|lightsalmon|lightseagreen|lightskyblue|lightslategray|lightslategrey|lightsteelblue|lightyellow|lime|limegreen|linen|magenta|maroon|mediumaquamarine|mediumblue|mediumorchid|mediumpurple|mediumseagreen|mediumslateblue|mediumspringgreen|mediumturquoise|mediumvioletred|midnightblue|mintcream|mistyrose|moccasin|navajowhite|navy|oldlace|olive|olivedrab|orange|orangered|orchid|palegoldenrod|palegreen|paleturquoise|palevioletred|papayawhip|peachpuff|peru|pink|plum|powderblue|purple|rebeccapurple|red|rosybrown|royalblue|saddlebrown|salmon|sandybrown|seagreen|seashell|sienna|silver|skyblue|slateblue|slategray|slategrey|snow|springgreen|steelblue|tan|teal|thistle|tomato|turquoise|violet|wheat|white|whitesmoke|yellow|yellowgreen)\b",
            "description": "Named color (e.g., red, blue, white)",
            "severity": "warning",
        },
    }

    # Directories to skip
    SKIP_DIRS = {
        "node_modules",
        "build",
        "dist",
        ".git",
        "__pycache__",
        "coverage",
        ".next",
        "out",
        "public",
    }

    # File extensions to check
    CHECK_EXTENSIONS = {".css", ".scss", ".sass", ".less"}

    # Lines to skip (comments, etc.)
    SKIP_LINE_PATTERNS = [
        r"^\s*/\*",  # Start of multi-line comment
        r"^\s*\*",  # Inside multi-line comment
        r"^\s*\*/",  # End of multi-line comment
        r"^\s*//",  # Single-line comment
    ]

    def __init__(self, base_path: str = "."):
        self.base_path = Path(base_path).resolve()
        self.compiled_patterns = {
            name: re.compile(config["regex"], re.IGNORECASE)
            for name, config in self.PATTERNS.items()
        }
        self.skip_line_regex = [
            re.compile(pattern) for pattern in self.SKIP_LINE_PATTERNS
        ]

    def should_check_file(self, file_path: Path) -> bool:
        """Check if file should be scanned."""
        return file_path.suffix in self.CHECK_EXTENSIONS

    def should_skip_dir(self, dir_name: str) -> bool:
        """Check if directory should be skipped."""
        return dir_name in self.SKIP_DIRS

    def is_comment_line(self, line: str) -> bool:
        """Check if line is a comment."""
        for pattern in self.skip_line_regex:
            if pattern.match(line):
                return True
        return False

    def scan_file(self, file_path: Path) -> List[ColorMatch]:
        """Scan a single file for hard-coded colors."""
        matches = []

        try:
            with open(file_path, "r", encoding="utf-8", errors="ignore") as f:
                in_comment_block = False

                for line_num, line in enumerate(f, 1):
                    # Track multi-line comment blocks
                    if "/*" in line:
                        in_comment_block = True
                    if "*/" in line:
                        in_comment_block = False
                        continue

                    # Skip comment lines
                    if in_comment_block or self.is_comment_line(line):
                        continue

                    # Check for hard-coded colors
                    for pattern_name, pattern in self.compiled_patterns.items():
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
                                ColorMatch(
                                    file_path=display_path,
                                    line_number=line_num,
                                    line_content=line.rstrip(),
                                    color_type=pattern_name,
                                    color_value=(
                                        ", ".join(found)
                                        if isinstance(found, list)
                                        else found
                                    ),
                                )
                            )
        except Exception as e:
            print(f"Warning: Could not read {file_path}: {e}", file=sys.stderr)

        return matches

    def scan_directory(self, target_dir: str = None) -> List[ColorMatch]:
        """Scan directory recursively for hard-coded colors."""
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

    def generate_report(
        self, matches: List[ColorMatch], output_format: str = "json"
    ) -> str:
        """Generate a report in JSON or Markdown format."""
        import json
        from datetime import datetime

        # Group by file
        by_file: Dict[str, List[ColorMatch]] = {}
        for match in matches:
            if match.file_path not in by_file:
                by_file[match.file_path] = []
            by_file[match.file_path].append(match)

        # Summary by color type
        by_type: Dict[str, int] = {}
        for match in matches:
            by_type[match.color_type] = by_type.get(match.color_type, 0) + 1

        if output_format == "json":
            report = {
                "timestamp": datetime.now().isoformat(),
                "summary": {
                    "total_issues": len(matches),
                    "files_affected": len(by_file),
                    "by_color_type": by_type,
                },
                "issues": [
                    {
                        "file": match.file_path,
                        "line": match.line_number,
                        "color_type": match.color_type,
                        "color_value": match.color_value,
                        "line_content": match.line_content,
                        "severity": self.PATTERNS[match.color_type]["severity"],
                    }
                    for match in matches
                ],
            }
            return json.dumps(report, indent=2)

        elif output_format == "markdown":
            lines = [
                f"# Hard-coded Colors Detection Report",
                f"",
                f"**Generated:** {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}",
                f"",
                f"## Summary",
                f"",
                f"- **Total Issues:** {len(matches)}",
                f"- **Files Affected:** {len(by_file)}",
                f"",
                f"### Issues by Color Type",
                f"",
            ]

            for color_type, count in sorted(by_type.items(), key=lambda x: -x[1]):
                desc = self.PATTERNS[color_type]["description"]
                lines.append(f"- **{color_type}**: {count} occurrences ({desc})")

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
                lines.append(f"| Line | Color Type | Color Value | Severity |")
                lines.append(f"|------|------------|-------------|----------|")

                for match in file_matches:
                    severity = self.PATTERNS[match.color_type]["severity"]
                    lines.append(
                        f"| {match.line_number} | {match.color_type} | `{match.color_value}` | {severity} |"
                    )

                lines.append(f"")

            lines.extend(
                [
                    f"",
                    f"## How to Fix",
                    f"",
                    f"Replace hard-coded colors with CSS variables:",
                    f"",
                    f"```css",
                    f"/* ❌ Bad */",
                    f"color: #1a73e8;",
                    f"",
                    f"/* ✅ Good */",
                    f"color: var(--primary-blue);",
                    f"```",
                    f"",
                    f"See `frontend/src/styles/variables.css` for available CSS variables.",
                ]
            )

            return "\n".join(lines)

        return ""

    def print_results(self, matches: List[ColorMatch], verbose: bool = True) -> None:
        """Print results in a formatted way."""
        if not matches:
            print("✅ No hard-coded colors detected! All colors use CSS variables.")
            return

        # Group by file
        by_file: Dict[str, List[ColorMatch]] = {}
        for match in matches:
            if match.file_path not in by_file:
                by_file[match.file_path] = []
            by_file[match.file_path].append(match)

        print(f"\n{'='*60}")
        print(f"⚠️  Found {len(matches)} hard-coded color(s) in {len(by_file)} file(s)")
        print(f"{'='*60}\n")

        for file_path, file_matches in sorted(by_file.items()):
            print(f"📄 {file_path}")
            for match in file_matches:
                severity = self.PATTERNS[match.color_type]["severity"]
                symbol = "❌" if severity == "error" else "⚠️"
                desc = self.PATTERNS[match.color_type]["description"]
                print(
                    f"  {symbol} Line {match.line_number}: [{match.color_type}] {match.color_value}"
                )
                if verbose:
                    print(f"     {match.line_content[:100]}")
            print()

        # Summary by color type
        print(f"\n{'─'*60}")
        print("Summary by color type:")
        by_type: Dict[str, int] = {}
        for match in matches:
            by_type[match.color_type] = by_type.get(match.color_type, 0) + 1

        for color_type, count in sorted(by_type.items(), key=lambda x: -x[1]):
            desc = self.PATTERNS[color_type]["description"]
            print(f"  • {color_type}: {count} occurrences ({desc})")
        print(f"{'─'*60}\n")

        # Suggest CSS variables
        print("💡 Tip: Replace hard-coded colors with CSS variables:")
        print("   Example: color: var(--primary-blue);")
        print("   See: frontend/src/styles/variables.css (or create one)")
        print()


def main():
    parser = argparse.ArgumentParser(
        description="Detect hard-coded colors in CSS files",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
    # Scan frontend directory
    python scripts/detect_hardcoded_colors.py frontend

    # Scan specific directory
    python scripts/detect_hardcoded_colors.py frontend/src/components

    # Run in CI mode (exit with error code if issues found)
    python scripts/detect_hardcoded_colors.py --ci

    # Scan multiple directories
    python scripts/detect_hardcoded_colors.py frontend/src/components frontend/src/pages
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
        choices=["hex", "rgb", "rgba", "hsl", "hsla", "named", "all"],
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
    detector = CSSColorDetector()

    # Filter patterns if specific one requested
    if args.pattern != "all":
        if args.pattern == "hex":
            patterns_to_keep = {
                k: v for k, v in detector.PATTERNS.items() if k.startswith("hex")
            }
        else:
            patterns_to_keep = {args.pattern: detector.PATTERNS[args.pattern]}

        detector.PATTERNS = patterns_to_keep

    # Generate report if requested
    if args.report:
        report = detector.generate_report(all_matches, args.report)

        if args.output:
            with open(args.output, "w", encoding="utf-8") as f:
                f.write(report)
            print(f"✅ Report saved to {args.output}")
        else:
            print(report)
    else:
        # Print results
        detector.print_results(all_matches, verbose=not args.quiet)

    # Exit with appropriate code
    if args.ci and all_matches:
        sys.exit(1)

    sys.exit(0)

    # Scan all specified paths
    all_matches = []
    for path in args.paths:
        matches = detector.scan_directory(path)
        all_matches.extend(matches)

    # Print results
    detector.print_results(all_matches, verbose=not args.quiet)

    # Exit with appropriate code
    if args.ci and all_matches:
        sys.exit(1)

    sys.exit(0)


if __name__ == "__main__":
    main()
