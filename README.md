# Sistema di monitoraggio gestito da Raspberry

> Titolo provvisorio della tesi.

Documentazione di avanzamento: contesto accademico, architettura, lavoro già svolto e attività ancora da completare.

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
4. comunica all’ESP32 di aver terminato, poi torna spento / in sleep.

In trasmissione da storage locale verso un altro device andrà gestita anche la **corruzione / integrità dei dati** (checksum, retry, ripresa trasferimenti incompleti).

### Domanda di ricerca / metriche

Ancora da formalizzare. Focus attuale: **risparmio energetico** (il Pi resta spento tranne quando serve).

Scenario operativo: il Pi è **sempre spento** tranne quando si rileva un insetto o è probabile che ci sia.

---

## 3. Architettura

```
                         outdoor / campo
 ┌──────────────────────────────────────────────────────────┐
 │                                                          │
 │   ┌─────────────────┐         wake (GPIO, da definire)   │
 │   │   ESP32-CAM     │──────────────────────────────────► │
 │   │  (sempre ON /   │         ◄── done / handshake       │
 │   │   low-power)    │                                    │
 │   └────────┬────────┘                                    │
 │            │ camera ESP (rilevazione preliminare)        │
 │            ▼                                             │
 │   ┌─────────────────┐     camera cable                   │
 │   │ Raspberry Pi 5  │◄──────────────── Camera Module 3   │
 │   │  rpi5-03        │                                    │
 │   │  (OFF di norma) │◄── sensori ambientali (solo sul Pi)│
 │   └─────────────────┘                                    │
 │            │                                             │
 │            ▼                                             │
 │   storage locale (foto JPG + telemetria)                 │
 │   → trasmissione esterna (da definire)                   │
 │   → controllo integrità / anti-corruzione in trasferimento│
 └──────────────────────────────────────────────────────────┘
```

**Alternativa power in valutazione:** oltre al wake via ESP32/GPIO, si sta considerando un **interruttore temporizzato** (timer) per alimentare/spegnere il Pi a intervalli o per finestre di tempo.

### Ruoli

| Componente           | Ruolo                                                                 | Stato            |
|----------------------|-----------------------------------------------------------------------|------------------|
| Raspberry Pi 5       | Acquisizione foto HD, lettura sensori, storage locale, elaborazione   | OS + SSH OK      |
| Camera Module 3      | Foto insetto (JPG)                                                    | Funzionante      |
| ESP32-CAM            | Rilevazione preliminare + wake del Pi + ricezione “done”              | Da configurare   |
| Sensori ambientali   | Umidità suolo, acqua, pressione/temperatura, metano, geolocalizzazione| Da collegare     |

> **Nota aperta:** i sensori sono previsti **solo sul Pi**. Il trigger di wake oggi è legato all’ESP32-CAM (camera / evento). Se in futuro servisse logging ambientale a Pi spento, andrà rivalutata la collocazione di alcuni sensori sull’ESP32.

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
| Power policy    | In valutazione: **`shutdown` completo** vs **sleep** |
| Power HW extra  | In valutazione: **interruttore temporizzato**        |
| Ambiente        | **Outdoor**                                         |
| Energia sistema | **Batteria** oppure **rete elettrica** (entrambi da supportare) |
| Alimentazione con ESP32 | **Condivisa** con l’ESP32-CAM                 |
| Avvio automatico job | Previsto via **systemd** (dopo wake/boot)       |

```bash
ssh rpi5-03@<ip-assegnato-da-dhcp>
# oppure accesso tramite Raspberry Pi Connect
```

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
| Scheda            | **ESP32-CAM** |
| Ruolo             | Rilevazione / probabilità presenza insetto → **wake Pi**; ricezione segnale di fine lavoro |
| Collegamento al Pi| Previsto via **GPIO** (scelta momentanea, può cambiare); in parallelo si valuta un **interruttore temporizzato** |
| Trigger attuale   | Solo su **evento** (non timer / remoto software, per ora) |
| Comunicazione     | **Bidirezionale**: ESP32 → wake; Pi → “ho finito / spegnimi” |
| Ambiente firmware | **PlatformIO** (scelta consigliata — vedi §8) |
| Deep sleep ESP    | **Non ancora deciso** |

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
| `.pdf`            | Paper di riferimento correlato alla tesi |
| `capture_rpi.sh`      | Avviatore bash del client di cattura (vedi §5.1) |
| `capture_client.txt`  | Client Python di cattura foto + metadati (vedi §5.2) |
| `pro-uZKfjCJP.jpeg`   | Immagine di esempio / prova |
| Firmware ESP32        | Da aggiungere |
| Schemi elettrici      | Da aggiungere (KiCad o equivalente) — **sì, versionati in questo repo** |

### 5.1 `capture_rpi.sh` — cosa fa

È lo **script di avvio** (bash). Non scatta le foto da solo: prepara l’ambiente e lancia il client Python.

In pratica, in ordine:

1. Si posiziona nella cartella del progetto.
2. Se esiste un file `.env.systemd`, carica da lì eventuali impostazioni (es. intervallo di cattura).
3. Cerca e attiva un ambiente Python (`pyenv` oppure un virtualenv).
4. Avvia il programma di cattura:
   - **senza argomenti** → modalità continua, una foto ogni N secondi (default **30**);
   - **con argomenti** → li passa così come sono al client Python.

È pensato per essere chiamato da **systemd** al boot del Pi: accendi la macchina e la cattura parte da sola, senza login SSH.

> Se non trova un ambiente Python valido, termina con errore e non cattura nulla.

### 5.2 `capture_client.txt` — cosa fa

È il **programma che scatta le foto** (codice Python; l’estensione è `.txt` ma il contenuto è uno script Python).

In sintesi: chiama `rpicam-still` (o `libcamera-still`), salva un JPG e, se disponibili, aggiunge GPS e dati BME280 ai metadati dell’immagine.

Dettaglio del flusso a ogni scatto:

1. Crea (se manca) la cartella `static/uploads/images/`.
2. Genera un nome file con data/ora, es. `rpi_20261019-124900.jpg`.
3. Lancia la fotocamera con risoluzione di default **4608×2592** (Camera Module 3) e qualità JPEG alta.
4. Opzioni utili da linea di comando:
   - una sola foto (`--oneshot`) oppure ciclo continuo;
   - zoom digitale, profilo `standard` / `macro`, autofocus, shutter, denoise, sharpness, contrast.
5. Dopo lo scatto prova a leggere:
   - **GPS** → latitudine / longitudine;
   - **BME280** → temperatura, umidità, pressione.
6. Se trova qualcosa, salva questi valori nei **metadati** collegati alla foto.

Modalità di esecuzione:

| Modo | Comportamento |
|------|----------------|
| Continuo (default) | Scatta, aspetta l’intervallo, ripete all’infinito |
| `--oneshot` | Scatta una foto e termina |

> **Limite attuale:** lo script importa moduli `backend.*` (`bme_reader`, `gps_reader`, `photo_metadata`) che **non sono presenti in questa repo**. Quindi, così com’è, non è eseguibile standalone: va completato o adattato al progetto di tesi.

### 5.3 Come lavorano insieme

```
systemd (o comando manuale)
        │
        ▼
 capture_rpi.sh          ← prepara Python / variabili
        │
        ▼
 capture_client.txt      ← scatta JPG + metadati GPS/BME
        │
        ▼
 static/uploads/images/rpi_….jpg
```

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

### Da fare

- [ ] Decidere policy power del Pi: **shutdown** vs **sleep**
- [ ] Valutare / progettare **interruttore temporizzato** vs (o insieme a) wake GPIO da ESP32-CAM
- [ ] Definire schema elettrico wake + alimentazione condivisa outdoor
- [ ] Firmware ESP32-CAM con **PlatformIO** (rilevazione, wake, handshake “done”; deep sleep TBD)
- [ ] Servizio **systemd** sul Pi per avvio automatico cattura/sensori al boot
- [ ] Collegare e pilotare i sensori sul Pi (soil moisture, acqua, P/T, metano, geo)
- [ ] Pipeline: evento → wake → foto + telemetria → salvataggio **locale** → notify ESP32 → spegnimento
- [ ] Criteri di “insetto rilevato / probabile” (soglie + computer vision)
- [ ] Trasmissione locale → altro device con **gestione corruzione / integrità** (checksum, retry, resume)
- [ ] Accesso remoto con **Raspberry Pi Connect**
- [ ] Misure energetiche (batteria vs rete) e test con `stress-ng`
- [ ] Schemi KiCad / BOM / foto cablaggio in repo
- [ ] Formalizzare ipotesi/metriche di tesi e scrittura entro primavera

---

## 7. Flusso operativo previsto

1. ESP32-CAM resta alimentato e monitora (camera / logica di probabilità insetto).
2. Al trigger, invia segnale di **wake/accensione** al Raspberry Pi 5.
3. Il Pi avvia rete, camera e script di acquisizione.
4. Cattura JPG insetto + lettura sensori ambientali + geolocalizzazione.
5. Salva tutto in **locale** (fase attuale).
6. In un secondo momento, trasferisce i dati verso un altro device con controlli di integrità (§7.1).
7. Notifica l’ESP32 (“done”) e si spegne / entra in sleep (o viene tagliato dall’interruttore temporizzato).
8. L’ESP32 torna in monitoraggio.

Handshaking, timeout e fail-safe (wake fallito, Pi bloccato acceso, timer, ecc.) **da definire**.

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

## 8. Chiarimenti (risposte alle tue domande)

### LED / buzzer di stato (domanda 13)

Intendevo un indicatore fisico sul Pi (LED o cicalino) per capire outdoor se è acceso, in cattura, in errore, ecc. **Non è un requisito** al momento: si può aggiungere dopo se serve in campo.

### Framework per programmare l’ESP32 (domanda 25) — scelta

