# Guida al codice

Questa guida descrive il codice presente e ne indica i limiti. `plan.pdf` definisce l’architettura prevista; `main.pdf` è il riferimento scientifico per l’acquisizione selettiva. I due PDF descrivono obiettivi più ampi di quelli implementati nel repository.

## Architettura realizzata e prevista

```text
ESP32-CAM (prototipo)                 Raspberry Pi 5 (prototipo)
camera di bordo → frame scartato       camera Pi → JPG
comando seriale 'w' → WAKE/J2          sensori configurabili → CSV
legge ALIVE                            GPS → possibile metadato
```

Il firmware non legge ancora il BME280 e non contiene forecaster o decider. Il BME280 di campo è previsto sul solo ESP32, ma la comunicazione ESP–Pi non è implementata. La modalità continuativa, il database e l’analisi visiva sul Pi sono obiettivi del piano, non funzioni complete disponibili oggi.

## Firmware ESP32 — `esp32/`

`src/main.cpp` è un prototipo PlatformIO/Arduino per la scheda AI-Thinker ESP32-CAM. Configura la camera, legge il segnale ALIVE sull’ingresso GPIO13 e può generare un impulso WAKE su GPIO14. Il comando seriale `w` avvia una prova manuale. `eventDetected()` acquisisce e rilascia un frame, ma restituisce sempre `false`; quindi non avviene alcun wake automatico. Se l’inizializzazione della camera fallisce, il firmware rimane in attesa e non accetta il comando seriale.

`platformio.ini` seleziona la board `esp32cam`, Arduino e i parametri di build. Va aggiornato quando sarà scelta la scheda definitiva. `include/secrets.h.example` è un modello, non contiene credenziali reali e non è usato dal firmware corrente.

Il pinout e il circuito WAKE/J2 devono essere verificati sulla scheda e sull’hardware. ALIVE è un livello elettrico e non conferma che Linux abbia terminato l’avvio. Il circuito di interfaccia J2 non è definito nel codice.

## Software Raspberry Pi — `raspberry_pi/`

### `capture_rpi.sh`

Imposta la root del progetto, carica `.env.systemd` se esiste, attiva l’ambiente Python e avvia `capture_client.py`. Con `--oneshot`, se la cattura termina correttamente, avvia anche `sensors.py`. Il wrapper non spegne il Pi: lo spegnimento è richiesto dall’unità systemd di esempio.

### `capture_client.py`

Richiama `rpicam-still` (o il comando legacy `libcamera-still`) per produrre immagini JPG in `static/uploads/images/`. Offre modalità singola o ripetuta e parametri di ripresa. Può aggiungere coordinate GPS al sidecar JSON se riceve un fix. Attualmente non legge il BME280 e non esegue analisi delle immagini.

**Problema rilevato in review:** il sidecar viene salvato solo quando è disponibile un fix GPS; senza fix, i metadati preparati non vengono scritti. Quando lo salva, il client aggiorna solo latitudine e longitudine: quota, satelliti, timestamp di acquisizione e impostazioni camera non vengono copiati nel file.

### `sensors.py` e `data/sensors.csv`

`sensors.py` esegue una lettura sequenziale dei dispositivi abilitati e aggiunge una riga CSV. La configurazione iniziale abilita GPS, acqua, suolo e metano: porte, pin, polarità e canali ADC sono esempi da confrontare con il cablaggio reale. I valori analogici di suolo e metano non sono calibrati; la conversione in percentuale o ppm non è una misura validata. Il BME locale è disattivato; in campo dovrà arrivare dall’ESP quando sarà definito il protocollo. Il backend SMBus legge il registro ID ma non confronta il valore con quello atteso e restituisce campi di misura vuoti.

Il timestamp CSV è quello di costruzione della riga, non un timestamp individuale di misura. Il file attuale contiene un’intestazione e un record di esempio: non è un database pronto per una raccolta scientifica.

### Configurazioni

`insect-capture.service` è un esempio per l’applicazione selettiva. Contiene utente, directory e percorsi assoluti dell’installazione `rpi5-03`; vanno adattati prima dell’uso. Il comando `poweroff` viene richiesto dopo l’esecuzione riuscita. Non abilitarlo durante prove o raccolte continuative.

`.env.systemd.example` è un modello di variabili; il wrapper ne usa l’ambiente Python e `CAPTURE_INTERVAL`. Le variabili per modalità, finestra giornaliera e cadenza sensori sono documentate come obiettivi, ma il wrapper non implementa una pianificazione giornaliera né un ciclo autonomo dei sensori.

## Moduli di supporto — `backend/`

- `gps_reader.py` legge frasi `$GPGGA` e converte coordinate NMEA. Non riconosce `$GNGGA` e non verifica la qualità del fix: le coordinate non vanno considerate validate.
- `bme_reader.py` è un helper per prove I²C sul Pi. Il backend SMBus verifica il chip ID ma restituisce misure vuote. Il Pi non deve ospitare il BME280 di campo secondo il piano.
- `photo_metadata.py` gestisce sidecar JSON. **Problema rilevato in review:** `create_metadata_for_capture()` copia superficialmente la struttura predefinita e condivide i dizionari interni tra chiamate.
- `__init__.py` rende `backend` un package Python.

La funzione GPS duplicata in `sensors.py` non ha la stessa gestione degli errori del modulo `backend/gps_reader.py`; la porta seriale non è garantita in chiusura su ogni percorso d’errore. Inoltre, i backend `spidev_raw` per suolo e metano restituiscono una tensione numerica, mentre la composizione della riga CSV si aspetta un dizionario: scegliendo questi backend, la registrazione può terminare con un’eccezione.

## Provenienza del codice e delle dipendenze

La cronologia e i file attuali non indicano URL o riferimenti a sorgenti online da cui siano stati copiati singoli blocchi. Non attribuisco quindi porzioni specifiche a tutorial o repository esterni senza prove. La logica di collegamento tra acquisizione, CSV, metadati, GPS e segnali WAKE/ALIVE è codice specifico di questo progetto; le funzioni `esp_camera_*`, Arduino, PlatformIO, `rpicam-still`, pySerial, Adafruit e GPIO sono API o strumenti forniti dai rispettivi progetti esterni. La presenza di un’API esterna non implica che il codice circostante sia stato copiato dalla sua documentazione.

Quando si importa codice da una fonte esterna, aggiungere nel file un commento con autore o progetto, URL, versione/commit e parti adattate. Per gli attuali sorgenti la provenienza originaria di eventuali copiature non è ricostruibile dai soli file disponibili.

## Albero essenziale

```text
esp32/                         Firmware PlatformIO
raspberry_pi/                  Script, configurazione e CSV del Pi
backend/                       Moduli Python di supporto
configurazioni_fisiche/        Progetti e documenti hardware KiCad
README.md                      Presentazione e stato del progetto
CODE_GUIDE.md                  Guida ai sorgenti software
config$awakening.md            Configurazione Pi/ESP e prove hardware
main.pdf                       Manoscritto scientifico di riferimento
plan.pdf                       Piano operativo della tesi
```

La cartella `configurazioni_fisiche/` è lasciata invariata; questa guida non modifica né riorganizza i suoi contenuti.
