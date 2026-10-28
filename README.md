# Smart camera per il monitoraggio visivo in campo

Documentazione di avanzamento del progetto di tesi, allineata al piano operativo.

**Tesisti:** David Cardinali e Tommaso Garofani  
**Relatore:** Francesco Betti Sorbelli  
**Correlatori:** Lorenzo Palazzetti e Cristina M. Pinotti  
**Piano operativo:** [`plan.pdf`](plan.pdf) (19 ottobre 2026)

**Riferimento scientifico per l’acquisizione selettiva:** [`main.pdf`](main.pdf), manoscritto sul controllo biology-aware del wake-up

**Guide di configurazione:**

- [Guida ai componenti software](CODE_GUIDE.md) — spiegazione di firmware, script, moduli Python e configurazioni
- [Configurazione e risveglio](config%24awakening.md) — guida consolidata Pi/ESP e prove hardware
- [Guida ai componenti software](CODE_GUIDE.md) — firmware, script, `sensors.py` e moduli Python `backend`

---

## Glossario rapido

| Termine | Significato in questo progetto |
|---------|--------------------------------|
| **Halt** | Il Raspberry è spento a livello software ma resta alimentato; si può riaccendere dal pulsante o dai pad J2. Non è “staccato dalla presa”. |
| **Wake** | Impulso con cui l’ESP32 riaccende il Pi (simula la pressione del pulsante). |
| **ALIVE** | Segnale dal Pi all’ESP: alto = Pi acceso; basso = Pi in halt. Evita di “premere” il pulsante se il Pi è già acceso. |
| **Forecaster** | Modulo sull’ESP che **prevede** temperatura e umidità (reti GRU quantizzate). |
| **Decider** | Modulo sull’ESP che **decide** se svegliare il Pi (filtro biologico + classificatore di raffinamento). |
| **App selettiva** | Il Pi resta in halt e si accende solo quando il decider autorizza uno scatto (studio dei consumi). |
| **App continuativa** | Il Pi resta acceso in una fascia oraria e raccoglie immagini + misure per costruire un dataset. |
| **TMC** | Manoscritto di riferimento sullo wake-up “biology-aware” (IEEE Transactions on Mobile Computing). |
| **CV** | Computer vision: analisi delle immagini sul Raspberry (rilevamento, conteggio, area colonie, …). |
| **BMSB** | Cimice asiatica (*Halyomorpha halys*), uno dei casi di studio. |
| **EEPROM** | Memoria di configurazione del Raspberry Pi 5 che conserva le impostazioni anche a spento; qui si usa per impostare come si comporta il Pi in halt. |
| **POWER_OFF_ON_HALT = 1** | Impostazione EEPROM che, quando il Pi entra in halt, spegne il rail a 3,3 V. Il consumo tipico scende a circa 0,01 W; il Pi resta collegato alla presa e riaccendibile da pulsante o pad J2. |
| **WAKE_ON_GPIO = 0** | Sul Pi 5 disabilita il risvevio via GPIO (usato sul Pi 4). L'accensione avviene tramite pulsante fisico o pad J2. |
| **Pad J2** | Punti di contatto sulla scheda del Raspberry Pi che simulano la pressione del pulsante di accensione. Chiudendo brevemente i due pad il Pi si avvia. |
| **Interfaccia WAKE/J2** | Circuito tra ESP32 e pad J2 che simula il pulsante di accensione; il circuito elettrico va ancora definito e verificato. |
| **I2C / UART / SPI** | Diversi standard di comunicazione tra schede e sensori: I2C per il BME280, UART per il GPS, SPI per letture analogiche tramite un convertitore ADC. |
| **ADC / MCP3008** | Convertitore analogico-digitale: permette al Pi (che ha solo pin digitali) di leggere sensori che restituiscono una tensione, come umidità del suolo e metano. |
| **NMEA / `$GPGGA`** | Standard e frase tipo usata dai ricevitori GPS per comunicare latitudine, longitudine e altre informazioni di posizione. |
| **Gradi-giorno** | Indicatore usato in agricoltura e entomologia per stimare lo sviluppo di un insetto in base alle temperature accumulate nel tempo. |
| **Indicatori fenologici** | Segnali dello stadio di sviluppo di una pianta o di un insetto (fioritura, schiusa, ecc.), usati per capire quando scattare foto o raccogliere dati. |
| **GRU quantizzate** | Rete neurale ricorrente (tipo GRU) resa più leggera tramite quantizzazione, così da poter girare sull'ESP32 con risorse limitate. |
| **HistGBT** | Classificatore di raffinamento citato nel manoscritto TMC: combina lo storico delle misure con una tecnica di machine learning (gradient boosting) per decidere se svegliare il Pi. |
| **Back-powering** | Rischio per cui una scheda alimentata tiene accesa un'altra attraverso i segnali di dati. Si evita non pilotando TX verso il Pi quando ALIVE è basso. |
| **Strapping pin** | Pin dell'ESP32 con funzioni speciali all'avvio (ad esempio GPIO12). Usarli come ingressi comuni può impedire il corretto boot della scheda. |
| **systemd / oneshot / poweroff** | systemd è il gestore di servizi del Raspberry Pi. Un servizio `oneshot` esegue un compito una volta e poi termina; `poweroff` spegne il sistema in modo controllato. |
| **rpicam-still / libcamera-still** | Comandi da terminale per scattare foto con la Camera Module 3 di Raspberry Pi. |
| **Burst (CSV)** | Lettura rapida in sequenza di tutti i sensori abilitati, con una sola riga scritta nel file CSV per ogni ciclo di misura. |

