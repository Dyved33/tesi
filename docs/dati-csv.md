# Dati raccolti sul Pi

Tutto quello che il Pi raccoglie finisce in file CSV sotto `raspberry_pi/data/` (o nella cartella indicata da `SMARTCAM_DATA_DIR`). Abbiamo scelto il CSV invece di un database perché:

- ogni foto si porta dietro i suoi metadati in un file accanto, quindi copiare una cartella sul server basta a non perdere niente;
- si apre con pandas, R o LibreOffice senza esportare;
- se un file si rovina si perde quel file, non tutto l'archivio.

Il codice che scrive i file è `raspberry_pi/smartcam/storage.py`. Le intestazioni sono fisse e sono definite nei moduli (`BME280_HEADER` ed `EVENTS_HEADER` in `esp_link.py`, `SENSORS_HEADER` in `sensors.py`, `SIDECAR_HEADER` in `capture_client.py`). Se cambiamo le colonne e il file esiste già con l'intestazione vecchia, il programma lo rinomina in `<nome>.<data>.csv` e ne inizia uno nuovo.

## Struttura della cartella

```text
data/
├── bme280.csv                              tutte le misure del BME280 arrivate dall'ESP
├── camera_events.csv                       tutti i movimenti visti dalla camera dell'ESP
├── sensors.csv                             tutte le letture dei sensori del Pi
└── images/
    ├── 20261127T164953_811Z_cam0.jpg       foto
    └── 20261127T164953_811Z_cam0.csv       metadati di quella foto (una riga)
```

Il nome della foto è l'ora dello scatto in UTC con i millisecondi, più l'indice della camera. Due scatti nello stesso secondo non si sovrascrivono.

Convenzioni comuni a tutti i file:

- date e ore in ISO-8601 UTC con i millisecondi (`2026-11-27T16:49:53.811+00:00`);
- un valore mancante è un campo vuoto;
- i booleani sono `1` / `0`;
- separatore virgola, punto decimale, codifica UTF-8;
- tutti gli orari vengono dall'orologio del Pi. Le colonne `pi_clock_synced` (in `bme280.csv`, `camera_events.csv` e nel CSV della foto) e `sensors_clock_synced` (in `sensors.csv`) valgono 1 se l'orologio era sincronizzato con NTP, 0 se non lo era (l'ora viene dall'RTC e potrebbe essere sbagliata se manca la batteria), vuote se non si è potuto controllare.

## `bme280.csv`

Una riga per misura dell'ESP. Le righe arrivano a blocchi a ogni scambio con l'ESP; se una misura è arrivata corrotta e poi ritrasmessa può comparire più in basso di quelle successive, quindi per l'ordine temporale va usato `measured_at_utc`.

| Colonna | Significato |
|---|---|
| `esp_boot_id` | numero casuale scelto dall'ESP a ogni avvio |
| `seq` | numero progressivo della misura dentro quell'avvio. La coppia (`esp_boot_id`, `seq`) è unica |
| `measured_at_utc` | ora della misura, calcolata come `received_at_utc - age_ms` |
| `received_at_utc` | ora in cui il Pi ha ricevuto la riga |
| `age_ms` | quanti ms erano passati dalla misura all'invio |
| `pi_clock_synced` | orologio del Pi sincronizzato con NTP (vedi le convenzioni sopra) |
| `status` | `ok`, `sensore_assente`, `timeout`, `fuori_scala`, `senza_umidita` (BMP280) |
| `temperature_c` | °C |
| `humidity_pct` | umidità relativa, % |
| `pressure_hpa` | hPa |

Misure ed eventi condividono il contatore `seq`, quindi i buchi nella sequenza vanno cercati unendo `bme280.csv` e `camera_events.csv`. Un buco vuol dire record persi; un cambio di `esp_boot_id` vuol dire che l'ESP si è riavviato.

## `camera_events.csv`

Una riga per ogni movimento visto dalla OV3660 dell'ESP, anche quelli che non hanno acceso il Pi. Serve allo studio energetico: confrontando eventi, wake e foto si vede quante accensioni sono state evitate o sprecate.

| Colonna | Significato |
|---|---|
| `esp_boot_id`, `seq`, `measured_at_utc`, `received_at_utc`, `age_ms`, `pi_clock_synced` | come in `bme280.csv` |
| `woke_pi` | 1 se l'evento ha mandato l'impulso WAKE; 0 se il Pi era già acceso o l'ultimo wake era troppo recente |
| `changed_pct` | percentuale dei blocchi dell'immagine cambiati rispetto allo sfondo |
| `mean_diff` | differenza media di luminosità rispetto allo sfondo (0-255) |

