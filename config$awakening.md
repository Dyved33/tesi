# Configurazione e risveglio del Raspberry Pi 5

Guida operativa consolidata dai documenti `piconfig.md`, `espconfig.md` e dalla nota storica `awakening.md`. Le sezioni seguono l'ordine consigliato: architettura, configurazione Pi, ESP e sensori, infine prove fisiche. Le versioni complete dei tre documenti di partenza sono conservate nelle appendici in fondo, così questa guida ne contiene tutto il materiale prima della rimozione dei file separati.

> **Stato del progetto:** il firmware inizializza la camera ESP32-CAM AI-Thinker, ma `eventDetected()` scarta i frame e restituisce sempre `false`. Il wake automatico da camera quindi non è implementato; `w` dal monitor USB-seriale è solo un test manuale. Il codice BME280 non è ancora integrato nel firmware ESP. Inoltre il circuito elettrico tra WAKE e J2 non è stato definito: non è previsto un optoisolatore e non si deve collegare GPIO14 direttamente ai pad senza prima progettare e verificare l'interfaccia.

## 1. Come dovrebbe funzionare

1. L'ESP32 resta alimentato anche quando il Raspberry è in halt e legge il BME280, collegato solo all'ESP.
2. La camera AI-Thinker, se confermata, rileva un evento. Le fotocamere collegate al Raspberry fanno le acquisizioni di campo dopo l'avvio.
3. Il codice di rilevamento chiama `onEvent()`. Questa applica il cooldown e chiama `ensurePiOn()`.
4. `ensurePiOn()` legge ALIVE. Se è alto, non invia un altro impulso. Se è basso, chiama `pulseJ2()` per attivare WAKE per 200 ms, poi `waitForAlive()` controlla ogni 250 ms che ALIVE diventi alto, fino a 15 secondi.
5. L'impulso può accendere il Pi perché il circuito esterno deve simulare la chiusura momentanea dei due pad J2, cioè la pressione del pulsante. `ensurePiOn()` non è solo una verifica: dopo il controllo chiama esplicitamente la funzione che genera l'impulso. ALIVE alto conferma solo il livello elettrico previsto, non che Linux abbia finito il boot o sia pronto.

Il firmware attuale implementa i punti 3–5 e la cattura dei frame, ma non il rilevamento vero: `eventDetected()` acquisisce un frame e poi restituisce costantemente `false`. Ricevere un frame non è quindi sufficiente a generare un evento. Va aggiunto un algoritmo che analizzi i byte dell'immagine e restituisca `true` quando riconosce l'evento.

## 2. Raspberry Pi 5: stato di alimentazione e configurazione

Il Pi 5 non offre suspend-to-RAM. In halt il sistema operativo è fermo, ma la scheda resta collegata all'alimentazione e può essere riavviata dal pulsante o da J2. Se si stacca del tutto l'alimentazione, l'ESP non può riaccenderlo tramite J2. ESP e BME280 devono restare alimentati indipendentemente dallo stato del Pi.

Aggiornamento iniziale:

```bash
sudo apt update && sudo apt full-upgrade -y
sudo reboot
```

Configurare l'EEPROM:

```bash
sudo rpi-eeprom-config --edit
```

Verificare/impostare:

```ini
POWER_OFF_ON_HALT=1
WAKE_ON_GPIO=0
```

Verificare il risultato con `sudo rpi-eeprom-config`. `POWER_OFF_ON_HALT=1` riduce il consumo in halt e spegne il rail a 3,3 V citato nei documenti. `WAKE_ON_GPIO=0` riflette il percorso Pi 5 tramite pulsante/J2, non il vecchio wake via GPIO3 del Pi 4.

### Linea ALIVE

La configurazione proposta usa GPIO17 del Pi come indicatore e GPIO13 dell'ESP come ingresso. In `/boot/firmware/config.txt` è proposto:

```ini
gpio=17=op,dh
```

Poi riavviare il Pi. Collegamento documentato: GPIO17 del Pi → GPIO13 dell'ESP, pulldown da 10 kΩ da GPIO13 a GND lato ESP e massa comune. Nel firmware `pinMode(PIN_ALIVE, INPUT_PULLDOWN)` configura GPIO13 come ingresso digitale con pull-down interno; `digitalRead()` ne legge il livello. Confermare con misure al banco che il livello sia quello atteso sia a Pi avviato sia in halt: i documenti usano “ALIVE” come proxy dello stato del Pi, ma il GPIO non dimostra che il sistema operativo sia pronto.

### Altri sensori collegati al Pi

Il GPS (UART), i sensori analogici tramite ADC/SPI e il sensore acqua digitale sono sul Pi. Il BME280 di campo **non** va collegato all'I²C del Pi: è sul solo ESP. Per GPS/ADC abilitare UART/SPI se necessari (`raspi-config` o `dtparam=spi=on`, `enable_uart=1` in `config.txt`), aggiungere l'utente ai gruppi richiesti (`dialout`, `gpio`, ed eventualmente `i2c`) e installare le dipendenze Python descritte in piconfig. Le interfacce e i pacchetti vanno attivati solo per i sensori effettivamente montati.