---

## 1. Contesto accademico

| Voce | Dettaglio |
|------|-----------|
| Titolo | Smart camera per il monitoraggio visivo in campo |
| Tesisti | David Cardinali, Tommaso Garofani |
| Relatore | Francesco Betti Sorbelli |
| Correlatori | Lorenzo Palazzetti, Cristina M. Pinotti |
| Ateneo | Università degli Studi di Perugia |
| Obiettivo temporale | Raccolta in campo **primavera 2027**; laurea indicativamente **luglio 2027** |

---

## 2. Obiettivo del progetto

Realizzare una **smart camera modulare** per il monitoraggio visivo in campo, alimentata all’inizio dalla rete elettrica. Componenti principali: **Raspberry Pi 5**, **ESP32**, sensori e **due fotocamere**.

Casi di studio possibili: cimice asiatica (BMSB), formiche, bombi, api e altri insetti. Per l’**afide lanigero del melo** i singoli individui sono troppo piccoli: interessa misurare l’**area delle colonie lanose** e come cambia nel tempo.

Il sistema ha **due modi di lavorare** (stesso hardware, software diverso):

| Applicazione | A cosa serve | Cosa fa il Raspberry |
|--------------|--------------|----------------------|
| **Acquisizione selettiva** (studio energetico, rif. TMC) | Accendere il Pi solo quando ha senso scattare, per risparmiare energia | Di solito in halt → l’ESP lo sveglia → foto e analisi → di nuovo halt |
| **Monitoraggio continuativo** | Costruire un dataset di immagini e misure | Resta acceso nella fascia oraria impostata (es. mattina–sera) |

In entrambe le applicazioni l’**analisi delle immagini avviene sul Raspberry** (rilevamento o segmentazione a seconda del bersaglio).

---

## 3. Architettura

