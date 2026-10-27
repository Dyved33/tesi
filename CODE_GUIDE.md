# Guida ai componenti software

Questa guida descrive i file di codice e configurazione eseguibile del repository: a cosa servono, come collaborano e quali parti sono ancora prototipi. Il riferimento per obiettivi e architettura è `plan.pdf`; `main.pdf` è il riferimento scientifico per l’acquisizione selettiva biology-aware. Il codice presente non implementa ancora tutta l’architettura descritta in quei documenti.

## Quadro generale

```text
ESP32 (firmware attuale: ESP32-CAM)
  ├─ controlla Pi tramite WAKE/J2 e legge ALIVE
  └─ al momento non legge BME280 e non esegue forecaster/decider

Raspberry Pi
  ├─ capture_rpi.sh → capture_client.py → rpicam-still → JPG + sidecar JSON
  └─ in modalità oneshot: sensors.py → una riga CSV → systemd poweroff
```

Il BME280 di campo è previsto sul solo ESP32, ma non è ancora implementato il collegamento dati ESP→Pi. Per questo `sensors.py` ha la lettura BME disabilitata per impostazione predefinita e il client di cattura non cerca di leggerlo via I2C sul Pi.

## Firmware ESP32 (`esp32/`)

### `src/main.cpp`

Firmware Arduino per una scheda AI-Thinker ESP32-CAM. Definisce il pinout della camera integrata, `PIN_WAKE` (GPIO14) e `PIN_ALIVE` (GPIO13).

- `piAlive()` legge ALIVE: HIGH indica che il rail osservato è presente; LOW è interpretato come Pi in halt.
- `pulseJ2()` porta WAKE alto per 200 ms e poi lo riporta basso. L’optoisolatore non è previsto; il circuito di interfaccia tra GPIO14 e i pad J2 è ancora da definire e verificare elettricamente.
- `waitForAlive()` controlla ALIVE ogni 250 ms fino al timeout.
- `ensurePiOn()` non invia un secondo impulso se ALIVE è già alto; altrimenti invia WAKE e attende la risposta.
- `initCamera()` configura il sensore della ESP32-CAM e sceglie buffer PSRAM/DRAM secondo la memoria rilevata.
- `eventDetected()` acquisisce e rilascia un frame, ma restituisce sempre `false`: l’inferenza è un punto di estensione, non una funzione implementata.
- `onEvent()` applica un cooldown di 30 secondi e prova ad assicurare che il Pi sia acceso.
- `setup()` inizializza USB-seriale, pin e camera; `loop()` controlla l’evento e accetta `w` dal monitor seriale USB del computer (115200 baud) per una prova manuale.

Nella versione attuale `eventDetected()` restituisce sempre false: il Pi può essere svegliato manualmente dal monitor USB-seriale, mentre il rilevamento automatico è ancora da implementare. La possibile AI-Thinker rileverà l’evento; le fotografie di campo restano affidate alle fotocamere del Raspberry.

Il primo evento è accettato subito; i successivi sono separati da un cooldown di 30 secondi.

### `platformio.ini`

Seleziona la piattaforma Espressif32, framework Arduino, board `esp32cam`, velocità seriale e opzioni di build. L’ambiente e il pinout vanno rivalutati quando sarà scelta la scheda ESP definitiva. I flag per PSRAM e partizione devono restare compatibili con quella scheda.

Comandi dalla cartella `esp32/`: `pio run` compila, `pio run -t upload` carica il firmware e `pio device monitor` apre la seriale a 115200 baud.

### `include/secrets.h.example`

Esempio di intestazione per credenziali Wi-Fi, da copiare in `secrets.h` solo se il firmware ne avrà bisogno. Il firmware attuale non usa Wi-Fi: WAKE e ALIVE funzionano tramite GPIO e il test manuale usa la seriale USB. Non inserire credenziali reali nei file tracciati da Git.

## Cattura e sensori sul Raspberry (`scripts and configuration/`)

### `capture_rpi.sh`

Wrapper shell che imposta la directory del progetto, carica `.env.systemd` se presente e attiva un ambiente Python tramite pyenv o `PYENV_ROOT/bin/activate`. Con argomenti inoltra il comando a `capture_client.py`; senza argomenti avvia la cattura ripetuta usando `CAPTURE_INTERVAL`. Se riceve `--oneshot`, dopo lo scatto lancia anche `sensors.py`.

Il wrapper non esegue da solo `poweroff`: nel ciclo selettivo lo fa `insect-capture.service` dopo il completamento con successo del comando. Lo script usa `set -e`: se la cattura termina con errore, la shell si interrompe prima di salvare la riga sensori. In modalità `--oneshot`, se la cattura riesce, esegue `sensors.py` e segnala l’errore se fallisce una delle fasi. Senza argomenti avvia il client in modalità continua con `CAPTURE_INTERVAL` (default 30 secondi); con argomenti inoltra le opzioni al client. `.env.systemd` può fornire impostazioni specifiche dell’installazione e dell’ambiente Python.

