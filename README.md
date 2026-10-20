# Sistema di monitoraggio gestito da Raspberry

> Titolo provvisorio della tesi.

Documentazione di avanzamento: contesto accademico, architettura, lavoro già svolto e attività ancora da completare.

**Guide di configurazione:**

- [Configurazione Raspberry Pi](piconfig.md) — EEPROM, halt, linea ALIVE, systemd, cattura
- [Configurazione ESP32-CAM](espconfig.md) — pin, cablaggio (alternative), firmware PlatformIO

---

## 1. Contesto accademico

| Voce              | Dettaglio                                      |
|-------------------|------------------------------------------------|
| Titolo (provvisorio) | Sistema di monitoraggio gestito da Raspberry |
| Relatore          | Francesco Betti Sorbelli                       |
| Ateneo            | Università degli Studi di Perugia              |
| Corso di laurea   | Informatica (L-31)                             |
| Scadenza indicativa | Entro primavera                              |

---

## 2. Obiettivo del progetto

Monitorare **cimici / insetti dannosi per il raccolto** con un nodo outdoor basato su **Raspberry Pi 5**, che **non resta sempre acceso**.

Il Pi viene **risvegliato da un ESP32-CAM** quando è rilevato (o è probabile) un insetto. Una volta attivo, il Raspberry:

1. cattura **foto** dell’insetto (Camera Module 3);
2. legge **dati ambientali** dai sensori collegati al Pi;
3. salva i dati **in locale** (per ora; trasmissione esterna in seguito);
4. torna in **halt** (spento ma alimentato, risvegliabile dal pulsante / pad J2).

In trasmissione da storage locale verso un altro device andrà gestita anche la **corruzione / integrità dei dati** (checksum, retry, ripresa trasferimenti incompleti).

### Domanda di ricerca / metriche

Ancora da formalizzare. Focus attuale: **risparmio energetico** (il Pi resta in halt tranne quando serve).

Scenario operativo: il Pi è **sempre in halt** tranne quando l’ESP rileva un evento e lo riaccende.

---

## 3. Architettura

```
                         outdoor / campo
 ┌──────────────────────────────────────────────────────────┐
 │                                                          │
 │   ┌─────────────────┐         WAKE (J2 via opto / alt.)  │
 │   │   ESP32-CAM     │──────────────────────────────────► │
 │   │  camera propria │         ◄── ALIVE (GPIO17 → ESP)   │
 │   │  (trigger / CV) │                                    │
 │   └─────────────────┘                                    │
 │                                                          │
 │   ┌─────────────────┐     camera cable                   │
 │   │ Raspberry Pi 5  │◄──────────────── Camera Module 3   │
 │   │  rpi5-03        │     (foto HD, solo sul Pi)         │
 │   │  (HALT di norma)│◄── sensori ambientali (solo sul Pi)│
 │   └─────────────────┘                                    │
 │            │                                             │
 │            ▼                                             │
 │   storage locale (foto JPG + telemetria)                 │
 │   → trasmissione esterna (da definire)                   │
 │   → controllo integrità / anti-corruzione in trasferimento│
 └──────────────────────────────────────────────────────────┘
```

**Linee elettriche (scelta principale documentata):**

| Linea | Direzione | Funzione |
|-------|-----------|----------|
| WAKE  | ESP → pad J2 del Pi (tramite optoaccoppiatore) | Simula la pressione del pulsante di accensione |
| ALIVE | GPIO17 del Pi → ESP | Indica all’ESP se il Pi è acceso |

Non c’è trasferimento immagini né handshake dati via HTTP tra ESP e Pi: l’ESP **sveglia** il Pi; il Pi **scatta da solo** con la Camera Module 3.

**Alternative di collegamento** (GPIO diretto, USB) e dettaglio cablaggio: vedi [espconfig.md](espconfig.md).

### Policy power (decisa)

Il Raspberry Pi 5 **non supporta suspend-to-RAM** (deep sleep). Gli stati utili sono:

- **acceso** — acquisizione in corso;
- **halt** — spento ma alimentato, risvegliabile dal pulsante di accensione o dai pad J2.

