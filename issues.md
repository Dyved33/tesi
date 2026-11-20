# Problemi aperti nel codice

Questa è la lista dei problemi che abbiamo trovato rileggendo il codice (prima revisione: 10 novembre 2026). Per ognuno indichiamo dove si trova, cosa succede e come pensiamo di sistemarlo. Sono ordinati per gravità:

- 🔴 **bloccante**: il flusso principale non funziona o il Pi resta acceso quando dovrebbe spegnersi;
- 🟠 **importante**: dati sbagliati o persi senza che nessuno se ne accorga;
- 🟡 **minore**: robustezza, pulizia, incoerenze.

I numeri restano fissi anche quando un problema viene risolto, così i riferimenti negli altri documenti continuano a valere. Un problema risolto viene spuntato (✅) con una riga che spiega la correzione.

## Riepilogo

| Stato | Problemi |
|---|---|
| ✅ Risolti | 1, 2, 3, 4, 7, 10, 11, 12, 13, 14, 15, 16, 25 |
| ◐ Risolti in parte | 6, 17, 24, 27 |
| ⏳ Aperti | 5, 8, 9, 18–23, 26, 28 |

> **Attenzione:** le correzioni sono state provate solo su PC, con una camera finta e senza sensori: wrapper, import, parsing GPS e fallimento della camera. Vanno riprovate sul Raspberry Pi vero prima di abilitare il servizio.

---

## 🔴 Bloccanti

### ✅ 1. `capture_client.py` non partiva se lanciato da `capture_rpi.sh`
**Dove:** `raspberry_pi/smartcam/capture_client.py`, `raspberry_pi/capture_rpi.sh`

Lo script faceva `from backend.gps_reader import ...`, ma lanciandolo come file Python metteva in `sys.path` la cartella dello script e non la root del progetto, quindi falliva con `ModuleNotFoundError: No module named 'backend'`. Di conseguenza tutto il ciclo `--oneshot` falliva.

**Correzione:** i moduli Python adesso sono nel package `raspberry_pi/smartcam/` e usano import relativi. Il wrapper aggiunge `raspberry_pi/` al `PYTHONPATH` e li lancia con `python -m smartcam.capture_client` e `python -m smartcam.sensors`.

### ✅ 2. Se lo scatto falliva, il Pi restava acceso per sempre
**Dove:** `raspberry_pi/systemd/insect-capture.service`

`ExecStartPost=/bin/systemctl poweroff` partiva solo se lo script terminava con successo. Inoltre con `Type=oneshot` systemd non ha timeout, quindi uno script bloccato teneva il Pi acceso.

**Correzione:**
- `SuccessAction=poweroff` e `FailureAction=poweroff`: il Pi si spegne in ogni caso;
- `TimeoutStartSec=180`: uno script bloccato viene terminato e il Pi si spegne lo stesso;
- `ConditionPathExists=!/boot/firmware/maintenance`: se esiste quel file il servizio viene saltato e il Pi resta acceso per la manutenzione. Secondo la documentazione di systemd, una condizione non soddisfatta non fa scattare `SuccessAction`/`FailureAction`.

Abbiamo controllato la sintassi con `systemd-analyze verify`.

### ✅ 3. Crash quando pyserial non era installato
**Dove:** `raspberry_pi/smartcam/capture_client.py`

Il record GPS "dummy" (con `latitude = None`) veniva trattato come un fix valido, e `float(None)` mandava in crash lo scatto.

**Correzione:** un fix senza coordinate viene trattato come "nessun fix". Inoltre la parte GPS e metadati è stata spostata in `_attach_gps_metadata()` e protetta da un `try`, perché un suo errore non deve far risultare fallito uno scatto già salvato.

### ✅ 4. In `capture_rpi.sh` la gestione degli exit code non funzionava
**Dove:** `raspberry_pi/capture_rpi.sh`

Con `set -e` lo script usciva al primo errore, quindi `CAPTURE_EXIT`/`SENSORS_EXIT` non servivano a niente e, se la foto falliva, i sensori non venivano letti.

