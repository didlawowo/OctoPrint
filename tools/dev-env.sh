#!/usr/bin/env bash
# Prepare the repository's own environment, independent of Homebrew and activation.
# Compatible with the Bash 3.2 shipped on macOS.
set -euo pipefail

cd "$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd -P)"

if ! command -v uv >/dev/null 2>&1; then
    echo 'uv is required. On macOS: brew install uv. Then run task init-dev again.' >&2
    exit 127
fi

version="${ATELIER_PYTHON:-3.11}"
if [[ ! "$version" =~ ^3\.(10|11|12|13|14)(\.[0-9]+)?$ ]]; then
    echo 'PYTHON_VERSION must be a supported Python 3.10-3.14 version.' >&2
    exit 2
fi

venv="$PWD/.venv"
if [[ -L "$venv" || ( -e "$venv" && ! -d "$venv" ) ]]; then
    echo '.venv must be a directory, not a symlink or a regular file. Nothing was changed.' >&2
    exit 1
fi

# An already activated environment, Conda or project override must not redirect us.
# Never override registry/proxy settings: those belong to the user's environment.
unset VIRTUAL_ENV CONDA_PREFIX PYTHONHOME PYTHONPATH UV_PROJECT_ENVIRONMENT UV_PYTHON
unset UV_VENV_CLEAR UV_VENV_ALLOW_EXISTING

# Download/select uv's standalone Python, not the broken Homebrew interpreter.
# Resolve it before moving an old environment, so a download failure is harmless.
uv python install "$version"
managed="$(uv python find --managed-python --system --no-project "$version")"

valid_environment() {
    [[ -f "$venv/pyvenv.cfg" && -f "$venv/bin/activate" && -x "$venv/bin/python" ]] || return 1
    "$venv/bin/python" -I - "$managed" "$venv" <<'PY'
import sys
from pathlib import Path

expected_python, expected_prefix = map(Path, sys.argv[1:])
assert sys.prefix != sys.base_prefix, "Not a virtual environment"
assert Path(sys.prefix).resolve() == expected_prefix.resolve(), "Wrong environment"
assert Path(sys._base_executable).resolve() == expected_python.resolve(), "Wrong base Python"
PY
}

if valid_environment >/dev/null 2>&1; then
    echo 'Reusing the existing uv-managed .venv.'
else
    if [[ -d "$venv" ]]; then
        backup="${venv}.broken-$(date -u +%Y%m%dT%H%M%SZ)-$$"
        if [[ -e "$backup" || -L "$backup" ]]; then
            echo 'Backup destination already exists; refusing to overwrite it.' >&2
            exit 1
        fi
        mv "$venv" "$backup"
        printf 'Previous environment preserved at %s\n' "$backup"
    fi
    # No python -m venv/ensurepip and no --clear: uv creates a fresh environment.
    uv venv --no-project --managed-python --python "$managed" "$venv"
    if ! valid_environment; then
        echo 'Environment verification failed; no packages will be installed.' >&2
        exit 1
    fi
fi

printf 'Environment ready: %s/bin/python\n' "$venv"
