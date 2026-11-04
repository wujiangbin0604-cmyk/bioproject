#!/usr/bin/env sh
set -eu
cd "$(CDPATH= cd -- "$(dirname -- "$0")" && pwd)"
if [ -x .venv-local/bin/python ]; then
  exec .venv-local/bin/python genescope.py "$@"
fi
if command -v python3.14 >/dev/null 2>&1; then
  exec python3.14 genescope.py "$@"
fi
exec python3 genescope.py "$@"
