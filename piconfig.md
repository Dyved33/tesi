# Configurazione Raspberry Pi 5

Guida operativa per halt a basso consumo, linea ALIVE, interfacce sensori, cattura automatica al boot e ritorno in halt.  
Contesto generale: [README.md](README.md). Lato ESP: [espconfig.md](espconfig.md).

---

## 0. Aggiornare il sistema

```bash
sudo apt update && sudo apt full-upgrade -y
sudo reboot
```

---

## 1. Halt (non deep sleep)

Il Raspberry Pi 5 **non supporta suspend-to-RAM**. Gli stati utili sono:

| Stato | Significato |
|-------|-------------|
| Acceso | Kernel e servizi attivi |
| Halt | Spento ma alimentato; riaccendibile dal pulsante o dai pad J2 |

Se togli l’alimentazione, nessun GPIO/segnale dall’ESP può riaccendere il Pi (servirebbe un relè o MOSFET sull’alimentatore).

---

## 2. EEPROM — consumo in halt

```bash
sudo rpi-eeprom-config --edit
```

Imposta:

```
POWER_OFF_ON_HALT=1
WAKE_ON_GPIO=0
```

| Impostazione | Effetto |
|--------------|---------|
| `POWER_OFF_ON_HALT=1` | Allo shutdown viene tolto il rail **3,3 V**. Il consumo tipico in halt scende da circa 1,2–1,6 W a circa **0,01 W**. Il pulsante di accensione / J2 resta utilizzabile. |
| `WAKE_ON_GPIO=0` | Sul Pi 5 l’accensione passa dal **pulsante e dai pad**, non dai GPIO come sul Pi 4. Non esiste il trucco “GPIO3 wake” della generazione precedente. |

Dopo la modifica, riavvia e verifica con:

```bash
sudo rpi-eeprom-config
```

---

## 3. Pad J2 (pulsante esterno)

I pad **J2** (tra il connettore della batteria RTC e il bordo della scheda) servono ad aggiungere un pulsante esterno: **chiudere brevemente i due pad** equivale a premere il pulsante di accensione a bordo.

| Situazione | Effetto di una chiusura breve |
|------------|-------------------------------|
| Pi in halt (alimentato) | Riavvio |
| Pi acceso (Raspberry Pi OS Lite) | Avvio dello **shutdown** |
| Pressione prolungata (~1 s+) | Spegnimento forzato (hard off) |

Per questo l’ESP **non deve** dare l’impulso WAKE senza conoscere lo stato del Pi: serve la linea **ALIVE** (vedi sotto e [espconfig.md](espconfig.md)).

---

## 4. Linea ALIVE — `config.txt`

File: `/boot/firmware/config.txt` (Bookworm).

Aggiungi:

```
gpio=17=op,dh
```

| Significato | Dettaglio |
|-------------|-----------|
| `op` | GPIO17 come output |
| `dh` | Drive high (alto) |

Il firmware porta GPIO17 **alto già all’avvio**. In halt, con `POWER_OFF_ON_HALT=1`, il rail 3,3 V è spento: la linea va bassa. Lato ESP serve una **pulldown** (documentata in espconfig).

Cablaggio proposto: **GPIO17 (Pi) → GPIO13 (ESP)**.

---

## 5. Interfacce hardware per i sensori

Il GPIO del Pi è **digitale only** (3.3 V, alto/basso). I tuoi sensori richiedono interfacce miste:

| Sensore | Interfaccia | Abilita con |
|---------|-------------|-------------|
| BME280 (pressione/temp/umidità) | I2C | `i2c` |
| GPS (NMEA seriale) | UART | `uart` |
| Umidità suolo / metano (analog) | SPI + ADC esterno (es. MCP3008) | `spi` |
| Acqua (switch digitale) | GPIO | già disponibile |

### Opzione A — `raspi-config` (consigliato)

```bash
sudo raspi-config
```