```
                              campo (outdoor)
 ┌─────────────────────────────────────────────────────────────────┐
 │  Box principale                                                  │
 │  ┌──────────────┐   WAKE (interfaccia da definire → J2) ┌───────┐ │
 │  │    ESP32     │─────────────────────────►│ Raspberry Pi 5   │ │
 │  │  previsione  │◄── ALIVE (GPIO17) ───────│ + 2 fotocamere   │ │
 │  │  + decisione │   dati BME (a richiesta  │ Camera Module 3  │ │
 │  │  (sempre on) │    o a cadenza)          │ + 2ª ottica      │ │
 │  └──────┬───────┘                          └────────┬─────────┘ │
 │         │ cavo I2C a tenuta                         │           │
 │         ▼                                           ▼           │
 │  ┌──────────────┐                      metano, suolo, acqua, GPS│
 │  │   BME280     │                      (solo sul Pi; letti solo │
 │  │  (custodia   │                       quando il Pi è acceso)  │
 │  │   3D fuori)  │                                               │
 │  └──────────────┘                                               │
 │                                                                  │
 │  salvataggio locale → database (misure, foto, GPS, log, CV)      │
 │  → Wi‑Fi / modem 4G → accesso remoto, backup, scambio con drone │
 └─────────────────────────────────────────────────────────────────┘
```

### Dove sono collegati i sensori

| Componente | Collegato a | Perché / note |
|------------|-------------|----------------|
| **BME280** (temperatura, umidità, pressione) | **Solo ESP32** | Custodia 3D **fuori** dal box; cavo a tenuta. Così si misura l’aria esterna, non il calore delle schede |
| Metano, umidità del suolo, sensore acqua, GPS, altri moduli | **Solo Raspberry Pi** | Si leggono solo a Pi acceso |
| Due fotocamere | Raspberry Pi | Supporti fissi; si orientano a mano in installazione |

ESP32 e BME280 **restano alimentati** anche quando il Raspberry è in halt o spento.

### Segnali di risveglio (solo applicazione selettiva)

| Linea | Direzione | Funzione |
|-------|-----------|----------|
| WAKE | ESP → interfaccia elettrica da definire → pad J2 del Pi | Simula una pressione breve del pulsante di accensione |
| ALIVE | GPIO17 del Pi → ESP | Dice all’ESP se il Pi è acceso |

### Consumo del Raspberry Pi 5

Il Pi 5 **non ha** lo spegnimento “leggero” in RAM (suspend-to-RAM). Stati usati nel progetto:

- **acceso** — acquisizione e analisi in corso;
- **halt** — spento ma ancora collegato all’alimentazione; riaccendibile da pulsante o pad J2.

Con l’impostazione EEPROM `POWER_OFF_ON_HALT=1`, in halt si spegne anche la linea a 3,3 V e il consumo tipico scende a circa **0,01 W**. Dettagli passo-passo: [configurazione e risveglio](config%24awakening.md).

### Ruoli dei componenti

| Componente | Cosa fa |
|------------|---------|
| Raspberry Pi 5 | Foto, analisi immagini, sensori propri, salvataggio/database; halt oppure fascia oraria continua |
| Camera Module 3 | Prima fotocamera (connettore CSI) |
| Seconda fotocamera | Ottica con abbastanza pixel sul soggetto (candidata: High Quality Camera + obiettivo intercambiabile; ancora da scegliere) |
| ESP32 | Legge il BME280; in app selettiva esegue previsione e decisione; manda le misure al Pi; controlla il risveglio |
| BME280 | Ambiente esterno, solo tramite ESP |

---

## 4. Hardware (sintesi)

### 4.1 Raspberry Pi 5 (`rpi5-03`)

| Voce | Valore |
|------|--------|
| Sistema operativo | Raspberry Pi OS 64-bit (Bookworm) |
| Memoria di massa | microSD 32 GB |
| Alimentazione iniziale | Rete elettrica (la batteria andrà supportata in seguito) |
| Rete | Wi‑Fi (laboratorio/casa, poi modem 4G esterno); anche Ethernet |
| Accesso remoto | SSH; previsto anche Raspberry Pi Connect / accesso autenticato |
| Nome host / utente | `rpi5-03` |
| Energia (app selettiva) | Halt + risveglio da J2; servizio systemd: una cattura al boot, poi spegnimento |

### 4.2 Fotocamere

