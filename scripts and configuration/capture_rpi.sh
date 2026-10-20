#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
DEFAULT_PROJECT_DIR="$(cd "${SCRIPT_DIR}/.." && pwd)"
PROJECT_DIR="${PROJECT_DIR:-$DEFAULT_PROJECT_DIR}"
cd "${PROJECT_DIR}"

# Optional per-host overrides.
if [[ -f "${PROJECT_DIR}/.env.systemd" ]]; then
  # shellcheck disable=SC1091
  source "${PROJECT_DIR}/.env.systemd"
fi

if [[ -z "${PYENV_ROOT:-}" ]]; then
  if [[ -d "$HOME/.pyenv" ]]; then
    PYENV_ROOT="$HOME/.pyenv"
  elif [[ -d "$HOME/pyenv" ]]; then
    PYENV_ROOT="$HOME/pyenv"
  fi
fi

if [[ -n "${PYENV_ROOT:-}" && -d "$PYENV_ROOT" ]]; then
  export PYENV_ROOT
  export PATH="$PYENV_ROOT/bin:$PATH"
fi

if command -v pyenv >/dev/null 2>&1; then
  eval "$(pyenv init -)"
  if [[ -n "${PYENV_VERSION:-}" ]]; then
    pyenv shell "$PYENV_VERSION"
  fi
elif [[ -n "${PYENV_ROOT:-}" && -f "${PYENV_ROOT}/bin/activate" ]]; then
  # Fallback: PYENV_ROOT points to a regular virtualenv folder.
  # shellcheck disable=SC1090
  source "${PYENV_ROOT}/bin/activate"
else
  echo "No Python env found. Configure either pyenv or a venv at \$PYENV_ROOT/bin/activate." >&2
  exit 1
fi

# Default capture interval for unattended mode; override in .env.systemd.
CAPTURE_INTERVAL="${CAPTURE_INTERVAL:-30}"

if [[ $# -gt 0 ]]; then
  exec python -m backend.capture_client "$@"
fi

exec python -m backend.capture_client --interval "$CAPTURE_INTERVAL"
