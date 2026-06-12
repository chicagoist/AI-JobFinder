#!/bin/bash
# Static type checker for Gemini JobAgent
# Usage: ./check_types.sh
#        ./check_types.sh --strict  (for stricter checks)

set -e

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
cd "$SCRIPT_DIR"

STRICT=""
if [ "$1" = "--strict" ]; then
    STRICT="--disallow-untyped-defs --disallow-incomplete-defs"
    echo "=== Running mypy in STRICT mode ==="
else
    echo "=== Running mypy (standard mode) ==="
fi

mypy job_agent/ $STRICT --config-file mypy.ini 2>&1

if [ $? -eq 0 ]; then
    echo ""
    echo "✅ All type checks passed!"
else
    echo ""
    echo "❌ Type errors found. Review and fix them."
    exit 1
fi
