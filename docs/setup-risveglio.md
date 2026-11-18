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

Conviene procedere un pezzo alla volta e annotare ogni volta scheda, pin, alimentazione, misure e risultato:

1. Pi da solo: boot, spegnimento, impostazioni EEPROM.
2. ESP e BME alimentati in modo indipendente dal Pi: devono restare accesi con il Pi in halt.
3. BME280 sull'ESP (quando ci sarà il firmware): indirizzo e valori plausibili.
4. ALIVE: misurare il GPIO17 a Pi acceso e in halt, **prima** di collegarlo all'ESP.
5. Circuito PC817 da solo, senza collegarlo al Pi: controllare con il multimetro che chiuda il contatto.
6. Comando `w` con il Pi acceso: siccome ALIVE è alto, l'impulso non deve partire.
7. Wake da halt: forma e durata dell'impulso, boot del Pi, ALIVE che sale.
8. Camera dell'ESP: solo che acquisisca i frame (il rilevamento non esiste ancora).
9. Quando ci sarà il rilevamento: casi positivi e negativi, cooldown, comportamento con Pi acceso e in halt.
10. Solo alla fine abilitare il servizio di scatto, dopo aver verificato che foto e spegnimento funzionino.

Sì: `platformio.ini` configura compilazione e dipendenze, mentre il caricamento si esegue con il target `upload`. Installare PlatformIO Core (`pio`) oppure l'estensione PlatformIO IDE, collegare la scheda via USB e aprire un terminale nella root del repository. Poi entrare nella cartella del progetto firmware ed eseguire:

```bash
cd firmware/esp32
pio run                                      # compila e scarica le librerie dichiarate
pio run -t upload                           # compila, poi carica sulla scheda
pio device monitor                          # monitor seriale a 115200 baud
# Se PlatformIO non trova la porta USB, indicarla esplicitamente, per esempio:
pio run -t upload --upload-port /dev/ttyUSB0
pio device monitor --port /dev/ttyUSB0
```

Su Windows la porta è tipicamente `COM3` (sostituire con quella mostrata dal sistema); su macOS `/dev/cu.usbserial-...`. La porta dipende dal convertitore USB della scheda. Per il primo caricamento della ESP32-CAM può essere necessario mettere la scheda in modalità bootloader (GPIO0 a GND durante il reset), poi rimuovere il ponticello e riavviare.

Nel monitor, scrivere `w` e premere Invio prova il percorso di wake a mano.

---

## 5. Sensori sul Pi

Secondo il piano GPS, sensore acqua, umidità del suolo e metano vanno sul Pi, mentre il BME280 va solo sull'ESP. Le interfacce previste sono UART per il GPS, ADC (MCP3008 su SPI) per i sensori analogici e GPIO per gli ingressi digitali. Dipendono però dai modelli che compreremo. I pin in `raspberry_pi/smartcam/sensors.py` sono solo un esempio.

Il flusso `--oneshot` fa una foto, legge i sensori una volta e termina, così il servizio può spegnere il Pi. La modalità continuativa (cadenze diverse per foto e misure, fascia oraria, database) non è ancora implementata.
