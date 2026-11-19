# Configurazione di Raspberry Pi ed ESP32

Questa guida raccoglie le configurazioni di Pi ed ESP32 e l'ordine in cui conviene fare le prove al banco. I requisiti sono quelli di [`plan.pdf`](plan.pdf). Tutto quello che riguarda l'hardware è da **verificare sulle schede vere** prima di collegare qualcosa: non siamo ancora alla configurazione di campo.

## A che punto siamo

- **ESP32:** il firmware in `firmware/esp32/src/main.cpp` gira su una ESP32-CAM AI-Thinker. Sa svegliare il Pi, ma solo a mano per il momento (comando `w` dal monitor seriale): il rilevamento automatico è uno stub che non scatta mai. Non legge ancora il BME280 e non contiene forecaster né decider.
- **Circuito di risveglio:** lo schema c'è, ma va ancora montato e provato.
- **Raspberry Pi:** ci sono gli script di scatto e di lettura sensori. Database, modalità continuativa e analisi delle immagini sono ancora da fare.

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

(`op` = uscita, `dh` = livello alto). Il collegamento è GPIO17 del Pi → GPIO13 dell'ESP, con un pulldown da 10 kΩ verso massa e la massa in comune.

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

## 2. ESP32 e BME280

In `firmware/esp32/platformio.ini` la board è `esp32cam`. Il firmware usa:

| Pin ESP | Funzione |
|---|---|
| GPIO14 | WAKE (uscita, verso il PC817) |
| GPIO13 | ALIVE (ingresso, dal GPIO17 del Pi) |

Sulla ESP32-CAM quasi tutti i pin sono occupati dalla camera. In particolare il **GPIO21 è il segnale Y5 della camera**, quindi non si può usare come SDA per il BME280 finché la camera è attiva. È uno dei motivi per cui la scheda definitiva sarà un'altra.

Il BME280 va **solo sull'ESP32**, fuori dal box, nella sua custodia. Il driver è `firmware/esp32/src/bme_reader.cpp` e usa una sola libreria, Adafruit BME280 per Arduino, dichiarata in `platformio.ini`; `beginBme280()` avvia I²C sui pin passati e `readBme280()` restituisce temperatura in °C, umidità in percentuale e pressione in hPa. Lo schema del modulo GY-BME280 (indirizzo `0x76`) è in [`hardware/sensors/BME280/`](../hardware/sensors/BME280/GY-BME280.md.md).

Il driver è pronto ma non viene ancora chiamato dal programma principale. Inoltre i pin dello schema (SDA GPIO21, SCL GPIO22) sulla ESP32-CAM corrente sono occupati rispettivamente dalla camera (Y5 e PCLK): **non collegare il BME a quei pin finché si usa la camera**. Occorre scegliere pin I²C liberi compatibili con la scheda definitiva prima di inizializzare il driver. Il protocollo, il formato e la sincronizzazione per trasferire le misure dall'ESP al Pi restano da definire.

---

## 3. Circuito di risveglio (WAKE → J2)

Lo schema KiCad è in [`hardware/pi5->esp32/`](../hardware/pi5-%3Eesp32/circuito.png):

```
ESP GPIO14 ──[330 Ω]──► PC817 pin 1 (anodo LED)
ESP GND    ───────────► PC817 pin 2 (catodo LED)
                         PC817 pin 4 (collettore) ──► J2 SIG
                         PC817 pin 3 (emettitore) ──► J2 GND

Pi GPIO17  ─────────┬──► ESP GPIO13
                   [10 kΩ]
                    │
GND comune ─────────┴─── (masse di Pi ed ESP collegate)
```

Quando l'ESP porta GPIO14 alto per 200 ms, il LED interno del PC817 si accende, il fototransistor conduce e chiude i due pad J2, proprio come quando si preme il pulsante. Con l'optoisolatore il GPIO dell'ESP non tocca mai direttamente i pad del Pi. La resistenza da 330 Ω limita la corrente del LED a circa 6 mA ((3,3 V − 1,2 V) / 330 Ω).

Cose da verificare prima di collegarlo al Pi:

- quale dei due pad J2 è effettivamente la massa (non darlo per scontato, va misurato);
- che il PC817 chiuda J2 in modo affidabile con l'impulso da 200 ms;
- che all'accensione o al reset dell'ESP il GPIO14 non generi impulsi spuri ([issues.md #11](../issues.md));
- che non ci sia back-powering dal GPIO17 quando l'ESP è spento ([issues.md #26](../issues.md)).

Il firmware non manda l'impulso se ALIVE è già alto. Questo però si basa solo sul livello del pin e non è un vero controllo dello stato del Pi.

---

## 4. Prove al banco

Procedi nell'ordine e passa alla fase successiva solo quando il risultato atteso è confermato. **Scollega l'alimentazione prima di cambiare i collegamenti**; non collegare GPIO17 al GPIO13 finché la misura ALIVE indicata sotto non è stata fatta. Se una misura o un comportamento non corrisponde a quanto atteso, fermati e controlla schema, pin e configurazione prima di alimentare il circuito successivo.

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
pio run -t upload                            # compila e carica il firmware nella ESP32
```

`pio run` controlla il codice e produce il firmware; `pio run -t upload` lo trasferisce nella memoria flash della scheda. Il file generato si trova in `.pio/build/esp32cam/firmware.bin`, ma normalmente non occorre selezionarlo o copiarlo: è PlatformIO a caricarlo. Attendi il messaggio di caricamento completato prima di scollegare la USB.

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

Il comando seriale `w` seguito da Invio richiede immediatamente un wake. Provalo solo dopo avere completato le verifiche elettriche e collegato correttamente il circuito: se ALIVE risulta basso, il firmware aziona WAKE. Con Pi acceso e ALIVE alto, il log deve invece mostrare che l'impulso viene saltato.

La ESP32-CAM corrente non usa ancora il BME280; il rilevamento automatico è uno stub e non genera wake. Quando firmware e pin I²C saranno pronti, prova il BME alimentando ESP e sensore senza il Pi e controlla che indirizzo e valori siano plausibili. Non usare GPIO21/22 per il BME su questa ESP32-CAM: sono usati dalla camera.

### B. Prove separate, ESP non collegata al Pi

4. **Alimentazione indipendente.** Verifica che ESP (e BME, quando integrato) restino alimentati mentre il Pi è in halt. Il Pi può spegnere le proprie uscite in questa condizione: non alimentare l'ESP dal GPIO del Pi.
5. **Misura ALIVE sul solo Pi.** Con il Pi acceso, misura GPIO17 rispetto a GND e annota il valore. Ripeti dopo `sudo halt`, lasciando collegata l'alimentazione, e annota anche quel valore. Il GPIO si configura alto durante il boot, ma non assumere che mantenga quel livello in halt. Se misuri tensione inattesa o instabile, non collegarlo all'ESP: ricontrolla configurazione e cablaggio. Solo dopo questa verifica prepara il collegamento GPIO17→GPIO13 con pulldown da 10 kΩ e massa comune, a schede spente.
6. **Prova isolatore scollegato dal Pi.** Alimenta il lato LED con una sorgente da banco a bassa tensione e corrente limitata, rispettando la resistenza da 330 Ω; verifica che il transistor del PC817 commuti e che torni aperto quando togli il comando. Misura la commutazione in tensione: non usare la modalità continuità/resistenza su un circuito alimentato. Identifica con il multimetro, a Pi spento, quale pad J2 è GND. Non collegare ancora i fili a J2.

### C. Prova integrata

7. Collega l'uscita isolata del PC817 ai pad J2 identificati, poi collega ALIVE già verificato. Mantieni l'ESP alimentato indipendentemente. Controlla a vista che non ci siano corti o fili scambiati prima di riaccendere.
8. Con il Pi **acceso**, apri il monitor seriale e invia `w` seguito da Invio. Il log deve indicare `ALIVE HIGH` e non deve esserci impulso su WAKE. Se il log indica `ALIVE LOW`, interrompi la prova e ricontrolla il segnale prima di lasciare che l'ESP chiuda J2.
9. Metti il Pi in halt lasciando alimentata l'ESP e invia `w`. Verifica il singolo impulso breve (200 ms), l'avvio del Pi e il passaggio di ALIVE al livello misurato durante il boot. Se il Pi non si avvia o ALIVE non cambia come previsto, interrompi e ricontrolla; non ripetere impulsi alla cieca. ALIVE segnala solo il livello GPIO, non che Linux abbia completato l'avvio.
10. Verifica che la camera ESP acquisisca frame. Questa prova non verifica il rilevamento: al momento `eventDetected()` restituisce sempre `false`. Quando il rilevamento sarà implementato, prova casi positivi e negativi, cooldown e comportamento con Pi acceso e in halt.
11. **Solo dopo il collaudo del ciclo completo**, abilita il servizio di scatto di §1 e verifica una foto, la lettura sensori e lo spegnimento previsto. Non abilitarlo durante prove o raccolta continua: spegne il Pi a ogni avvio.

---

## 5. Sensori sul Pi

Secondo il piano GPS, sensore acqua, umidità del suolo e metano vanno sul Pi, mentre il BME280 va solo sull'ESP. Le interfacce previste sono UART per il GPS, ADC (MCP3008 su SPI) per i sensori analogici e GPIO per gli ingressi digitali. Dipendono però dai modelli che compreremo. I pin in `raspberry_pi/smartcam/sensors.py` sono solo un esempio.

Il flusso `--oneshot` fa una foto, legge i sensori una volta e termina, così il servizio può spegnere il Pi. La modalità continuativa (cadenze diverse per foto e misure, fascia oraria, database) non è ancora implementata.
