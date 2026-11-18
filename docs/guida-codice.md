# Guida al codice

Qui spieghiamo cosa fa ogni file sorgente e, soprattutto, **cosa non fa ancora**. Gli obiettivi completi del progetto sono descritti in [`plan.pdf`](plan.pdf): il codice di oggi ne copre solo una parte. 

## Il quadro generale

```text
ESP32-CAM (prototipo)                  Raspberry Pi 5 (prototipo)
camera di bordo → frame scartato       Camera Module 3 → JPG
comando seriale 'w' → WAKE (J2)        sensori del Pi → riga CSV
legge ALIVE                            GPS → coordinate nel JSON della foto
```

Ad oggi:

- il risveglio del Pi da parte dell'ESP è scritto e si può provare a mano;
- sul Pi si possono fare foto e leggere i sensori (con i limiti descritti sotto);
- **mancano** la lettura del BME280 sull'ESP, forecaster e decider, il protocollo ESP→Pi, il database, la modalità continuativa vera e propria e l'analisi delle immagini.

---

## Firmware ESP32: `firmware/esp32/`

### `src/main.cpp`

È un prototipo Arduino/PlatformIO per la **ESP32-CAM AI-Thinker**, che usiamo come scheda provvisoria. Funziona così:

- in `setup()` configura i pin (WAKE = GPIO14 in uscita, ALIVE = GPIO13 in ingresso con pulldown) e inizializza la camera;
- in `loop()` chiama `eventDetected()`, che per ora prende un frame e lo butta via restituendo sempre `false`, quindi **non ci sono wake automatici**;
- se dal monitor seriale arriva `w`, chiama `onEvent()`: se ALIVE è basso manda un impulso di 200 ms su WAKE e aspetta fino a 15 s che ALIVE diventi alto;
- tra due eventi ci sono almeno 30 s di cooldown.

Due cose da sapere:

- ALIVE alto significa solo che il GPIO17 del Pi è alto, non che Linux abbia finito il boot;
- se la camera non parte il firmware si blocca, e a quel punto non risponde nemmeno al comando `w`.

### `platformio.ini`

Board `esp32cam`, framework Arduino, monitor a 115200 baud e dipendenza Adafruit BME280. Per compilare e caricare il firmware si usa `pio run` e `pio run -t upload` dalla cartella `firmware/esp32/`; la guida [`setup-risveglio.md`](setup-risveglio.md) spiega la porta seriale e il bootloader.

### `src/bme_reader.h` e `src/bme_reader.cpp`

Driver del BME280 collegato all'ESP32. Usa la libreria Adafruit BME280 per Arduino, scaricata da PlatformIO in base a `lib_deps` in `platformio.ini`. `beginBme280(sda, scl, address)` inizializza il bus I²C e il sensore; `readBme280(...)` restituisce valori compensati in °C, percentuale e hPa. Il driver non è ancora chiamato da `main.cpp`: i pin I²C vanno stabiliti sulla scheda definitiva, perché sulla ESP32-CAM GPIO21 e GPIO22 sono impegnati dalla camera.

### `include/secrets.h.example`

Modello per le credenziali Wi-Fi. Il firmware attuale non lo usa.

---

## Software del Raspberry Pi: `raspberry_pi/`

```text
raspberry_pi/
├── capture_rpi.sh          script di avvio (a mano o da systemd)
├── requirements.txt        dipendenze Python
├── smartcam/               package Python
│   ├── capture_client.py   scatto delle foto
│   ├── sensors.py          lettura dei sensori → CSV
│   ├── gps_reader.py       GPS (NMEA)
│   └── photo_metadata.py   JSON accanto alle foto
├── systemd/
│   ├── insect-capture.service
│   └── .env.systemd.example
└── data/sensors.csv
```

I moduli del package usano import relativi, quindi vanno lanciati **come moduli** dalla cartella `raspberry_pi/`:

```bash
cd raspberry_pi
python3 -m smartcam.capture_client --oneshot
python3 -m smartcam.sensors
```

Lanciarli come file (`python3 smartcam/sensors.py`) non funziona. `capture_rpi.sh` si occupa già di tutto, impostando `PYTHONPATH`.

### `capture_rpi.sh`

È lo script da lanciare (a mano o da systemd). Nell'ordine:

1. si sposta nella root del progetto e aggiunge `raspberry_pi/` al `PYTHONPATH`;
2. carica `.env.systemd`, se esiste;
3. attiva l'ambiente Python (pyenv oppure un virtualenv);
4. lancia `smartcam.capture_client`;
5. con `--oneshot` lancia anche `smartcam.sensors`, **anche se la foto è fallita**;
6. esce con 1 se uno dei due è fallito.

Lo script non spegne il Pi: lo spegnimento lo chiede l'unità systemd.

### `smartcam/capture_client.py`

Costruisce la riga di comando per `rpicam-still` (o `libcamera-still` sui sistemi più vecchi) e salva un JPG in `static/uploads/images/`. Permette di scegliere risoluzione, qualità, zoom digitale, autofocus (con un profilo "macro" già pronto), tempo di esposizione e altri parametri: `--help` li elenca tutti.

Con `--oneshot` fa una foto ed esce, senza questa opzione scatta in ciclo ogni `--interval` secondi. Dopo lo scatto prova a leggere il GPS e, se trova un fix, salva latitudine e longitudine in un JSON accanto alla foto. Un errore del GPS o dei metadati viene scritto nel log ma non fa fallire lo scatto, perché la foto a quel punto è già salvata. Per ora non legge il BME280 e non analizza le immagini.

### `smartcam/sensors.py` e `data/sensors.csv`

`sensors.py` legge **una volta** tutti i sensori abilitati, uno dopo l'altro, e aggiunge una riga a `raspberry_pi/data/sensors.csv`. Tutta la configurazione sta nel dizionario `SENSORS` all'inizio del file: per ogni sensore si può abilitarlo o disabilitarlo e scegliere quale implementazione usare (ad esempio gpiozero o RPi.GPIO, oppure `dummy` per provare senza hardware).

- il GPS è letto con il modulo `gps_reader`; il BME280 è collegato all'ESP32 e non è letto da questo script;
- suolo e metano passano dall'ADC MCP3008, letto con la classe `MCP3008` di gpiozero.

Cose da tenere a mente:

- **pin, porte e canali sono esempi**, non il cablaggio di campo;
- i valori di suolo e metano sono tensioni grezze: la percentuale di umidità è una proporzione non calibrata e i ppm di metano non vengono calcolati;
- il BME280 è disabilitato, perché in campo i suoi dati arriveranno dall'ESP;
- il timestamp è quello della riga, non delle singole misure;
- se una lettura fallisce si ripiega sul dummy, ma il sensore viene contato come "ok" lo stesso 

Il CSV contiene per ora solo l'intestazione e una riga di prova. Più avanti ci finiranno i dati estratti dal database.

### `smartcam/gps_reader.py`

Apre la seriale e aspetta una frase GGA con un fix valido. Il parsing lo fa la libreria **pynmea2**, che controlla il checksum e accetta sia `$GPGGA` sia `$GNGGA`. Le frasi con qualità del fix 0 vengono scartate. Restituisce posizione, quota, satelliti, qualità del fix e HDOP.

### Driver BME280 dell'ESP32

Il vecchio modulo Python per leggere il BME280 sul Pi è stato rimosso: il sensore di progetto è collegato soltanto all'ESP32. Il driver attuale è `firmware/esp32/src/bme_reader.cpp`.

### `smartcam/photo_metadata.py`

Legge e scrive il JSON accanto a ogni foto (`foto.jpg` → `foto.json`) e definisce la struttura standard dei metadati.

### `systemd/insect-capture.service` e `systemd/.env.systemd.example`

