# Altro che si può fare per la tesi

## Documentazione del codice

- Sphinx. Le docstring sono già in stile Google, quindi bastano le estensioni `sphinx.ext.autodoc` e `sphinx.ext.napoleon`. In `conf.py` bisogna aggiungere `raspberry_pi/` a `sys.path` e impostare `autodoc_mock_imports = ["gpiozero", "serial", "pynmea2"]`: così la documentazione si genera anche su PC, senza le librerie hardware.
- Doxygen. In `firmware/esp32/main/main.ino` i commenti delle funzioni vanno arricchiti con `@brief`, `@param` e `@return`.
- Breathe. Fa entrare la documentazione Doxygen del firmware nello stesso sito Sphinx, così c'è un'unica documentazione per tutto il progetto.

## Test e integrazione continua

- Test con pytest. Si possono testare su PC le parti che non dipendono dall'hardware: `parse_gga`, `build_center_roi`, `resolve_af_settings`, `in_daily_window`, `storage.append_rows` e `esp_link.sync()`. Per quest'ultimo basta un finto ESP su una pseudo-seriale (`pty.openpty()`), come abbiamo fatto a mano nella revisione del 27/11.
- GitHub Actions. Un workflow che a ogni push lancia i test e compila il firmware con `arduino-cli` in tutte e due le versioni (`DIAGNOSTICA` 0 e 1), così ci accorgiamo subito se un commit rompe la compilazione (è già successo: a novembre due `.ino` nella stessa cartella impedivano di compilare).

## Licenza

Manca un file `LICENSE`. Il codice usa o adatta parti con licenza MIT (pynmea2, SparkFun BME280), BSD (gpiozero) e Apache-2.0 (pin della camera dall'esempio CameraWebServer di Espressif). Chiedono tutte di mantenere l'avviso di copyright.

## Diario delle prove al banco

Un file (es. `docs/diario-prove.md`) in cui annotare ogni prova: data, configurazione hardware, pin, alimentazione, misure, foto e risultato. Sarà la base del capitolo sperimentale della tesi.

## Versioni del codice

Usare i tag git per segnare le tappe principali (es. `v0.1-banco`, `v0.2-box`, `v1.0-campo`). Così nella tesi si può citare la versione esatta del codice usata per ogni esperimento.

## Uniformità della lingua

Commenti, documenti e messaggi di log sono in italiano; i nomi delle funzioni sono in italiano nel firmware e in inglese nel codice Python, e le colonne dei CSV sono in inglese. Conviene decidere una regola e scriverla in `docs/guida-codice.md`.