Per l'app selettiva, il servizio Pi può fare una cattura al boot e poi eseguire `poweroff`; per l'app continuativa resta acceso nella finestra stabilita. Non attivare un servizio che spegne il Pi durante le prove di wake.

## 3. ESP32: scheda, pin e BME280

La configurazione PlatformIO presente usa `board = esp32cam`, cioè la AI-Thinker ESP32-CAM. Il firmware definisce GPIO14 come WAKE e GPIO13 come ALIVE. Sulla AI-Thinker GPIO21 è già usato dalla camera (segnale Y5), quindi non è disponibile come SDA finché la camera è attiva. Anche gli altri pin I²C vanno scelti dopo aver controllato il pinout completo della scheda; GPIO12 è un pin di strapping e GPIO16 è usato dalla PSRAM.

Il BME280 è previsto all'esterno del box, nel suo case, collegato a 3,3 V (dopo verifica del modulo), GND, SDA e SCL dell'ESP. L'indirizzo I²C usuale è `0x76` o `0x77`, da verificare sul modulo. Il firmware dovrà inizializzare I²C e il driver BME in `setup()`, rilevare il sensore, poi leggere periodicamente temperatura, umidità e pressione con timestamp. Un errore di lettura va registrato e non usato come misura valida. Le letture alimenteranno storico e futura politica forecaster/decider; la pressione è registrata ma esclusa dal decider TMC secondo la guida ESP. Il codice di lettura presente altrove nel repository va adattato alla libreria e al framework Arduino/PlatformIO prima di integrarlo.

Protocollo, trasporto ESP→Pi e sincronizzazione degli orologi non sono ancora definiti. Evitare di trasmettere verso il Pi quando ALIVE è basso, per ridurre il rischio di alimentarlo attraverso le linee dati.

### Wake e interfaccia verso J2

J2 è il connettore a due pad del Raspberry: chiudere brevemente i contatti simula il pulsante. Nel firmware GPIO14 viene impostato come uscita e `pulseJ2()` lo porta HIGH per 200 ms, poi LOW. Questo livello deve comandare un circuito che chiuda i due pad. L'optoisolatore non è previsto dalla documentazione corrente; tuttavia il circuito diretto non è ancora specificato. Prima di collegare GPIO14 a J2 occorre definire lo schema, controllare livelli e polarità e verificare l'interfaccia separatamente. Non trattare il codice firmware come schema elettrico.

La linea J2/pulsante può avviare il Pi da halt, ma una pressione prolungata può provocare uno spegnimento forzato. Per questo il firmware genera un impulso breve. La risposta esatta dipende dallo stato del Pi e dalla configurazione software.

#### Proposta di schema senza optoisolatore

Userei un piccolo relè con contatto normalmente aperto (NO): i due terminali del contatto vanno ai due pad J2, come un pulsante esterno. GPIO14 non deve pilotare direttamente la bobina: comanda la base di un transistor NPN attraverso una resistenza. L'emettitore del transistor va a GND ESP; il collettore va a un capo della bobina e l'altro capo della bobina alla sua alimentazione nominale. Una resistenza base-emettitore mantiene il transistor spento durante il boot. Un diodo di ricircolo va in antiparallelo alla bobina, con catodo al positivo e anodo al collettore. Scegliere relè, transistor, resistenze, diodo e alimentazione in base alle specifiche dei componenti.

```text
+V bobina ───── bobina ───── collettore NPN
     │                           emettitore ─── GND ESP
     └──── catodo D1   anodo ────┘

GPIO14 ── Rbase ── base NPN
                    │
                 Rpull-down
                    │
                  GND ESP

J2 pad 1 ───── contatto NO del relè ───── J2 pad 2
```

D1 è in parallelo alla bobina: catodo al positivo bobina, anodo al collettore.

