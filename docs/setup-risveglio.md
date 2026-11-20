# Configurazione di Raspberry Pi ed ESP32-CAM

Questa guida raccoglie le configurazioni di Pi ed ESP32-CAM, i collegamenti tra le due schede e l'ordine in cui conviene fare le prove al banco. I requisiti sono quelli di [`plan.pdf`](plan.pdf). Tutto quello che riguarda l'hardware è da **verificare sulle schede vere** prima di collegare qualcosa: non siamo ancora alla configurazione di campo.

## A che punto siamo

- **ESP32:** il firmware in `firmware/esp32/src/main.cpp` gira su una **ESP32-CAM** (pinout AI-Thinker, scheda non modificata). Acquisisce i frame della camera di bordo, sveglia il Pi (per ora solo a mano, con il comando `w`: il rilevamento in `eventDetected()` è da scrivere) e, quando il Pi si accende, gli manda via UART le misure del BME280. Il firmware compila, ma non è ancora stato provato sulla scheda.
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

(`op` = uscita, `dh` = livello alto). Il collegamento è GPIO17 del Pi → GPIO2 dell'ESP, con un pulldown da 10 kΩ verso massa e la massa in comune.

Va verificato con il multimetro cosa fa il pin durante boot, funzionamento, spegnimento e halt. ALIVE dice solo che il pin è alto: non garantisce che Linux sia pronto, e durante lo spegnimento resta alto per un po'.

### Servizio di scatto (app selettiva)

L'unità [`insect-capture.service`](../raspberry_pi/systemd/insect-capture.service) a ogni boot fa una foto più una lettura dei sensori e poi spegne il Pi. Lo spegne **in ogni caso**: sia se va tutto bene, sia se qualcosa fallisce, sia se lo script si blocca per più di 3 minuti. I percorsi sono quelli del nostro Pi (`/home/rpi5-03/tesi`): prima di installarla vanno controllati utente, directory e file d'ambiente.

