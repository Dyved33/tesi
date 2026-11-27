# Configurazione di Raspberry Pi ed ESP32-S3-CAM

Questa guida raccoglie le configurazioni di Pi ed ESP32-S3-CAM, i collegamenti tra le due schede e l'ordine in cui conviene fare le prove al banco. I requisiti sono quelli di [`plan.pdf`](plan.pdf). Tutto quello che riguarda l'hardware è da **verificare sulle schede vere** prima di collegare qualcosa: non siamo ancora alla configurazione di campo.

## A che punto siamo

- **ESP32:** la scheda fotografata è una variante ESP32-S3-CAM con modulo ESP32-S3-N16R8, camera OV3660, slot SD e due USB-C. Il firmware attuale (`firmware/esp32/src/main.ino`) gestisce WAKE, ALIVE, BME280 e UART; non inizializza ancora la camera e non è stato collaudato sulla scheda.
- **Circuito di risveglio:** lo schema c'è (optoisolatore PC817, vedi sotto), ma va ancora montato e provato.
- **Raspberry Pi:** ci sono gli script di scatto e di lettura sensori, con alcuni bug noti ([issues.md](../issues.md)). Database, modalità continuativa e analisi delle immagini sono ancora da fare.

---

## 1. Raspberry Pi 5

### Halt e consumo

Quando il Pi non serve lo mettiamo in **halt**: il sistema operativo è spento, ma la scheda resta collegata all'alimentazione e si può riaccendere dal pulsante o dai pad J2. Se invece si toglie l'alimentazione, J2 non serve più a niente. ESP32 e BME280 devono restare alimentati anche mentre il Pi è in halt.

Nella EEPROM del Pi impostiamo:

```ini
POWER_OFF_ON_HALT=1
WAKE_ON_GPIO=0
```

`POWER_OFF_ON_HALT=1` spegne anche il 3,3 V durante l'halt, e il consumo scende a circa 0,01 W. `WAKE_ON_GPIO=0` disattiva il risveglio tramite GPIO3: a noi basta J2. Per modificarle:

```bash
sudo rpi-eeprom-config --edit
```