Il contatto del relè resta separato elettricamente dalla bobina e collega solo i due terminali J2. La documentazione Raspberry descrive J2 come ingresso per un pulsante NO momentaneo che ponticella i due pad; il relè replica quel contatto. Un relè è diverso da un optoisolatore, pur mantenendo separati i due circuiti. Il contatto deve essere adatto a commutare un segnale di bassa tensione/corrente. Il diodo limita la sovratensione induttiva della bobina che altrimenti potrebbe danneggiare il transistor. Se si sceglie invece un transistor/MOSFET direttamente in parallelo a J2, prima bisogna conoscere schema e livelli dei due pad: non assumere che uno sia GND e non unire le masse senza averlo verificato. [Raspberry Pi: pulsante NO sui pad J2](https://www.raspberrypi.com/documentation/computers/raspberry-pi.html) · [Omron: pilotaggio relè con transistor e soppressione del transitorio bobina](https://components.omron.com/us-en/faq/relays/FAQE10040).

### PSRAM e camera

PSRAM significa *pseudo-static RAM*: memoria esterna aggiuntiva montata su alcune schede. `psramFound()` del core Arduino-ESP32 verifica se è disponibile; il codice usa allora buffer camera in PSRAM e può scegliere una risoluzione maggiore. Senza PSRAM usa memoria interna e una configurazione più piccola. `esp_camera_init()`, `camera_fb_t`, `esp_camera_fb_get()` e `esp_camera_fb_return()` fanno parte del driver `esp32-camera`, incluso dal framework. `CAMERA_GRAB_LATEST` è un'opzione del driver che preferisce il frame più recente. `fb` è il *frame buffer*: struttura con dati immagine, dimensione e metadati; dopo l'elaborazione va restituito al driver.

Inizialmente si può verificare solo che la camera catturi frame validi. In seguito l'algoritmo di visione dovrà analizzare il contenuto e produrre un esito evento. La presenza di un frame prova la cattura, non il riconoscimento.

## 4. Build, flash e monitor seriale

Da una shell sul computer di sviluppo, nella cartella del progetto ESP:

```bash
cd esp32
pio run
pio run -t upload
pio device monitor
```

Il monitor seriale è la finestra del computer collegata alla porta USB della scheda ESP32; va aperto a 115200 baud. Digitare `w` e premere Invio invia il carattere alla scheda e richiama `onEvent()`. Il comando è un test manuale del percorso WAKE, non una prova della detection della camera. Il primo evento è accettato subito; quelli seguenti sono limitati dal cooldown di 30 secondi.

## 5. Prove fisiche, nell'ordine consigliato

Eseguire le prove per passaggi, senza collegare subito insieme tutti i circuiti:

1. **Verificare il Pi da solo.** Avviare il Pi, provare una breve pressione del pulsante e confermare il comportamento; poi eseguire uno shutdown pulito. Confermare che in halt il Pi resta alimentato e che il pulsante/J2 può riavviarlo. Verificare le impostazioni EEPROM e GPIO17 con multimetro o analizzatore logico, senza presumere che `ALIVE` equivalga a “Linux pronto”.
2. **Verificare l'alimentazione autonoma ESP.** Alimentare ESP e BME in modo che restino accesi quando il Pi è in halt. Controllare tensioni, polarità e stabilità dell'alimentazione; non usare il rail 3,3 V del Pi se si spegne in halt.
3. **Provare il BME280 isolatamente.** Collegare VCC, GND, SDA e SCL ai pin ESP scelti e verificare con il firmware di prova che il sensore risponda a `0x76` o `0x77` e fornisca valori plausibili. Ripetere mentre il Pi è in halt per confermare che ESP e sensore restino operativi.
4. **Provare ALIVE senza WAKE.** Con ESP e Pi alimentati, misurare il segnale a GPIO13 in stato avviato e in halt. Confermare livelli e pulldown; controllare che il firmware riporti il valore letto. Correggere il cablaggio/configurazione se la lettura non segue gli stati attesi.
5. **Definire e verificare il circuito WAKE/J2 prima di collegarlo alla ESP.** Progettare l'interfaccia elettrica mancante. A Pi disalimentato, verificare con schema e tester quali pad sono i contatti J2. Provare la chiusura momentanea con un contatto normalmente aperto isolato dal GPIO, rispettando le indicazioni Raspberry, e confermare avvio da halt. Non fare prove di cortocircuito o applicare tensioni ai pad.
6. **Provare il comando firmware con ALIVE alto.** Collegare l'interfaccia verificata, avviare Pi ed ESP, aprire il monitor USB-seriale e inviare `w`. Atteso: il firmware rileva ALIVE alto e salta l'impulso. Verificare che il Pi non venga spento o riavviato.
7. **Provare il wake da halt.** Spegnere il Pi con `poweroff`/halt, lasciando ESP alimentato. Verificare ALIVE basso, inviare `w` e controllare con monitor/logica che WAKE duri circa 200 ms; il Pi dovrebbe avviarsi e ALIVE diventare alto entro il timeout configurato. Se non succede, interrompere e controllare separatamente ALIVE, circuito WAKE e log seriali.
8. **Provare la cattura camera.** Verificare inizializzazione e acquisizione ripetuta di frame, restituendo ogni framebuffer al driver. Questo non prova ancora la detection: l'attuale `eventDetected()` restituisce sempre `false`.
9. **Provare il flusso evento completo solo dopo aver implementato la detection.** Presentare un evento noto e uno negativo, verificare che il classificatore distingua i due casi, che un evento chiami `onEvent()` una sola volta e che il cooldown impedisca impulsi ripetuti. Ripetere con Pi acceso e in halt.
10. **Provare il ciclo applicativo Pi.** Solo dopo aver stabilizzato il wake, abilitare il servizio di acquisizione previsto: boot, acquisizione della fotocamera collegata al Pi, eventuale salvataggio e shutdown pulito. Verificare una nuova riaccensione ESP-triggered.

Per i test del circuito usare alimentatori e strumenti da banco adeguati; interrompere se livelli o collegamenti non corrispondono allo schema. Il punto 5 resta un prerequisito: la documentazione corrente non specifica ancora il circuito WAKE/J2.

## 6. Nota storica: `awakening.md` e Raspberry Pi 4

La sezione legacy archiviata in appendice descriveva un Raspberry Pi 4: GPIO3 portato a massa per il wake e UART per i messaggi dopo il boot. Non applicare quel circuito, pinout o firmware al Pi 5. Il piano attuale usa J2 + ALIVE sul Pi 5 e BME280/decisione sull'ESP.

## 7. Documentazione di riferimento

- [Firmware ESP](esp32/src/main.cpp)
- [Documentazione hardware Raspberry Pi](https://www.raspberrypi.com/documentation/computers/raspberry-pi.html)

## Appendici: contenuto integrale delle guide sorgenti

Le guide seguenti sono incluse integralmente come archivio del materiale originale. Per la sequenza aggiornata e le prove hardware fa fede la guida consolidata sopra. La vecchia nota `awakening.md` resta esplicitamente materiale Pi 4 e non va applicata al Pi 5.

### Appendice A — configurazione Raspberry Pi
# Configurazione Raspberry Pi 5

Guida operativa per halt, linea ALIVE, sensori **collegati al Pi**, cattura al boot (app selettiva) e modalità continuativa.  
Contesto: [README.md](README.md) · Piano: [`plan.pdf`](plan.pdf) · ESP: [sezione ESP](#appendice-b--configurazione-esp32).

> **In breve:** questa guida serve a configurare il Raspberry Pi 5 per due usi: (1) **app selettiva** — il Pi sta in halt e si accende solo quando l'ESP32 lo sveglia, scatta una foto e torna in halt; (2) **app continuativa** — il Pi resta acceso in una fascia oraria e raccoglie foto e misure a cadenze regolari.

---

## 0. Aggiornare il sistema

```bash
sudo apt update && sudo apt full-upgrade -y
sudo reboot
```

---

## 1. Halt (non deep sleep)

Il Raspberry Pi 5 **non supporta suspend-to-RAM**. Stati utili:

| Stato | Significato |
|-------|-------------|
| Acceso | Kernel e servizi attivi |
| Halt | Spento ma alimentato; riaccendibile da pulsante o pad J2 |

Se togli l'alimentazione, nessun segnale dall'ESP può riaccendere il Pi (servirebbe relè/MOSFET sull'alimentatore).

> **Perché l'halt:** il Raspberry Pi 5 non ha lo spegnimento “leggero” in RAM (suspend-to-RAM). L'halt è lo stato più vicino allo spento che il Pi 5 supporta: il sistema è fermo ma la scheda resta collegata alla corrente, così l'ESP32 può ancora riaccenderla premendo virtualmente il pulsante (pad J2).

**Vincolo di piano:** ESP32 e BME280 devono **restare alimentati** quando il Pi è in halt o disalimentato.

---

## 2. EEPROM — consumo in halt

```bash
sudo rpi-eeprom-config --edit
```

```
POWER_OFF_ON_HALT=1
WAKE_ON_GPIO=0
```

| Impostazione | Effetto |
|--------------|---------|
| `POWER_OFF_ON_HALT=1` | Allo shutdown viene tolto il rail **3,3 V**. Consumo tipico in halt ~**0,01 W**. Pulsante / J2 restano utilizzabili. |
| `WAKE_ON_GPIO=0` | Sul Pi 5 l'accensione passa da pulsante e pad, non da GPIO come sul Pi 4. |

> **Perché POWER_OFF_ON_HALT = 1:** con questa impostazione, quando il Pi entra in halt viene tolta l'alimentazione al rail a 3,3 V. Il consumo scende a circa 0,01 W, ma il Pi resta collegato alla presa e può essere riacceso dal pulsante o dai pad J2. Senza questa impostazione il consumo in halt sarebbe più alto.

Verifica:

```bash
sudo rpi-eeprom-config
```

---

## 3. Pad J2 (pulsante esterno)

I pad **J2** simulano il pulsante di accensione: chiusura breve dei due pad.

| Situazione | Effetto |
|------------|---------|
| Pi in halt | Riavvio |
| Pi acceso (OS Lite) | Avvio shutdown |
| Pressione ~1 s+ | Hard off |

L’ESP **non** deve dare WAKE senza conoscere lo stato del Pi → linea **ALIVE** ([sezione ESP](#appendice-b--configurazione-esp32)).

---

## 4. Linea ALIVE — `config.txt`

File: `/boot/firmware/config.txt` (Bookworm).

```
gpio=17=op,dh
```

GPIO17 alto già all’avvio; in halt con `POWER_OFF_ON_HALT=1` il rail 3,3 V è spento → linea bassa. Lato ESP: pulldown (vedi espconfig).

Cablaggio proposto: **GPIO17 (Pi) → pin ALIVE sull’ESP**.

---

## 5. Interfacce hardware per i sensori sul Pi

Per piano, sul Raspberry restano: **metano, umidità suolo, monitoraggio acqua, GPS** (e moduli futuri).  
Il **BME280 non è sul Pi**: è collegato **solo all’ESP32**; il Pi riceve T/umidità/pressione dall’ESP (protocollo da consolidare).

Il GPIO del Pi è digitale 3,3 V. Interfacce tipiche:

| Sensore | Interfaccia | Abilita con |
|---------|-------------|-------------|
| GPS (NMEA) | UART | `uart` |
| Umidità suolo / metano (analog) | SPI + ADC (es. MCP3008) | `spi` |
| Acqua (switch digitale) | GPIO | già disponibile |
| BME280 | — | **non** su I2C del Pi (solo ESP) |

> **I2C / UART / SPI in breve:** sono diversi modi per far dialogare il Pi con i sensori. **I2C** serve per il BME280 (ma in campo il BME280 sta solo sull'ESP32, non sul Pi). **UART** serve per il GPS, che parla in formato NMEA. **SPI** serve per leggere sensori analogici (suolo, metano) tramite un convertitore ADC come l'MCP3008, perché il Pi ha solo pin digitali e non sa leggere tensioni direttamente.

I2C sul Pi può restare abilitato per eventuali altri moduli; non usarlo per il BME di campo.

### Opzione A — `raspi-config`

```bash
sudo raspi-config
```

**Interfacing Options:** SPI Sì (se ADC); Serial Port → login shell **No**, hardware seriale **Sì**.

### Opzione B — `/boot/firmware/config.txt`

```ini
dtparam=spi=on
enable_uart=1
# dtparam=i2c_arm=on   # solo se servono altri dispositivi I2C sul Pi
```

```bash
sudo reboot
```

---

## 6. Permessi utente

```bash
sudo usermod -aG dialout,gpio $USER
# se usi I2C per altri moduli: aggiungi anche i2c
# sudo usermod -aG i2c,dialout,gpio $USER
```

> **dialout / gpio / i2c in breve:** sono gruppi di utenti Linux che danno il permesso di usare porte seriali (`dialout`), pin GPIO (`gpio`) e bus I2C (`i2c`). Senza di essi lo script Python non può accedere all'hardware.

Logout/login o reboot, poi `groups`.

---

## 7. Dipendenze Python

Preferire un venv:

```bash
python3 -m venv ~/venv
source ~/venv/bin/activate
pip install gpiozero pyserial adafruit-circuitpython-mcp3xxx spidev
```

| Pacchetto | Uso |
|-----------|-----|
| `gpiozero` | Sensore acqua digitale |
| `pyserial` | GPS NMEA |
| `adafruit-circuitpython-mcp3xxx` / `spidev` | ADC per suolo/metano |

La lettura BME sul Pi (librerie Adafruit/smbus) serve solo in laboratorio se si testa un BME temporaneo sul Pi; in campo i dati BME arrivano dall’ESP.

---

## 8. Verifica interfacce

```bash
ls /dev/tty*          # GPS: ttyAMA0 / ttyS0 / ttyUSB0
# i2cdetect -y 1      # non aspettarsi il BME di campo sul Pi
rpicam-still -o test.jpg --timeout 2000
```

Quando il protocollo ESP→Pi sarà definito, verificare anche ricezione di un pacchetto BME con timestamp.

---

## 9. Due modalità software

### 9.1 App selettiva (energy-aware) — oneshot + halt

Al boot: cattura (e letture sensori Pi se previste) → `poweroff`.

Storage foto:

```
static/uploads/images/rpi_YYYYMMDD-HHMMSS.jpg
```

Script:

- [`capture_rpi.sh`](scripts%20and%20configuration/capture_rpi.sh) — attiva Python e lancia il client
- [`capture_client.py`](scripts%20and%20configuration/capture_client.py) — scatto via `rpicam-still`

```bash
bash "scripts and configuration/capture_rpi.sh" --oneshot
sudo systemctl poweroff
```

Unità di esempio: [`insect-capture.service`](scripts%20and%20configuration/insect-capture.service).

```bash
sudo cp "scripts and configuration/insect-capture.service" /etc/systemd/system/
# adatta User e path
sudo systemctl daemon-reload
sudo systemctl enable insect-capture.service
```

Per test lunghi: disabilita il servizio o togli il `poweroff`.

Variabili: copia [`.env.systemd.example`](scripts%20and%20configuration/.env.systemd.example) in `.env.systemd` nella root del progetto sul Pi. Imposta `PYENV_ROOT` al percorso del virtualenv (per esempio `/home/rpi5-03/venv`); il wrapper ne attiva `bin/activate`. In alternativa configura pyenv e `PYENV_VERSION`.

```bash
CAPTURE_MODE=selective   # oneshot + halt
CAPTURE_INTERVAL=30
```

### 9.2 App continuativa (dataset)

Il Pi resta acceso nella finestra giornaliera (es. mattina–sera). Cadenze **indipendenti** e configurabili, ad esempio:

| Flusso | Esempio |
|--------|---------|
| Misure ambientali | ogni 1 min (BME via ESP + sensori sul Pi) |
| Fotografie | ogni 5 min (una o entrambe le camere) |

Da implementare: timer/cron o servizi systemd periodici, database con id/timestamp, sync orologi ESP/Pi. Non usare `insect-capture.service` con `poweroff` in questa modalità.

```bash
CAPTURE_MODE=continuous
CAPTURE_INTERVAL=300          # secondi tra foto
SENSOR_INTERVAL=60            # secondi tra burst sensori
# DAILY_WINDOW_START=06:00
# DAILY_WINDOW_END=20:00
```

---

## 10. Directory dati

```bash
mkdir -p ~/tesi/static/uploads/images ~/tesi/data
chmod 755 ~/tesi/data
```

---

## 11. Script sensori sul Pi

```bash
cd ~/tesi
source ~/venv/bin/activate
python3 "scripts and configuration/sensors.py"
```

Legge i sensori **hostati sul Pi** (GPS, acqua, suolo, metano). Il campo BME nel CSV andrà popolato dai dati ricevuti dall’ESP quando il protocollo sarà pronto. La spiegazione di `sensors.py` è in [CODE_GUIDE.md](CODE_GUIDE.md).

---

## 12. Checklist rapida

- [ ] Sistema aggiornato
- [ ] EEPROM halt configurata
- [ ] ALIVE in `config.txt`
- [ ] SPI/UART (e I2C solo se serve) abilitati
- [ ] Utente nei gruppi giusti
- [ ] Test camera Module 3; seconda camera quando disponibile
- [ ] `~/tesi/data` presente
- [ ] Modalità scelta: selettiva (systemd + poweroff) o continuativa (niente poweroff automatico)
- [ ] BME di campo **non** cablato sull’I2C del Pi

---

## 13. Cosa non configurare qui

- BME280 diretto sul Pi in installazione di campo — **solo ESP**
- Wake via GPIO3 “alla Pi 4” — **non applicabile**
- Deep sleep del kernel — **non supportato**
- Taglio alimentazione Pi prima del completamento di `poweroff` — da evitare (sequenza concordata con ESP)

### Appendice B — configurazione ESP32
# Configurazione ESP32

Guida pin, cablaggio wake, BME280 e firmware PlatformIO, allineata a [`plan.pdf`](plan.pdf).  
Contesto: [README.md](README.md) · Pi: [sezione configurazione Pi](#2-raspberry-pi-5-stato-di-alimentazione-e-configurazione).

> **In breve:** l'ESP32 è il “cervello sempre acceso” del sistema. Anche quando il Raspberry Pi è in halt (o spento), l'ESP32 resta alimentato, legge il BME280, prevede temperatura e umidità, e decide se svegliare il Pi inviando un impulso sul pad J2.

---

## 1. Ruolo dell’ESP (piano)

| Compito | Dettaglio |
|---------|-----------|
| Lettura **BME280** | Unico host del sensore: T, umidità, pressione + timestamp |
| Inoltro al Pi | A richiesta o alla cadenza dell’applicazione |
| App selettiva (TMC) | **Forecaster** (GRU quantizzate) + **decider** (filtro biologico + raffinamento tipo HistGBT) → autorizza o meno il wake |
| Wake hardware | Impulso che chiude i pad J2 solo se ALIVE basso; optoisolatore non previsto |
| Alimentazione | Sempre on, anche a Pi in halt |

La possibile ESP32-CAM AI-Thinker può fare da sensore di rilevamento evento e richiedere il wake. Le foto di campo e le acquisizioni dettagliate restano affidate alle fotocamere sul Raspberry. La decisione di wake dovrà integrare il rilevamento con i dati BME280 e la politica ambientale prevista.

### Scheda attuale vs target

| | Stato |
|---|--------|
| **Target di piano** | ESP32 (senza obbligo di camera) + BME280 I2C + WAKE/ALIVE + protocollo dati verso Pi |
| **Codice in repo oggi** | Progetto PlatformIO su board `esp32cam` (AI-Thinker): camera inizializzata ma rilevamento evento stub, wake J2 + ALIVE; BME280 non ancora implementato |

Il firmware va evoluto: implementare il rilevamento camera, aggiungere BME280 e la pipeline forecaster/decider. La camera ESP e le fotocamere del Pi hanno ruoli distinti.

---

## 2. BME280 — collocazione e cablaggio

| Voce | Scelta di piano |
|------|-----------------|
| Host elettrico | **Solo ESP32** (non sul Pi) |
| Posizione fisica | Fuori dal box principale, **case 3D dedicato** |
| Collegamento | Cavo attraverso passaggio a tenuta → solo ESP |
| Motivo | Misurare l’ambiente esterno, non il calore delle schede nel box |

Pin I2C tipici (da confermare sul modulo GY-BME280 / equivalente e sulla scheda ESP scelta):

| Segnale BME | Note |
|-------------|------|
| VCC | 3,3 V (verificare modulo) |
| GND | Comune con ESP |
| SDA / SCL | Bus I2C ESP (pin liberi, non di strapping) |

Indirizzi usuali: `0x76` o `0x77`. Schema KiCad di riferimento in `schemi elettrici/BME280/`.

---

## 3. Pin wake / ALIVE (scheda di lavoro attuale: ESP32-CAM)

Assunzione firmware attuale: **ESP32-CAM AI-Thinker** senza SD. Pin tipicamente liberi: **2, 12, 13, 14, 15**.

| Pin | Uso | Motivo |
|-----|-----|--------|
| **GPIO14** | WAKE → circuito di chiusura J2 | Libero |
| **GPIO13** | ALIVE ← Pi GPIO17 | Libero |
| GPIO12 | Evitare come ingresso dal Pi | Strapping: alto al boot → flash 1,8 V |
| GPIO16 | Occupato | PSRAM |
| GPIO21 | Occupato | segnale Y5 della camera AI-Thinker; non usarlo come SDA mentre la camera è attiva |

Su una scheda ESP32 “nuda” o DevKit i pin WAKE/ALIVE/I2C andranno riassegnati e documentati qui.

> **Strapping pin in breve:** alcuni pin dell'ESP32 hanno funzioni speciali all'avvio (ad esempio GPIO12 determina la tensione di flash). Usarli come ingressi comuni può impedire il corretto boot della scheda. Per questo GPIO12 va evitato come pin di ingresso dal Pi.

---

## 4. Collegamento ESP ↔ Pi — interfaccia da verificare

### WAKE + ALIVE

| Linea | Direzione | Funzione |
|-------|-----------|----------|
| WAKE | ESP GPIO14 → circuito da definire → pad **J2** | Simula pressione breve del pulsante |
| ALIVE | Pi GPIO17 → ESP GPIO13 | Alto = GPIO17 attivo; basso = non attivo |

**WAKE**

1. Il firmware porta GPIO14 alto per **200 ms**, poi basso.
2. Non è previsto un optoisolatore. Il circuito che traduce questo segnale nella chiusura dei due pad J2 e la compatibilità elettrica vanno definiti e verificati prima del cablaggio. Non collegare GPIO14 direttamente ai pad senza aver verificato schema e livelli.

**ALIVE**

1. Pi `GPIO17` → ESP `GPIO13`.
2. Pulldown **10 kΩ** GPIO13→GND (lato ESP).
3. **GND comune** Pi–ESP.

> **Back-powering in breve:** è il rischio che una scheda alimentata tenga accesa un'altra attraverso i segnali di dati. Per evitarlo, non si devono pilotare i segnali TX verso il Pi quando ALIVE è basso (Pi in halt).

**Alimentazione ESP:** con `POWER_OFF_ON_HALT=1` il 3,3 V del Pi si spegne; il 5 V del Pi resta tipicamente su. Alimentare l’ESP da lì o dallo stesso alimentatore a monte (requisito: ESP+BME vivi a Pi spento).

### Dati BME / comandi

Oltre a WAKE/ALIVE serve un canale dati (UART, USB-seriale, ecc.) per:

- inoltrare misure BME con **timestamp di misura** (distinto da quello di ricezione sul Pi);
- sincronizzare orologi;
- (app selettiva) coordinare la sequenza di arresto controllato.

Protocollo e pin: da definire dopo la scelta definitiva della scheda ESP. Non pilotare TX verso il Pi mentre ALIVE è basso (back-powering).

L’interfaccia WAKE/J2 è ancora da consolidare sullo schema elettrico e verificare al banco.

---

## 5. Logica firmware target

```
loop:
  leggi BME280 → storico per forecaster
  forecaster → previsioni T/umidità
  decider (filtro biologico + raffinamento) → autorizza?
  se autorizza e ALIVE basso → impulso WAKE
  se ALIVE alto → non ritentare (acceso o in shutdown)
  su richiesta / cadenza → invia ultimo sample BME al Pi
```

Concordare con i modelli di riferimento: cadenze di lettura, orizzonte previsioni, memoria decisioni, storico per gradi-giorno e indicatori fenologici.

### Codice attuale (`esp32/`)

Comportamento oggi:

1. Inizializzazione della camera AI-Thinker per rilevare eventi; le fotocamere per le acquisizioni restano collegate al Pi.
2. `PIN_WAKE` basso a riposo; `PIN_ALIVE` input.
3. `eventDetected()` rileva l’evento; `onEvent()` applica il cooldown e chiama `ensurePiOn()`. Se ALIVE è basso, `ensurePiOn()` pulsa WAKE/J2 e attende ALIVE alto.
4. Prova manuale: inviare `w` dal monitor USB-seriale a 115200 baud.

### Build e flash

```bash
cd esp32
# cp include/secrets.h.example include/secrets.h   # solo se serve Wi‑Fi
pio run
pio run -t upload
pio device monitor
```

Board attuale in `platformio.ini`: `esp32cam`. Aggiornare `board` / pin quando si passa alla scheda definitiva.

---

## 6. Trappole

| Tema | Dettaglio |
|------|-----------|
| BME nel box | Sfalserebbe T/umidità: case esterno obbligatorio |
| Latenza boot Pi | 15–30 s tipici dall’impulso al Pi pronto |
| Finestra shutdown | ALIVE resta alto finché il rail 3,3 V non cade: non ritentare WAKE |
| Impulso lungo | ≥ ~1 s → hard off |
| Consumo ESP | Sempre acceso: misurare; ottimizzazioni successive (duty cycle letture, non deep-sleep se deve prevedere) |
| Regole BMSB | Validare prima di riusarle su altri insetti |

---

## 7. Checklist

1. [x] Wake J2 + ALIVE come percorso logico; interfaccia elettrica WAKE/J2 da confermare
2. [ ] Cablare BME280 **solo** sull’ESP; case 3D esterno + passaggio a tenuta
3. [ ] Verificare letture BME a Pi in halt (ESP alimentato)
4. [ ] Definire e verificare circuito WAKE/J2; pulldown ALIVE 10 kΩ e massa comune
5. [ ] Flash e test WAKE solo a ALIVE basso
6. [ ] Protocollo inoltro misure + sync orologi
7. [ ] Integrare forecaster/decider; ritirare trigger basato su camera ESP
8. [ ] Misure energetiche ESP (e confronto con paper TMC)

### Appendice C — nota storica awakening

> Nota di coerenza: l'introduzione originale qui sotto menzionava un optoisolatore sul Pi 5. È superata dalla decisione attuale documentata nella prima parte: nessun optoisolatore previsto e interfaccia WAKE/J2 da progettare. Il contenuto seguente è incluso solo come archivio del percorso Pi 4.
# LEGACY — wake stile Pi 4 (GPIO3 + UART)

> **Non applicare al Raspberry Pi 5 né al piano operativo attuale.**
>
> Documento storico. Sul Pi 5 il wake usa **pad J2 + optoaccoppiatore** e la linea **ALIVE**;
> l'ESP decide il wake con **forecaster/decider** sui dati **BME280** (non con UART di evento come qui sotto).
>
> **Perché non si usa sul Pi 5:** sul Pi 4 il wake si faceva portando GPIO3 a massa; sul Pi 5 quel pin non ha questa funzione e l'accensione avviene tramite pad J2 o pulsante fisico. Inoltre il Pi 5 non supporta `WAKE_ON_GPIO=1`. Questo documento è solo un riferimento storico.
>
> Documentazione corrente:
> - Piano: [`plan.pdf`](plan.pdf)
> - Panoramica: [README.md](README.md)
> - ESP: [sezione ESP](#appendice-b--configurazione-esp32)
> - Pi: [sezione Pi](#appendice-a--configurazione-raspberry-pi)
> - Firmware: [`esp32/src/main.cpp`](esp32/src/main.cpp)

---

## Contenuto originale (riferimento Pi 4)

### Come funzionava il risveglio (Pi 4)

Il Pi 4 in halt non esegue software: il risveglio è hardware quando **GPIO3** (pin 5) va a massa. La UART serve solo dopo il boot.

1. L’ESP rileva l’evento.
2. Porta GPIO3 del Pi a LOW per ~100–200 ms.
3. Il Pi si avvia (~20–30 s).
4. Poi comunicazione via UART.

I messaggi durante il boot vanno persi: l’ESP deve ritrasmettere fino a conferma.

### Firmware ESP (versione Pi 4)

Strumenti: Arduino IDE / PlatformIO, driver USB-seriale, eventuali librerie camera.

```cpp
const int WAKE_PIN = 14;      // collegato a GPIO3 del Pi
const int UART_RX  = 13;      // da TX del Pi (GPIO14)
const int UART_TX  = 15;      // verso RX del Pi (GPIO15)

void setup() {
  pinMode(WAKE_PIN, INPUT);   // alta impedenza: non pilota mai HIGH
  Serial2.begin(115200, SERIAL_8N1, UART_RX, UART_TX);
}

void wakePi() {
  pinMode(WAKE_PIN, OUTPUT);
  digitalWrite(WAKE_PIN, LOW);
  delay(200);
  pinMode(WAKE_PIN, INPUT);   // rilascia la linea
}

void loop() {
  if (eventoRilevato()) {
    wakePi();
    Serial2.println("EVENT");
  }
}
```

Rilasciare il pin (INPUT) dopo l’impulso; non tenerlo HIGH (pull-up 3,3 V sul Pi).

### Lato Raspberry (versione storica)

1. `raspi-config` → Serial: login shell No, hardware Sì → `/dev/serial0`.
2. EEPROM: su Pi 4 `WAKE_ON_GPIO=1` di default. Su Pi 5 questo path **non** vale.
3. Listener Python su UART + unità systemd (esempio storico omesso nei dettagli di deploy: non usare in produzione Pi 5).

### Verifiche (solo se si ripete un banco Pi 4)

- Wake manuale GPIO3→GND a Pi in halt.
- Loopback UART / `screen /dev/serial0 115200`.
- Attenzione: GPIO3 è anche SCL I2C1.