```bash
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

## 2. ESP32-CAM: camera, BME280 e collegamento con il Pi

### 2.1 La scheda e cosa fa il firmware

Usiamo una **ESP32-CAM con pinout AI-Thinker**, con la camera collegata al connettore a flat della scheda. Il sensore della camera di solito è un OV2640, ma il driver riconosce da solo anche gli altri modelli compatibili (OV3660, OV5640). **La scheda non va modificata**: tutti i collegamenti passano dai pin laterali, che vanno a una board di collegamento tra ESP e Pi.

Sulla scheda gira **un unico firmware** (`firmware/esp32/src/main.cpp`) con tre funzioni:

| Funzione | Come funziona | Stato |
|---|---|---|
| **Risveglio su evento** | la camera acquisisce frame di continuo; quando `eventDetected()` vede qualcosa (ad esempio un insetto che passa davanti alla camera) l'ESP accende il Pi | l'acquisizione c'è, l'algoritmo di rilevamento è da scrivere |
| **Risveglio manuale** | per le prove: scrivere `w` nel monitor seriale USB | funzionante |
| **Misure del BME280** | quando il Pi si accende l'ESP fa una misura e gliela manda; poi una al minuto finché il Pi resta acceso | funzionante |

Le immagini della camera dell'ESP servono solo a decidere *quando* svegliare il Pi e non vengono inviate: le foto per il dataset le fanno le fotocamere del Pi.

In `firmware/esp32/platformio.ini` la board è `esp32cam`, con la PSRAM attiva e la tabella delle partizioni `huge_app.csv`.

La scheda va alimentata a **5 V** dal suo pin dedicato, con un alimentatore indipendente dal Pi, perché deve restare accesa anche con il Pi in halt. La camera assorbe picchi di corrente, quindi serve un alimentatore che regga almeno 500 mA: con alimentazioni deboli la ESP32-CAM tende a riavviarsi (*brown-out*).

### 2.2 I pin disponibili

Sulla ESP32-CAM quasi tutti i GPIO sono già occupati:

| GPIO | Occupato da |
|---|---|
| 0, 5, 18, 19, 21, 22, 23, 25, 26, 27, 32, 34, 35, 36, 39 | camera (clock, bus dei pixel, sincronismi, bus di configurazione, power-down) |
| 16 | PSRAM |
| 1, 3 | UART0: programmazione e monitor seriale via USB |
| 33 | LED rosso sul retro della scheda |
| 4 | LED flash: qualsiasi livello alto lo accende |

Sui pin laterali restano **2, 12, 13, 14, 15** (sono le linee dello slot microSD), ciascuno con qualche vincolo:

| GPIO | Vincolo | Cosa ci può andare |
|---|---|---|
| 2 | pin di *strapping*: per **caricare il firmware** deve essere basso | un ingresso che a Pi spento è basso: **ALIVE** |
| 12 | pin di *strapping*: se è **alto al reset** l'ESP imposta la flash a 1,8 V e **non parte** | solo un'uscita bassa a riposo: **WAKE** (il LED del PC817 verso massa lo tiene basso) |
| 13 | nessuno | **SDA** del BME280 |
| 14 | all'avvio emette per qualche istante un segnale PWM ([issues.md #11](../issues.md)) | **TX verso il Pi**: al massimo il Pi riceve qualche byte spurio. Non WAKE, perché accenderebbe il Pi a ogni reset dell'ESP |
| 15 | pin di *strapping*: se è basso all'avvio l'ESP non stampa il log di boot (innocuo) | **SCL** del BME280: le resistenze di pull-up del modulo lo tengono alto, cioè al valore normale |

Sono cinque pin per cinque funzioni. Non ne avanza uno per la ricezione dal Pi, quindi **la UART va solo dall'ESP al Pi** (vedi 2.5).

### 2.3 Collegamenti verso la board

| ESP32-CAM | Funzione | Sulla board / verso il Pi |
|---|---|---|
| GPIO12 | WAKE (uscita) | 330 Ω → PC817 pin 1; il PC817 chiude i pad J2 del Pi (sezione 3) |
| GPIO2 | ALIVE (ingresso) | ← GPIO17 del Pi (pin fisico 11), pulldown 10 kΩ verso massa |
| GPIO14 | TX (UART2) | 1 kΩ in serie → GPIO15 / RXD del Pi (pin fisico 10) |
| GPIO13 | SDA I2C | SDA del GY-BME280 |
| GPIO15 | SCL I2C | SCL del GY-BME280 |
| 3V3 | alimentazione del sensore | VCC e CSB del GY-BME280 |
| GND | massa comune | GND del Pi (es. pin fisico 6), catodo del PC817, GND e SDO del GY-BME280 |
| 5V | alimentazione della scheda | alimentatore indipendente |

Componenti sulla board: PC817 con la resistenza da 330 Ω, pulldown da 10 kΩ su ALIVE, resistenza da 1 kΩ in serie sul TX, connettori verso il Pi e verso il BME280.

Tre conseguenze pratiche:

- **il firmware si carica con il Pi spento** (o con la board staccata): se ALIVE è alto, il GPIO2 impedisce all'ESP di entrare in modalità di programmazione;
- **la microSD non va inserita**, perché i suoi pin sono usati per altro;
- il monitor seriale USB (GPIO1/3) resta libero per i log e per i comandi di prova.

Rispetto al primo schema cambiano tre cose: WAKE passa dal GPIO14 al GPIO12, ALIVE dal GPIO13 al GPIO2, e il BME280 dai GPIO21/22 (che sulla ESP32-CAM sono pin della camera) ai GPIO13/15. Vanno quindi aggiornati i due schemi KiCad: [`hardware/pi5->esp32/`](../hardware/pi5-%3Eesp32/circuito.png) e [`hardware/sensors/BME280/`](../hardware/sensors/BME280/GY-BME280.md.md).

### 2.4 BME280

Il BME280 ha un suo bus I2C sui GPIO13 (SDA) e 15 (SCL), aperto con `Wire` sulla porta I2C 0 dell'ESP32. La camera si configura con un altro bus I2C (nei suoi datasheet si chiama SCCB), sui GPIO26/27 e sulla porta I2C 1: i due bus sono indipendenti.

Il sensore si legge con la libreria [SparkFun BME280](https://github.com/sparkfun/SparkFun_BME280_Arduino_Library) in *forced mode*: il BME280 fa una misura solo quando glielo chiediamo e poi torna in sleep, così consuma meno e non si scalda. Oversampling ×1 e filtro spento sono la configurazione che il datasheet Bosch consiglia per il monitoraggio meteo. L'indirizzo è `0x76`, perché sul modulo SDO è a massa.

La libreria Adafruit BME280, che avevamo previsto, qui non si può usare: la sua dipendenza *Adafruit Unified Sensor* definisce un tipo `sensor_t` con lo stesso nome di uno del driver della camera, e il firmware non compila.

Se il sensore non risponde il firmware riprova ogni 10 s, e intanto camera, wake e UART continuano a funzionare. Il bus va a 100 kHz: con il cavo lungo verso la custodia esterna, se le letture falliscono, si può abbassare `I2C_FREQ_HZ` in `main.cpp`.

### 2.5 Invio delle misure al Pi (UART)

**Quando parte una misura.** L'ESP segue il segnale ALIVE:

```
ALIVE sale (il Pi si accende) ──► misura del risveglio (tipo W), subito
        │
        │  attesa di PI_BOOT_DELAY_MS = 60 s (il Pi finisce il boot)
        ▼