Conviene controllare sulla [documentazione ufficiale](https://www.raspberrypi.com/documentation/computers/raspberry-pi.html#raspberry-pi-bootloader-configuration) che le opzioni siano le stesse per la versione di bootloader installata. Gli 0,01 W sono il valore riportato da Raspberry Pi: il consumo reale lo misureremo noi.

### Segnale ALIVE

Per far sapere all'ESP che il Pi è acceso usiamo il GPIO17, che deve essere alto appena possibile durante il boot. In `/boot/firmware/config.txt` aggiungiamo:

```ini
gpio=17=op,dh
```

(`op` = uscita, `dh` = livello alto). Il collegamento è GPIO17 del Pi → GPIO1 dell'ESP, con un pulldown da 10 kΩ verso massa e la massa in comune.

Va verificato con il multimetro cosa fa il pin durante boot, funzionamento, spegnimento e halt. ALIVE dice solo che il pin è alto: non garantisce che Linux sia pronto, e durante lo spegnimento resta alto per un po'.

### Servizio di scatto (app selettiva)

L'unità [`insect-capture.service`](../raspberry_pi/systemd/insect-capture.service) a ogni boot fa una foto più una lettura dei sensori e poi spegne il Pi. Lo spegne **in ogni caso**: sia se va tutto bene, sia se qualcosa fallisce, sia se lo script si blocca per più di 3 minuti. La configurazione qui sotto assume utente `rpi5-03` e progetto in `/home/rpi5-03/progetto`; se hai scelto un altro utente o percorso, sostituiscili coerentemente anche in `insect-capture.service` e `.env.systemd`.

**Prima configurazione via microSD e SSH.** I comandi seguenti assumono che Raspberry Pi OS sia già scritto sulla scheda, che l'utente sia `rpi5-03` e che la rete Wi-Fi sia configurata. Dal PC, con la scheda inserita, crea un file vuoto chiamato `maintenance` nella partizione `bootfs` (su Raspberry Pi OS recenti può apparire come `bootfs`). Abilita SSH nella configurazione dell'immagine oppure, se il tuo sistema supporta il metodo file, crea lì anche un file vuoto `ssh`. Espelli la scheda in sicurezza e avvia il Pi.

Dal terminale del PC collegati al Pi (usa l'indirizzo IP al posto del nome se `raspberrypi.local` non viene trovato):

```bash
ssh rpi5-03@raspberrypi.local
```

Sul Pi, prepara la directory del progetto e l'ambiente Python. Questo presume che il repository sia già presente in `/home/rpi5-03/progetto`; se non lo è, copialo/clonalo prima in quella directory.

```bash
mkdir -p /home/rpi5-03/progetto
cd /home/rpi5-03/progetto/raspberry_pi
python3 -m venv --system-site-packages .venv
.venv/bin/pip install -r requirements.txt
```

Il virtualenv usa i pacchetti di Raspberry Pi OS (in particolare `gpiozero` e il backend GPIO) e installa `pyserial` e `pynmea2` da `requirements.txt`. La fotocamera viene chiamata tramite il comando di sistema `rpicam-still`.

Sempre sul Pi, dalla root del progetto, crea il file locale d'ambiente partendo dall'esempio e controllane il contenuto:

```bash
cd /home/rpi5-03/progetto
cp raspberry_pi/systemd/.env.systemd.example .env.systemd
nano .env.systemd
```

Verifica che contenga almeno `CAPTURE_MODE=selective`, `CAPTURE_INTERVAL=30`, `PYENV_ROOT=/home/rpi5-03/progetto/raspberry_pi/.venv` e `PROJECT_DIR=/home/rpi5-03/progetto`. Lascia commentate le righe `DAILY_WINDOW_START`, `DAILY_WINDOW_END` e `SENSOR_INTERVAL`: sono segnaposto per funzioni non implementate. In `nano`, salva con Ctrl+O, Invio ed esci con Ctrl+X.

Con `maintenance` presente il servizio viene saltato e il Pi resta disponibile. Prova manualmente il flusso dalla root del progetto:

```bash
cd /home/rpi5-03/progetto
bash raspberry_pi/capture_rpi.sh --oneshot
```

Questo prova una foto e una lettura sensori; per la prova completa servono camera e sensori collegati. Non installare/abilitare il servizio durante la manutenzione: il servizio va attivato solo dopo il collaudo, perché spegne il Pi dopo ogni avvio.

Quando il collaudo è concluso e vuoi attivare il ciclo selettivo, rimuovi prima il file `maintenance` dalla partizione `bootfs` (dal PC) oppure dal Pi, poi installa e abilita il servizio:

```bash
cd /home/rpi5-03/progetto
sudo cp raspberry_pi/systemd/insect-capture.service /etc/systemd/system/
sudo systemctl daemon-reload
sudo systemctl enable insect-capture.service
```

⚠️ **Non abilitarla durante le prove** o per la raccolta continua: il Pi si spegnerebbe dopo ogni avvio.

**Modalità manutenzione.** Con il servizio abilitato il Pi si spegne subito dopo lo scatto, quindi non c'è tempo per collegarsi in SSH. Per tenerlo acceso basta creare un file vuoto `maintenance` nella partizione di boot:

```bash
sudo touch /boot/firmware/maintenance   # dal Pi
# oppure dal PC: inserire la microSD e creare il file "maintenance" nella partizione "bootfs"
```

Finché il file esiste il servizio viene saltato. Per tornare al funzionamento normale basta cancellarlo.

Per lanciare a mano lo stesso flusso, dalla root del progetto:

```bash
bash raspberry_pi/capture_rpi.sh --oneshot
```

Lo script ha bisogno di un ambiente Python (pyenv o virtualenv) con le dipendenze di [`requirements.txt`](../raspberry_pi/requirements.txt). Copiare [`.env.systemd.example`](../raspberry_pi/systemd/.env.systemd.example) nella root del progetto come `.env.systemd` e impostare i percorsi del proprio Pi.

> Prima di abilitare il servizio in campo va provato tutto il ciclo sul Pi vero: le correzioni ai problemi bloccanti di [issues.md](../issues.md) sono state provate solo su PC, con una camera finta.

---

## 2. ESP32-S3-CAM: BME280 e collegamento con il Pi

### 2.1 Scheda e stato del firmware

La scheda riconoscibile dalle foto è una variante generica **ESP32-S3-CAM**: modulo ESP32-S3-N16R8 (16 MB flash e 8 MB PSRAM), camera OV3660 su flat, slot microSD, due USB-C e header da 40 pin. Sul PCB si leggono `V1695` e `127294G_Y1127_231016`. Questi codici non identificano in modo univoco il produttore e non è disponibile uno schema ufficiale verificato per questa revisione; trattare quindi il pinout esterno come da confermare al banco.

Il firmware in `firmware/esp32/src/main.ino` al momento:

- accetta `w` dal monitor USB e genera un impulso WAKE se ALIVE è basso;
- legge il BME280 via I2C, riprovando l'inizializzazione ogni 10 s;
- apre la UART quando ALIVE sale, aspetta 60 s e invia una misura, poi una al minuto;
- non inizializza la camera: il rilevamento automatico non è presente.

### 2.2 Configurazione PlatformIO

`firmware/esp32/platformio.ini` usa l'ambiente `esp32s3_cam`, con `board = esp32-s3-devkitc-1` come profilo generico, flash da 16 MB e PSRAM OPI. La scheda non è una DevKitC-1 ufficiale: il profilo serve a selezionare il target ESP32-S3 e va considerato una base di compilazione. Il firmware compila con PlatformIO 8.0.0 / Arduino-ESP32 3.3.12; non è ancora stato caricato o collaudato sulla scheda reale.

### 2.3 GPIO assegnati nel firmware

La mappa sotto evita i GPIO usati dalla camera DVP e dalla PSRAM secondo il pinout reperibile per questa famiglia di schede. Non essendoci uno schema ufficiale della specifica revisione, questi collegamenti sono **proposti, non collaudati**. Controllare continuità e livelli prima di collegare Pi, BME280 o optoisolatore.

| GPIO ESP32-S3 | Funzione firmware | Collegamento previsto |
|---|---|---|
| GPIO42 | WAKE, uscita | 330 Ω → LED PC817; il transistor PC817 chiude J2 del Pi |
| GPIO1 | ALIVE, ingresso | dal GPIO17 del Pi; pulldown esterno 10 kΩ verso massa |
| GPIO2 | UART TX | tramite 1 kΩ al GPIO15/RXD del Pi (pin fisico 10) |
| GPIO47 | I2C SDA | SDA del modulo GY-BME280 |
| GPIO48 | I2C SCL | SCL del modulo GY-BME280 |
| 3V3 | alimentazione BME280 | VCC e CSB |
| GND | massa | GND e SDO del BME280; massa comune secondo lo schema del circuito |
| 5V | alimentazione ESP | usare una porta/alimentazione USB adeguata |

Nel GY-BME280, collegare SDO a GND per l'indirizzo `0x76` (oppure a 3V3 per `0x77`). Alimentare il modulo a 3,3 V. Il cavo I2C verso la custodia esterna può richiedere una frequenza inferiore a 100 kHz se le letture non sono stabili.

I GPIO WAKE/ALIVE/UART indicati sono configurati nel sorgente, ma non sono stati verificati con misure sulla scheda. Non montare ancora il cablaggio definitivo e non collegare direttamente WAKE ai pad J2.

### 2.4 Protocollo UART

L'ESP apre la UART solo mentre ALIVE è alto, per limitare il rischio di alimentare il Pi spento attraverso RXD. L'invio parte dopo `PI_BOOT_DELAY_MS` (60 s), poi si ripete ogni minuto. La riga prodotta dal firmware attuale è:

```text
BME,<uptime_ms>,<temperatura_C>,<umidita_percento>,<pressione_hPa>
```

`uptime_ms` è `millis()` al momento dell'invio; non è un timestamp civile né l'età della misura. Il ricevitore sul Pi non è ancora implementato. La velocità UART configurata è 9600 baud; il monitor USB resta a 115200 baud.

### 2.5 Avvio e comandi di prova

Da `firmware/esp32`, usare `pio run -e esp32s3_cam` per compilare, `pio run -e esp32s3_cam -t upload` per caricare e `pio device monitor -b 115200` per il monitor. La scheda ha una porta USB-UART e una USB nativa: usare la porta collegata al convertitore USB-UART per il monitor seriale configurato con `Serial`.

- `w`: richiesta manuale di wake; può azionare J2 se ALIVE è basso.
- `r`: richiama una misura BME280 e la passa alla funzione di invio; verificare il comportamento UART prima di usarlo con il Pi spento.

Queste prove vanno eseguite prima con ESP e sensore isolati dal Pi. In seguito verificare con multimetro il segnale ALIVE e il circuito optoisolato, quindi collaudare UART e wake separatamente. La mappa GPIO e l'alimentazione della scheda non sono ancora state validate in hardware.

---

## 3. Circuito di risveglio (WAKE → J2)

Lo schema KiCad in [`hardware/pi5->esp32/`](../hardware/pi5-%3Eesp32/circuito.png) è una bozza elettrica del PC817, ma usa un connettore ESP generico e **non rappresenta il pinout della ESP32-S3-CAM fotografata**. Va aggiornato prima di usarlo per cablare la board. I GPIO indicati sotto sono quelli proposti nel firmware, non ancora collaudati:

```
ESP GPIO42 ──[330 Ω]──► PC817 pin 1 (anodo LED)
ESP GND    ───────────► PC817 pin 2 (catodo LED)
                         PC817 pin 4 (collettore) ──► J2 SIG
                         PC817 pin 3 (emettitore) ──► J2 GND

Pi GPIO17  ─────────┬──► ESP GPIO1
                   [10 kΩ]
                    │
GND comune ─────────┴─── (masse di Pi ed ESP collegate)
```

Quando l'ESP porta GPIO42 alto per 200 ms, il LED interno del PC817 si accende, il fototransistor conduce e chiude i due pad J2, proprio come quando si preme il pulsante. Con l'optoisolatore il GPIO dell'ESP non tocca mai direttamente i pad del Pi. La resistenza da 330 Ω limita la corrente del LED a circa 6 mA ((3,3 V − 1,2 V) / 330 Ω).

Cose da verificare prima di collegarlo al Pi:

- quale dei due pad J2 è effettivamente la massa (non darlo per scontato, va misurato);
- che il PC817 chiuda J2 in modo affidabile con l'impulso da 200 ms;
- che all'accensione o al reset dell'ESP il GPIO42 resti basso: niente impulsi spuri verso il Pi, e l'ESP parte normalmente (vedi 2.2 e [issues.md #11](../issues.md));
- che non ci sia back-powering dal GPIO17 quando l'ESP è spento ([issues.md #26](../issues.md)).

Il firmware non manda l'impulso se ALIVE è già alto. Questo però si basa solo sul livello del pin e non è un vero controllo dello stato del Pi.

---

## 4. Prove al banco

Procedi nell'ordine e passa alla fase successiva solo quando il risultato atteso è confermato. **Scollega l'alimentazione prima di cambiare i collegamenti**; non collegare GPIO17 al GPIO1 dell'ESP finché la misura ALIVE indicata sotto non è stata fatta. Se una misura o un comportamento non corrisponde a quanto atteso, fermati e controlla schema, pin e configurazione prima di alimentare il circuito successivo.

Annota per ogni prova scheda/revisione, pin, alimentazione, misura e risultato. In particolare, non dare per scontata la massa o la polarità dei pad: verifica sul Pi reale.

### A. Verifica separata delle schede

1. **Pi da solo.** Avvia e arresta il Pi; verifica la configurazione EEPROM effettiva e che il pulsante di accensione lo riavvii dall'halt. Non collegare ancora ESP o circuito WAKE.
2. **ESP da sola: compilazione e caricamento del firmware.** Per queste operazioni lascia la ESP32-S3-CAM scollegata dal Pi e collega via USB solo il convertitore USB-seriale della scheda. Chiudi eventuali altri programmi che stanno usando la stessa porta seriale.

   Puoi usare PlatformIO in uno di questi due modi:

   - **Visual Studio Code:** installa l'estensione *PlatformIO IDE*, apri in VS Code la cartella `firmware/esp32` (quella che contiene `platformio.ini`) e attendi che PlatformIO installi la piattaforma ESP32 e le librerie. Nella barra di PlatformIO seleziona l'ambiente `esp32s3_cam`; usa **Build** per compilare e **Upload** per scrivere il firmware nella memoria flash della scheda. Il terminale integrato è un'alternativa ai pulsanti dell'interfaccia.
   - **Terminale:** installa PlatformIO Core, che fornisce il comando `pio`, apri un terminale nella root del repository e usa:

```bash
cd firmware/esp32                            # entra nella cartella con platformio.ini
pio run                                      # compila e installa le dipendenze necessarie
pio run -t upload                            # compila e carica il firmware nella ESP32 (con il Pi spento, vedi 2.3)
```

`pio run` controlla il codice e produce il firmware; `pio run -t upload` lo trasferisce nella memoria flash della scheda. Il file generato si trova in `.pio/build/esp32s3_cam/firmware.bin`, ma normalmente non occorre selezionarlo o copiarlo: è PlatformIO a caricarlo. Attendi il messaggio di caricamento completato prima di scollegare la USB. Se la board di collegamento è già montata, carica il firmware **con il Pi spento** o con la board staccata: carica con il circuito Pi–ESP scollegato finché il comportamento dei pin di boot non è verificato (vedi 2.3).

Se PlatformIO non trova la porta, individua quella assegnata dal sistema e specificala esplicitamente. È spesso `/dev/ttyUSB0` o `/dev/ttyACM0` su Linux, `COM3` (o un altro `COM`) su Windows e `/dev/cu.usbserial-...` su macOS:

```bash
pio run -t upload --upload-port /dev/ttyUSB0
```

Sostituisci l'esempio con la porta effettiva. Per il primo caricamento, o se l'upload si blocca su "Connecting", questa ESP32-S3-CAM potrebbe richiedere la modalità bootloader: collega GPIO0 a GND, premi e rilascia RESET (o togli e ridai alimentazione), avvia l'upload e, quando inizia il trasferimento, rilascia GPIO0 da GND. Se il convertitore ha pulsanti `BOOT` e `RST/RESET`, in genere si ottiene lo stesso risultato tenendo premuto `BOOT`, premendo e rilasciando `RST`, poi rilasciando `BOOT` quando parte il caricamento. La sequenza può dipendere dal convertitore. A upload concluso, **rimuovi ogni collegamento GPIO0-GND e riavvia**.

3. **Apri il monitor seriale.** Dopo l'upload, avvia il monitor a 115200 baud per vedere i messaggi del firmware:

```bash
pio device monitor
# Se necessario, indica anche qui la porta:
pio device monitor --port /dev/ttyUSB0
```

Con l'estensione VS Code puoi usare l'azione **Monitor** di PlatformIO, impostata a 115200 baud (`monitor_speed` è già configurato in `platformio.ini`). Per chiudere il monitor da terminale, premi `Ctrl+C`; la porta deve essere libera per fare un nuovo upload.

All'avvio il log dovrebbe mostrare l'esito dell'inizializzazione BME280 e la riga `Pin ESP32-S3-CAM: ...` con i GPIO configurati.

Il comando seriale `w` seguito da Invio richiede immediatamente un wake. Provalo solo dopo avere completato le verifiche elettriche e collegato correttamente il circuito: se ALIVE risulta basso, il firmware aziona WAKE. Con Pi acceso e ALIVE alto, il log deve invece mostrare che l'impulso viene saltato.

Il comando `r` richiama una misura del BME280; nel sorgente attuale `sendReading()` scrive anche sulla UART, quindi provarlo con il Pi scollegato. Il bus I2C è configurato sui GPIO47 (SDA) e 48 (SCL). Il rilevamento con la camera non è implementato.

### B. Prove separate, ESP non collegata al Pi

4. **Alimentazione indipendente.** Verifica che ESP e BME restino alimentati mentre il Pi è in halt. Il Pi può spegnere le proprie uscite in questa condizione: non alimentare l'ESP dal GPIO del Pi.
5. **Misura ALIVE sul solo Pi.** Con il Pi acceso, misura GPIO17 rispetto a GND e annota il valore. Ripeti dopo `sudo halt`, lasciando collegata l'alimentazione, e annota anche quel valore. Il GPIO si configura alto durante il boot, ma non assumere che mantenga quel livello in halt. Se misuri tensione inattesa o instabile, non collegarlo all'ESP: ricontrolla configurazione e cablaggio. Solo dopo questa verifica prepara il collegamento GPIO17→GPIO1 dell'ESP con pulldown da 10 kΩ e massa comune, a schede spente.
6. **Prova isolatore scollegato dal Pi.** Alimenta il lato LED con una sorgente da banco a bassa tensione e corrente limitata, rispettando la resistenza da 330 Ω; verifica che il transistor del PC817 commuti e che torni aperto quando togli il comando. Misura la commutazione in tensione: non usare la modalità continuità/resistenza su un circuito alimentato. Con l'oscilloscopio controlla anche che il GPIO42 (WAKE) resti basso durante il reset dell'ESP. Identifica con il multimetro, a Pi spento, quale pad J2 è GND. Non collegare ancora i fili a J2.

### C. Prova integrata

7. Collega l'uscita isolata del PC817 ai pad J2 identificati, poi collega ALIVE già verificato. Mantieni l'ESP alimentato indipendentemente. Controlla a vista che non ci siano corti o fili scambiati prima di riaccendere.
8. Con il Pi **acceso**, apri il monitor seriale e invia `w` seguito da Invio. Il log deve indicare `ALIVE HIGH` e non deve esserci impulso su WAKE. Se il log indica `ALIVE LOW`, interrompi la prova e ricontrolla il segnale prima di lasciare che l'ESP chiuda J2.
9. Metti il Pi in halt lasciando alimentata l'ESP e invia `w`. Verifica il singolo impulso breve (200 ms), l'avvio del Pi e il passaggio di ALIVE al livello misurato durante il boot. Se il Pi non si avvia o ALIVE non cambia come previsto, interrompi e ricontrolla; non ripetere impulsi alla cieca. ALIVE segnala solo il livello GPIO, non che Linux abbia completato l'avvio.
10. **UART.** Collega il TX dell'ESP (GPIO2, con la resistenza da 1 kΩ) al RXD del Pi e apri `picocom -b 9600 /dev/ttyAMA0` sul Pi (vedi 2.5). Dopo il ritardo di 60 s arriva una riga `BME,uptime,temp,umidita,pressione`, poi una riga al minuto. Con il Pi in halt, misura che sul pin RXD del Pi non arrivi tensione dall'ESP.
11. La camera OV3660 è montata sulla scheda, ma il firmware attuale non la inizializza; la prova di acquisizione e il rilevamento restano da implementare.
12. **Solo dopo il collaudo del ciclo completo**, abilita il servizio di scatto di §1 e verifica una foto, la lettura sensori e lo spegnimento previsto. Non abilitarlo durante prove o raccolta continua: spegne il Pi a ogni avvio.

---

## 5. Sensori sul Pi

Secondo il piano GPS, sensore acqua, umidità del suolo e metano vanno sul Pi, mentre il BME280 va solo sull'ESP. Le interfacce previste sono UART per il GPS, ADC (MCP3008 su SPI) per i sensori analogici e GPIO per gli ingressi digitali. Dipendono però dai modelli che compreremo. I pin in `raspberry_pi/smartcam/sensors.py` sono solo un esempio.

Il flusso `--oneshot` fa una foto, legge i sensori una volta e termina, così il servizio può spegnere il Pi. La modalità continuativa (cadenze diverse per foto e misure, fascia oraria, database) non è ancora implementata.