Vai in **Interfacing Options** e abilita:
- `I2C` → Sì
- `SPI` → Sì (solo se usi un ADC esterno per i sensori analogici)
- `Serial Port` → **No** alla login shell su seriale, **Sì** all’hardware seriale

Questo libera `/dev/ttyAMA0` o `/dev/ttyS0` per il GPS.

### Opzione B — modifica manuale di `/boot/firmware/config.txt`

Aggiungi (o decommenta) queste righe:

```ini
dtparam=i2c_arm=on
dtparam=spi=on
enable_uart=1
```

Poi riavvia:

```bash
sudo reboot
```

---

## 6. Permessi utente

Lo script sensori ha bisogno di accesso ai dispositivi I2C, porte seriali e GPIO. Aggiungi l’utente ai gruppi richiesti:

```bash
sudo usermod -aG i2c,dialout,gpio $USER
```

Effettua il logout e login di nuovo (o riavvia) perché le modifiche ai gruppi abbiano effetto.

Verifica:

```bash
groups
```

---

## 7. Dipendenze Python

```bash
sudo apt install -y python3-pip python3-smbus i2c-tools
pip3 install --break-system-packages gpiozero adafruit-circuitpython-bme280 pyserial
```

Note:
- `i2c-tools` fornisce `i2cdetect` (comando di verifica sotto).
- `gpiozero` serve per la lettura digitale del sensore acqua.
- `adafruit-circuitpython-bme280` è la libreria consigliata per BME280.
- `pyserial` legge le frasi NMEA dal GPS su UART.
- Se usi un ADC MCP3008 per sensori analogici (suolo/metano), installa anche:
  ```bash
  pip3 install --break-system-packages adafruit-circuitpython-mcp3xxx spidev
  ```

Su Bookworm (64-bit), i pacchetti pip possono richiedere `--break-system-packages` oppure un ambiente virtuale. Per un progetto di tesi è preferibile il venv:

```bash
python3 -m venv ~/venv
source ~/venv/bin/activate
pip install gpiozero adafruit-circuitpython-bme280 pyserial adafruit-circuitpython-mcp3xxx spidev
```

---

## 8. Verifica interfacce e rilevamento sensori

### Scan bus I2C — `i2cdetect -y 1`

```bash
i2cdetect -y 1
```

**Cosa fa:** scandisce il bus I2C 1 (bus principale del Pi) e stampa una tabella degli indirizzi dove ha risposto un dispositivo.

**Cosa cercare:**
- BME280 risponde tipicamente a `0x76` o `0x77`.
- Se vedi solo `--`, I2C non funziona o nulla è cablato.
- Se vedi `UU`, l’indirizzo è in uso da un driver kernel (solitamente va bene).

### Dispositivi seriali — `ls /dev/tty*`

```bash
ls /dev/tty*
```

**Cosa fa:** elenca tutti i dispositivi seriali/TTY.

**Cosa cercare:**
- `/dev/ttyAMA0` — UART principale su Pi 5 (probabile GPS se cablato su GPIO 14/15).
- `/dev/ttyS0` — UART secondario/mini.
- `/dev/ttyUSB0` — se il GPS usa un adattatore USB-seriale.

Se non vedi il dispositivo atteso, controlla il cablaggio e che `enable_uart=1` sia impostato.

### Sanity check camera

```bash
rpicam-still -o test.jpg --timeout 2000
ls -lh test.jpg
```

---

## 9. Cattura al boot e ritorno in halt

Niente server HTTP: al boot il Pi esegue la cattura (Camera Module 3) e poi torna in halt.

### 9.1 Storage foto

Il client in repo salva in:

```
static/uploads/images/rpi_YYYYMMDD-HHMMSS.jpg
```

Assicurati che la working directory del servizio sia la root del progetto (dove esistono `capture_rpi.sh` e, a regime, il pacchetto `backend`).

### 9.2 Script

