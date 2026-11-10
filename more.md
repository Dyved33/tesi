# Altro che si può fare per la tesi

Idee per migliorare il repository oltre ai problemi elencati in [issues.md](issues.md).

## Documentazione del codice

- **Sphinx.** Le docstring sono già in stile Google, quindi bastano le estensioni `sphinx.ext.autodoc` e `sphinx.ext.napoleon`. In `conf.py` bisogna aggiungere `raspberry_pi/` a `sys.path` e impostare `autodoc_mock_imports = ["board", "gpiozero", "RPi", "smbus2", "bme280"]`: così la documentazione si genera anche su PC, senza le librerie hardware.
- **Doxygen.** In `firmware/esp32/src/main.cpp` i commenti delle funzioni vanno arricchiti con `@brief`, `@param` e `@return`.
- **Breathe.** Fa entrare la documentazione Doxygen del firmware nello stesso sito Sphinx, così c'è un'unica documentazione per tutto il progetto.

## Test e integrazione continua

- **Test con pytest.** Si possono testare su PC le parti che non dipendono dall'hardware: `_parse_gga`, `build_center_roi`, `resolve_af_settings` e le funzioni dei metadati.
- **GitHub Actions.** Un workflow che a ogni push lancia i test e compila il firmware con `pio run`. In questo modo il problema #27 (firmware mai compilato) si risolve da solo e resta controllato nel tempo.

## Licenza

Manca un file `LICENSE`. Il codice include parti con licenza MIT (Adafruit, pynmea2, RPi.bme280) e Apache-2.0 (esempio CameraWebServer di Espressif). La licenza Apache-2.0 chiede di mantenere l'avviso di copyright.

## Diario delle prove al banco

Un file (es. `docs/diario-prove.md`) in cui annotare ogni prova: data, configurazione hardware, pin, alimentazione, misure, foto e risultato. Sarà la base del capitolo sperimentale della tesi.

## Versioni del codice

Usare i tag git per segnare le tappe principali (es. `v0.1-banco`, `v0.2-box`, `v1.0-campo`). Così nella tesi si può citare la versione esatta del codice usata per ogni esperimento.

## Uniformità della lingua

Commenti e documenti sono in italiano, mentre i messaggi di log sono in inglese. Conviene decidere una regola e scriverla in `docs/guida-codice.md`.