Se l’alimentazione viene tagliata del tutto, nessun segnale dall’ESP può riaccendere il Pi (servirebbe un relè/MOSFET sull’alimentatore). La strada adottata è l’**halt** con `POWER_OFF_ON_HALT=1` (dettaglio in [piconfig.md](piconfig.md)).

### Ruoli

| Componente           | Ruolo                                                                 | Stato            |
|----------------------|-----------------------------------------------------------------------|------------------|
| Raspberry Pi 5       | Acquisizione foto HD, lettura sensori, storage locale, poi halt       | OS + SSH OK      |
| Camera Module 3      | Foto insetto (JPG) — **solo sul Pi**                                  | Funzionante      |
| ESP32-CAM            | Rilevazione preliminare (camera propria + CV da configurare) + wake   | Firmware in repo |
| Sensori ambientali   | Umidità suolo, acqua, pressione/temperatura, metano, geolocalizzazione| Da collegare     |

> **Nota:** i sensori sono previsti **solo sul Pi**. Il trigger di wake è sull’ESP32-CAM (camera integrata / evento configurabile). Se in futuro servisse logging ambientale a Pi in halt, andrà rivalutata la collocazione di alcuni sensori sull’ESP32.

---

## 4. Hardware

### 4.1 Raspberry Pi 5 (`rpi5-03`)

| Voce            | Valore                                              |
|-----------------|-----------------------------------------------------|
| Modello         | Raspberry Pi 5                                      |
| OS              | Raspberry Pi OS **64-bit** (Bookworm; immagine principale dalla pagina download ufficiale) |
| Storage         | microSD **32 GB**                                   |
| Alimentazione   | Alimentatore ufficiale dello **starter kit** Raspberry |
| Rete            | **Wi‑Fi e Ethernet** (IP via DHCP se non assegnato altrimenti) |
| Accesso remoto  | **SSH** abilitato; previsto anche **Raspberry Pi Connect** |
| Hostname        | `rpi5-03`                                           |
| Utente          | `rpi5-03`                                           |
| Credenziali     | Configurate sul dispositivo — **non documentate in chiaro in questo file** |
| Power policy    | **Halt** (`POWER_OFF_ON_HALT=1`); wake da J2 / pulsante |
| Ambiente        | **Outdoor**                                         |
| Energia sistema | **Batteria** oppure **rete elettrica** (entrambi da supportare) |
| Alimentazione con ESP32 | **Condivisa** con l’ESP32-CAM                 |
| Avvio automatico job | **systemd** al boot → cattura oneshot → `poweroff` |

```bash
ssh rpi5-03@<ip-assegnato-da-dhcp>
# oppure accesso tramite Raspberry Pi Connect
```

Configurazione EEPROM, `config.txt`, systemd: [piconfig.md](piconfig.md).

### 4.2 Fotocamera (Raspberry Pi)

| Voce        | Valore |
|-------------|--------|
| Modello     | **Camera Module 3** (Sony IMX708) |
| Collegamento| Camera cable (CSI) |
| Sensore     | ~11.9 MP — risoluzione nativa **4608 × 2592** |
| Formato     | **JPG** |
| Uso         | Solo **foto** (non video/streaming al momento) |
| Tool        | **`rpicam-still`** (stack libcamera) |
| Storage     | **Locale** per ora; poi trasferimento verso altro device |
| Integrità   | In trasferimento: gestire **corruzione dati** (vedi §7.1) |
| Metadati    | Timestamp (e simili) ricavati **a parte**, non necessariamente via EXIF camera |

Esempio di cattura:

```bash
rpicam-still -o insect_$(date +%Y%m%d_%H%M%S).jpg
```

### 4.3 ESP32-CAM