invio della misura W ──► poi una misura P ogni BME_PERIOD_MS = 60 s
        │
ALIVE scende (il Pi si spegne) ──► la UART si chiude
```

La misura W è quella fatta *nel momento del risveglio*, anche se arriva al Pi un minuto dopo. Il ritardo serve perché il programma che la riceve deve essere già partito: va tarato sul tempo di boot reale del nostro Pi. Le misure P servono alla modalità continuativa; se non servono basta mettere `BME_PERIOD_MS = 0`. Con il Pi spento l'ESP non manda niente e non tiene uno storico.

**Formato.** 115200 baud, 8N1, una riga di testo per misura:

```
BME,<seq>,<tipo>,<age_ms>,<temp_C>,<rh_%>,<press_hPa>
```

Esempio: `BME,7,W,60012,18.25,64.10,1012.37`.

| Campo | Significato |
|---|---|
| `seq` | numero progressivo della misura; riparte da 1 quando l'ESP si riavvia |
| `tipo` | `W` = misura del risveglio, `P` = misura periodica |
| `age_ms` | quanti millisecondi fa è stata fatta la misura |
| `temp_C`, `rh_%`, `press_hPa` | temperatura (°C), umidità relativa (%), pressione (hPa) |

L'ESP non ha un orologio vero, quindi invece dell'ora manda l'età della misura: il Pi calcola l'ora della misura come *ora di ricezione − age_ms*. Così ogni misura ha sia l'orario in cui è stata **fatta** sia quello in cui il Pi l'ha **ricevuta**, come chiede il piano.

**Back-powering.** ESP e Pi lavorano entrambi a 3,3 V, quindi il filo TX va direttamente al RXD del Pi, senza adattatori di livello. Con `POWER_OFF_ON_HALT=1`, però, il Pi in halt è senza alimentazione, mentre una linea TX a riposo sta **alta**: se l'ESP tenesse la UART sempre aperta, alimenterebbe il Pi spento attraverso il suo RXD (lo stesso fenomeno di [issues.md #26](../issues.md)). Per questo il firmware apre la UART solo quando ALIVE è alto e la chiude quando scende, lasciando il pin come ingresso. La resistenza da 1 kΩ limita la corrente nei casi che il firmware non copre (il PWM del GPIO14 all'avvio dell'ESP, la fase di spegnimento del Pi).

**Configurazione del Pi.** Sul Pi 5 la UART sui GPIO14/15 è la UART0 (`/dev/ttyAMA0`); la console seriale di default sta invece sul connettore di debug dedicato. In `/boot/firmware/config.txt` aggiungiamo:

```ini
dtparam=uart0=on
```

e controlliamo con `sudo raspi-config` (*Interface Options → Serial Port*) che sulla seriale **non** ci sia la shell di login. Anche questo va verificato sulla [documentazione ufficiale](https://www.raspberrypi.com/documentation/computers/configuration.html#configure-uarts) per la versione di sistema installata.

Per vedere le righe che arrivano:

```bash
sudo apt install picocom
picocom -b 115200 /dev/ttyAMA0   # uscita: Ctrl-A Ctrl-X
```

Il programma che legge queste righe e le salva nel database **non è ancora scritto**.

### 2.6 Dalla camera al risveglio

A ogni giro di `loop()` (circa 5 volte al secondo) il firmware:

```
acquisisce un frame ──► eventDetected()? ──no──► fine del giro
                              │ sì
                              ▼
                     cooldown di 30 s passato? ──no──► evento ignorato
                              │ sì
                              ▼
                     ALIVE già alto? ──sì──► niente impulso (il Pi è già acceso)
                              │ no
                              ▼
                     impulso di 200 ms su WAKE ──► attesa di ALIVE (max 15 s)
