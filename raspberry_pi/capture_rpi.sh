#!/usr/bin/env bash
# Punto di ingresso dello scatto, da lanciare a mano o tramite systemd.
# Carica le impostazioni locali (.env.systemd), attiva il virtualenv e lancia
# smartcam.capture_client con gli argomenti ricevuti.
# Lo spegnimento del Pi NON lo fa questo script: lo chiede l'unità systemd.
#
# Uso:
#   bash raspberry_pi/capture_rpi.sh --oneshot         # app selettiva: una foto + ESP + sensori
#   bash raspberry_pi/capture_rpi.sh                   # app continuativa (cadenze da .env.systemd)
#   bash raspberry_pi/capture_rpi.sh --oneshot --no-esp   # prova senza ESP collegato
#
# Provenienza: scritto da noi. La riga che calcola SCRIPT_DIR è la classica
# risposta di Stack Overflow:
# https://stackoverflow.com/questions/59895/how-do-i-get-the-directory-where-a-bash-script-is-located-from-within-the-script

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_DIR="${PROJECT_DIR:-$(cd "${SCRIPT_DIR}/.." && pwd)}"

# Impostazioni di questo Pi, se il file esiste. "set -a" esporta tutte le
# variabili lette, altrimenti Python non le vedrebbe.
if [[ -f "${PROJECT_DIR}/.env.systemd" ]]; then
  set -a
  # shellcheck disable=SC1091
  source "${PROJECT_DIR}/.env.systemd"
  set +a
fi

VENV_DIR="${VENV_DIR:-${SCRIPT_DIR}/.venv}"
if [[ ! -f "${VENV_DIR}/bin/activate" ]]; then
  echo "Virtualenv non trovato in ${VENV_DIR}: vedi docs/setup-risveglio.md" >&2
  exit 1
fi
# shellcheck disable=SC1091
source "${VENV_DIR}/bin/activate"

# Il package smartcam sta in raspberry_pi/.
cd "${SCRIPT_DIR}"
exec python -m smartcam.capture_client "$@"
