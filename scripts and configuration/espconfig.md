# Configurazione ESP32

Guida pin, cablaggio wake, BME280 e firmware PlatformIO, allineata a [`plan.pdf`](../plan.pdf).  
Contesto: [README.md](../README.md) · Pi: [piconfig.md](piconfig.md).

> **In breve:** l'ESP32 è il “cervello sempre acceso” del sistema. Anche quando il Raspberry Pi è in halt (o spento), l'ESP32 resta alimentato, legge il BME280, prevede temperatura e umidità, e decide se svegliare il Pi inviando un impulso sul pad J2.

---

## 1. Ruolo dell’ESP (piano)

| Compito | Dettaglio |
|---------|-----------|
| Lettura **BME280** | Unico host del sensore: T, umidità, pressione + timestamp |
| Inoltro al Pi | A richiesta o alla cadenza dell’applicazione |
| App selettiva (TMC) | **Forecaster** (GRU quantizzate) + **decider** (filtro biologico + raffinamento tipo HistGBT) → autorizza o meno il wake |
| Wake hardware | Impulso su pad J2 del Pi (via opto) solo se ALIVE basso |
| Alimentazione | Sempre on, anche a Pi in halt |

Le fotocamere sono **solo sul Raspberry**. L’ESP non scatta le foto di campo e non deve basare la decisione di wake su una camera propria: la politica usa dati ambientali e indicatori temporali/fenologici (gradi-giorno). La pressione si registra ma, nel lavoro TMC, è **esclusa** dal decider.

### Scheda attuale vs target

| | Stato |
|---|--------|
| **Target di piano** | ESP32 (senza obbligo di camera) + BME280 I2C + WAKE/ALIVE + protocollo dati verso Pi |
| **Codice in repo oggi** | Progetto PlatformIO su board `esp32cam` (AI-Thinker): wake J2 + ALIVE; stub “evento” ancora legato alla camera integrata |

Il wake J2/ALIVE resta valido. Va evoluto il firmware: togliere la dipendenza dalla camera ESP, aggiungere BME280 e la pipeline forecaster/decider.

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
| **GPIO14** | WAKE → opto → J2 | Libero |
| **GPIO13** | ALIVE ← Pi GPIO17 | Libero |
| GPIO12 | Evitare come ingresso dal Pi | Strapping: alto al boot → flash 1,8 V |
| GPIO16 | Occupato | PSRAM |

Su una scheda ESP32 “nuda” o DevKit i pin WAKE/ALIVE/I2C andranno riassegnati e documentati qui.

> **Strapping pin in breve:** alcuni pin dell'ESP32 hanno funzioni speciali all'avvio (ad esempio GPIO12 determina la tensione di flash). Usarli come ingressi comuni può impedire il corretto boot della scheda. Per questo GPIO12 va evitato come pin di ingresso dal Pi.

---

## 4. Collegamento ESP ↔ Pi — Alternativa A (scelta)

### WAKE + ALIVE

| Linea | Direzione | Funzione |
|-------|-----------|----------|
| WAKE | ESP GPIO14 → pad **J2** (via **PC817**) | Simula pressione breve del pulsante |
| ALIVE | Pi GPIO17 → ESP GPIO13 | Alto = Pi acceso; basso = halt |

**WAKE**

1. ESP `GPIO14` → **330 Ω** → LED (anodo) PC817; catodo → GND ESP.
2. Fototransistor sui pad J2 (emettitore massa, collettore segnale — verificare col tester).
3. Impulso: alto ~**200 ms**, poi basso. **Mai** ~1 s (hard off).

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

### Alternative B/C (solo riferimento)

GPIO diretto senza opto e USB-as-wake **non** sono la strada primaria sul Pi 5. USB resta utile per alimentazione/debug in banco.

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

1. Init camera AI-Thinker (da rimuovere/neutralizzare nel path target).
2. `PIN_WAKE` basso a riposo; `PIN_ALIVE` input.
3. Su `eventDetected()` (stub): se ALIVE basso → WAKE.
4. Test manuale seriale: carattere `w`.

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

1. [x] Wake Alternativa A (J2 + opto + ALIVE) come path hardware
2. [ ] Cablare BME280 **solo** sull’ESP; case 3D esterno + passaggio a tenuta
3. [ ] Verificare letture BME a Pi in halt (ESP alimentato)
4. [ ] PC817 + 330 Ω + pulldown 10 kΩ + GND comune
5. [ ] Flash e test WAKE solo a ALIVE basso
6. [ ] Protocollo inoltro misure + sync orologi
7. [ ] Integrare forecaster/decider; ritirare trigger basato su camera ESP
8. [ ] Misure energetiche ESP (e confronto con paper TMC)