`insect-capture.service` è l'unità systemd dell'app selettiva: al boot lancia `capture_rpi.sh --oneshot` e poi spegne il Pi **in ogni caso** (successo, errore o timeout di 3 minuti). Se esiste il file `/boot/firmware/maintenance` il servizio viene saltato e il Pi resta acceso per la manutenzione. Utente e percorsi sono quelli del nostro Pi (`/home/rpi5-03/tesi`) e vanno adattati. **Non va abilitata** durante le prove o per la raccolta continuativa.

`.env.systemd.example` è il modello per le variabili d'ambiente: va copiato nella root come `.env.systemd`. Per ora gli script usano solo le variabili di Python e `CAPTURE_INTERVAL`; le altre (modalità, fascia oraria, cadenza dei sensori) sono segnaposto per funzioni ancora da scrivere.

---

## Da dove viene il codice

All'inizio di ogni file c'è una sezione **"Provenienza"** che distingue le parti scritte da noi da quelle prese o adattate da fonti esterne, con il link alla fonte.

### Codice preso o adattato da fonti esterne

| Parte | Fonte |
|---|---|
| Pin e configurazione della camera in `main.cpp` | esempio *CameraWebServer* di Espressif (`camera_pins.h`, `CameraWebServer.ino`), Apache-2.0 |
| Lettura BME280 sul firmware ESP32 (`bme_reader.cpp`) | libreria [Adafruit BME280 per Arduino](https://github.com/adafruit/Adafruit_BME280_Library), MIT |
| Parsing NMEA (`gps_reader.py`) | libreria [pynmea2](https://github.com/Knio/pynmea2), MIT |
| Lettura MCP3008 (`sensors.py`) | classe `MCP3008` di [gpiozero](https://gpiozero.readthedocs.io/en/stable/api_spi.html), BSD |
| Ingressi digitali (`sensors.py`) | documentazione gpiozero e RPi.GPIO |
| Riga `SCRIPT_DIR=...` in `capture_rpi.sh` | risposta molto nota su Stack Overflow |
| Inizializzazione di pyenv | README di pyenv |
| Opzioni di `rpicam-still` | documentazione ufficiale Raspberry Pi |
| Direttive dell'unità systemd | documentazione di systemd |
### Sostituzioni con librerie esistenti

Abbiamo controllato, script per script, se una libreria o un esempio ufficiale potesse sostituire il nostro codice fatto a mano. Dove la sostituzione era piccola e riduceva i bug l'abbiamo fatta, altrimenti l'abbiamo solo annotata.

| Script | Parte | Decisione |
|---|---|---|
| `gps_reader.py` | parser NMEA scritto a mano | **sostituito** con pynmea2: aggiunge controllo del checksum, `$GNGGA` e qualità del fix |
| `sensors.py` | copia della lettura GPS | **sostituita** con `gps_reader` |
| `sensors.py` | MCP3008 via Adafruit (chip select errato) e via spidev a mano | **sostituiti** con `gpiozero.MCP3008` |
| `capture_client.py` | chiamata a `rpicam-still` con `subprocess` | **non sostituita**: [Picamera2](https://github.com/raspberrypi/picamera2) sarebbe l'alternativa ufficiale, ma richiede di riscrivere lo scatto e provarlo sulla camera vera ([issues.md #28](../issues.md)) |
| `photo_metadata.py` | JSON sidecar | **tenuto**: è codice minimo basato sulla libreria standard |
| `capture_rpi.sh`, unità systemd | | niente da sostituire |
| `main.cpp` | logica WAKE/ALIVE | niente da sostituire; il driver BME280 è separato in `bme_reader.cpp` e usa Adafruit BME280 per Arduino |

**Regola per il futuro:** quando copiamo o adattiamo codice da internet, aggiungiamo subito nel file un commento con l'URL, l'autore o il progetto, la licenza e cosa abbiamo modificato.
