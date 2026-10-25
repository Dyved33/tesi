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
- `pulseJ2()` porta WAKE alto per 200 ms e poi lo riporta basso. Il circuito PC817 è previsto per chiudere momentaneamente i pad J2.
- `waitForAlive()` controlla ALIVE ogni 250 ms fino al timeout.
- `ensurePiOn()` non invia un secondo impulso se ALIVE è già alto; altrimenti invia WAKE e attende la risposta.
- `initCamera()` configura il sensore della ESP32-CAM e sceglie buffer PSRAM/DRAM secondo la memoria rilevata.
- `eventDetected()` acquisisce e rilascia un frame, ma restituisce sempre `false`: l’inferenza è un punto di estensione, non una funzione implementata.
- `onEvent()` applica un cooldown di 30 secondi e prova ad assicurare che il Pi sia acceso.
- `setup()` inizializza seriale, pin e camera; `loop()` controlla l’evento e accetta `w` dalla seriale per una prova manuale.

Quindi, nella versione attuale non c’è un trigger automatico: il Pi può essere svegliato manualmente da seriale, mentre il percorso automatico attende ancora la logica di evento. La camera sull’ESP è una dipendenza temporanea del prototipo; il piano assegna le fotografie di campo alle fotocamere del Raspberry.

Nota sul cooldown: `lastEventMs` parte da zero, quindi una richiesta nei primi 30 secondi dall’avvio viene scartata come cooldown. Tenerne conto nei test manuali.

### `platformio.ini`

Seleziona la piattaforma Espressif32, framework Arduino, board `esp32cam`, velocità seriale e opzioni di build. L’ambiente e il pinout vanno rivalutati quando sarà scelta la scheda ESP definitiva. I flag per PSRAM e partizione devono restare compatibili con quella scheda.

Comandi dalla cartella `esp32/`: `pio run` compila, `pio run -t upload` carica il firmware e `pio device monitor` apre la seriale a 115200 baud.

### `include/secrets.h.example`

Esempio di intestazione per credenziali Wi-Fi, da copiare in `secrets.h` solo se il firmware ne avrà bisogno. Il firmware attuale non usa Wi-Fi: WAKE e ALIVE funzionano tramite GPIO e il test manuale usa la seriale USB. Non inserire credenziali reali nei file tracciati da Git.

## Cattura e sensori sul Raspberry (`scripts and configuration/`)

### `capture_rpi.sh`

Wrapper shell che imposta la directory del progetto, carica `.env.systemd` se presente e attiva un ambiente Python tramite pyenv o `PYENV_ROOT/bin/activate`. Con argomenti inoltra il comando a `capture_client.py`; senza argomenti avvia la cattura ripetuta usando `CAPTURE_INTERVAL`. Se riceve `--oneshot`, dopo lo scatto lancia anche `sensors.py`.

Il wrapper non esegue da solo `poweroff`: nel ciclo selettivo lo fa `insect-capture.service` dopo il completamento con successo del comando. Un errore di cattura o sensori deve essere gestito prima che il servizio completi il ciclo.

### `capture_client.py`

Interfaccia a riga di comando per acquisire immagini con `rpicam-still` (o `libcamera-still` come fallback). `build_parser()` definisce modalità oneshot/continua e parametri di ripresa; `resolve_af_settings()` combina il profilo standard/macro con le opzioni AF; `build_center_roi()` calcola una regione centrale per lo zoom digitale; `capture_photo()` esegue la CLI, salva il JPG sotto `static/uploads/images/` e aggiorna un sidecar JSON con il fix GPS disponibile; `main()` gestisce ciclo e intervallo.

Non legge direttamente il BME280: i dati di campo dovranno arrivare dall’ESP quando esisterà il protocollo. Le opzioni di camera sono singole impostazioni di acquisizione; la selezione e l’uso della seconda fotocamera non sono ancora orchestrati da questo client.

### `sensors.py`

Lettore oneshot che raccoglie i sensori collegati al Pi e aggiunge una riga a `scripts and configuration/data/sensors.csv`. `SENSORS` contiene flag, pin, porte, canali ADC e backend scelti; `CSV_HEADER` definisce lo schema; gli helper `read_*` accedono a GPS NMEA, ingresso digitale acqua, MCP3008/sensori analogici o implementazioni dummy; `read_sensor_with_fallback()` registra errori e tenta l’alternativa configurata; `main()` legge i dispositivi abilitati e scrive il burst.

Il BME locale è disattivato per impostazione predefinita: le funzioni Adafruit/SMBus rimangono utili solo per prove al banco. La routine SMBus nel file è un segnaposto e non calcola misure compensate, quindi non va usata per dati scientifici. Anche sensori analogici, calibrazione in percentuale/ppm, pin e soglie sono configurazioni da adattare ai modelli e al cablaggio effettivi. Le righe CSV attuali sono campioni/schema iniziale, non un database completo.

### `data/sensors.csv`

CSV iniziale con intestazione e riga di esempio per controllare i nomi delle colonne. `sensors.py` scrive nel file in questa cartella; prima di una raccolta reale occorre decidere se archiviare/ruotare il CSV iniziale e verificare lo schema rispetto ai dati acquisiti.

### `insect-capture.service`

Unità systemd `oneshot`: avvia il wrapper quando il Pi completa il boot e, se il processo termina correttamente, `ExecStartPost` chiede al sistema di eseguire `poweroff`. `User`, directory del progetto, file ambiente e percorso dello script sono esempi dipendenti dall’installazione e vanno aggiornati sul Raspberry. Non abilitarla per la modalità continuativa.

### `.env.systemd.example`

Modello delle variabili lette dal servizio/wrapper: modalità, intervallo foto e sensori, e selezione dell’ambiente Python. Va copiato come `.env.systemd` nella root del progetto sul Pi e personalizzato; non contiene segreti.

### `awakening.md`

Nota storica sul risveglio via GPIO3 per Raspberry Pi 4. Il documento è marcato come legacy e non descrive il circuito scelto per il Pi 5, che usa i pad J2 tramite optoisolatore e una linea ALIVE.

## File di esclusione Git

La `.gitignore` di root esclude file di lavoro Aider, output PlatformIO e impostazioni/cache di VS Code. `esp32/.gitignore` esclude l’ambiente di build `.pio` e `include/secrets.h`, che contiene eventuali credenziali locali; il file da versionare è invece `secrets.h.example`.

La cartella `backend/__pycache__/` contiene bytecode Python generato automaticamente, non sorgenti da modificare a mano.

## Moduli Python di supporto (`backend/`)

- `gps_reader.py`: apre la porta seriale configurata, cerca frasi `$GPGGA`, estrae latitudine/longitudine, quota e satelliti, e converte le coordinate gradi-minuti in gradi decimali. Il parser attuale riconosce il prefisso `GPGGA`; ricevitori che emettono `GNGGA` richiedono un’estensione. Il dummy è un fallback senza dati GPS reali.
- `bme_reader.py`: helper per lettura BME280 via I2C Adafruit, mantenuto per prove al banco. L’opzione SMBus verifica l’ID ma restituisce campi vuoti senza compensazione; il dummy non è una misura. Il client di cattura non usa questo modulo per il BME di campo.
- `photo_metadata.py`: crea, legge e scrive sidecar JSON accanto alle immagini. Definisce la struttura base per posizione, misure, timestamp e impostazioni; non modifica gli EXIF dell’immagine. `create_metadata_for_capture()` è un helper disponibile, mentre il client corrente compone parte dei metadati direttamente.
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
