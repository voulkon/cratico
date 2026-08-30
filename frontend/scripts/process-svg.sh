#!/usr/bin/env bash
# =============================================================================
# process-svg.sh — Apply the Crati SVG processing pipeline to a raw SVG.
#
# Usage:
#   ./process-svg.sh <input.svg> [output.svg] [--stroke-width N] [--strip-stroke-width]
#
# Transformations applied (in order):
#   1. fill="black"          → fill="currentColor"
#   2. stroke="black"        → stroke="currentColor"
#   3. stroke="#<hex>"       → stroke="currentColor"
#   4. fill-opacity="..."    → removed
#   5. stroke-opacity="..."  → removed
#   6. stroke-width="<N>"    → stroke-width="<value>"   (if --stroke-width given)
#   7. stroke-width="..."    → removed                  (if --strip-stroke-width)
#
# Examples:
#   # Process a Canva SVG for use as favicon:
#   ./process-svg.sh raw.svg public/favicon.svg --stroke-width 4
#
#   # Process for use as logo (CSS-controlled stroke-width):
#   ./process-svg.sh raw.svg src/assets/logo.svg --strip-stroke-width
# =============================================================================

set -euo pipefail

# ---- Parse arguments -------------------------------------------------------
INPUT=""
OUTPUT=""
STROKE_WIDTH=""
STRIP_STROKE=false

while [[ $# -gt 0 ]]; do
  case "$1" in
    --stroke-width)
      STROKE_WIDTH="$2"
      shift 2
      ;;
    --strip-stroke-width)
      STRIP_STROKE=true
      shift
      ;;
    -*)
      echo "Unknown option: $1" >&2
      exit 1
      ;;
    *)
      if [[ -z "$INPUT" ]]; then
        INPUT="$1"
      elif [[ -z "$OUTPUT" ]]; then
        OUTPUT="$1"
      else
        echo "Too many arguments: $1" >&2
        exit 1
      fi
      shift
      ;;
  esac
done

if [[ -z "$INPUT" ]]; then
  echo "Usage: $0 <input.svg> [output.svg] [--stroke-width N] [--strip-stroke-width]" >&2
  exit 1
fi

if [[ -z "$OUTPUT" ]]; then
  OUTPUT="$INPUT"  # in-place
fi

if [[ ! -f "$INPUT" ]]; then
  echo "Input file not found: $INPUT" >&2
  exit 1
fi

# ---- Processing pipeline ---------------------------------------------------

SED_SCRIPT=(
  # 1-3: Hardcoded colours → currentColor
  -e 's/fill="black"/fill="currentColor"/g'
  -e 's/stroke="black"/stroke="currentColor"/g'
  -e 's/stroke="#[0-9A-Fa-f]{3,6}"/stroke="currentColor"/g'

  # 4-5: Strip opacity attributes (they fight with currentColor)
  -e 's/ fill-opacity="[^"]*"//g'
  -e 's/ stroke-opacity="[^"]*"//g'
)

if [[ -n "$STROKE_WIDTH" ]]; then
  # 6: Set all stroke-widths to a specific value
  SED_SCRIPT+=(-e "s/stroke-width=\"[0-9.]+\"/stroke-width=\"$STROKE_WIDTH\"/g")
elif $STRIP_STROKE; then
  # 7: Strip stroke-width entirely (let CSS control it)
  SED_SCRIPT+=(-e 's/ stroke-width="[^"]*"//g')
fi

sed -E "${SED_SCRIPT[@]}" "$INPUT" > "${OUTPUT}.tmp" && mv "${OUTPUT}.tmp" "$OUTPUT"

echo "✔ Processed: $INPUT → $OUTPUT"