```

`eventDetected()` è il punto in cui va scritto l'algoritmo di rilevamento: riceve il frame dalla camera e deve restituire `true` quando nell'immagine c'è qualcosa per cui vale la pena svegliare il Pi. **Oggi restituisce sempre `false`**, quindi i wake automatici non partono mai.

Il comando `w` dal monitor seriale passa per lo stesso percorso (`onEvent()`), quindi rispetta anche lui il cooldown e il controllo di ALIVE. Se la camera non si inizializza, il rilevamento resta disattivato ma il resto del firmware funziona.

---

## 3. Circuito di risveglio (WAKE → J2)

Lo schema KiCad è in [`hardware/pi5->esp32/`](../hardware/pi5-%3Eesp32/circuito.png):

```
ESP GPIO12 ──[330 Ω]──► PC817 pin 1 (anodo LED)
ESP GND    ───────────► PC817 pin 2 (catodo LED)
                         PC817 pin 4 (collettore) ──► J2 SIG
                         PC817 pin 3 (emettitore) ──► J2 GND

Pi GPIO17  ─────────┬──► ESP GPIO2
                   [10 kΩ]
                    │
GND comune ─────────┴─── (masse di Pi ed ESP collegate)
```

Quando l'ESP porta GPIO12 alto per 200 ms, il LED interno del PC817 si accende, il fototransistor conduce e chiude i due pad J2, proprio come quando si preme il pulsante. Con l'optoisolatore il GPIO dell'ESP non tocca mai direttamente i pad del Pi. La resistenza da 330 Ω limita la corrente del LED a circa 6 mA ((3,3 V − 1,2 V) / 330 Ω).

Cose da verificare prima di collegarlo al Pi:

- quale dei due pad J2 è effettivamente la massa (non darlo per scontato, va misurato);
- che il PC817 chiuda J2 in modo affidabile con l'impulso da 200 ms;
- che all'accensione o al reset dell'ESP il GPIO12 resti basso: niente impulsi spuri verso il Pi, e l'ESP parte normalmente (vedi 2.2 e [issues.md #11](../issues.md));
- che non ci sia back-powering dal GPIO17 quando l'ESP è spento ([issues.md #26](../issues.md)).

Il firmware non manda l'impulso se ALIVE è già alto. Questo però si basa solo sul livello del pin e non è un vero controllo dello stato del Pi.

---

## 4. Prove al banco

Procedi nell'ordine e passa alla fase successiva solo quando il risultato atteso è confermato. **Scollega l'alimentazione prima di cambiare i collegamenti**; non collegare GPIO17 al GPIO2 dell'ESP finché la misura ALIVE indicata sotto non è stata fatta. Se una misura o un comportamento non corrisponde a quanto atteso, fermati e controlla schema, pin e configurazione prima di alimentare il circuito successivo.

Annota per ogni prova scheda/revisione, pin, alimentazione, misura e risultato. In particolare, non dare per scontata la massa o la polarità dei pad: verifica sul Pi reale.

### A. Verifica separata delle schede

1. **Pi da solo.** Avvia e arresta il Pi; verifica la configurazione EEPROM effettiva e che il pulsante di accensione lo riavvii dall'halt. Non collegare ancora ESP o circuito WAKE.
2. **ESP da sola: compilazione e caricamento del firmware.** Per queste operazioni lascia la ESP32-CAM scollegata dal Pi e collega via USB solo il convertitore USB-seriale della scheda. Chiudi eventuali altri programmi che stanno usando la stessa porta seriale.

   Puoi usare PlatformIO in uno di questi due modi:

   - **Visual Studio Code:** installa l'estensione *PlatformIO IDE*, apri in VS Code la cartella `firmware/esp32` (quella che contiene `platformio.ini`) e attendi che PlatformIO installi la piattaforma ESP32 e le librerie. Nella barra di PlatformIO seleziona l'ambiente `esp32cam`; usa **Build** per compilare e **Upload** per scrivere il firmware nella memoria flash della scheda. Il terminale integrato è un'alternativa ai pulsanti dell'interfaccia.
   - **Terminale:** installa PlatformIO Core, che fornisce il comando `pio`, apri un terminale nella root del repository e usa:

```bash
cd firmware/esp32                            # entra nella cartella con platformio.ini
pio run                                      # compila e installa le dipendenze necessarie
pio run -t upload                            # compila e carica il firmware nella ESP32 (con il Pi spento, vedi 2.3)
```

`pio run` controlla il codice e produce il firmware; `pio run -t upload` lo trasferisce nella memoria flash della scheda. Il file generato si trova in `.pio/build/esp32cam/firmware.bin`, ma normalmente non occorre selezionarlo o copiarlo: è PlatformIO a caricarlo. Attendi il messaggio di caricamento completato prima di scollegare la USB. Se la board di collegamento è già montata, carica il firmware **con il Pi spento** o con la board staccata: con ALIVE alto il GPIO2 impedisce all'ESP di entrare in modalità di programmazione (vedi 2.3).

Se PlatformIO non trova la porta, individua quella assegnata dal sistema e specificala esplicitamente. È spesso `/dev/ttyUSB0` o `/dev/ttyACM0` su Linux, `COM3` (o un altro `COM`) su Windows e `/dev/cu.usbserial-...` su macOS:

```bash
pio run -t upload --upload-port /dev/ttyUSB0
```

Sostituisci l'esempio con la porta effettiva. Per il primo caricamento, o se l'upload si blocca su "Connecting", questa ESP32-CAM potrebbe richiedere la modalità bootloader: collega GPIO0 a GND, premi e rilascia RESET (o togli e ridai alimentazione), avvia l'upload e, quando inizia il trasferimento, rilascia GPIO0 da GND. Se il convertitore ha pulsanti `BOOT` e `RST/RESET`, in genere si ottiene lo stesso risultato tenendo premuto `BOOT`, premendo e rilasciando `RST`, poi rilasciando `BOOT` quando parte il caricamento. La sequenza può dipendere dal convertitore. A upload concluso, **rimuovi ogni collegamento GPIO0-GND e riavvia**.

3. **Apri il monitor seriale.** Dopo l'upload, avvia il monitor a 115200 baud per vedere i messaggi del firmware:

```bash
pio device monitor
# Se necessario, indica anche qui la porta:
pio device monitor --port /dev/ttyUSB0
```

Con l'estensione VS Code puoi usare l'azione **Monitor** di PlatformIO, impostata a 115200 baud (`monitor_speed` è già configurato in `platformio.ini`). Per chiudere il monitor da terminale, premi `Ctrl+C`; la porta deve essere libera per fare un nuovo upload.

All'avvio il log deve mostrare `Camera ready` e `BME280 ready at 0x76` (se il sensore è collegato) e la riga `Pins: ...` con i pin usati.

Il comando seriale `w` seguito da Invio richiede immediatamente un wake. Provalo solo dopo avere completato le verifiche elettriche e collegato correttamente il circuito: se ALIVE risulta basso, il firmware aziona WAKE. Con Pi acceso e ALIVE alto, il log deve invece mostrare che l'impulso viene saltato.

Il comando `r` fa una misura del BME280 e la stampa (solo sul monitor, non la manda al Pi): prova il BME alimentando ESP e sensore senza il Pi e controlla che indirizzo e valori siano plausibili, poi ripeti con il cavo lungo della custodia. Il BME280 va su GPIO13 (SDA) e GPIO15 (SCL), non su GPIO21/22, che su questa ESP32-CAM sono usati dalla camera (vedi 2.4). Il rilevamento automatico è ancora uno stub e non genera wake.

### B. Prove separate, ESP non collegata al Pi

4. **Alimentazione indipendente.** Verifica che ESP e BME restino alimentati mentre il Pi è in halt. Il Pi può spegnere le proprie uscite in questa condizione: non alimentare l'ESP dal GPIO del Pi.
5. **Misura ALIVE sul solo Pi.** Con il Pi acceso, misura GPIO17 rispetto a GND e annota il valore. Ripeti dopo `sudo halt`, lasciando collegata l'alimentazione, e annota anche quel valore. Il GPIO si configura alto durante il boot, ma non assumere che mantenga quel livello in halt. Se misuri tensione inattesa o instabile, non collegarlo all'ESP: ricontrolla configurazione e cablaggio. Solo dopo questa verifica prepara il collegamento GPIO17→GPIO2 dell'ESP con pulldown da 10 kΩ e massa comune, a schede spente.
6. **Prova isolatore scollegato dal Pi.** Alimenta il lato LED con una sorgente da banco a bassa tensione e corrente limitata, rispettando la resistenza da 330 Ω; verifica che il transistor del PC817 commuti e che torni aperto quando togli il comando. Misura la commutazione in tensione: non usare la modalità continuità/resistenza su un circuito alimentato. Con l'oscilloscopio controlla anche che il GPIO12 (WAKE) resti basso durante il reset dell'ESP. Identifica con il multimetro, a Pi spento, quale pad J2 è GND. Non collegare ancora i fili a J2.

### C. Prova integrata

7. Collega l'uscita isolata del PC817 ai pad J2 identificati, poi collega ALIVE già verificato. Mantieni l'ESP alimentato indipendentemente. Controlla a vista che non ci siano corti o fili scambiati prima di riaccendere.
8. Con il Pi **acceso**, apri il monitor seriale e invia `w` seguito da Invio. Il log deve indicare `ALIVE HIGH` e non deve esserci impulso su WAKE. Se il log indica `ALIVE LOW`, interrompi la prova e ricontrolla il segnale prima di lasciare che l'ESP chiuda J2.
9. Metti il Pi in halt lasciando alimentata l'ESP e invia `w`. Verifica il singolo impulso breve (200 ms), l'avvio del Pi e il passaggio di ALIVE al livello misurato durante il boot. Se il Pi non si avvia o ALIVE non cambia come previsto, interrompi e ricontrolla; non ripetere impulsi alla cieca. ALIVE segnala solo il livello GPIO, non che Linux abbia completato l'avvio.
10. **UART.** Collega il TX dell'ESP (GPIO14, con la resistenza da 1 kΩ) al RXD del Pi e apri `picocom -b 115200 /dev/ttyAMA0` sul Pi (vedi 2.5). Dopo circa 60 s dal boot deve arrivare la riga `BME,…,W,…`, poi una riga `P` al minuto. Con il Pi in halt, misura che sul pin RXD del Pi non arrivi tensione dall'ESP.
11. Verifica che la camera ESP acquisisca frame. Questa prova non verifica il rilevamento: al momento `eventDetected()` restituisce sempre `false`. Quando il rilevamento sarà implementato, prova casi positivi e negativi, cooldown e comportamento con Pi acceso e in halt.
12. **Solo dopo il collaudo del ciclo completo**, abilita il servizio di scatto di §1 e verifica una foto, la lettura sensori e lo spegnimento previsto. Non abilitarlo durante prove o raccolta continua: spegne il Pi a ogni avvio.

---

## 5. Sensori sul Pi

Secondo il piano GPS, sensore acqua, umidità del suolo e metano vanno sul Pi, mentre il BME280 va solo sull'ESP. Le interfacce previste sono UART per il GPS, ADC (MCP3008 su SPI) per i sensori analogici e GPIO per gli ingressi digitali. Dipendono però dai modelli che compreremo. I pin in `raspberry_pi/smartcam/sensors.py` sono solo un esempio.

Il flusso `--oneshot` fa una foto, legge i sensori una volta e termina, così il servizio può spegnere il Pi. La modalità continuativa (cadenze diverse per foto e misure, fascia oraria, database) non è ancora implementata.
