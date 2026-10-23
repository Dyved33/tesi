# pyexplanation — walkthrough di `sensors.py`

Spiega `sensors.py`, il lettore oneshot dei sensori **collegati al Raspberry Pi**.  
Allineato a [`plan.pdf`](../plan.pdf): il **BME280 non è sul Pi** (solo ESP32); questo script gestisce GPS, acqua, suolo, metano e lascia uno slot per i valori BME ricevuti dall’ESP.

Vedi anche: [piconfig.md](piconfig.md), [espconfig.md](espconfig.md).

> **In breve:** `sensors.py` legge una tantum (burst) i sensori collegati al Raspberry Pi (GPS, acqua, suolo, metano), scrive una riga in `data/sensors.csv` ed esce. Non è un demone: non resta in attesa in un loop. Il BME280 non è letto direttamente qui perché in campo sta sull'ESP32; i suoi valori arrivano al Pi tramite il protocollo ESP→Pi (ancora da definire).

---

## Scopo

Nella **app selettiva** il Pi è in halt e viene svegliato dall’ESP quando il decider autorizza. Mentre è acceso, lo script:

1. legge i sensori hostati sul Pi in un burst rapido;
2. appende una riga a `data/sensors.csv`;
3. esce in modo che la pipeline possa procedere al `poweroff`.

Nella **app continuativa** può essere chiamato a cadenza (es. ogni minuto), senza poweroff.

Non è un demone: non resta in loop interno (salvo future varianti).

---

## Struttura del file

| Sezione | Contenuto |
|---------|-----------|
| `SENSORS` | Flag, pin, porte UART, canali ADC. Adattare al cablaggio reale |
| `CSV_PATH` / `CSV_HEADER` | Una riga per ciclo di lettura |
| Helper | Timestamp ISO UTC, create/append CSV |
| `read_*` primari | Implementazioni consigliate |
| Blocchi `====` | Alternative (altra libreria / dummy) |
| `main()` | Legge i sensori abilitati, scrive CSV, exit 0/1 |

---

## BME280 e piano operativo

| Dove | Cosa |
|------|------|
| Installazione di campo | BME **solo sull’ESP**; case esterno |
| Questo script | Colonna BME nel CSV: da popolare con dati **inoltrati dall’ESP** (timestamp di misura distinto da ricezione) |
| Config `SENSORS["bme280"]` | Se `enabled` e ancora su I2C locale → solo per **prove al banco** con un BME temporaneo sul Pi. In campo: disabilitare lettura I2C locale e usare il path ESP |

Finché il protocollo ESP→Pi non è pronto, i campi BME possono restare vuoti o dummy senza far fallire l’intero burst.

---

## Alternative `# ===`

Ogni sensore ha alternative tra commenti `# ============================================================`.

| Sensore | Primario | Alternative |
|---------|----------|-------------|
| BME280 (banco) | Adafruit I2C | smbus2, dummy / **futuro: da ESP** |
| GPS | pyserial NMEA `$GPGGA` | dummy |
| Acqua | gpiozero | RPi.GPIO, dummy |
| Suolo | MCP3008 Adafruit | spidev raw, GPIO digital, dummy |
| Metano | MCP3008 Adafruit | spidev raw, GPIO DO, dummy |

Esempio switch:

```python
"library": "dummy"     # nessun hardware ancora
"library": "spidev_raw"
```

> **Dummy in breve:** “dummy” è un'implementazione fittizia che restituisce valori di esempio senza hardware reale. Serve per sviluppare e testare lo script anche quando i sensori non sono ancora collegati.

> **Oneshot in breve:** una lettura “oneshot” viene eseguita una sola volta e poi il programma termina. È diversa da un demone, che resta in esecuzione in background in attesa di eventi.

---

## CSV

| Colonna | Significato |
|---------|-------------|
| `timestamp_iso` | Istante del burst (UTC) |
| `bme280_*` | Da ESP in campo (o I2C locale solo in banco) |
| `gps_*` | Fix NMEA |
| `water_present_bool` | Presenza/livello (funzione da precisare in piano) |
| `soil_moisture_*` | ADC / % grezza |
| `methane_*` | Tensione; ppm dopo calibrazione |
| `sensors_ok` / `sensors_failed` | Elenco esiti |

---

## Esecuzione

```bash
cd ~/tesi
source ~/venv/bin/activate
python3 "scripts and configuration/sensors.py"
```

Exit `0` se tutti i sensori abilitati ok, `1` se qualcuno fallisce (la riga viene comunque scritta con i campi disponibili).

---

## Integrazione con la cattura

`capture_rpi.sh --oneshot` lancia `python -m backend.capture_client`, che può allegare metadati ambientali alla foto. Target: stessi valori BME provenienti dall’ESP e letture dei sensori Pi, collegabili per timestamp al DB del dataset.

---

## Calibrazione

- **MQ metano:** tensione ≠ ppm; calibrare R0 e curva del datasheet.
- **Suolo:** % lineare solo grezza; calibrare su secco/saturo.
- **BME:** compensazione a carico del firmware ESP (o libreria Adafruit se in banco sul Pi).

---

## Prima di un run in campo

1. Passi halt/ALIVE/interfacce in [piconfig.md](piconfig.md).
2. BME di campo cablato sull’ESP, non sull’I2C del Pi ([espconfig.md](espconfig.md)).
3. `SENSORS` allineato al cablaggio reale; BME I2C locale off in produzione.
4. Un `sensors.py` manuale → riga in `data/sensors.csv`.
5. Ciclo selettivo: wake → boot → cattura + sensori → poweroff; oppure cadenze continuative senza poweroff.
