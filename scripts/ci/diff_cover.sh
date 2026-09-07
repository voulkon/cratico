#!/usr/bin/env bash
# Run diff-cover with repo-standard flags, parameterized so other flows
# (different thresholds, branches, coverage files) can reuse it.
#
# Usage: diff_cover.sh [coverage_xml] [compare_branch] [fail_under]
# Env overrides: DIFF_COVER_FORMAT (default markdown:diff-cover.md)
set -euo pipefail

COVERAGE_XML="${1:-coverage.xml}"
COMPARE_BRANCH="${2:-origin/main}"
FAIL_UNDER="${3:-1}"
FORMAT="${DIFF_COVER_FORMAT:-markdown:diff-cover.md}"

poetry run diff-cover "$COVERAGE_XML" \
  --compare-branch="$COMPARE_BRANCH" \
  --fail-under="$FAIL_UNDER" \
  --format "$FORMAT"
