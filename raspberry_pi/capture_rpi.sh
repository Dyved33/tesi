#!/usr/bin/env bash
# Punto di ingresso per lo scatto, da lanciare a mano o tramite systemd.
# In ordine: entra nella root del progetto, carica le impostazioni locali
# (.env.systemd), attiva l'ambiente Python e lancia smartcam.capture_client.
# Con --oneshot, dopo la foto, scrive anche una riga di sensori nel CSV
# (smartcam.sensors). I sensori vengono letti anche se la foto fallisce.
# Lo spegnimento del Pi NON lo fa questo script: lo chiede l'unità systemd,
# che lo spegne sia se lo script riesce sia se fallisce.
#
# Uso:
#   bash raspberry_pi/capture_rpi.sh --oneshot      # una foto + sensori
#   bash raspberry_pi/capture_rpi.sh                # foto ogni CAPTURE_INTERVAL secondi
#   bash raspberry_pi/capture_rpi.sh --interval 60  # altre opzioni passate al client
#
# Provenienza:
# - Struttura dello script scritta da noi.
# - La riga che calcola SCRIPT_DIR con dirname "${BASH_SOURCE[0]}" è la
#   classica risposta di Stack Overflow per trovare la cartella dello script:
#   https://stackoverflow.com/questions/59895/how-do-i-get-the-directory-where-a-bash-script-is-located-from-within-the-script
# - L'inizializzazione di pyenv (PYENV_ROOT, PATH, eval "$(pyenv init -)")
#   segue il README ufficiale di pyenv:
#   https://github.com/pyenv/pyenv#set-up-your-shell-environment-for-pyenv

# -e: esce al primo comando che fallisce; -u: errore se si usa una variabile
# non definita; -o pipefail: una pipe fallisce se fallisce un suo pezzo.
set -euo pipefail

# Cartella di questo script e root del progetto (la cartella sopra),
# a meno che PROJECT_DIR non sia già impostata dall'esterno.
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
DEFAULT_PROJECT_DIR="$(cd "${SCRIPT_DIR}/.." && pwd)"
PROJECT_DIR="${PROJECT_DIR:-$DEFAULT_PROJECT_DIR}"
cd "${PROJECT_DIR}"

# Il package Python "smartcam" sta in raspberry_pi/: lo aggiungiamo al path
# di Python, così "python -m smartcam.xxx" funziona da qualsiasi cartella.
export PYTHONPATH="${SCRIPT_DIR}${PYTHONPATH:+:${PYTHONPATH}}"

# Impostazioni specifiche di questo Pi, se il file esiste.
if [[ -f "${PROJECT_DIR}/.env.systemd" ]]; then
  # shellcheck disable=SC1091
  source "${PROJECT_DIR}/.env.systemd"
fi

# Se PYENV_ROOT non è impostata, proviamo le due posizioni più comuni.
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

# Caso 1: pyenv installato -> lo inizializziamo e scegliamo la versione.
# Caso 2: PYENV_ROOT punta in realtà a un normale virtualenv -> lo attiviamo.
# Altrimenti non sappiamo quale Python usare e ci fermiamo.
if command -v pyenv >/dev/null 2>&1; then
  eval "$(pyenv init -)"
  if [[ -n "${PYENV_VERSION:-}" ]]; then
    pyenv shell "$PYENV_VERSION"
  fi
elif [[ -n "${PYENV_ROOT:-}" && -f "${PYENV_ROOT}/bin/activate" ]]; then
  # shellcheck disable=SC1090
  source "${PYENV_ROOT}/bin/activate"
else
  echo "No Python env found. Configure either pyenv or a venv at \$PYENV_ROOT/bin/activate." >&2
  exit 1
fi

# Intervallo tra le foto in modalità continua; si cambia in .env.systemd.
CAPTURE_INTERVAL="${CAPTURE_INTERVAL:-30}"

# Controlliamo se tra gli argomenti c'è --oneshot.
ONESHOT=false
for arg in "$@"; do
  if [[ "$arg" == "--oneshot" ]]; then
    ONESHOT=true
    break
  fi
done

# Con "set -e" un comando che fallisce terminerebbe subito lo script: con
# "|| VAR=$?" catturiamo l'exit code e decidiamo noi cosa fare.
CAPTURE_EXIT=0
if [[ $# -gt 0 ]]; then
  # Ci sono argomenti: li passiamo così come sono al client.
  python -m smartcam.capture_client "$@" || CAPTURE_EXIT=$?
else
  # Nessun argomento: modalità continua con l'intervallo configurato.
  python -m smartcam.capture_client --interval "$CAPTURE_INTERVAL" || CAPTURE_EXIT=$?
fi

# In modalità oneshot (ciclo dell'app selettiva) leggiamo anche i sensori,
# anche se la foto è fallita: sono comunque dati utili.
if [[ "$ONESHOT" == "true" ]]; then
  echo "[capture_rpi] Running smartcam.sensors for environmental CSV logging..."
  SENSORS_EXIT=0
  python -m smartcam.sensors || SENSORS_EXIT=$?
  if [[ $CAPTURE_EXIT -ne 0 || $SENSORS_EXIT -ne 0 ]]; then
    echo "[capture_rpi] capture exit=${CAPTURE_EXIT}, sensors exit=${SENSORS_EXIT}" >&2
    exit 1
  fi
fi

exit "$CAPTURE_EXIT"
