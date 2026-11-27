# Configurazione di Raspberry Pi ed ESP32-S3-CAM

Qui ci sono le configurazioni di Pi ed ESP, i collegamenti tra le due schede e l'ordine in cui fare le prove al banco. I requisiti vengono da [`plan.pdf`](plan.pdf), i pin da [pinout.md](pinout.md).

## A che punto siamo (27/11/2026)

- Il wake funziona: dal monitor dell'ESP il comando `w` accende il Pi.
- Dopo il ciclo il Pi torna in halt da solo: è il comportamento voluto di `insect-capture.service`.
- L'ESP non trova il BME280: la scansione I2C non vede nessun dispositivo, nemmeno con SDA e SCL scambiati. Non è un problema di indirizzo ma di collegamento. Vedi la sezione 2.4.
- Il ricevitore delle misure sul Pi adesso c'è (`smartcam.esp_link`), ma serve il filo in più Pi GPIO14 → ESP GPIO41.
- Il firmware adesso usa la OV3660 per rilevare il movimento e accendere il Pi: è compilato ma non ancora provato sulla scheda.

---

## 1. Raspberry Pi 5

### 1.1 Halt e consumo

Quando il Pi non serve lo mettiamo in halt: il sistema operativo è spento ma la scheda resta alimentata e si riaccende dal pulsante o dai pad J2. Se si toglie l'alimentazione J2 non serve più a niente. ESP32 e BME280 devono restare alimentati anche con il Pi in halt.

Nella EEPROM del Pi (`sudo rpi-eeprom-config --edit`):

```ini
POWER_OFF_ON_HALT=1
WAKE_ON_GPIO=0
```

`POWER_OFF_ON_HALT=1` spegne anche il 3,3 V durante l'halt e il consumo scende a circa 0,01 W secondo la [documentazione](https://www.raspberrypi.com/documentation/computers/raspberry-pi.html#raspberry-pi-bootloader-configuration) (lo misureremo noi). Ha anche un effetto che ci serve: quando il 3,3 V si spegne, GPIO17 va a zero, quindi ALIVE basso vuol dire che l'arresto è davvero finito. `WAKE_ON_GPIO=0` disattiva il risveglio da GPIO3, perché usiamo J2.

### 1.2 `config.txt`

In `/boot/firmware/config.txt`, in fondo:

```ini
gpio=17=op,dh          # ALIVE: GPIO17 uscita alta appena possibile durante il boot
dtparam=uart0=on       # UART0 su GPIO14/15 -> /dev/ttyAMA0, collegata all'ESP
dtoverlay=uart2-pi5    # UART2 su GPIO4/5   -> /dev/ttyAMA2, collegata al GPS
dtparam=spi=on         # SPI0 per l'MCP3008
```

Sulla UART0 non deve esserci la console di Linux, altrimenti l'ESP riceve i messaggi del kernel e il prompt di login. Con `sudo raspi-config` → Interface Options → Serial Port: "login shell over serial" No, "serial port hardware" Sì. Poi controllare che in `/boot/firmware/cmdline.txt` non ci sia `console=serial0,115200`.

Dopo il riavvio:

```bash
ls -l /dev/ttyAMA0 /dev/ttyAMA2 /dev/spidev0.0   # devono esistere tutti e tre
pinctrl get 17                                   # deve dire "op dh"
```

Il GPS prima era configurato anche lui su `/dev/ttyAMA0`, cioè sugli stessi pin dell'ESP: per questo lo abbiamo spostato sulla UART2.

### 1.3 Utente, permessi e orologio

L'utente che esegue gli script deve poter usare seriali, GPIO e SPI:

```bash
sudo usermod -aG dialout,gpio,spi,video rpi5-03
```

Il timestamp delle misure dell'ESP è calcolato con l'orologio del Pi, quindi l'ora del Pi deve essere giusta. In campo senza rete serve la batteria dell'RTC sul connettore BAT del Pi 5. Si controlla con `timedatectl`. Se l'ora è prima del 2026 il Pi non la manda all'ESP (lo scrive nel log). In ogni CSV c'è anche una colonna (`pi_clock_synced` o `sensors_clock_synced`) che dice se in quel momento l'orologio era stato sincronizzato con NTP: così dopo si possono riconoscere i dati con l'ora non verificata.

