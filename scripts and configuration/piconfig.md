# Configurazione Raspberry Pi 5

Guida operativa per halt, linea ALIVE, sensori **collegati al Pi**, cattura al boot (app selettiva) e modalità continuativa.  
Contesto: [README.md](../README.md) · Piano: [`plan.pdf`](../plan.pdf) · ESP: [espconfig.md](espconfig.md).

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

L’ESP **non** deve dare WAKE senza conoscere lo stato del Pi → linea **ALIVE** ([espconfig.md](espconfig.md)).

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

- [`capture_rpi.sh`](capture_rpi.sh) — attiva Python e lancia il client
- `backend/capture_client` — scatto via `rpicam-still`

```bash
./capture_rpi.sh --oneshot
sudo systemctl poweroff
```

Unità di esempio: [`insect-capture.service`](insect-capture.service).

```bash
sudo cp "scripts and configuration/insect-capture.service" /etc/systemd/system/
# adatta User e path
sudo systemctl daemon-reload
sudo systemctl enable insect-capture.service
```

Per test lunghi: disabilita il servizio o togli il `poweroff`.

Variabili: copia [`.env.systemd.example`](.env.systemd.example) in `.env.systemd` nella root del progetto sul Pi.

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

Legge i sensori **hostati sul Pi** (GPS, acqua, suolo, metano). Il campo BME nel CSV andrà popolato dai dati ricevuti dall’ESP quando il protocollo sarà pronto. Dettaglio: [pyexplanation.md](pyexplanation.md).

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
