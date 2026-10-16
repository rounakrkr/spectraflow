#!/usr/bin/env bash
# macOS / Linux launcher. Double-click in Finder, or run ./SpectraFlow.command
cd "$(dirname "$0")" || exit 1

# Prefer this project's own venv, then a sibling venv, then system Python
if [ -x ".venv/bin/python" ]; then
    PY=".venv/bin/python"
elif [ -x "../.venv/bin/python" ]; then
    PY="../.venv/bin/python"
elif command -v python3 >/dev/null 2>&1; then
    PY="python3"
else
    echo "Python 3 not found. Install it from https://www.python.org/downloads/ and retry."
    read -r -p "Press Enter to close..." _
    exit 1
fi

"$PY" main.py
status=$?
if [ $status -ne 0 ]; then
    echo
    echo "SpectraFlow exited with an error (code $status)."
    read -r -p "Press Enter to close..." _
fi
exit $status
