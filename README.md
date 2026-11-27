# Smart camera per il monitoraggio visivo in campo

Questo è il repository della nostra tesi triennale: una smart camera da lasciare in un frutteto (o in un campo) che fotografa gli insetti e registra le condizioni ambientali, consumando meno energia possibile. Qui teniamo codice, firmware, schemi elettrici e appunti di configurazione.

Tesisti: David Cardinali e Tommaso Garofani  
Relatore: Francesco Betti Sorbelli  
Correlatori: Lorenzo Palazzetti e Cristina M. Pinotti  
Università degli Studi di Perugia. Raccolta dati in campo prevista per la primavera 2027.

Documenti:

- [`docs/plan.pdf`](docs/plan.pdf): il piano operativo, il riferimento per obiettivi e requisiti;
- [Configurazione e prove al banco](docs/setup-risveglio.md): come configurare Pi ed ESP32 e in che ordine fare le prove;
- [Mappa dei pin](docs/pinout.md): tutti i collegamenti tra Raspberry Pi, ESP32, BME280 e sensori;
- [Protocollo UART](docs/protocollo-uart.md): come misure del BME280 ed eventi della camera passano dall'ESP al Pi;
- [Dati raccolti](docs/dati-csv.md): i file CSV prodotti sul Pi, colonna per colonna;
- [Guida al codice](docs/guida-codice.md): cosa fa ogni file sorgente e cosa ancora non fa;
- [Registro delle revisioni](docs/revisioni.md): cosa abbiamo cambiato in ogni revisione e perché.

Per l'acquisizione selettiva ci basiamo sul manoscritto *A Two-Tier Biology-Aware Wake-Up Control for Energy-Measured IoT Insect Monitoring*, che è riservato e quindi non è nel repository.

---

## L'idea in breve

Vogliamo costruire una camera modulare: un box stagno con dentro un Raspberry Pi 5, un ESP32, due fotocamere e una morsettiera a cui collegare i sensori. All'inizio sarà alimentata dalla rete elettrica.

I casi di studio possibili sono la cimice asiatica (BMSB), formiche, bombi, api e altri insetti. Un caso a parte è l'afide lanigero del melo: i singoli individui sono troppo piccoli per essere contati, quindi lì misuriamo l'area delle colonie lanose e come cambia nel tempo.

Lo stesso hardware deve supportare due applicazioni, che cambiano solo nel software:

| Applicazione | A cosa serve | Cosa fa il Raspberry |
|---|---|---|
| Acquisizione selettiva (studio energetico, rif. TMC) | accendere il Pi solo quando ha senso scattare | resta in halt; l'ESP lo sveglia, il Pi scatta, salva e torna in halt |
| Monitoraggio continuativo | costruire un dataset di immagini e misure | resta acceso in una fascia oraria, con cadenze diverse per foto e misure |

In entrambi i casi l'analisi delle immagini (rilevamento degli insetti o segmentazione delle colonie) girerà sul Raspberry.

