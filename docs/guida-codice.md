# Guida al codice

Qui spieghiamo cosa fa ogni file sorgente e cosa non fa ancora. Gli obiettivi completi sono in [`plan.pdf`](plan.pdf): il codice di oggi ne copre una parte.

## Il quadro generale

```text
ESP32-S3-CAM (sempre acceso)               Raspberry Pi 5 (acceso solo quando serve)

BME280 ──I2C──► misura ogni minuto
                buffer di 48 ore
movimento (OV3660) ── WAKE (PC817 → J2) ──► il Pi si accende
ALIVE ◄────────────── GPIO17 alto ─────────  systemd lancia capture_rpi.sh --oneshot
                                             1. foto con rpicam-still
UART ◄─── HELLO / TIME / GET / ACK ──────── 2. esp_link scarica misure ed eventi
     ───► INFO / M / E / END / OK ────────►     → bme280.csv, camera_events.csv
                                             3. sensors legge GPS, acqua, suolo, metano → sensors.csv
                                             4. CSV accanto alla foto con tutti i metadati
                                             5. poweroff → ALIVE torna basso
```

Cosa funziona oggi:

- il wake del Pi dall'ESP con il comando `w` (provato il 27/11);
- il rilevamento del movimento con la OV3660 che accende il Pi (compilato, da provare sulla scheda);
- la raccolta di misure del BME280 ed eventi della camera sull'ESP e lo scaricamento sul Pi (provato su PC con un ESP simulato, da provare sulle schede);
- foto, sensori del Pi e CSV dei metadati (provati su PC con una camera finta e senza sensori);
- la modalità continuativa con cadenze separate per foto e sensori e la fascia oraria.

Cosa manca: forecaster e decider, analisi delle immagini, trasferimento al server, accesso remoto.

---

## Firmware ESP32: `firmware/esp32/main/main.ino`

Il firmware è un unico sketch per Arduino IDE, diviso in sezioni numerate:

| Sezione | Contenuto |
|---|---|
| 1. configurazione | pin (collegamento con il Pi, BME280, camera), soglie del movimento, tempi, dimensione del buffer |
| 2. buffer | buffer circolare di misure ed eventi non ancora confermati dal Pi |
| 3. BME280 | inizializzazione, misura in forced mode, scansione I2C |
| 4. camera e movimento | inizializzazione della OV3660 e confronto dei fotogrammi |
| 5. collegamento con il Pi | WAKE, ALIVE e protocollo UART |
| 6. diagnostica | comandi di prova del cablaggio, compilati solo con `DIAGNOSTICA 1` |
| 7. comandi dal monitor USB | `w`, `r`, `s`, `i`, `h` |
| 8. `setup()` e `loop()` | |

Prima c'erano `main.ino` e `main_diagnostica.ino`, due copie dello stesso codice nella stessa cartella. Così non compilava, perché Arduino IDE unisce tutti i `.ino` di una cartella e `setup()` e `loop()` risultavano definite due volte. In più ogni modifica andava fatta due volte. Adesso c'è un file solo, e l'interruttore `#define DIAGNOSTICA` in cima decide se compilare anche i comandi di prova. Abbiamo anche tolto la configurazione PlatformIO: usiamo solo Arduino IDE.

I tipi (`EsitoMisura`, `Record`, `StatoWake`) sono tutti in alto, prima delle funzioni, perché Arduino IDE genera da solo i prototipi delle funzioni e li mette prima della prima funzione: lì i tipi devono essere già definiti.

### `loop()`

Gira ogni 10 ms e chiama quattro funzioni, nessuna delle quali si blocca:

1. `bmeAggiorna()`: se il sensore non è pronto riprova a inizializzarlo ogni 10 s; ogni minuto fa una misura e la mette nel buffer, anche se il sensore manca (con l'esito di errore);
2. `cameraAggiorna()`: ogni 500 ms prende un fotogramma e lo confronta con lo sfondo; se c'è un evento lo mette nel buffer e chiede il wake;
3. `linkAggiorna()`: segue ALIVE, apre o chiude la UART, porta avanti l'impulso di WAKE e risponde ai comandi del Pi;
4. `leggiComandiUsb()`: comandi dal monitor.

Prima l'attesa di ALIVE dopo il wake fermava tutto per 15 secondi. Adesso il wake è una piccola macchina a stati (`RIPOSO → IMPULSO → ATTESA_ALIVE`).

### Buffer

Un array di 2880 `Record` usato come buffer circolare (circa 68 KB di RAM). Un record è una misura (`'M'`: temperatura, umidità, pressione, esito) o un evento della camera (`'E'`: percentuale di blocchi cambiati, differenza media, flag "ha acceso il Pi"). Misure ed eventi condividono il numero progressivo `seq`, così un solo `ACK` del Pi conferma entrambi. `bufferConferma(seq)` toglie i record fino a `seq` compreso, e la chiama solo l'`ACK`. A buffer pieno si sovrascrive il record più vecchio e lo si conta come perso.

### BME280

`bmeInizializza()` legge il registro dell'ID chip (0xD0) agli indirizzi 0x76 e 0x77 e inizializza la libreria SparkFun sul primo che risponde. Il controllo dell'ID lo facciamo noi perché la libreria accetta anche il BMP280, che non ha l'umidità: in quel caso l'esito delle misure è `MISURA_SENZA_UMIDITA` e l'umidità resta vuota.

`bmeMisura()` usa il forced mode: il sensore fa una conversione e torna a dormire. Con l'oversampling x1 la conversione dura al massimo 9,3 ms, quindi aspettiamo 10 ms e poi il bit "measuring", con un limite di 100 ms. Se il limite scade (per esempio il cavo si è staccato e il registro si legge 0xFF) il sensore viene segnato come non pronto e reinizializzato. I valori fuori dai limiti del datasheet vengono scartati.

### Camera e movimento

`cameraInizializza()` configura la OV3660 con il driver `esp_camera` compreso nel pacchetto ESP32 di Arduino: scala di grigi 160×120, due framebuffer in PSRAM, sempre l'ultimo fotogramma disponibile. La configurazione della camera passa da un bus I2C (SCCB) sulla porta 1, mentre il BME280 usa `Wire` sulla porta 0, quindi i due bus non si disturbano. Se l'inizializzazione fallisce si riprova ogni 30 s, e intanto il resto del firmware continua a funzionare.

`cameraConfronta()` divide l'immagine in 192 blocchi da 10×10 pixel, calcola la luminosità media di ognuno e la confronta con lo sfondo. Lo sfondo si aggiorna a ogni fotogramma con una media mobile (`SFONDO_ALFA = 0.1`), che assorbe i cambi di luce lenti ma non un insetto che passa in pochi fotogrammi. Le soglie e la logica sono descritte in [setup-risveglio.md](setup-risveglio.md#25-rilevamento-del-movimento).

La Camera Module 3 non si può usare qui: ha un'interfaccia MIPI CSI-2 che l'ESP32-S3 non ha.

### Collegamento con il Pi

Il protocollo è in [protocollo-uart.md](protocollo-uart.md). Due dettagli:

- la UART si apre solo con ALIVE alto e, quando si chiude, il pin TX torna un ingresso per non alimentare il Pi in halt attraverso il suo RXD;
- `linkRichiediWake()` non manda l'impulso se ALIVE è già alto, perché un'altra pressione di J2 a Pi acceso lo spegnerebbe.

### Diagnostica

Con `DIAGNOSTICA 1` si aggiungono i comandi `p`, `a`, `l`, `u`, `c` (tabella in [setup-risveglio.md](setup-risveglio.md#23-comandi-dal-monitor)). Il più utile per il problema del BME280 è `p`: legge SDA e SCL con il pulldown interno attivo, e da lì si capisce se il modulo è collegato e alimentato senza bisogno del multimetro.

Il firmware compila senza warning in tutte e due le versioni (provato il 27/11/2026 con il core Arduino-ESP32 3.3 e l'opzione `-Wall`). Non è ancora stato caricato sulla scheda. Usa il 32% della RAM, quasi tutta per il buffer, e il 12% della flash.

---

## Software del Raspberry Pi: `raspberry_pi/`

```text
raspberry_pi/
├── capture_rpi.sh            avvio (a mano o da systemd)
├── requirements.txt          dipendenze Python
├── smartcam/                 package Python
│   ├── capture_client.py     programma principale: foto + raccolta dati
│   ├── esp_link.py           scarica dall'ESP misure del BME280 ed eventi della camera
│   ├── sensors.py            sensori collegati al Pi
│   ├── gps_reader.py         GPS (NMEA)
│   ├── storage.py            scrittura dei CSV
│   └── config.py             percorsi, porte, cadenze
├── systemd/
│   ├── insect-capture.service
│   └── .env.systemd.example
└── data/                     dati raccolti (non nel repository)
```

I moduli usano import relativi, quindi vanno lanciati come moduli dalla cartella `raspberry_pi/`:

```bash
cd raspberry_pi
.venv/bin/python -m smartcam.capture_client --oneshot
.venv/bin/python -m smartcam.esp_link
.venv/bin/python -m smartcam.sensors
.venv/bin/python -m smartcam.gps_reader
```

### `capture_rpi.sh`

Carica `.env.systemd` (con `set -a`, altrimenti le variabili non arrivano a Python), attiva il virtualenv in `VENV_DIR` e lancia `smartcam.capture_client` con gli stessi argomenti. Non spegne il Pi: lo fa l'unità systemd.

### `smartcam/capture_client.py`

È il programma principale e ha due modalità.

Con `--oneshot` (app selettiva) fa, in quest'ordine:

1. la foto, per prima perché è il motivo per cui il Pi è stato acceso;
2. lo scambio con l'ESP (`esp_link.sync()`);
3. la lettura dei sensori (`sensors.read_and_save()`);
4. il CSV accanto alla foto, con impostazioni di scatto, `sha256` del file, evento della camera che ha acceso il Pi, ultima misura del BME280, esito dello scambio con l'ESP e lettura dei sensori.

Senza `--oneshot` (app continuativa) ripete i passi 2-3 ogni `--sensor-interval` secondi e 1-4 ogni `--interval` secondi, solo dentro la fascia `DAILY_WINDOW_START`-`DAILY_WINDOW_END`. Le scadenze avanzano di un periodo fisso sul tempo monotono, quindi la durata dello scatto non fa slittare la cadenza.

Lo scatto lancia `rpicam-still` con un timeout, così una camera bloccata non blocca il ciclo. Abbiamo valutato la libreria [Picamera2](https://github.com/raspberrypi/picamera2), che terrebbe la camera aperta nel ciclo continuo (senza rifare ogni volta accensione e autofocus) e darebbe i metadati di scatto (esposizione, guadagno, posizione della lente). Per ora restiamo su `rpicam-still` perché lo scatto andrebbe riscritto e provato sulla camera vera; se lo faremo, quei metadati andranno aggiunti al CSV della foto. Il nome del file è l'ora UTC con i millisecondi più l'indice della camera (`--camera`, per quando avremo la seconda). `--zoom` fa un ritaglio centrale con `--roi`: non aggiunge dettaglio. Il profilo `macro` cambia solo i valori di default dell'autofocus. `--no-esp` serve per provare al banco senza ESP.

### `smartcam/esp_link.py`

Implementa il lato Pi del [protocollo UART](protocollo-uart.md). `sync()` manda `HELLO`, `TIME`, `GET`, scrive le misure in `data/bme280.csv` e gli eventi della camera in `data/camera_events.csv`, solo quelli non ancora presenti (controllando la coppia boot/seq nelle ultime righe dei due file) e solo dopo che i file sono su disco manda `ACK`. Se una riga arriva corrotta l'ACK si ferma al record prima, così l'ESP la rimanda al giro dopo. `latest_measurement()` e `latest_wake_event()` danno l'ultima misura e l'ultimo evento che ha acceso il Pi, che finiscono nel CSV della foto. Gli errori non generano eccezioni: finiscono nel campo `error` del risultato e poi nel CSV della foto.

### `smartcam/sensors.py`

Legge una volta tutti i sensori configurati nel dizionario `SENSORS` e aggiunge una riga a `data/sensors.csv`. Rispetto alla versione precedente:

- il sensore dell'acqua usa `is_active` di gpiozero: prima il valore veniva invertito due volte e "bagnato" usciva al contrario;
- un sensore che va in errore finisce in `sensors_failed` con il suo messaggio, invece di essere sostituito dal dummy e contato come "ok". Il dummy si sceglie solo esplicitamente (`"dummy": True`) e ha la sua colonna;
- sono state tolte le varianti con RPi.GPIO, che sul Pi 5 non funziona;
- la percentuale di umidità del suolo si calcola solo dopo aver inserito le due tensioni di calibrazione (`volt_dry`, `volt_wet`), e funziona sia per le sonde in cui la tensione sale con l'acqua sia per quelle in cui scende;
- per il metano salviamo la tensione: i ppm richiedono la calibrazione in aria pulita. Il modulo MQ-4 esce a 5 V, quindi tra sensore e MCP3008 c'è un partitore (10 kΩ + 18 kΩ, valori in `SENSORS`) e il codice riporta la lettura alla tensione vera del sensore;
- `python -m smartcam.sensors --calibra-suolo` stampa la media di 10 letture della sonda del suolo: serve a trovare `volt_dry` e `volt_wet` (prova 16 in [setup-risveglio.md](setup-risveglio.md#c-sensori-del-pi)).

Pin, canali e porte sono quelli di [pinout.md](pinout.md), ma i modelli dei sensori non sono ancora stati scelti.

### `smartcam/gps_reader.py`

Apre la seriale del GPS (UART2, `/dev/ttyAMA2`) e aspetta al massimo 5 s una frase GGA con un fix valido. Il parsing lo fa pynmea2, che controlla il checksum e accetta `$GPGGA` e `$GNGGA`; le frasi con qualità 0 vengono scartate perché pynmea2 restituirebbe coordinate 0,0. Nessun fix non è un errore (restituisce `None`), mentre porta o librerie mancanti sì.

### `smartcam/storage.py`

Funzioni per scrivere i CSV. `append_rows()` crea il file con l'intestazione, fa `fsync` prima di tornare e, se trova un file con intestazione diversa, lo rinomina invece di mescolare colonne diverse. `write_sidecar()` scrive il CSV di una foto. `read_tail()` legge solo la fine di un file, che cresce per mesi. `clock_synced()` chiede a `timedatectl` se l'orologio del Pi è sincronizzato con NTP; il risultato finisce nelle colonne `*clock_synced` di tutti i CSV. Il formato dei file è in [dati-csv.md](dati-csv.md).

### `systemd/insect-capture.service` e `.env.systemd.example`

L'unità dell'app selettiva: al boot lancia `capture_rpi.sh --oneshot` e poi spegne il Pi in ogni caso (successo, errore o timeout di 3 minuti). Se esiste `/boot/firmware/maintenance` viene saltata. Non aspetta più la rete, che allungava il boot senza motivo. Utente e percorsi (`rpi5-03`, `/home/rpi5-03/progetto`) vanno adattati al proprio Pi.

`.env.systemd.example` è il modello del file con percorsi, cadenze, fascia oraria e porte seriali; va copiato nella root del progetto come `.env.systemd`.

---

## Da dove viene il codice

All'inizio di ogni file c'è una sezione "Provenienza" che distingue le parti scritte da noi da quelle prese o adattate da fonti esterne.

| Parte | Fonte |
|---|---|
| Inizializzazione e forced mode del BME280 (`main.ino`, sezione 3) | esempi `Example2_I2CAddress` e `Example6_LowPower` della libreria [SparkFun BME280](https://github.com/sparkfun/SparkFun_BME280_Arduino_Library), MIT |
| Tempi di conversione, registro ID, limiti di misura | datasheet Bosch BME280 (BST-BME280-DS002) |
| Pin e configurazione della camera (`main.ino`, sezione 4) | `camera_pins.h` e `CameraWebServer.ino` dell'esempio CameraWebServer di Arduino-ESP32 (modello `ESP32S3_EYE`), Apache-2.0 |
| Checksum del protocollo UART | stesso schema delle frasi NMEA 0183 |
| Parsing NMEA (`gps_reader.py`) | libreria [pynmea2](https://github.com/Knio/pynmea2), MIT |
| Lettura MCP3008 e ingressi digitali (`sensors.py`) | [gpiozero](https://gpiozero.readthedocs.io/en/stable/), BSD |
| Riga `SCRIPT_DIR=...` in `capture_rpi.sh` | risposta molto nota su Stack Overflow |
| Opzioni di `rpicam-still` | documentazione ufficiale Raspberry Pi |
| Direttive dell'unità systemd | documentazione di systemd |

Il resto (rilevamento del movimento, protocollo UART, buffer, macchina a stati del wake, comandi di diagnostica, raccolta dati e formato dei CSV) è scritto da noi.

Quando copiamo o adattiamo codice da internet aggiungiamo subito nel file un commento con l'URL, l'autore o il progetto, la licenza e cosa abbiamo modificato.