### `capture_client.py`

Interfaccia a riga di comando per acquisire immagini con `rpicam-still` (o `libcamera-still` come fallback). `build_parser()` definisce modalità oneshot/continua e parametri di ripresa: dimensioni, qualità, zoom, profilo standard/macro, autofocus, shutter, denoise e controlli immagine. `resolve_af_settings()` combina il profilo con gli override AF; `build_center_roi()` calcola una regione centrale per lo zoom digitale; `capture_photo()` esegue il comando, salva il JPG sotto `static/uploads/images/` e aggiorna un sidecar JSON con timestamp, impostazioni e fix GPS disponibile. `main()` gestisce percorsi, ciclo e intervallo. Il client non legge il BME280: il BME di campo è sull’ESP e il protocollo di inoltro non è ancora disponibile.

### `sensors.py`

Lettore **oneshot**: legge una volta i sensori collegati al Pi, appende un record a `scripts and configuration/data/sensors.csv` e termina. Non è un processo residente. In modalità selettiva viene eseguito dopo lo scatto; in modalità continuativa può essere richiamato a intervalli regolari.

`SENSORS` configura abilitazione, pin, porte UART, canali ADC e backend. `CSV_HEADER` definisce lo schema. Gli helper `read_*` accedono a GPS NMEA, ingresso digitale acqua e MCP3008/sensori analogici. I backend alternativi includono librerie Adafruit, `spidev`, `RPi.GPIO`/`gpiozero` e dummy. `read_sensor_with_fallback()` registra gli errori e tenta il fallback configurato; `main()` legge i dispositivi abilitati in sequenza, costruisce timestamp ed esiti, aggiunge la riga e restituisce `0` se tutte le letture abilitate riescono o `1` in caso di errori. Scrive comunque i valori disponibili. È un burst sequenziale, non una misura simultanea.

| Sensore | Implementazioni | Limiti |
|---|---|---|
| BME280 | Adafruit I²C, SMBus, dummy | I²C locale solo al banco; in campo è collegato all’ESP |
| GPS | `pyserial`, NMEA `$GPGGA`, dummy | Non riconosce ancora `$GNGGA`; attende un fix fino al timeout |
| Acqua | `gpiozero`, `RPi.GPIO`, dummy | Polarità e significato del livello dipendono dal cablaggio |
| Suolo | MCP3008 Adafruit, `spidev` raw, ingresso digitale, dummy | Il valore analogico richiede calibrazione |
| Metano | MCP3008 Adafruit, `spidev` raw, ingresso digitale DO, dummy | Tensione ≠ ppm senza calibrazione del sensore |

Il BME locale è disattivato per impostazione predefinita: la routine SMBus è un segnaposto che verifica il chip ID ma non calcola misure compensate. I dummy sono solo dati fittizi/vuoti, non misure. La riga CSV contiene timestamp ISO UTC, campi sensore e liste di esiti. Il timestamp del record non sostituisce il timestamp di misura; per i dati BME inoltrati dall’ESP dovranno essere conservati sia il tempo di misura sia quello di ricezione. La calibrazione di suolo e metano, i pin, la polarità e le soglie vanno verificati sul cablaggio reale. Il CSV presente è uno schema/campione iniziale, non un database definitivo.

Per eseguirlo manualmente sul Pi: attivare il virtualenv e lanciare `python3 "scripts and configuration/sensors.py"`; controllare poi il record aggiunto al CSV. Prima del campo allineare `SENSORS` all’hardware e lasciare disabilitata la lettura I²C locale del BME.

### `data/sensors.csv`

CSV iniziale con intestazione e riga di esempio per controllare i nomi delle colonne. `sensors.py` scrive nel file in questa cartella; prima di una raccolta reale occorre decidere se archiviare/ruotare il CSV iniziale e verificare lo schema rispetto ai dati acquisiti.

### `insect-capture.service`

Unità systemd `oneshot`: avvia il wrapper quando il Pi completa il boot e, se il processo termina correttamente, `ExecStartPost` chiede al sistema di eseguire `poweroff`. `User`, directory del progetto, file ambiente e percorso dello script sono esempi dipendenti dall’installazione e vanno aggiornati sul Raspberry. Non abilitarla per la modalità continuativa.

### `.env.systemd.example`

Modello delle variabili lette dal servizio/wrapper: modalità, intervallo foto e sensori, e selezione dell’ambiente Python. Va copiato come `.env.systemd` nella root del progetto sul Pi e personalizzato; non contiene segreti.

### Guida consolidata di configurazione

