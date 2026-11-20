# Guida al codice

Qui spieghiamo cosa fa ogni file sorgente e, soprattutto, **cosa non fa ancora**. Gli obiettivi completi del progetto sono descritti in [`plan.pdf`](plan.pdf): il codice di oggi ne copre solo una parte. 

## Il quadro generale

```text
ESP32-CAM (prototipo)                  Raspberry Pi 5 (prototipo)
camera di bordo → eventDetected() ┐    Camera Module 3 → JPG
comando seriale 'w' ──────────────┴─►  WAKE (J2): il Pi si accende
legge ALIVE ◄────────────────────────  GPIO17 alto quando il Pi è acceso
BME280 → misura al risveglio          sensori del Pi → riga CSV
misure → UART verso il Pi ──────────►  (ricezione ancora da scrivere)
                                       GPS → coordinate nel JSON della foto
```

Ad oggi:

- il risveglio del Pi da parte dell'ESP è scritto e si può provare a mano;
- sul Pi si possono fare foto e leggere i sensori (con i limiti descritti sotto);
- l'ESP acquisisce i frame della camera, sveglia il Pi (a mano, per ora) e gli manda le misure del BME280 via UART, ma sul Pi nessun programma le riceve ancora;
- **mancano** il rilevamento sulla camera dell'ESP, forecaster e decider, il database, la modalità continuativa vera e propria e l'analisi delle immagini.

---

## Firmware ESP32: `firmware/esp32/`

Il firmware gira su una **ESP32-CAM** (pinout AI-Thinker) ed è scritto con il framework Arduino su PlatformIO. Collegamenti, scelta dei pin e protocollo con il Pi sono descritti nella [guida di configurazione](setup-risveglio.md#2-esp32-cam-camera-bme280-e-collegamento-con-il-pi); qui spieghiamo come è organizzato il codice.

### Cosa fa

Sulla scheda gira un unico firmware con tre funzioni:

1. **risveglio su evento**: acquisisce di continuo frame dalla camera di bordo e, quando vede qualcosa (ad esempio un insetto che passa davanti alla camera), sveglia il Pi;
2. **risveglio manuale**, per le prove: comando `w` dal monitor seriale USB;
3. **misure del BME280**: quando il Pi si accende fa una misura, aspetta che il Pi finisca il boot e gliela manda via UART; poi gli manda una misura al minuto finché resta acceso.

Il rilevamento vero e proprio **non c'è ancora**: `eventDetected()` acquisisce il frame ma restituisce sempre `false`.

### Come è organizzato `src/main.cpp`

Il file è diviso in blocchi, separati da commenti:

| Blocco | Funzioni | Cosa fanno |
|---|---|---|
| Risveglio del Pi | `piAlive()`, `pulseJ2()`, `waitForAlive()`, `ensurePiOn()`, `onEvent()` | leggono ALIVE, danno l'impulso di 200 ms su WAKE e aspettano che il Pi si accenda. `onEvent()` è il punto d'ingresso comune a evento e comando `w`, e applica un cooldown di 30 s |
| Camera e rilevamento | `initCamera()`, `eventDetected()` | configurano la camera (pin AI-Thinker, JPEG, risoluzione in base alla PSRAM) e acquisiscono un frame. In `eventDetected()` va scritto l'algoritmo di rilevamento |
| BME280 | `initBme()`, `serviceBme()`, `takeForcedMeasurement()`, `measure()` | inizializzano il sensore (riprovando ogni 10 s se non risponde) e fanno una misura in forced mode |
| UART verso il Pi | `servicePiLink()`, `sendReading()` | seguono ALIVE: quando sale aprono la UART e fanno la misura del risveglio, dopo `PI_BOOT_DELAY_MS` la mandano, poi mandano una misura ogni `BME_PERIOD_MS`; quando scende chiudono la UART |

In cima al file ci sono tutte le costanti da cui dipende il comportamento: pin, indirizzo e frequenza I2C, ritardo di invio dopo il boot del Pi, periodo delle misure, durata dell'impulso, timeout e cooldown. Per cambiare un collegamento o una tempistica basta modificare lì.

### Il ciclo principale

`setup()` porta WAKE basso (così il PC817 non chiude J2 per sbaglio), configura ALIVE come ingresso, lascia chiusa la UART verso il Pi, apre il bus I2C del BME280 e inizializza la camera. Se la camera non parte, il firmware lo scrive nel log e continua senza rilevamento.

`loop()` gira circa 5 volte al secondo e a ogni giro:

1. `serviceBme()`: se il BME280 non è pronto, prova a inizializzarlo;
2. `servicePiLink()`: gestisce UART e invio delle misure in base ad ALIVE;
3. `eventDetected()`: acquisisce un frame e, se c'è un evento, chiama `onEvent()`;
4. legge i comandi dal monitor seriale USB: `w` per il wake manuale, `r` per stampare una misura del BME280.

### Limiti noti

- ALIVE alto significa solo che il GPIO17 del Pi è alto, non che Linux abbia finito il boot: per questo la misura del risveglio parte dopo un ritardo fisso, da tarare sul Pi vero.
- La UART va solo dall'ESP al Pi (non avanzano pin per la ricezione): il Pi non può chiedere misure, le riceve e basta. Se il programma sul Pi parte dopo l'invio, la misura del risveglio va persa.
- L'ESP non ha un orologio vero: ogni misura viaggia con la sua "età" in millisecondi e l'ora la ricostruisce il Pi.
- Durante l'attesa di ALIVE (fino a 15 s) il `loop()` è bloccato ([issues.md #24](../issues.md)).
- Il firmware compila con PlatformIO senza warning, ma **non è ancora stato provato sulla scheda** ([issues.md #27](../issues.md)).

### `platformio.ini`

Board `esp32cam`, framework Arduino, PSRAM attiva, tabella delle partizioni `huge_app.csv` (lascia più spazio al programma), monitor a 115200 baud. L'unica dipendenza esterna è la libreria SparkFun BME280, che PlatformIO scarica da sola alla prima compilazione. Non usiamo la Adafruit BME280 perché va in conflitto con il driver della camera (dettagli nella [guida di configurazione](setup-risveglio.md#24-bme280)).

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

Il vecchio modulo Python per leggere il BME280 sul Pi è stato rimosso: il sensore di progetto è collegato soltanto all'ESP32. La lettura è in `firmware/esp32/src/main.cpp` (libreria SparkFun BME280).

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
| Inizializzazione e misura del BME280 in `main.cpp` | esempi `Example2_I2CAddress` e `Example6_LowPower` della libreria [SparkFun BME280](https://github.com/sparkfun/SparkFun_BME280_Arduino_Library), MIT |
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
| `main.cpp` | logica WAKE/ALIVE | niente da sostituire. Per il BME280 usiamo la libreria [SparkFun BME280](https://github.com/sparkfun/SparkFun_BME280_Arduino_Library) invece di scrivere un driver (la Adafruit va in conflitto con il driver della camera) |

**Regola per il futuro:** quando copiamo o adattiamo codice da internet, aggiungiamo subito nel file un commento con l'URL, l'autore o il progetto, la licenza e cosa abbiamo modificato.