| Opzione        | In sintesi |
|----------------|------------|
| **Arduino IDE**| Più semplice per iniziare; tante librerie ESP32-CAM |
| **PlatformIO** | Come Arduino ma più ordinato (progetti, `platformio.ini`, dipendenze versionate) |
| **ESP-IDF**    | Ufficiale Espressif; più potente, curva più ripida |
| **MicroPython**| Python sulla scheda; rapido da prototipare, meno tipico per produzione |

**Scelta consigliata per questa tesi: PlatformIO.**

Motivi: riusa l’ecosistema librerie Arduino (utile per ESP32-CAM), tiene il progetto in cartelle versionabili nel repo Git, fissa le versioni di framework/librerie (riproducibilità), si integra bene con VS Code / Cursor. Arduino IDE va bene per prove lampo; ESP-IDF solo se servono API low-level avanzate.

### Deep sleep sull’ESP32 (domanda 26)

Con **deep sleep** l’ESP32 spegne quasi tutto e consuma pochissimo, svegliandosi solo a intervalli o su interrupt. Utile a batteria; complica camera, Wi‑Fi e timing del wake.

**Stato decisione: non ancora deciso.**

### “Grandezze” dei sensori (domanda 28)

Era solo la domanda: *cosa misura ciascun sensore?* Ora compilata in §4.4 (umidità suolo, acqua, P/T, metano, posizione).

### Pipeline automatica al boot / systemd (domanda 34)

Su Linux, un **servizio systemd** può avviare automaticamente allo startup lo script di cattura/sensori, così dopo il wake del Pi non serve login manuale.

**Decisione: sì** — da implementare quando la pipeline di cattura sarà stabile.

### Linguaggio sul Pi (domanda 35)

Dipende dal sensore/libreria: tipicamente **Python** per I2C/SPI/GPIO e orchestrazione; **bash** per wrapper (`rpicam-still`, shutdown); C/C++ solo se serve performance (vision). Misto è normale.

### Privacy immagini (domanda 39)

In outdoor agricolo il rischio persone in foto è basso ma non nullo. Possibilità tipiche:

- inquadrare solo suolo/piante;
- non caricare cloud senza accordo;
- anonimizzare / non salvare dati personali;
- documentare retention (quanto a lungo tieni le JPG).

**Storage attuale: solo locale.** Trasmissione verso altro device in seguito, con gestione corruzione (§7.1). Privacy foto: inquadrare suolo/piante dove possibile; retention da documentare.

---

## 9. Privacy, sicurezza e buone pratiche

- Non committare password, chiavi SSH private, token Raspberry Pi Connect o Wi‑Fi in chiaro.
- Outdoor: protezione IP/scatola stagna, condensazione, cavi alimentazione condivisa Pi ↔ ESP32.
- Segnale wake GPIO: livelli 3.3 V, debounce, eventuale MOSFET/relè se si taglia il 5 V; valutare anche l’**interruttore temporizzato**.
- Recovery: timeout se il Pi non completa il ciclo; evitare che resti acceso a vuoto in batteria.
- Trasferimenti: non cancellare i file locali finché l’integrità lato destinazione non è verificata.

---

## 10. Roadmap

1. Fissare **shutdown vs sleep** e schema wake (GPIO ESP32-CAM e/o **interruttore temporizzato**).
2. Firmware minimo ESP32-CAM con **PlatformIO** (wake + handshake “done”; deep sleep TBD).
3. **systemd** per job automatici al boot + sensori sul Pi uno alla volta + logging locale.
4. Integrazione completa evento → foto + telemetria → spegnimento.
5. Trasmissione verso altro device con **anti-corruzione** (hash, retry, resume).
6. Computer vision / soglie; misure consumo; test `stress-ng`.
7. Schemi + BOM in repo; scrittura tesi entro primavera.

---

## 11. Riferimenti

- Paper locale: [`main.pdf`](./main.pdf)
- [Raspberry Pi Documentation](https://www.raspberrypi.com/documentation/)
- [Camera Module 3](https://www.raspberrypi.com/documentation/accessories/camera.html) — 4608×2592, IMX708
- [rpicam-still / libcamera](https://www.raspberrypi.com/documentation/computers/camera.html)
- [Raspberry Pi Connect](https://www.raspberrypi.com/documentation/services/connect.html)
- [ESP32-CAM (Espressif / moduli AI Thinker)](https://docs.espressif.com/)
- Relatore: Francesco Betti Sorbelli — Università di Perugia

---

## 12. Changelog documentazione

| Data       | Modifica |
|------------|----------|
| 2026-10-19 | Prima bozza README |
| 2026-10-19 | Aggiornamento completo da risposte (obiettivo insetti, HW, sensori sul Pi, ESP32-CAM, rete, roadmap) |
| 2026-10-19 | PlatformIO; timer HW; systemd sì; storage locale; integrità trasmissione; deep sleep TBD |
| 2026-10-19 | Spiegazione dettagliata di `capture_rpi.sh` e `capture_client.txt` (§5.1–5.3) |
