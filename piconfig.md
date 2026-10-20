# Configurazione Raspberry Pi 5

Guida operativa per halt a basso consumo, linea ALIVE, cattura automatica al boot e ritorno in halt.  
Contesto generale: [README.md](README.md). Lato ESP: [espconfig.md](espconfig.md).

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

Riferimento utile sul consumo “vampire”: note di Jeff Geerling sul firmware del Pi 5.

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

## 5. Cattura al boot e ritorno in halt

Niente server HTTP: al boot il Pi esegue la cattura (Camera Module 3) e poi torna in halt.

### 5.1 Storage foto

Il client in repo salva in:

```
static/uploads/images/rpi_YYYYMMDD-HHMMSS.jpg
```

Assicurati che la working directory del servizio sia la root del progetto (dove esistono `capture_rpi.sh` e, a regime, il pacchetto `backend`).

### 5.2 Script

- [`capture_rpi.sh`](capture_rpi.sh) — attiva Python e lancia il client
- [`capture_client.txt`](capture_client.txt) — scatto via `rpicam-still` / `libcamera-still`

In modalità energy-aware usare **`--oneshot`**.

Esempio manuale (dopo pyenv/venv configurati):

```bash
./capture_rpi.sh --oneshot
sudo systemctl poweroff
```

### 5.3 Unità systemd (esempio)

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

### 5.4 `.env.systemd` (opzionale)

Esempio nella root del progetto sul Pi:

```bash
CAPTURE_INTERVAL=30
# PYENV_VERSION=3.11.x
# PYENV_ROOT=/home/rpi5-03/.pyenv
```

Caricato automaticamente da `capture_rpi.sh` se il file esiste.

---

## 6. Checklist rapida sul Pi

1. [ ] EEPROM: `POWER_OFF_ON_HALT=1`, `WAKE_ON_GPIO=0`
2. [ ] `config.txt`: `gpio=17=op,dh`
3. [ ] Verifica Camera Module 3 con `rpicam-still`
4. [ ] Ambiente Python + (quando pronti) moduli `backend.*`
5. [ ] Unità systemd oneshot → poweroff abilitata
6. [ ] Test: halt → impulso J2 / pulsante → boot → foto in `static/uploads/images/` → halt

---

## 7. Cosa non configurare qui

- Trasferimento foto dall’ESP via HTTP — **non previsto**
- Wake via GPIO3 “alla Pi 4” — **non applicabile** al Pi 5
- Deep sleep del kernel — **non supportato**