Il Pi nell'app selettiva si spegne da solo a fine ciclo, quindi per leggere i log di un ciclo bisogna guardare l'avvio precedente. Per farlo il journal deve essere persistente:

```bash
sudo mkdir -p /var/log/journal
sudo systemctl restart systemd-journald
journalctl -b -1 -u insect-capture.service   # log del ciclo dell'avvio precedente
```

### 1.4 Software

Prima configurazione: scrivere Raspberry Pi OS (Bookworm, 64 bit) sulla microSD con Raspberry Pi Imager, abilitando SSH e Wi-Fi. Prima di avviare, creare un file vuoto `maintenance` nella partizione `bootfs` (vedi 1.5). Poi:

```bash
ssh rpi5-03@rpi5-03.local
git clone <url del repository> /home/rpi5-03/progetto
cd /home/rpi5-03/progetto/raspberry_pi
python3 -m venv --system-site-packages .venv
.venv/bin/pip install -r requirements.txt
cd ..
cp raspberry_pi/systemd/.env.systemd.example .env.systemd
nano .env.systemd
```

Il virtualenv usa `gpiozero` e `lgpio` di Raspberry Pi OS (per questo `--system-site-packages`). In `.env.systemd` controllare percorsi, cadenze e porte seriali.

Prova del ciclo selettivo a mano, senza spegnimento:

```bash
bash raspberry_pi/capture_rpi.sh --oneshot            # foto + ESP + sensori
bash raspberry_pi/capture_rpi.sh --oneshot --no-esp   # se l'ESP non è collegato
```

I file finiscono in `raspberry_pi/data/` ([dati-csv.md](dati-csv.md)). L'exit code è 1 se foto, ESP o uno dei sensori non hanno funzionato; il motivo è nel log e nelle colonne `*_error*` dei CSV.

Modalità continuativa (foto ogni `CAPTURE_INTERVAL` secondi, sensori ed ESP ogni `SENSOR_INTERVAL`, dentro la fascia `DAILY_WINDOW_*`):

```bash
bash raspberry_pi/capture_rpi.sh
```

### 1.5 Servizio dell'app selettiva e modalità manutenzione

[`insect-capture.service`](../raspberry_pi/systemd/insect-capture.service) a ogni boot lancia `capture_rpi.sh --oneshot` e poi spegne il Pi in ogni caso: se va tutto bene, se qualcosa fallisce o se lo script resta bloccato per più di 3 minuti. Va abilitato solo dopo aver provato tutto a mano:

```bash
sudo cp raspberry_pi/systemd/insect-capture.service /etc/systemd/system/
sudo systemctl daemon-reload
sudo systemctl enable insect-capture.service
```

Non va abilitato per la raccolta continuativa né durante le prove, perché spegne il Pi a ogni avvio.

Per tenere il Pi acceso con il servizio abilitato si crea un file vuoto `maintenance` nella partizione di boot: finché esiste il servizio viene saltato.

```bash
sudo touch /boot/firmware/maintenance   # dal Pi
# dal PC: inserire la microSD e creare il file "maintenance" in "bootfs"
```

Per tornare al funzionamento normale basta cancellarlo.

---

## 2. ESP32-S3-CAM

### 2.1 Scheda e firmware

La scheda è una ESP32-S3-CAM generica: modulo ESP32-S3-N16R8 (16 MB di flash, 8 MB di PSRAM), camera OV3660 collegata con il suo cavo flat, slot microSD, due USB-C. Non c'è uno schema ufficiale per questa revisione, quindi la mappa dei GPIO in [pinout.md](pinout.md) è da confermare al banco.

Il firmware è un unico file, `firmware/esp32/main/main.ino`. Fa quattro cose:

- misura il BME280 ogni minuto;
- guarda la scena con la OV3660 e, se vede un movimento, accende il Pi;
- tiene misure ed eventi in un buffer finché il Pi non li scarica;
- risponde ai comandi del Pi sulla UART.

Forecaster e decider non ci sono ancora: per ora ogni movimento prova a svegliare il Pi, con almeno 30 s tra un wake e l'altro.

In cima al file c'è l'interruttore `#define DIAGNOSTICA 0`. Con `1` lo stesso firmware ha in più i comandi per provare il cablaggio (sezione 2.3). Il codice di campo è identico nelle due versioni, quindi non ci sono due copie da tenere allineate. In campo va caricato con `0`.

