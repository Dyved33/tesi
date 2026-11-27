# Registro delle revisioni

Qui teniamo traccia di cosa cambiamo nel repository a ogni revisione e perché. La revisione più recente sta in alto.

## 27/11/2026 (seconda parte): chiusura di `issues.md`

Abbiamo chiuso tutte le voci rimaste aperte e tolto `issues.md`. Le cose che si possono fare solo con le schede in mano sono diventate passi delle [prove al banco](setup-risveglio.md#4-prove-al-banco) con il risultato atteso, e il resto è nella lista "Da fare" del README.

### Codice

- Orologio del Pi: tutti i CSV hanno una colonna (`pi_clock_synced` o `sensors_clock_synced`) che dice se in quel momento l'orologio era sincronizzato con NTP. Serve a riconoscere i dati raccolti con un'ora non verificata, per esempio in campo senza rete e senza batteria dell'RTC. La funzione è `storage.clock_synced()`.
- Metano: dimensionato il partitore tra l'uscita a 5 V del modulo MQ-4 e l'MCP3008 (10 kΩ + 18 kΩ, al massimo 3,21 V sul canale). `sensors.py` riporta la lettura alla tensione vera del sensore ([pinout.md](pinout.md)).
- Umidità del suolo: nuovo comando `python -m smartcam.sensors --calibra-suolo`, che dà la media di 10 letture per trovare i due punti di calibrazione (prova 16).
- Picamera2: valutata e non adottata, per ora resta `rpicam-still`. Il motivo è scritto in [guida-codice.md](guida-codice.md) e nel commento di `capture_client.py`.
- `.gitignore`: aggiunto `.history/` (cronologia locale di VS Code).

### Spostato nelle prove al banco

- Livello di WAKE durante il reset dell'ESP (prova 5).
- Back-powering tra le schede attraverso ALIVE e UART (prova 8).
- BME280 che non risponde e controllo BME280/BMP280 (prova 3).
- Camera e taratura del movimento, consumi (prove 4, 18, 19).
- Sensore acqua, calibrazione del suolo e partitore del metano (prove 15-17).

### Spostato nella lista "Da fare" del README

- Aggiornare gli schemi KiCad ai collegamenti di [pinout.md](pinout.md).
- Montare la batteria dell'RTC del Pi.

### Da fare a mano con git

- Togliere dal repository le due cartelle `configurazioni_fisiche/*/.history`, registrate per sbaglio come submodule senza `.gitmodules`, e `.vscode/c_cpp_properties.json`, che è nel `.gitignore` ma era stato aggiunto prima della regola. I comandi sono nella sezione "Da fare" del README.

## 27/11/2026: firmware in un file, raccolta dati completa, documentazione

Siamo partiti dal piano operativo e abbiamo ricontrollato documentazione, firmware e script del Pi. La mattina avevamo provato il wake: il Pi si accendeva con il comando `w` dell'ESP, ma l'ESP non trovava il BME280.

### Firmware ESP32

- Prima c'erano `src/main/main.ino` e `src/main/main_diagnostica.ino`, identici e nella stessa cartella, quindi il progetto non compilava. Adesso c'è un solo file, `firmware/esp32/main/main.ino`, diviso in 8 sezioni numerate. In cima c'è l'interruttore `#define DIAGNOSTICA`: con 1 si aggiungono i comandi di prova del cablaggio (`p`, `a`, `l`, `u`, `c`), con 0 è il firmware di campo.
- Tolti `platformio.ini`, `include/secrets.h.example` (non era usato) e la cartella `src/`: il firmware si apre e si carica con Arduino IDE ([setup-risveglio.md §2.2](setup-risveglio.md#22-caricare-il-firmware-arduino-ide)).
- La camera OV3660 della scheda adesso è usata per rilevare il movimento: confronto a blocchi con uno sfondo che si aggiorna lentamente. Un movimento accende il Pi, con almeno 30 s tra due wake. Le soglie vanno tarate. La Camera Module 3 non si può collegare all'ESP32-S3 (ha un'interfaccia MIPI CSI-2, l'ESP32-S3 solo quella parallela), quindi resta sul Pi.
- Il BME280 viene misurato ogni minuto anche a Pi spento. Misure ed eventi della camera restano in un buffer di 48 ore finché il Pi non conferma di averli salvati.
- L'indirizzo del BME280 viene cercato in automatico (0x76 e 0x77) e il firmware legge il chip ID, perché la libreria accetta anche il BMP280, che non ha l'umidità.
- Il wake non blocca più il `loop()` per 15 secondi: è una macchina a stati.
- Pin attuali: SDA 47, SCL 21 (il GPIO48 pilota il LED RGB), RX dal Pi sul GPIO41 (filo nuovo).

### Collegamento Pi–ESP

- La UART adesso va nei due sensi: serve il filo Pi GPIO14 → 1 kΩ → ESP GPIO41.
- Nuovo protocollo `HELLO` / `TIME` / `GET` / `ACK` con checksum. Il Pi ricava l'ora di ogni misura dalla sua età, quindi l'ora della misura è distinta da quella di ricezione, come chiede il piano ([protocollo-uart.md](protocollo-uart.md)).
- Il GPS era configurato sulla stessa UART dell'ESP: spostato sulla UART2, GPIO4/5.

### Software del Pi

- Nuovo modulo `esp_link.py` che scarica misure ed eventi dall'ESP. Prima sul Pi non c'era nessun programma che leggesse la UART.
- I metadati non sono più in un JSON scritto solo con il GPS: accanto a ogni foto c'è un CSV con tutto. Le serie temporali sono in `bme280.csv`, `camera_events.csv` e `sensors.csv` ([dati-csv.md](dati-csv.md)). Abbiamo valutato SQLite e scelto i CSV.
- `capture_client.py` fa tutto il ciclo (foto, ESP, sensori, CSV) e ha la modalità continuativa con cadenze separate e fascia oraria.
- `sensors.py`: corretto il sensore d'acqua che dava il risultato al contrario; un sensore guasto non risulta più "ok"; tolto RPi.GPIO, che sul Pi 5 non funziona; umidità del suolo calcolata da due punti di calibrazione.
- `capture_rpi.sh` esporta le variabili di `.env.systemd`, che prima non arrivavano a Python.
- Nomi delle foto in UTC con i millisecondi; un solo `--timeout-ms`.
- Nuovi moduli `config.py` (percorsi, porte, cadenze) e `storage.py` (scrittura dei CSV); tolto `photo_metadata.py`.
- L'unità systemd non aspetta più la rete. Lo spegnimento a fine ciclo è voluto.

### Documentazione

- Nuovi: [pinout.md](pinout.md) (tutti i pin di Pi, ESP32 e BME280), [protocollo-uart.md](protocollo-uart.md), [dati-csv.md](dati-csv.md) e questo registro.
- Riscritti README, [setup-risveglio.md](setup-risveglio.md), [guida-codice.md](guida-codice.md) e la lista dei problemi aperti (allora `issues.md`).
- `hardware/sensors/BME280/GY-BME280.md.md` rinominato in `GY-BME280.md`.

### File tolti

- `db/init.sql`: bozza PostgreSQL incompleta e non usata.
- `raspberry_pi/data/sensors.csv`: conteneva una riga di prova; adesso `raspberry_pi/data/` è nel `.gitignore`.

### Come è stato provato

- Firmware: compilato senza warning, con `DIAGNOSTICA` a 0 e a 1. Non è ancora stato caricato sulla scheda.
- Software del Pi: provato su PC con un finto ESP su una pseudo-seriale, che parla lo stesso protocollo del firmware, una camera finta e nessun sensore. Abbiamo provato anche il caso di una riga corrotta: la misura arriva al giro successivo e non si perde niente.
- Da fare sulle schede: BME280, UART con il filo nuovo, camera e soglie del movimento.

## 10/11/2026: prima revisione del codice

Prima lettura completa del codice, con l'elenco dei problemi trovati in `issues.md`. Corretti i problemi bloccanti del ciclo di scatto: package `smartcam`, spegnimento garantito dall'unità systemd, gestione degli exit code. Parser GPS sostituito con pynmea2, ADC letto con `gpiozero.MCP3008`.