`config$awakening.md` contiene la sequenza di configurazione Pi/ESP, le prove fisiche ordinate e l’archivio delle guide precedenti. La sezione storica Pi 4 descrive GPIO3/UART e non va applicata al Pi 5.

## File di esclusione Git

La `.gitignore` di root esclude file di lavoro Aider, output PlatformIO e impostazioni/cache di VS Code. `esp32/.gitignore` esclude l’ambiente di build `.pio` e `include/secrets.h`, che contiene eventuali credenziali locali; il file da versionare è invece `secrets.h.example`.

La cartella `backend/__pycache__/` contiene bytecode Python generato automaticamente, non sorgenti da modificare a mano.

## Moduli Python di supporto (`backend/`)

- `gps_reader.py`: apre la porta seriale, attende una frase `$GPGGA`, converte coordinate gradi/minuti in decimali ed estrae quota e satelliti. Restituisce `None` su timeout/errore; se manca pyserial produce una struttura dummy. Non gestisce ancora `$GNGGA` e non controlla tutte le condizioni di qualità del fix.
- `bme_reader.py`: helper I²C per prove al banco. `auto` preferisce Adafruit, poi SMBus; l’indirizzo previsto è `0x76`/`0x77`. Adafruit fornisce letture compensate; SMBus controlla solo il chip ID e restituisce temperature/umidità/pressione vuote. Il dummy non è una misura. Non è il lettore del BME di campo e `capture_client.py` non lo chiama.
- `photo_metadata.py`: crea, carica e salva sidecar JSON accanto alle immagini (`foto.jpg` → `foto.json`) senza toccare gli EXIF. Il record base comprende GPS, misure, timestamp, impostazioni camera e letture sensori; valori mancanti restano `null`. `create_metadata_for_capture()` prepara una struttura, ma il client attuale compone direttamente parte dei metadati.
- `__init__.py`: marca `backend` come package Python e documenta lo scopo dei moduli.

## Fonti tecniche e riferimenti

**Limite di provenienza:** il repository e la cronologia Git non registrano URL, tutorial o commit esterni da cui siano stati copiati/adattati i sorgenti. I link seguenti sono documentazione ufficiale che corrisponde alle API e ai protocolli presenti, aggiunta per consentire di verificarli; non è possibile attestare che siano le fonti originali usate quando il codice fu scritto. Per ricostruire la provenienza precisa serve una conferma di chi ha scritto i file o la cronologia esterna (appunti, PR, cronologia browser).

### ESP32 e firmware

- [Espressif `esp32-camera`: README ed esempio di acquisizione frame](https://github.com/espressif/esp32-camera/blob/master/README.md) — configurazione `camera_config_t`, inizializzazione, acquisizione e rilascio del framebuffer.
- [Espressif Arduino-ESP32: API GPIO](https://docs.espressif.com/projects/arduino-esp32/en/latest/api/gpio.html) — modalità input/output, pull-down, `digitalRead()` e `digitalWrite()` usati per ALIVE/WAKE.
- [PlatformIO: `platformio.ini`](https://docs.platformio.org/en/latest/projectconf.html) e [piattaforma Espressif32](https://docs.platformio.org/en/latest/platforms/espressif32.html) — configurazione ambiente, board e framework.
- [Arduino: `loop()`](https://docs.arduino.cc/language-reference/en/structure/sketch/loop/) — modello `setup()`/`loop()` del firmware.

### Sensori e cattura Raspberry Pi

- [Adafruit CircuitPython BME280](https://docs.circuitpython.org/projects/bme280/en/latest/) e [guida Adafruit I2C su Raspberry Pi/Linux](https://learn.adafruit.com/circuitpython-on-raspberrypi-linux/i2c-sensors-and-devices) — accesso al BME280 tramite I2C; nel progetto l’accesso diretto dal Pi resta solo per prove.
- [gpiozero: dispositivi di input digitali](https://gpiozero.readthedocs.io/en/stable/api_input.html) e [dispositivi SPI/MCP3008](https://gpiozero.readthedocs.io/en/latest/api_spi.html) — ingresso acqua e letture analogiche tramite ADC.
- [pySerial: documentazione e API `Serial`](https://pyserial.readthedocs.io/en/latest/) — porta UART e lettura delle frasi NMEA dal GPS.
- [GPSD: descrizione delle frasi NMEA, inclusa GGA](https://gpsd.io/gpsd.html) — contesto dei campi posizione/fix usati dal parser.
- [Raspberry Pi: documentazione software camera e `rpicam-still`](https://www.raspberrypi.com/documentation/computers/camera_software.html) — opzioni CLI di cattura richiamate dal client.
- [systemd: unità service, `ExecStart` e `ExecStartPost`](https://www.freedesktop.org/software/systemd/man/latest/systemd.service.html) — semantica dell’unità oneshot.