La Camera Module 3 non si può collegare all'ESP32-S3: usa un'interfaccia MIPI CSI-2 e l'ESP32-S3 ha solo l'interfaccia parallela (DVP) della OV3660. Per questo la CM3 resta sul Pi e fa le foto vere, mentre la OV3660 serve solo a capire quando vale la pena accendere il Pi.

### 2.2 Caricare il firmware (Arduino IDE)

1. Installare il supporto per le schede ESP32 (Board Manager: "esp32" di Espressif, versione 3.x) e la libreria "SparkFun BME280" dal Library Manager. Il driver della camera (`esp_camera.h`) è già compreso nel pacchetto ESP32.
2. Aprire `firmware/esp32/main/main.ino`.
3. Impostare:
   - scheda "ESP32S3 Dev Module";
   - Flash Size "16MB (128Mb)";
   - PSRAM "OPI PSRAM" (necessaria: i fotogrammi della camera stanno in PSRAM);
   - USB CDC On Boot "Disabled" (il monitor passa dal convertitore USB-seriale);
   - Upload Speed 921600 (se dà errori, 115200).
4. Collegare la USB-C del convertitore USB-seriale (di solito marcata "COM"), scegliere la porta e caricare. Se l'upload resta fermo su "Connecting...", tenere premuto BOOT, premere e rilasciare RST, poi rilasciare BOOT.
5. Aprire il Serial Monitor a 115200 baud.

Conviene caricare il firmware con il Pi spento o scollegato, finché non abbiamo verificato cosa fanno i pin durante il reset.

### 2.3 Comandi dal monitor

| Comando | Cosa fa |
|---|---|
| `w` | wake del Pi; non fa niente se il Pi è già acceso o se l'ultimo wake è di meno di 30 s fa |
| `r` | misura subito e la mette nel buffer |
| `s` | stato: boot ID, Pi acceso/spento, BME280, camera, record nel buffer, ora ricevuta dal Pi |
| `i` | scansione del bus I2C |
| `h` | aiuto |

In più, con `DIAGNOSTICA 1`:

| Comando | Cosa fa |
|---|---|
| `p` | livello delle linee SDA e SCL: dice se il modulo BME280 è collegato e alimentato |
| `a` | cerca dispositivi I2C su tutte le coppie dei GPIO liberi 14, 21, 38, 39, 40, 47, 48 |
| `l` | segue ALIVE per 20 s e stampa ogni cambio |
| `u` | ponte UART: quello che arriva dal Pi va sul monitor e viceversa (`~` per uscire) |
| `c` | per 10 s stampa la percentuale di immagine cambiata, per tarare le soglie del movimento |

Questi comandi bloccano il firmware per qualche secondo, ed è il motivo per cui non stanno nella versione di campo.

### 2.4 Il BME280 non viene trovato

La scansione I2C che non trova niente su nessun indirizzo, nemmeno scambiando SDA e SCL, vuol dire che il chip non risponde proprio. L'indirizzo (0x76 o 0x77) non c'entra: il firmware prova entrambi. Con `DIAGNOSTICA 1`:

1. `p` controlla le due linee. Con il pulldown interno attivo, una linea collegata a un modulo alimentato legge HIGH perché i pull-up del modulo sono più forti. Se una legge LOW il filo non arriva su quel GPIO, oppure il modulo non è alimentato;
2. con il multimetro: 3,3 V tra VCC e GND del modulo, continuità da GPIO47 a SDA e da GPIO21 a SCL. Controllare anche le saldature dell'header del modulo, che sui moduli economici spesso arrivano non saldati;
3. `a` prova tutte le coppie dei GPIO liberi. Se il sensore risponde su un'altra coppia, i fili sono su pin diversi da quelli che pensiamo (succede facilmente leggendo la serigrafia dell'header);
4. quando risponde, il messaggio all'avvio (o `s`) dice se è un BME280 (chip ID 0x60) o un BMP280 (0x58, senza umidità).

### 2.5 Rilevamento del movimento