## `sensors.csv`

Una riga per lettura dei sensori collegati al Pi (un "burst": i sensori vengono letti uno dopo l'altro).

| Colonna | Significato |
|---|---|
| `sensors_clock_synced` | orologio del Pi sincronizzato con NTP |
| `sensors_started_at_utc`, `sensors_finished_at_utc` | inizio e fine del burst |
| `gps_measured_at_utc` | ora in cui è arrivato il fix GPS; vuota se non c'era fix |
| `gps_latitude`, `gps_longitude` | gradi decimali, negativi a Sud e Ovest |
| `gps_altitude_m` | quota sul livello del mare |
| `gps_satellites` | satelliti usati |
| `gps_fix_quality` | campo GGA: 1 = GPS, 2 = DGPS, 4/5 = RTK |
| `gps_hdop` | diluizione orizzontale della precisione (più basso è meglio) |
| `water_present` | 1 se il sensore dell'acqua è bagnato |
| `soil_moisture_voltage` | tensione della sonda, V |
| `soil_moisture_percent` | percentuale calcolata con i due punti di calibrazione; vuota finché non li misuriamo (`python -m smartcam.sensors --calibra-suolo`) |
| `soil_wet` | solo con l'uscita digitale del modulo |
| `methane_voltage` | tensione di uscita del sensore MQ, V, già corretta per il partitore (i ppm richiedono la calibrazione) |
| `methane_alarm` | solo con l'uscita digitale del modulo |
| `sensors_ok` | sensori letti davvero |
| `sensors_dummy` | sensori disattivati in configurazione (`"dummy": True`) |
| `sensors_failed` | sensori andati in errore |
| `sensors_errors` | messaggio di errore di ognuno |

Un GPS senza fix sta in `sensors_ok` con le colonne vuote: il modulo ha risposto, è il cielo che non c'era.

## CSV accanto alla foto

Una sola riga, con intestazione. Contiene tutto quello che serve a usare la foto senza guardare gli altri file.

| Gruppo | Colonne | Note |
|---|---|---|
| foto | `image_file`, `captured_at_utc`, `pi_clock_synced`, `mode`, `pi_boot_id`, `camera_index`, `size_bytes`, `sha256` | `mode` è `selective` o `continuous`; `pi_boot_id` raggruppa i dati dello stesso avvio del Pi; `sha256` serve a controllare la copia sul server |
| scatto | `width`, `height`, `quality`, `zoom`, `roi`, `timeout_ms`, `af_mode`, `af_range`, `af_speed`, `af_window`, `af_on_capture`, `shutter_us`, `denoise`, `sharpness`, `contrast` | valori effettivamente passati a `rpicam-still` |
| BME280 | `bme_esp_boot_id`, `bme_seq`, `bme_measured_at_utc`, `bme_received_at_utc`, `bme_status`, `bme_temperature_c`, `bme_humidity_pct`, `bme_pressure_hpa` | l'ultima misura presente in `bme280.csv` al momento dello scatto; la riga completa si ritrova con (`bme_esp_boot_id`, `bme_seq`) |
| wake | `wake_esp_boot_id`, `wake_seq`, `wake_measured_at_utc`, `wake_changed_pct` | l'ultimo evento della camera che ha acceso il Pi: nell'app selettiva è quello che ha causato lo scatto |
| ESP | `esp_sync_at_utc`, `esp_received`, `esp_lost`, `esp_error` | esito dell'ultimo scambio con l'ESP |
| sensori del Pi | tutte le colonne di `sensors.csv` | l'ultima lettura dei sensori: nell'app selettiva è quella fatta subito dopo la foto, in quella continuativa la più recente |
| errori | `errors` | problemi dello scatto |

Le misure associate alla foto hanno sempre il loro orario, quindi si può controllare quanto sono "vecchie" rispetto a `captured_at_utc` e scartarle se serve.

## Cosa manca

- I risultati dell'analisi delle immagini (modello, versione, conteggi o aree) andranno in un altro CSV accanto alla foto quando avremo i modelli.
- Il trasferimento verso il server non c'è ancora. Il piano chiede di non cancellare gli originali prima che la copia sia verificata: lo `sha256` nel CSV della foto serve a questo.
- Per leggere tutti i CSV delle foto in un'unica tabella:

```python
import glob
import pandas as pd

foto = pd.concat(pd.read_csv(f) for f in sorted(glob.glob("data/images/*.csv")))
```