**Correzione:** gli exit code si catturano con `|| VAR=$?`. I sensori vengono letti anche se la foto fallisce, e alla fine lo script esce con 1 se almeno uno dei due è fallito (e lo scrive su stderr). Lo spegnimento non dipende più dall'exit code (vedi #2).

---

## 🟠 Importanti

### 5. Il sensore d'acqua con gpiozero dà il risultato al contrario
**Dove:** `raspberry_pi/smartcam/sensors.py`, `read_water()`

Con `pull_up=True` gpiozero imposta in automatico lo stato attivo a LOW, quindi `sensor.value` vale già 1 quando il pin è basso, cioè "bagnato" ([docs gpiozero](https://gpiozero.readthedocs.io/en/stable/api_input.html)). Il `not sensor.value` lo inverte una seconda volta e il risultato è "bagnato" quando è asciutto. La variante `read_water_rpigpio()` legge invece il livello grezzo ed è corretta.

**Soluzione:** `wet = bool(sensor.value)` (oppure `sensor.is_active`). Va poi verificato al banco con il sensore vero.

### ◐ 6. Un sensore che fallisce viene segnato "ok" nel CSV
**Dove:** `raspberry_pi/smartcam/sensors.py`, `read_sensor_with_fallback()`

~~La lettura ADC con Adafruit falliva sempre (chip select passato senza `digitalio.DigitalInOut`).~~ Risolto: ora l'ADC si legge con `gpiozero.MCP3008`, con i chip select hardware CE0/CE1.

Resta aperto il problema principale: quando una lettura va in errore si ripiega sul dummy e il sensore finisce lo stesso in `sensors_ok`. La riga di esempio in `data/sensors.csv` lo mostra, e lo abbiamo rivisto anche nelle prove su PC, dove tutti i sensori senza hardware risultano "ok".

**Soluzione:** un ripiego sul dummy dovrebbe finire in `sensors_failed`, o almeno in una nuova colonna `sensors_dummy`.

### ✅ 7. Scegliere `spidev_raw` faceva andare in crash lo script
`read_adc_spidev()` restituiva un `float` dove `main()` si aspettava un dizionario.

**Correzione:** l'implementazione spidev è stata eliminata e sostituita da `gpiozero.MCP3008` (vedi #6). `main()` adesso legge i sensori con un unico ciclo.

### 8. Il JSON della foto si salva solo se c'è il GPS, e con pochi dati
**Dove:** `raspberry_pi/smartcam/capture_client.py`

Il sidecar viene scritto solo quando c'è un fix GPS. Anche in quel caso contiene solo latitudine e longitudine: quota, satelliti, qualità del fix, HDOP (ora restituiti da `gps_reader`), timestamp e parametri della camera si perdono. Per il dataset descritto in `plan.pdf` servono tutti.

**Soluzione:** scrivere il JSON sempre, usando `create_metadata_for_capture()` (dopo aver sistemato il punto 9).

### 9. `create_metadata_for_capture()` sporca i default tra una chiamata e l'altra
**Dove:** `raspberry_pi/smartcam/photo_metadata.py`

`dict(DEFAULT_METADATA)` fa una copia superficiale: `sensor_readings` e `camera_settings` sono gli stessi oggetti per tutte le foto. L'abbiamo verificato: dopo una chiamata con GPS, la chiamata successiva senza GPS (e `DEFAULT_METADATA` stesso) contiene ancora `{'gps_satellites': 7}`.

**Soluzione:** `copy.deepcopy(DEFAULT_METADATA)`.

### ✅ 10. Il GPS accettava posizioni senza fix valido
Non si controllavano qualità del fix e checksum, e si riconosceva solo `$GPGGA`.

**Correzione:** il parsing ora lo fa [pynmea2](https://github.com/Knio/pynmea2): verifica il checksum, accetta qualsiasi `$xxGGA` (anche `$GNGGA`) e scarta le frasi con `gps_qual = 0`. Questo controllo è necessario, perché senza fix pynmea2 restituisce 0.0 come coordinate. Le prove con frasi valide, senza fix, con checksum sbagliato e con coordinate Sud/Ovest danno il risultato atteso.

**Ancora da fare:** salvare `fix_quality` e `hdop` anche nel CSV e nel JSON (vedi #8).

### ✅ 11. Il GPIO14 dell'ESP32 emette un segnale PWM all'avvio
**Dove:** `firmware/esp32/src/main.cpp` (`PIN_WAKE`)

Sull'ESP32 alcuni pin, tra cui il GPIO14, mandano un segnale PWM durante il boot, prima che `setup()` li porti a LOW. Ogni reset o brown-out dell'ESP potrebbe quindi chiudere J2 tramite il PC817 e accendere il Pi senza motivo. Il GPIO14 è anche il clock della microSD sulla ESP32-CAM.

**Correzione:** WAKE è stato spostato sul GPIO12. È un pin di strapping che al reset deve essere basso (altrimenti l'ESP non parte), e il LED del PC817 verso massa lo garantisce; non emette segnali al boot. Il GPIO14 ora fa da TX verso il Pi, dove il PWM produce al massimo qualche byte spurio. Resta da controllare con l'oscilloscopio che durante il reset il GPIO12 stia basso, e va aggiornato lo schema KiCad in `hardware/pi5->esp32/`. Dettagli in `docs/setup-risveglio.md`, sezione 2.

---

## 🟡 Minori

### ✅ 12. API Adafruit CircuitPython BME280 obsoleta
Superato: il BME280 è collegato solo all'ESP32; il lettore Python del Pi è stato rimosso e il firmware usa la libreria Adafruit BME280 per Arduino.

### ✅ 13. Indirizzo BME280 incoerente
Il driver ESP32 usa l'indirizzo predefinito `0x76`, come nello schema in `hardware/sensors/BME280/` (SDO a GND).

### ✅ 14. Il backend SMBus non leggeva le misure e non chiudeva il bus
Superato: non esiste più un backend SMBus sul Pi; il BME280 è gestito dal firmware ESP32.

### ✅ 15. Porta seriale non chiusa in caso di eccezione
`gps_reader.py` ora usa `with serial.Serial(...) as ser:`.

### ✅ 16. Codice GPS duplicato
`sensors.py` ora usa `gps_reader.get_gps_fix()`.

### ◐ 17. Codice morto e chiavi di configurazione che non corrispondono
- ✅ Il commento della chiave `library` dell'acqua ora indica `rpigpio`, il valore che il dispatcher riconosce davvero.
- ✅ Rimosso il vecchio lettore Python BME280: il sensore appartiene al firmware ESP32.
- ⏳ `read_soil_moisture_gpio()` e `read_methane_gpio()` non vengono mai chiamate.
- ⏳ `wet_bool` / `alarm_bool` non hanno una colonna nel CSV e vengono scartati.

### 18. Percentuale di umidità del suolo probabilmente invertita
La formula assume 0 V = secco. Molti sensori capacitivi economici fanno il contrario. Va calibrata sulla sonda vera, con i due punti "aria" e "acqua".

### 19. Variabili d'ambiente documentate ma non usate
`CAPTURE_MODE`, `DAILY_WINDOW_START/END` e `SENSOR_INTERVAL` in `.env.systemd.example` non vengono lette da nessuno script.

### 20. `After=network-online.target` rallenta il ciclo selettivo
Il servizio aspetta la rete prima di scattare, ma lo scatto non ne ha bisogno. Nell'app selettiva ogni secondo di boot è energia consumata. Conviene toglierlo, oppure spostare l'upload in un servizio separato.

### 21. Timestamp e nomi file
- Le foto usano l'ora **locale** al secondo (`rpi_YYYYMMDD-HHMMSS.jpg`), mentre il CSV usa **UTC**. Conviene usare UTC ovunque.
- Due scatti nello stesso secondo si sovrascrivono.
- `IMAGE_DIR` è relativo alla directory corrente.

### 22. Ciclo continuo che "scivola"
In `capture_client.py` la pausa parte dopo scatto e GPS (fino a ~10 s), quindi il periodo reale è `interval + durata scatto`.

### 23. `--warmup-ms` e `--timeout-ms` vengono semplicemente sommati
Le due opzioni finiscono entrambe in `-t`, quindi non ha senso tenerle separate. L'help dice "passed to libcamera-still", ma non è così.

### ◐ 24. Firmware ESP32
- ✅ `camera_config_t config = {};`: i campi non assegnati ora sono azzerati.
- ✅ Usati i nomi nuovi `pin_sccb_sda/scl`.
- ✅ Se la camera non si inizializza il firmware non si blocca più: il rilevamento resta disattivato, ma BME280, UART e comando `w` funzionano. Lo stesso vale se manca il BME280, che il firmware riprova a inizializzare ogni 10 s.
- ⏳ `waitForAlive()` blocca il `loop()` per fino a 15 s: nel frattempo non si acquisiscono frame e non si leggono i comandi dal monitor seriale.
- ⏳ `secrets.h.example` e `USE_WIFI` non sono usati.

### ✅ 25. `platformio.ini`: flag `-mfix=fp`
Non ci risulta un flag GCC Xtensa con questo nome (esiste `-mfix-esp32-psram-cache-issue`).

**Correzione:** l'abbiamo verificato compilando: il compilatore risponde `unrecognized command-line option '-mfix=fp'` e la build fallisce. Il flag è stato tolto da `platformio.ini`.

### 26. Back-powering tramite ALIVE
Con `gpio=17=op,dh` il Pi tiene GPIO17 alto. Se l'ESP non è alimentato, quei 3,3 V entrano nel GPIO2 (prima GPIO13) e, attraverso i diodi di protezione interni, arrivano al suo rail di alimentazione. Il pulldown da 10 kΩ va verso massa e non limita questa corrente. Conviene una resistenza in serie (es. 1 kΩ) o un secondo optoisolatore.

Lo stesso rischio c'è, al contrario, sulla UART verso il Pi: una linea TX a riposo è alta e alimenterebbe il Pi in halt attraverso il suo RXD. Il firmware tiene la UART chiusa finché ALIVE è basso; in più è previsto 1 kΩ in serie sul filo ESP TX → Pi RXD. Va misurato al banco (vedi `docs/setup-risveglio.md`, sezione 4, prova 9).

### ◐ 27. Il firmware non è stato compilato dopo le ultime modifiche
**Dove:** `firmware/esp32/`

Nelle ultime revisioni abbiamo cambiato solo i commenti di `main.cpp` e `platformio.ini` (abbiamo verificato in automatico che il codice, tolti i commenti, sia identico). Sulla macchina della revisione però PlatformIO non è installato, quindi il firmware non è stato compilato. Non sappiamo nemmeno se compilasse prima, perché il repository non contiene un log di build.

**Aggiornamento (20 novembre 2026):** il firmware (board `esp32cam`) compila senza errori né warning con PlatformIO, piattaforma espressif32 8.0.0 (arduino-esp32 3.3.12) e SparkFun BME280 2.0.9. Uso: RAM 11 %, flash 12 %. Compilando abbiamo anche scoperto che la versione precedente **non poteva compilare**, per il flag `-mfix=fp` (#25).

**Cosa resta:** caricarlo sulla scheda e ripetere le prove con i comandi `w` e `r` e con la UART verso il Pi.

### 28. Valutare Picamera2 al posto di `rpicam-still`
**Dove:** `raspberry_pi/smartcam/capture_client.py`

Lo scatto oggi lancia `rpicam-still` come processo esterno: ogni foto riaccende la camera e rifà l'autofocus. [Picamera2](https://github.com/raspberrypi/picamera2) è la libreria Python ufficiale: terrebbe la camera aperta nel ciclo continuo, darebbe accesso diretto ai metadati di scatto (esposizione, guadagno, posizione della lente) e risolverebbe il #23. Non l'abbiamo adottata perché bisogna riscrivere lo scatto e provarlo sulla camera vera. Sarà utile anche quando aggiungeremo la seconda fotocamera.
