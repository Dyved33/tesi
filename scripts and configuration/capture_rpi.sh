#!/usr/bin/env bash
# Entry point used manually or by systemd. It enters the project directory,
# loads host-specific environment settings, activates Python, then runs the
# photo client. In oneshot mode it also records one sensor CSV row; the
# systemd unit (not this wrapper) requests poweroff after successful exit.
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

# Detect oneshot mode
ONESHOT=false
for arg in "$@"; do
  if [[ "$arg" == "--oneshot" ]]; then
    ONESHOT=true
    break
  fi
done

if [[ $# -gt 0 ]]; then
  # Explicit CLI arguments select oneshot or customized continuous capture.
  python "${SCRIPT_DIR}/capture_client.py" "$@"
  CAPTURE_EXIT=$?
else
  # No CLI arguments means continuous mode with the configured interval.
  python "${SCRIPT_DIR}/capture_client.py" --interval "$CAPTURE_INTERVAL"
  CAPTURE_EXIT=$?
fi

# In oneshot mode (energy-aware cycle), also run sensors.py for CSV logging
if [[ "$ONESHOT" == "true" ]]; then
  # With `set -e`, an unsuccessful camera client exits before sensor logging.
  echo "[capture_rpi] Running sensors.py for environmental CSV logging..."
  python "${SCRIPT_DIR}/sensors.py"
  SENSORS_EXIT=$?
  # Exit with error if either failed
  if [[ $CAPTURE_EXIT -ne 0 || $SENSORS_EXIT -ne 0 ]]; then
    exit 1
  fi
fi

exit $CAPTURE_EXIT