| Voce              | Valore |
|-------------------|--------|
| Scheda            | **ESP32-CAM** (AI-Thinker) |
| Camera            | Camera **integrata** sulla scheda (non è la Camera Module 3) |
| Ruolo             | Rilevazione / probabilità presenza insetto → **wake Pi** |
| Collegamento al Pi| **Principale:** WAKE su J2 via optoaccoppiatore + ALIVE su GPIO; alternative GPIO / USB in valutazione (vedi [espconfig.md](espconfig.md)) |
| Trigger           | Input **configurabile** (computer vision sulla camera ESP — da implementare) |
| Comunicazione     | Solo wake + senso stato (ALIVE); **nessun** trasferimento foto ESP→Pi |
| Ambiente firmware | **PlatformIO** — cartella [`esp32/`](esp32/) |
| Deep sleep ESP    | Opzionale in futuro (es. wake da PIR) per ridurre consumo |

### 4.4 Sensori (collegati al Raspberry Pi)

| Sensore / funzione     | Grandezza                        | Host | Stato        |
|------------------------|----------------------------------|------|--------------|
| Soil moisture          | Umidità del suolo                | Pi   | Da collegare |
| Acqua                  | Presenza / livello acqua         | Pi   | Da collegare |
| Pressione / temperatura| Pressione atmosferica, temperatura | Pi | Da collegare |
| Metano                 | Concentrazione CH₄ / gas         | Pi   | Da collegare |
| Geolocalizzazione      | Posizione (GPS o equivalente)    | Pi   | Da collegare |

**Soglie di trigger / allarme:** da regolare in base a **dati storici** e a **computer vision** (non ancora fissate).

### 4.5 Tool di test hardware sul Pi

| Tool        | Scopo |
|-------------|--------|
| `stress-ng` | Stressare CPU (e non solo) per osservare comportamento HW, **CPU e ventola** |

```bash
stress-ng --cpu 0 --timeout 60s
```

---

## 5. Software e file già in repository

| Elemento              | Note |
|-----------------------|------|
| `main.pdf`            | Paper di riferimento correlato alla tesi |
| `piconfig.md`         | Guida configurazione Raspberry Pi (halt, ALIVE, systemd) |
| `espconfig.md`        | Guida ESP32-CAM (cablaggio, pin, firmware) |
| `esp32/`              | Progetto PlatformIO: wake Pi + stub evento/CV |
| `capture_rpi.sh`      | Avviatore bash del client di cattura (vedi §5.1) |
| `capture_client.txt`  | Client Python di cattura foto + metadati (vedi §5.2) |
| `pro-uZKfjCJP.jpeg`   | Immagine di esempio / prova |
| `schemi elettrici/`   | KiCad / schemi (es. BME280) |

### 5.1 `capture_rpi.sh` — cosa fa

È lo **script di avvio** (bash). Non scatta le foto da solo: prepara l’ambiente e lancia il client Python.

In pratica, in ordine:

1. Si posiziona nella cartella del progetto (derivata dalla posizione dello script, oppure da `PROJECT_DIR`).
2. Se esiste un file `.env.systemd`, carica da lì eventuali impostazioni (es. `CAPTURE_INTERVAL`, `PYENV_VERSION`).
3. Cerca e attiva un ambiente Python (`pyenv` oppure un virtualenv in `$PYENV_ROOT`).
4. Avvia il programma di cattura come modulo Python:
   - **senza argomenti** → modalità continua, una foto ogni N secondi (default **30**, override con `CAPTURE_INTERVAL`);
   - **con argomenti** → li passa così come sono al client (es. `--oneshot`).

È pensato per essere chiamato da **systemd** al boot del Pi: dopo il wake, la cattura parte senza login SSH.

> Se non trova un ambiente Python valido, termina con errore e non cattura nulla.

**Uso energy-aware (consigliato):** al boot lanciare con `--oneshot`, poi `systemctl poweroff` per tornare in halt. Dettaglio unità systemd in [piconfig.md](piconfig.md).

```bash
# Esempio manuale (dopo aver configurato pyenv/venv)
./capture_rpi.sh --oneshot
./capture_rpi.sh --oneshot --profile macro --zoom 2.0
./capture_rpi.sh                  # continuo, intervallo da CAPTURE_INTERVAL o 30s
```

### 5.2 `capture_client.txt` — cosa fa