- [`capture_rpi.sh`](capture_rpi.sh) — attiva Python e lancia il client
- [`capture_client.txt`](capture_client.txt) — scatto via `rpicam-still` / `libcamera-still`

In modalità energy-aware usare **`--oneshot`**.

Esempio manuale (dopo pyenv/venv configurati):

```bash
./capture_rpi.sh --oneshot
sudo systemctl poweroff
```

### 9.3 Unità systemd (esempio)

Adatta i path (`WorkingDirectory`, path dello script) alla macchina `rpi5-03`.

`/etc/systemd/system/insect-capture.service`:

```ini
[Unit]
Description=One-shot insect capture after wake, then halt
After=network-online.target
Wants=network-online.target

[Service]
Type=oneshot
User=rpi5-03
WorkingDirectory=/home/rpi5-03/tesi
Environment=PROJECT_DIR=/home/rpi5-03/tesi
# Opzionale: EnvironmentFile=-/home/rpi5-03/tesi/.env.systemd
ExecStart=/home/rpi5-03/tesi/capture_rpi.sh --oneshot
ExecStartPost=/bin/systemctl poweroff
RemainAfterExit=no

[Install]
WantedBy=multi-user.target
```

Abilitazione:

```bash
sudo systemctl daemon-reload
sudo systemctl enable insect-capture.service
```

Note:

- `ExecStartPost=... poweroff` spegne anche se vuoi distinguere fallimento cattura vs successo: in quel caso usa uno script wrapper che fa poweroff solo su exit 0, oppure un secondo oneshot `OnSuccess=`.
- Per sessioni di test lunghe, **disabilita** temporaneamente il servizio o commenta il `poweroff`.
- I moduli `backend.*` richiesti da `capture_client` devono essere presenti nel `WorkingDirectory` (oggi non sono ancora in questa repo — vedi README §5.2).

### 9.4 `.env.systemd` (opzionale)

Esempio nella root del progetto sul Pi:

```bash
CAPTURE_INTERVAL=30
# PYENV_VERSION=3.11.x
# PYENV_ROOT=/home/rpi5-03/.pyenv
```

Caricato automaticamente da `capture_rpi.sh` se il file esiste.

---

## 10. Directory dati per i sensori

Lo script sensori scrive il CSV qui (e il client foto scrive in `static/uploads/images/`):

```bash
mkdir -p ~/tesi/static/uploads/images ~/tesi/data
chmod 755 ~/tesi/data
```

---

## 11. Eseguire lo script sensori (oneshot)

Dalla root del repo:

```bash
cd ~/tesi
python3 sensors.py
# oppure, se usi un venv:
source ~/venv/bin/activate
python3 sensors.py
```

Legge tutti i sensori una volta, aggiunge una riga a `data/sensors.csv` ed esce. È progettato per essere chiamato da `capture_rpi.sh --oneshot` durante la finestra in cui il Pi è sveglio, seguito da `poweroff`.

---

## 12. Checklist rapida prima del primo esecuzione

- [ ] Sistema aggiornato e riavviato
- [ ] I2C, SPI, UART abilitati in `config.txt` / `raspi-config`
- [ ] Utente nei gruppi `i2c`, `dialout`, `gpio`
- [ ] Dipendenze Python installate
- [ ] `i2cdetect -y 1` mostra BME280 (`0x76` o `0x77`) se cablato
- [ ] `ls /dev/tty*` mostra il dispositivo seriale del GPS
- [ ] Test foto camera riuscito
- [ ] `~/tesi/data` esiste per l’output CSV
- [ ] `SENSORS` in `sensors.py` corrisponde al cablaggio reale (pin, indirizzo, porta)

---

## 13. Cosa non configurare qui

- Trasferimento foto dall’ESP via HTTP — **non previsto**
- Wake via GPIO3 “alla Pi 4” — **non applicabile** al Pi 5
- Deep sleep del kernel — **non supportato**