| Fotocamera | Stato | Note |
|------------|-------|------|
| Camera Module 3 (sensore IMX708) | In uso / verificata | Comando `rpicam-still`, JPG, circa 4608×2592 |
| Seconda (es. HQ + obiettivo) | Da scegliere e acquistare | Zoom ottico o lunga focale; pixel sufficienti sul bersaglio; in frutteto distanze fino a circa 4 m |

La scelta dell’ottica **va fatta prima** del progetto definitivo del box (ingombro obiettivo, finestra trasparente, fissaggi).

### 4.3 ESP32 e BME280

L’ESP32 sta nel box principale; il BME280 sta fuori, nella sua custodia. Tra ESP e Pi: segnali WAKE/ALIVE e trasferimento delle misure (protocollo ancora da fissare: seriale, USB, ecc.).

Il firmware in [`esp32/`](esp32/) oggi è una **bozza** di risveglio su scheda **ESP32-CAM**. Obiettivo di piano: ESP32 che legge il BME280 e applica previsione + decisione — vedi [configurazione e risveglio](config%24awakening.md).

### 4.4 Altri sensori (sul Pi)

| Sensore | Cosa misura | Stato |
|---------|-------------|-------|
| Umidità suolo | Umidità nel terreno | Modello e interfaccia da identificare |
| Monitoraggio acqua | Funzione da precisare nel gruppo | Da collegare |
| Metano | Gas / CH₄ | Da collegare |
| GPS | Posizione | Da collegare |

È prevista una **morsettiera modulare**: si possono aggiungere o sostituire i moduli supportati senza rifare tutto il cablaggio, con connettori a tenuta e polarizzati.

---

## 5. Software

### 5.1 Acquisizione selettiva (studio energetico)

Riferimento: manoscritto *A Two-Tier Biology-Aware Wake-Up Control for Energy-Measured IoT Insect Monitoring* (IEEE TMC).

In sintesi:

1. L’ESP legge il BME280 e mantiene lo storico necessario.
2. Il **forecaster** prevede temperatura e umidità.
3. Il **decider** combina regole biologiche e un classificatore di raffinamento (nel paper: HistGBT) e decide se svegliare il Pi.
4. La pressione si **registra** ma, nel lavoro TMC, **non entra** nelle variabili del decider.
5. Le regole biologiche riguardano la BMSB; per altri insetti vanno validate a parte.
6. A Pi in halt i sensori sul Pi **non** vengono letti; solo l’ESP continua a usare il BME secondo la politica.
7. Se autorizzato: il Pi si accende → fotografa → analizza → salva → spegnimento controllato (non si taglia l’alimentazione prima che l’halt sia completo).
8. Si misurano i consumi reali di entrambe le schede e delle operazioni (avvio, caricamento modello, inferenza, spegnimento).

### 5.2 Monitoraggio continuativo (dataset)

- Il Pi resta acceso nella fascia oraria configurata (esempio: mattina–sera).
- Legge il BME tramite l’ESP e direttamente gli altri sensori; le **cadenze** di misure e foto sono **indipendenti** e configurabili (esempio di piano: misure ogni minuto, foto ogni cinque minuti).
- Serve un **database** che colleghi misure, immagini, GPS, log e risultati dell’analisi con identificativi e orari coerenti.
- Gli orologi di ESP e Pi vanno sincronizzati; l’orario della **misura** va tenuto distinto da quello della **ricezione** sul Pi.
- Sul Pi girano i modelli di visione: presenza, posizione e conteggio insetti, oppure area delle colonie lanose; nel database si conservano anche versione del modello e risultati.

### 5.3 Connettività e scambio dati