![Idea del professore per l'installazione in campo](docs/img/idea-prof_installazione-in-campo.jpeg)

*Bozza dell'installazione in campo proposta dal professore come spunto. Non è il progetto definitivo: alcune scelte, come i sensori RS485, sono diverse da quelle del piano.*

---

## Architettura

```text
 ┌─────────────────────────────────────────────────────────────────────┐
 │  Box principale                                                     │
 │  ┌──────────────────┐  WAKE (GPIO42 → PC817 → J2)  ┌──────────────┐ │
 │  │ ESP32-S3-CAM     │─────────────────────────────►│ Raspberry    │ │
 │  │ sempre acceso,   │◄──── ALIVE (Pi GPIO17) ──────│ Pi 5         │ │
 │  │ camera OV3660    │◄──── UART: comandi ──────────│ + Camera     │ │
 │  │ per il movimento,│───── UART: misure, eventi ──►│   Module 3   │ │
 │  │ buffer di 48 h   │      (solo a Pi acceso)      │ + 2ª camera  │ │
 │  └────────┬─────────┘                              └──────┬───────┘ │
 │           │ I2C, cavo a tenuta                            │         │
 └───────────┼───────────────────────────────────────────────┼─────────┘
             ▼                                               ▼
     BME280 nella custodia                   GPS, metano, suolo, acqua
     esterna stampata in 3D                  (letti solo a Pi acceso)

 Pi: foto + CSV accanto a ogni foto, bme280.csv, camera_events.csv, sensors.csv
     → Wi-Fi / modem 4G → accesso remoto, backup, scambio con il drone
```

La scelta più importante è la divisione dei compiti tra le due schede:

- l'ESP32 resta sempre acceso e consuma poco. Misura il BME280 ogni minuto e tiene le misure in memoria finché il Pi non le scarica. Guarda la scena con la sua camera OV3660 e, se vede un movimento, accende il Pi con un impulso su WAKE (in futuro deciderà il decider);
- il Raspberry Pi 5 consuma molto di più. Fa le foto, scarica le misure dall'ESP, legge gli altri sensori e salva tutto. Nell'app selettiva passa la maggior parte del tempo in halt.

Il BME280 sta fuori dal box, in una custodia stampata in 3D, collegato solo all'ESP con un cavo a tenuta. Dentro misurerebbe il calore delle schede invece dell'aria esterna.

| Componente | Collegato a | Note |
|---|---|---|
| BME280 (temperatura, umidità, pressione) | solo ESP32 | custodia 3D esterna |
| Metano, umidità del suolo, sensore acqua, GPS | solo Raspberry Pi | si leggono solo a Pi acceso |
| Due fotocamere | Raspberry Pi | supporti fissi, orientate a mano in installazione |
| Camera OV3660 | ESP32-S3-CAM (cavo flat) | rileva il movimento per decidere quando accendere il Pi |

### Come si sveglia il Pi

Il Pi 5 non ha una vera sospensione in RAM, quindi per noi esistono due stati: acceso e halt (spento via software ma ancora alimentato). Con l'opzione EEPROM `POWER_OFF_ON_HALT=1` in halt il consumo scende a circa 0,01 W.

Per riaccenderlo usiamo i pad J2, gli stessi contatti del pulsante di accensione. I collegamenti tra le due schede sono quattro più la massa:

| Linea | Direzione | A cosa serve |
|---|---|---|
| WAKE | ESP GPIO42 → PC817 → pad J2 | "preme" il pulsante di accensione con un impulso di 200 ms |
| ALIVE | Pi GPIO17 → ESP GPIO1 | alto mentre il Pi è acceso; torna basso quando l'arresto è finito |
| UART TX | ESP GPIO2 → Pi GPIO15 (RXD) | risposte e misure dell'ESP |
| UART RX | Pi GPIO14 (TXD) → ESP GPIO41 | comandi del Pi (`HELLO`, `GET`, `ACK`...) |

Il ciclo dell'app selettiva:

```text
l'ESP vede un movimento con la OV3660 (in futuro: forecaster + decider)
  → impulso WAKE sui pad J2 → il Pi si avvia → ALIVE alto, l'ESP apre la UART
  → systemd lancia raspberry_pi/capture_rpi.sh --oneshot
  → foto → misure dall'ESP → sensori del Pi → CSV della foto
  → poweroff → ALIVE basso, l'ESP chiude la UART
```

I dettagli sono in [configurazione](docs/setup-risveglio.md), [mappa dei pin](docs/pinout.md) e [protocollo UART](docs/protocollo-uart.md).

---

## Hardware

Raspberry Pi 5 (hostname e utente `rpi5-03`): Raspberry Pi OS 64 bit (Bookworm) su microSD da 32 GB, accesso via SSH. In campo useremo un modem 4G esterno.

Fotocamere:

| Fotocamera | Stato | Note |
|---|---|---|
| Camera Module 3 (IMX708) | funzionante | `rpicam-still`, JPG fino a 4608×2592 |
| Seconda camera | da scegliere | candidata: [High Quality Camera](https://www.raspberrypi.com/products/raspberry-pi-high-quality-camera/) con obiettivo a lunga focale; nel frutteto lavoriamo fino a circa 4 m |

La seconda ottica va scelta prima di progettare il box, perché da lei dipendono ingombri, finestra trasparente e fissaggi.

ESP32: variante ESP32-S3-CAM N16R8 con camera OV3660 e due porte USB-C, PCB marcato `V1695` / `127294G_Y1127_231016`. Non c'è uno schema ufficiale, quindi i pin in [pinout.md](docs/pinout.md) vanno confermati al banco.

Sensori sul Pi:

| Sensore | Cosa misura | Interfaccia prevista | Stato |
|---|---|---|---|
| Umidità del suolo | umidità del terreno | analogica, MCP3008 su SPI | modello da scegliere |
| Sensore acqua | da definire nel gruppo | ingresso digitale | da collegare |
| Metano (serie MQ) | CH₄ | analogica, MCP3008 | da collegare |
| GPS | posizione | UART2 | da collegare |

Nel box ci sarà una morsettiera con connettori a tenuta e polarizzati, per aggiungere o sostituire un sensore senza rifare il cablaggio.

---

## Software

### Acquisizione selettiva

L'idea viene dal manoscritto TMC:

1. l'ESP legge il BME280 e tiene lo storico delle misure (fatto: buffer di 48 ore);
2. un forecaster (reti GRU quantizzate, abbastanza leggere per l'ESP) prevede temperatura e umidità;
3. un decider combina regole biologiche (per esempio i gradi-giorno) con un classificatore (HistGBT nel paper) e decide se svegliare il Pi;
4. se la risposta è sì, il Pi si accende, scatta, analizza, salva e torna in halt;
5. misuriamo i consumi reali di ogni fase (avvio, caricamento del modello, inferenza, spegnimento).

Nel lavoro TMC la pressione viene registrata ma non entra nel decider, e le regole biologiche sono pensate per la cimice asiatica, quindi per altri insetti vanno validate. Mentre il Pi è in halt i suoi sensori non vengono letti.

### Monitoraggio continuativo

Il Pi resta acceso nella fascia oraria impostata e raccoglie misure e foto con cadenze indipendenti (il piano propone una misura al minuto e una foto ogni cinque minuti). È già implementato in `capture_client.py`.

### Dove finiscono i dati

Tutto finisce in CSV sotto `raspberry_pi/data/` ([dettagli](docs/dati-csv.md)):

- accanto a ogni foto un CSV con impostazioni di scatto, hash del file, evento che ha acceso il Pi, ultima misura del BME280 e ultima lettura dei sensori del Pi;
- `bme280.csv` con tutte le misure arrivate dall'ESP, ognuna con l'ora in cui è stata fatta e quella in cui il Pi l'ha ricevuta;
- `camera_events.csv` con tutti i movimenti visti dall'ESP e se hanno acceso il Pi;
- `sensors.csv` con tutte le letture dei sensori del Pi.

### Connettività

All'inizio useremo il Wi-Fi del laboratorio, poi un modem 4G. Acquisizione e salvataggio devono funzionare anche senza rete; quando la connessione torna, i dati vanno trasferiti senza duplicati e senza cancellare troppo presto gli originali. È previsto anche uno scambio dati wireless con un secondo Raspberry Pi 5 montato su un drone.

---

## Cosa c'è nel repository

| Percorso | Contenuto |
|---|---|
| `docs/` | piano operativo e documentazione |
| `firmware/esp32/main/main.ino` | firmware dell'ESP32 (Arduino IDE): BME280, rilevamento del movimento, buffer, WAKE, ALIVE, UART; con `DIAGNOSTICA 1` anche i comandi di prova del cablaggio |
| `raspberry_pi/smartcam/` | package Python: scatto, scambio con l'ESP, sensori, GPS, CSV |
| `raspberry_pi/capture_rpi.sh` | avvio dello scatto (a mano o da systemd) |
| `raspberry_pi/systemd/` | unità systemd e modello delle variabili d'ambiente |
| `hardware/` | schemi KiCad: collegamento Pi–ESP e sensore BME280 (da aggiornare ai pin attuali) |

Per provare il software del Pi (dalla root del repository):

```bash
python3 -m venv --system-site-packages raspberry_pi/.venv
raspberry_pi/.venv/bin/pip install -r raspberry_pi/requirements.txt
bash raspberry_pi/capture_rpi.sh --oneshot           # una foto + ESP + sensori
bash raspberry_pi/capture_rpi.sh --oneshot --no-esp  # senza ESP collegato
```

Per il firmware: aprire `firmware/esp32/main/main.ino` con Arduino IDE (impostazioni nella [guida di configurazione](docs/setup-risveglio.md#22-caricare-il-firmware-arduino-ide)).

---

## A che punto siamo

Fatto:

- [x] Piano operativo condiviso (`docs/plan.pdf`)
- [x] Raspberry Pi 5 configurato (OS, hostname `rpi5-03`, SSH, rete)
- [x] Camera Module 3 provata con `rpicam-still`
- [x] Strategia halt + WAKE/ALIVE definita
- [x] Wake del Pi dall'ESP provato al banco (27/11/2026)
- [x] Firmware ESP in un solo file: BME280 con buffer, rilevamento del movimento con la OV3660, WAKE non bloccante, protocollo UART con conferma, comandi di diagnostica; compilato, da provare sulla scheda
- [x] Programma sul Pi che scarica misure ed eventi dall'ESP e li salva (provato su PC con un ESP simulato)
- [x] Raccolta dati in CSV, con un CSV accanto a ogni foto
- [x] Modalità continuativa con cadenze separate e fascia oraria

Da fare:

- [ ] Fare le [prove al banco](docs/setup-risveglio.md#4-prove-al-banco): oggi firmware e software del Pi sono provati solo in compilazione e su PC
- [ ] Far rispondere il BME280 (lo scan I2C non lo trova, vedi [setup-risveglio.md §2.4](docs/setup-risveglio.md#24-il-bme280-non-viene-trovato))
- [ ] Collegare la linea Pi GPIO14 → ESP GPIO41 e provare la UART sulle schede
- [ ] Aggiornare gli schemi KiCad: `hardware/pi5->esp32/` ha un connettore ESP generico e mancano la resistenza da 1 kΩ su ALIVE e le due linee UART; `hardware/sensors/BME280/` ha ancora i GPIO21/22 di una vecchia scheda. I pin giusti sono in [pinout.md](docs/pinout.md)
- [ ] Montare la batteria dell'RTC del Pi, per avere l'ora giusta in campo anche senza rete
- [ ] Togliere dal repository due cartelle registrate per sbaglio come submodule (senza `.gitmodules`) e un file di VS Code che è nel `.gitignore` ma era stato aggiunto prima della regola:

  ```bash
  git rm --cached "configurazioni_fisiche/pi5->esp32/.history" "configurazioni_fisiche/sensors/BME280/.history" .vscode/c_cpp_properties.json
  rm -r configurazioni_fisiche
  ```
- [ ] Board di collegamento ESP–Pi (PC817, resistenze, connettori)
- [ ] Scegliere seconda fotocamera e ottica, prove al banco (pixel sul bersaglio)
- [ ] Scegliere e collegare i sensori del Pi (modelli, ADC, connettori a tenuta), calibrare la sonda del suolo e il sensore di metano
- [ ] Provare e tarare il rilevamento del movimento in campo e misurare quanto consuma la camera dell'ESP sempre accesa
- [ ] Firmware: forecaster e decider
- [ ] CAD del box e delle custodie, stampa 3D, prove di tenuta all'acqua
- [ ] Modelli di visione sul Pi, valutati su dati separati da quelli di sviluppo
- [ ] Trasferimento dei dati al server, accesso remoto, collegamento con il Pi sul drone
- [ ] Campagna di raccolta in campo (primavera 2027)

---

## Glossario

| Termine | Significato |
|---|---|
| Halt | il Pi è spento via software ma ancora alimentato: si riaccende dal pulsante o dai pad J2 |
| Wake | l'impulso con cui l'ESP32 accende il Pi |
| ALIVE | segnale dal GPIO17 del Pi all'ESP; dice solo che il pin è alto, non che Linux abbia finito il boot |
| Pad J2 | i due contatti sulla scheda del Pi 5 collegati al pulsante di accensione |
| PC817 | optoisolatore (LED + fototransistor nello stesso chip): l'ESP chiude J2 senza un collegamento elettrico diretto |
| EEPROM | memoria del Pi 5 con la configurazione del bootloader, tra cui il comportamento in halt |
| Forecaster | il modulo sull'ESP che prevede temperatura e umidità |
| Decider | il modulo sull'ESP che decide se svegliare il Pi |
| GRU quantizzate | reti neurali ricorrenti con pesi a pochi bit, per girare su un microcontrollore |
| HistGBT | Histogram-based Gradient Boosting Trees, il classificatore del decider nel paper |
| Gradi-giorno | somma delle temperature sopra una soglia nel tempo; si usa per stimare lo sviluppo di un insetto |
| TMC | IEEE Transactions on Mobile Computing, la rivista a cui è stato sottoposto il manoscritto |
| BMSB | Brown Marmorated Stink Bug, la cimice asiatica (*Halyomorpha halys*) |
| I2C / UART / SPI | protocolli di comunicazione: I2C per il BME280, UART per ESP e GPS, SPI per l'ADC |
| ADC / MCP3008 | convertitore analogico-digitale: il Pi non ha ingressi analogici |
| NMEA / GGA | il formato testuale con cui i GPS mandano la posizione |
| Back-powering | una scheda spenta alimentata "di traverso" attraverso i pin di segnale di un'altra |
| Strapping pin | pin dell'ESP32 che all'avvio decidono la modalità di boot |
| Burst | lettura in sequenza di tutti i sensori del Pi, salvata come una riga di `sensors.csv` |
| Boot ID / seq | identificano un record dell'ESP (misura o evento): numero casuale scelto a ogni avvio dell'ESP più numero progressivo |
| Evento | movimento visto dalla camera OV3660 dell'ESP; può far accendere il Pi |
| `DIAGNOSTICA` | interruttore in cima a `main.ino`: con 1 il firmware ha anche i comandi per provare il cablaggio |