È il **programma che scatta le foto** (codice Python; l’estensione è `.txt` ma il contenuto è uno script Python destinato a essere eseguito come `python -m backend.capture_client`).

In sintesi: chiama `rpicam-still` (o `libcamera-still`), salva un JPG e, se disponibili, aggiunge GPS e dati BME280 ai metadati dell’immagine.

Dettaglio del flusso a ogni scatto:

1. Crea (se manca) la cartella `static/uploads/images/`.
2. Genera un nome file con data/ora, es. `rpi_20261019-124900.jpg`.
3. Lancia la fotocamera con risoluzione di default **4608×2592** (Camera Module 3) e qualità JPEG alta.
4. Opzioni utili da linea di comando:
   - una sola foto (`--oneshot`) oppure ciclo continuo (`--interval`);
   - zoom digitale (`--zoom`), profilo `standard` / `macro`;
   - autofocus (`--af-mode`, `--af-range`, `--af-speed`, `--af-window`, `--af-on-capture`);
   - shutter, denoise, sharpness, contrast.
5. Dopo lo scatto prova a leggere:
   - **GPS** → latitudine / longitudine;
   - **BME280** → temperatura, umidità, pressione.
6. Se trova qualcosa, salva questi valori nei **metadati** collegati alla foto (via moduli `backend.photo_metadata`).

Modalità di esecuzione:

| Modo | Comportamento |
|------|----------------|
| Continuo (default) | Scatta, aspetta l’intervallo, ripete all’infinito |
| `--oneshot` | Scatta una foto e termina (adatto al ciclo wake → captura → halt) |

> **Limite attuale:** lo script importa moduli `backend.*` (`bme_reader`, `gps_reader`, `photo_metadata`) che **non sono presenti in questa repo**. Quindi, così com’è, non è eseguibile standalone: va completato o adattato al progetto di tesi (stub dei reader, oppure packaging come pacchetto `backend`).

### 5.3 Come lavorano insieme (ciclo energy-aware)

```
ESP rileva evento → impulso WAKE (J2)
        │
        ▼
 Pi esce da halt / boot
        │
        ▼
 systemd (After=… )  →  capture_rpi.sh --oneshot
        │
        ▼
 capture_client      →  JPG in static/uploads/images/
        │
        ▼
 systemctl poweroff  →  halt (rail 3V3 off se EEPROM configurata)
```

In modalità di sviluppo/test sul Pi già acceso si può usare il ciclo continuo senza poweroff.

---

## 6. Stato avanzamento

### Completato

- [x] Definizione obiettivo applicativo (monitoraggio insetti / raccolto, energy-aware)
- [x] Installazione OS Raspberry Pi 5 (64-bit Bookworm)
- [x] Configurazione hostname/utente `rpi5-03`, SSH abilitato
- [x] Rete Wi‑Fi + Ethernet
- [x] Collegamento Camera Module 3 via camera cable
- [x] Verifica cattura con `rpicam-still` (JPG)
- [x] Disponibilità `stress-ng` per test CPU/ventola
- [x] Policy power: **halt** (no deep sleep sul Pi 5); schema wake J2 + ALIVE documentato
- [x] Guide `piconfig.md` / `espconfig.md` e bozza firmware PlatformIO in `esp32/`

### Da fare

- [ ] Scegliere e cablare in modo definitivo l’alternativa di collegamento (J2+opto vs GPIO vs USB) — vedi [espconfig.md](espconfig.md)
- [ ] Applicare sul Pi le impostazioni EEPROM / `config.txt` / unità systemd di [piconfig.md](piconfig.md)
- [ ] Completare firmware ESP32-CAM: **computer vision** / criterio di evento sulla camera ESP
- [ ] Collegare e pilotare i sensori sul Pi (soil moisture, acqua, P/T, metano, geo)
- [ ] Rendere eseguibile la pipeline di cattura (moduli `backend.*` mancanti)
- [ ] Criteri di “insetto rilevato / probabile” (soglie + CV)
- [ ] Trasmissione locale → altro device con **gestione corruzione / integrità** (checksum, retry, resume)
- [ ] Accesso remoto con **Raspberry Pi Connect**
- [ ] Misure energetiche (batteria vs rete) e test con `stress-ng`
- [ ] Schemi KiCad / BOM / foto cablaggio wake in repo
- [ ] Formalizzare ipotesi/metriche di tesi e scrittura entro primavera