- Connessione: prima Wi‑Fi di laboratorio/casa, poi modem 4G esterno. Acquisizione e salvataggio locale devono funzionare anche **senza rete**; alla riconnessione si riprendono i trasferimenti senza duplicare o cancellare troppo presto gli originali.
- Accesso remoto autenticato: stato del sistema, ultime acquisizioni, spazio disco, temperature, errori; comandi essenziali (avvio/arresto raccolta, cambio cadenze). Nell’app selettiva l’accesso al Pi c’è solo quando è acceso e in rete.
- Previsto uno scambio wireless con un **secondo Raspberry Pi 5 sul drone** (file, sincronizzazione, comandi), da provare prima al banco e poi a distanze crescenti.

### 5.4 File nel repository

| Elemento | Contenuto |
|----------|-----------|
| `plan.pdf` | Piano operativo del progetto e fonte per obiettivi, hardware e attività |
| `main.pdf` | Manoscritto scientifico di riferimento per forecaster, decider e valutazione energetica |
| `config$awakening.md` | Guida consolidata Pi/ESP, prove WAKE/J2 e archivio delle guide originali |
| `scripts and configuration/capture_rpi.sh` | Wrapper per ambiente Python, scatto e burst dei sensori |
| `scripts and configuration/sensors.py` | Lettura una tantum dei sensori **sul Pi** |
| `scripts and configuration/insect-capture.service` | Servizio systemd per l’app selettiva |
| `scripts and configuration/capture_client.py` | Scatto con `rpicam-still` e metadati GPS |
| `backend/` | Helper metadati e lettore GPS; `bme_reader.py` è solo per prove al banco |
| `esp32/` | Firmware PlatformIO (oggi: risveglio; poi BME + politica) |
| `schemi elettrici/` | Schemi KiCad, tra cui BME280 |

**Ciclo tipico dell’app selettiva:**

```
ESP (previsione + decisione) autorizza
        → impulso WAKE sui pad J2
        → il Pi si avvia
        → systemd lancia scripts and configuration/capture_rpi.sh --oneshot
        → foto JPG + lettura dei sensori Pi abilitati
        → systemctl poweroff → di nuovo in halt
```

(`--oneshot` = una cattura, poi un burst dei sensori abilitati sul Pi; il servizio systemd esegue quindi `poweroff`. Il BME280 di campo non è ancora ricevuto dall’ESP.)

---

## 6. Stato di avanzamento

### Completato / in corso

- [x] Piano operativo condiviso (`plan.pdf`)
- [x] Sistema operativo sul Pi 5, hostname `rpi5-03`, SSH, rete
- [x] Camera Module 3 verificata (`rpicam-still`)
- [x] Strategia halt + schema WAKE/ALIVE documentato
- [x] Guide di configurazione e bozza firmware di risveglio in `esp32/`
- [x] Bozza pipeline di cattura e sensori nel repository

### Da fare (come da piano)

- [ ] Scegliere la seconda fotocamera/ottica e fare prove al banco (pixel sul bersaglio)
- [ ] Confermare la scheda ESP definitiva; cablare il BME280 **solo** sull’ESP; custodia 3D esterna
- [ ] Schema elettrico completo; verificare che ESP e BME restino alimentati a Pi in halt
- [ ] Firmware: lettura BME + previsione/decisione; protocollo di invio dati al Pi
- [ ] Collegare i sensori sul Pi (modelli, convertitori ADC, connettori a tenuta)
- [ ] Progetto CAD del box e delle custodie sensori; stampa 3D; tenuta all’acqua
- [ ] Software app selettiva e app continuativa (database, cadenze)
- [ ] Modelli di visione sul Pi; valutazione su dati separati da quelli di sviluppo
- [ ] Wi‑Fi / 4G, accesso remoto, sincronizzazione, collegamento al Pi sul drone
- [ ] Campagna di raccolta in campo, primavera 2027

---

## 7. Cronologia della documentazione

| Data | Modifica |
|------|----------|
| 2026-10-19 | Prime bozze README e guide (halt, ESP32-CAM) |
| 2026-10-20 | Architettura WAKE/ALIVE; PlatformIO |
| 2026-10-23 | Allineamento a `plan.pdf`; testo in italiano più chiaro; glossario |
