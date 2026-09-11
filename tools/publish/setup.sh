#!/usr/bin/env bash
# One-time setup for the publishing pipeline: Python venv + pinned pandoc.
set -euo pipefail
cd "$(dirname "$0")"
if [ ! -x .venv/bin/python ]; then
  python3 -m venv .venv
fi
.venv/bin/pip install -q --upgrade pip
.venv/bin/pip install -q -r requirements.txt
.venv/bin/python publish.py setup
echo "ready: .venv/bin/python publish.py all <document>"
