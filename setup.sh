#!/usr/bin/env sh
# Builds the venv, then hands off to install.py.
# Usage:  ./setup.sh                       set up
#         ./setup.sh --uninstall           tear down
#         ./setup.sh --uninstall --purge   tear down, no questions asked
set -eu

ROOT=$(CDPATH= cd -- "$(dirname -- "$0")" && pwd)
VENV="$ROOT/.venv"
PY="$VENV/bin/python"
INSTALLER="$ROOT/install.py"

# Echoes the path to a usable interpreter, or fails (which set -e turns into an
# exit, as long as callers assign the result to a variable first).
find_python() {
	for candidate in python3 python; do
		if command -v "$candidate" >/dev/null 2>&1 &&
			"$candidate" -c 'import sys; sys.exit(0 if sys.version_info >= (3, 9) else 1)' 2>/dev/null; then
			command -v "$candidate"
			return 0
		fi
	done
	echo "Python 3.9+ is required but was not found on PATH." >&2
	return 1
}

if [ "${1:-}" = "--uninstall" ]; then
	shift
	if [ -x "$PY" ]; then
		"$PY" "$INSTALLER" --uninstall "$@" || true
	else
		echo "No venv found; removing the scheduled job with the system Python."
		SYSTEM_PYTHON=$(find_python)
		"$SYSTEM_PYTHON" "$INSTALLER" --uninstall "$@" || true
	fi

	# Done last: install.py runs from inside the venv.
	if [ -d "$VENV" ]; then
		rm -rf "$VENV"
		echo "  removed .venv"
	fi
	exit 0
fi

if [ ! -x "$PY" ]; then
	echo "Creating virtual environment in .venv"
	SYSTEM_PYTHON=$(find_python)
	"$SYSTEM_PYTHON" -m venv "$VENV"
fi

echo "Installing dependencies"
"$PY" -m pip install --quiet --upgrade pip
"$PY" -m pip install --quiet -r "$ROOT/requirements.txt"
echo

exec "$PY" "$INSTALLER" "$@"