La camera lavora in scala di grigi a 160×120, un fotogramma ogni mezzo secondo. L'immagine è divisa in 192 blocchi da 10×10 pixel e per ogni blocco si confronta la luminosità media con uno "sfondo" che segue lentamente la scena, così le variazioni graduali di luce non contano. C'è un evento quando cambia almeno il 3% dei blocchi. Sopra il 60% consideriamo che sia cambiata la luce (una nuvola, l'esposizione automatica) e lo sfondo riparte da zero. Un movimento che continua conta come un solo evento ogni 10 s.

Ogni evento finisce nel buffer con la percentuale di blocchi cambiati e un flag che dice se ha acceso il Pi. Sul Pi arriva in `data/camera_events.csv`, e il CSV della foto riporta l'evento che ha causato il wake.

Le soglie sono in cima al file e vanno tarate in campo con il comando `c`. A 160×120 un insetto piccolo lontano dalla camera occupa pochi pixel: è un primo filtro grezzo, che il decider dovrà migliorare.

### 2.6 Collegamento con il Pi

I fili sono in [pinout.md](pinout.md), il protocollo in [protocollo-uart.md](protocollo-uart.md). In breve: l'ESP apre la UART quando ALIVE sale, il Pi chiede i record con `GET` e li conferma con `ACK` dopo averli salvati. I record confermati escono dal buffer, gli altri restano lì.

---

## 3. Circuito di risveglio (WAKE → J2)

```text
ESP GPIO42 ──[330 Ω]──► PC817 pin 1 (anodo LED)
ESP GND    ───────────► PC817 pin 2 (catodo LED)
                         PC817 pin 4 (collettore) ──► J2 segnale
                         PC817 pin 3 (emettitore) ──► J2 massa

Pi GPIO17 ──[1 kΩ]──┬──► ESP GPIO1 (ALIVE)
                  [10 kΩ]
                    │
GND comune ─────────┴─── (masse di Pi ed ESP collegate)
```

Quando l'ESP porta GPIO42 alto per 200 ms il LED del PC817 si accende, il fototransistor conduce e chiude J2 come il pulsante. Il GPIO dell'ESP non tocca mai direttamente i pad del Pi.

Da verificare prima di collegarlo al Pi:

- quale dei due pad J2 è la massa (con il multimetro, a Pi spento);
- che GPIO42 resti basso durante il reset dell'ESP, altrimenti ogni reset dell'ESP accende (o spegne) il Pi (prova 5);
- che non ci sia back-powering tra le schede quando una delle due è spenta: ALIVE e la linea Pi TXD → ESP GPIO41 possono alimentare l'ESP spento attraverso i diodi di protezione, e la TX dell'ESP può alimentare il Pi in halt. Per questo ci sono le resistenze da 1 kΩ in serie e il firmware tiene la TX come ingresso finché ALIVE è basso. Si misura con la prova 8 della sezione 4.

Lo schema KiCad in [`hardware/pi5->esp32/`](../hardware/pi5-%3Eesp32/circuito.png) ha ancora un connettore ESP generico e non ha la resistenza da 1 kΩ su ALIVE né le due linee UART: va aggiornato ai collegamenti di [pinout.md](pinout.md) (è nella lista "Da fare" del README).

---

## 4. Prove al banco

Andare in ordine e passare alla prova dopo solo se il risultato è quello atteso. Scollegare l'alimentazione prima di cambiare i collegamenti. Per ogni prova annotare data, pin, alimentazione, misura e risultato (vedi `more.md`, diario delle prove). Finché queste prove non sono fatte, firmware e software del Pi sono stati provati solo in compilazione e su PC.

### A. Schede separate

1. Pi da solo. Avviarlo, controllare EEPROM (`rpi-eeprom-config`), `config.txt` e i comandi di 1.2. Fare `sudo halt` e verificare che il pulsante lo riaccenda. Con `timedatectl` controllare che l'ora sia giusta anche dopo aver tolto la rete e riavviato: se non lo è, manca la batteria dell'RTC (1.3).
2. ALIVE sul Pi. Misurare GPIO17 (pin 11) rispetto a GND con il Pi acceso, durante lo spegnimento e in halt. Ci aspettiamo 3,3 V da acceso e 0 V in halt.
3. BME280. Caricare il firmware con `DIAGNOSTICA 1`, aprire il monitor e seguire la sezione 2.4 (`p`, `i`, `a`) finché all'avvio non compare "BME280 trovato". Controllare il chip ID: se è 0x58 il modulo è un BMP280 e l'umidità non ci sarà, quindi va comprato un BME280 vero.
4. Camera. All'avvio deve comparire "Camera pronta". Se compare "Camera non inizializzata", controllare il flat e la tabella dei pin della camera in [pinout.md](pinout.md#3-esp32-s3-cam). Con `c`, muovere una mano davanti alla camera: le righe devono passare da circa 0% a sopra il 3% e segnare "evento".
5. WAKE al reset. Con l'oscilloscopio su GPIO42, premere RST dell'ESP e togliere e ridare alimentazione: il pin deve restare basso, senza impulsi. Se un impulso c'è, ogni reset dell'ESP accenderebbe il Pi (o lo spegnerebbe se acceso): mettere una resistenza da 10 kΩ tra GPIO42 e GND e ripetere.
6. PC817 senza Pi. Con l'ESP che manda l'impulso (`w`), misurare in tensione che il transistor del PC817 commuti. Con il multimetro, a Pi spento, trovare quale pad J2 è la massa.

### B. Schede collegate

7. Collegare PC817 → J2, ALIVE (con 1 kΩ e 10 kΩ) e massa comune. ESP alimentata per conto suo.
8. Back-powering. Con il Pi acceso e l'ESP senza alimentazione, misurare il 3V3 dell'ESP: deve restare vicino a 0 V. Se sale sopra qualche centinaio di mV la corrente passa da ALIVE o da GPIO41 attraverso i diodi di protezione: aumentare le resistenze in serie (per esempio 4,7 kΩ) e rimisurare. Poi il contrario: Pi in halt ed ESP accesa, sul pin 10 (RXD) del Pi non deve arrivare tensione.
9. Con il Pi acceso, comando `l`: ALIVE deve essere HIGH. Comando `w`: deve rifiutarsi di mandare l'impulso.
10. Con il file `maintenance` presente, `sudo halt`, poi `w`: un solo impulso, il Pi si avvia, ALIVE sale. Il Pi deve restare acceso (il servizio è saltato).
11. UART. Collegare le due linee con le resistenze da 1 kΩ. Con il comando `u` e `picocom -b 115200 /dev/ttyAMA0` sul Pi, quello che si scrive da una parte deve comparire dall'altra.
12. Sul Pi: `.venv/bin/python -m smartcam.esp_link` deve scaricare misure ed eventi e scriverli in `data/bme280.csv` e `data/camera_events.csv`; lanciato una seconda volta deve ricevere solo quelli nuovi.
13. Ciclo completo. `bash raspberry_pi/capture_rpi.sh --oneshot`: una foto, il suo CSV, una riga in `sensors.csv`, le misure nuove in `bme280.csv` e gli eventi nuovi in `camera_events.csv`.
14. Solo a questo punto: caricare il firmware con `DIAGNOSTICA 0`, abilitare il servizio (1.5), togliere `maintenance` e mettere il Pi in halt. Un movimento davanti alla OV3660 deve accendere il Pi, che fa il ciclo e torna in halt da solo; ALIVE deve tornare basso.

### C. Sensori del Pi

Da fare quando avremo i modelli definitivi.

15. Sensore acqua. Bagnare il contatto e lanciare `.venv/bin/python -m smartcam.sensors`: `water_present` deve essere 1, e 0 con il contatto asciutto.
16. Umidità del suolo, calibrazione. Con la sonda all'aria lanciare `.venv/bin/python -m smartcam.sensors --calibra-suolo` e scrivere la media in `volt_dry` (`SENSORS` in `sensors.py`). Ripetere con la sonda in un bicchiere d'acqua fino alla linea indicata sulla scheda e scrivere la media in `volt_wet`. Da quel momento `soil_moisture_percent` viene calcolata.
17. Metano. Prima di collegarlo all'MCP3008, misurare con il multimetro l'uscita del partitore (10 kΩ + 18 kΩ, vedi [pinout.md](pinout.md)) con il modulo alimentato: non deve superare 3,3 V. Poi controllare che `methane_voltage` nel CSV corrisponda alla tensione misurata direttamente su AO.

### D. In campo

18. Taratura del movimento. Con `DIAGNOSTICA 1` e la camera puntata sulla scena vera, usare `c` a diverse ore del giorno. Le soglie in cima a `main.ino` vanno scelte in modo che il passaggio di un insetto superi `SOGLIA_MIN_PERCENTO` e il vento sulle foglie no. Dopo qualche giorno di raccolta, confrontare `camera_events.csv` con le foto per contare i wake inutili.
19. Consumi. Misurare la corrente dell'ESP con la camera accesa e quella del Pi nelle varie fasi (halt, avvio, scatto, spegnimento), come chiede il piano per lo studio energetico.