---

## 7. Flusso operativo previsto

1. ESP32-CAM resta alimentato e monitora (camera integrata / logica di probabilità insetto — CV da configurare).
2. Al trigger, se la linea ALIVE è bassa (Pi in halt), invia impulso **WAKE** sui pad J2 (via optoaccoppiatore nella soluzione principale).
3. Il Pi esce da halt, avvia rete, camera e servizio di acquisizione.
4. Cattura JPG insetto (Camera Module 3) + lettura sensori ambientali + geolocalizzazione (quando disponibili).
5. Salva tutto in **locale** (fase attuale).
6. In un secondo momento, trasferisce i dati verso un altro device con controlli di integrità (§7.1).
7. Il Pi esegue `poweroff` e torna in **halt**.
8. L’ESP32 torna in monitoraggio; non deve ritentare il wake finché ALIVE è alto (incluso durante lo shutdown).

Timeout e fail-safe (wake fallito, Pi bloccato acceso) **da affinarsi** in test sul campo.

### 7.1 Integrità in trasmissione (locale → altro device)

Obbligo di progetto: durante il trasferimento dei dati (foto JPG + telemetria) dallo storage locale verso un altro device bisogna **gestire la corruzione e le interruzioni**.

Aspetti da coprire (da implementare):

| Meccanismo              | Perché |
|-------------------------|--------|
| Checksum / hash (es. SHA-256) | Verificare che il file ricevuto sia identico all’originale |
| Ack + retry             | Ritrasmettere se hash non coincide o trasferimento interrotto |
| Resume / chunk          | Riprendere file grandi senza ripartire da zero (utile outdoor / rete instabile) |
| Stato “pending / sent / verified” | Evitare di cancellare in locale dati non ancora verificati lato destinazione |
| Log errori              | Diagnosticare corruzioni ricorrenti (SD, cavo, Wi‑Fi) |

Fino a quando la trasmissione non è pronta, i dati restano **solo in locale**.

---

## 8. Specifiche

### Framework per programmare l’ESP32 — scelta

| Opzione        | In sintesi |
|----------------|------------|
| **Arduino IDE**| Più semplice per iniziare; tante librerie ESP32-CAM |
| **PlatformIO** | Come Arduino ma più ordinato (progetti, `platformio.ini`, dipendenze versionate) |
| **ESP-IDF**    | Ufficiale Espressif; più potente, curva più ripida |
| **MicroPython**| Python sulla scheda; rapido da prototipare, meno tipico per produzione |

**Scelta: PlatformIO.**

Motivi: riusa l’ecosistema librerie Arduino (utile per ESP32-CAM), tiene il progetto in cartelle versionabili nel repo Git, fissa le versioni di framework/librerie (riproducibilità), si integra bene con VS Code / Cursor. Arduino IDE va bene per prove lampo; ESP-IDF solo se servono API low-level avanzate.

Build e flash: vedi [espconfig.md](espconfig.md) e cartella [`esp32/`](esp32/).

---

## 9. Changelog documentazione

| Data       | Modifica |
|------------|----------|
| 2026-10-19 | Prima bozza README |
| 2026-10-19 | Aggiornamento completo da risposte (obiettivo insetti, HW, sensori sul Pi, ESP32-CAM, rete, roadmap) |
| 2026-10-19 | PlatformIO; timer HW; systemd sì; storage locale; integrità trasmissione; deep sleep TBD |
| 2026-10-19 | Spiegazione dettagliata di `capture_rpi.sh` e `capture_client.txt` (§5.1–5.3) |
| 2026-10-20 | Architettura halt + WAKE/ALIVE; guide `piconfig.md` / `espconfig.md`; firmware `esp32/`; niente HTTP ESP↔Pi; capture spiegati per ciclo oneshot→poweroff |
