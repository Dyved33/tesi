# Configurazione ESP32-CAM

Guida pin, cablaggio (alternative), firmware PlatformIO e trappole.  
Contesto generale: [README.md](README.md). Lato Pi: [piconfig.md](piconfig.md).

---

## 1. Due fotocamere, due ruoli

| Dispositivo | Camera | Ruolo |
|-------------|--------|-------|
| **ESP32-CAM** | Camera **integrata** sulla scheda AI-Thinker | Trigger / rilevazione preliminare (computer vision da configurare) |
| **Raspberry Pi 5** | **Camera Module 3** (CSI) | Foto HD dopo il wake |

L’ESP **non** invia immagini al Pi. Sveglia solo il Pi; il Pi scatta in autonomia.

---

## 2. Scheda e pin liberi

Assunzione di lavoro: **ESP32-CAM AI-Thinker** senza SD in uso. Quasi tutti i pin sono occupati dalla camera; restano tipicamente liberi: **2, 12, 13, 14, 15**.

| Pin | Uso proposto | Motivo |
|-----|--------------|--------|
| **GPIO14** | WAKE (uscita verso opto / circuito wake) | Libero |
| **GPIO13** | ALIVE (ingresso dal Pi GPIO17) | Libero |
| GPIO12 | **Non usare** come ingresso pilotato dal Pi | Pin di **strapping**: alto al boot → flash a 1,8 V e la scheda non parte |
| GPIO16 | Occupato | **PSRAM** |

---

## 3. Alternative di collegamento ESP ↔ Pi

> **SCELTA DEFINITIVA: Alternativa A** (J2 + optoaccoppiatore + ALIVE)
> 
> Questa è l'unica modalità affidabile per Pi 5 con `POWER_OFF_ON_HALT=1`.
> Le alternative B e C sono documentate solo per riferimento storico.

### Alternativa A — J2 + optoaccoppiatore + ALIVE ✅ **SCELTA**

Due linee elettriche:

| Linea | Direzione | Funzione |
|-------|-----------|----------|
| WAKE | ESP GPIO14 → pad **J2** del Pi (tramite **PC817**) | Simula pressione breve del pulsante di accensione |
| ALIVE | Pi GPIO17 → ESP GPIO13 | Alto = Pi acceso (rail 3V3 su); basso = halt |

**Cablaggio WAKE**

1. ESP `GPIO14` → resistenza **330 Ω** → LED (anodo) di un optoaccoppiatore **PC817**.
2. Catodo del LED → GND (ESP).
3. Fototransistor del PC817 sui due pad **J2**: emettitore sul pad di massa (verificare col tester), collettore sull’altro pad.
4. Impulso firmware: alto per ~**200 ms**, poi basso. **Mai** tenere alto ~1 s (hard off).

**Cablaggio ALIVE**

1. Pi `GPIO17` → ESP `GPIO13`.
2. Pulldown **10 kΩ** da GPIO13 verso GND (lato ESP).
3. **GND comune** tra Pi ed ESP (necessaria per ALIVE).

**Alimentazione ESP**

Con `POWER_OFF_ON_HALT=1` si spegne il rail 3,3 V; il pin **5 V** del Pi resta tipicamente alimentato in halt. Si può alimentare l’ESP da lì, oppure a monte dallo stesso alimentatore.

**Perché l’opto:** l’unica linea “in ingresso” verso i pad di power del Pi è isolata; si evita di pilotare GPIO del Pi quando il rail è spento.

### Alternativa B — GPIO diretto

Collegare un GPIO ESP a un GPIO (o ingresso power) del Pi **senza** opto / J2.

| Pro | Contro |
|-----|--------|
| Meno componenti | Sul Pi 5 **non** c’è wake affidabile via GPIO3 come sul Pi 4 |
| Cablaggio più semplice | Pilotare un pin del Pi **senza alimentazione** può back-powering tramite i diodi di protezione |
| | Rischio di spegnere il Pi se si “preme” il power path mentre è già acceso (senza ALIVE) |

Da valutare solo in laboratorio, con ALIVE (o equivalente) e misure di corrente. Non è la strada documentata come primaria.

### Alternativa C — USB

| Uso possibile | Note |
|---------------|------|
| Alimentazione ESP | Comodo in banco; outdoor dipende da come è cablato il Pi in halt |
| Seriale di debug | Utile in sviluppo (`/dev/ttyUSB…` o UART su USB) |
| Wake del Pi | **Non** è un meccanismo affidabile di uscita da halt: USB non sostituisce il pulsante/J2 |

In produzione outdoor l’USB resta candidata per **alimentazione e debug**, non come unico path di wake.

---

## 4. Logica firmware (cartella `esp32/`)

Progetto **PlatformIO**: [`esp32/`](esp32/).

Comportamento previsto:

1. Init camera AI-Thinker (pattern Analogous a CameraWebServer).
2. `PIN_WAKE` output basso a riposo; `PIN_ALIVE` input (pulldown).
3. Su **evento** (hook configurabile / stub CV):
   - se ALIVE è **basso** → impulso WAKE → attendere ALIVE alto (timeout);
   - se ALIVE è **alto** → non dare impulso (Pi già acceso o in shutdown).
4. Il Pi, una volta avviato, cattura da solo e torna in halt (vedi [piconfig.md](piconfig.md)).

Computer vision: oggi c’è un **placeholder** (`eventDetected()`). Va sostituito con il modello/soglia scelti per la tesi.

Wi‑Fi: **non necessario** per il wake GPIO. `secrets.h` è opzionale per esperimenti futuri.

### Build e flash

```bash
cd esp32
# Copia le credenziali solo se ti servono:
# cp include/secrets.h.example include/secrets.h

pio run
pio run -t upload
pio device monitor
```

Board: `esp32cam` (AI-Thinker) in `platformio.ini`.

---

## 5. Trappole

| Tema | Dettaglio |
|------|-----------|
| Latenza boot | Dall’impulso WAKE al Pi pronto per catturare possono passare **15–30 s** (ordine di grandezza). L’ESP non deve assumere che il lavoro sul Pi sia istantaneo. |
| UART verso Pi spento | Non pilotare TX/GPIO verso un Pi in halt: rischio back-powering. Se serve UART (`dtparam=uart0=on`, `/dev/ttyAMA0`), tieni il TX ESP in alta impedenza finché ALIVE è basso. |
| Finestra di shutdown | Tra l’inizio dello shutdown e lo spegnimento del rail 3,3 V, ALIVE resta **alto**. Non ritentare WAKE in quella finestra: aspetta che ALIVE torni basso, poi valuta un nuovo evento. |
| Consumo ESP | Se l’ESP resta sempre acceso con camera attiva, consuma tipicamente **centinaia di mW** — spesso più del Pi in halt (~0,01 W). Per ottimizzare in seguito: deep sleep ESP + wake da **PIR** (`esp_sleep_enable_ext0_wakeup`), non dalla sola camera. |
| Impulso troppo lungo | Impulso WAKE ≥ ~1 s può forzare hard off invece di un boot pulito. |

---

## 6. Checklist lato ESP

1. [x] **Scegliere alternativa A / B / C e cablare** → **A scelta definitiva**
2. [ ] Se A: PC817 + 330 Ω + pulldown 10 kΩ + GND comune
3. [ ] Verificare con tester i pad J2 (massa vs segnale)
4. [ ] Flash firmware `esp32/` e test impulso solo a ALIVE basso
5. [ ] Implementare `eventDetected()` (CV / soglia)
6. [ ] (Opzionale) misurare consumi; valutare PIR + deep sleep
