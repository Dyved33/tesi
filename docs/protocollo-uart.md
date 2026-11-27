# Protocollo UART tra Pi ed ESP32

Le misure del BME280 e gli eventi della camera passano dall'ESP al Pi su una UART a 115200 baud (8N1), sui pin descritti in [pinout.md](pinout.md). Il codice è in `firmware/esp32/main/main.ino`, sezione 5 (ESP) e `raspberry_pi/smartcam/esp_link.py` (Pi).

## Perché così

Il piano chiede che le misure arrivino al Pi con il loro timestamp e che nessuna vada persa. I vincoli sono questi:

- il Pi è spento quasi sempre, mentre l'ESP misura ogni minuto;
- l'ESP non ha un orologio sincronizzato, conosce solo `millis()`;
- un byte corrotto non deve diventare una misura sbagliata nel dataset.

Per questo:

1. l'ESP tiene misure ed eventi (i "record") in un buffer circolare da 2880 posti, cioè 48 ore di misure, finché il Pi non conferma di averli salvati;
2. parla solo il Pi: l'ESP risponde ai comandi, così non manda niente mentre il Pi sta ancora facendo il boot;
3. ogni misura porta la sua età in millisecondi al momento dell'invio. Il Pi calcola l'ora della misura come `ora di ricezione - età`. L'errore è il tempo di trasmissione della riga (pochi ms) più l'errore dell'orologio del Pi;
4. ogni riga dell'ESP finisce con un checksum come le frasi NMEA del GPS;
5. un record è identificato da `(boot, seq)`: `boot` è un numero casuale scelto a ogni avvio dell'ESP, `seq` riparte da 1 a ogni avvio. Così se l'ESP si riavvia non si confondono record diversi con lo stesso `seq`.

La UART si apre solo con ALIVE alto. Quando il Pi è in halt l'ESP rimette il pin TX come ingresso, altrimenti la linea a riposo (alta) alimenterebbe il Pi attraverso RXD.

## Comandi

Le righe sono testo ASCII che termina con `\n`. I comandi del Pi non hanno checksum, le risposte dell'ESP sì (`*` seguito da due cifre esadecimali, XOR di tutti i caratteri prima dell'asterisco).

| Pi → ESP | ESP → Pi | Significato |
|---|---|---|
| `HELLO` | `INFO,<boot>,<uptime_ms>,<chip_id>,<indirizzo>,<in_buffer>,<persi>,<camera>*CS` | stato dell'ESP; `chip_id` 60 = BME280, 58 = BMP280, 00 = sensore non trovato; `persi` sono i record sovrascritti a buffer pieno; `camera` è 1 se la OV3660 funziona |
| `TIME,<epoch_s>` | `OK,TIME*CS` oppure `ERR,TIME*CS` | ora UNIX del Pi, che l'ESP userà per forecaster e decider. Se l'ora è prima del 2026 l'ESP la rifiuta |
| `GET` | una riga `M,...` per misura e una `E,...` per evento, poi `END,<n>*CS` | tutti i record nel buffer, dal più vecchio |
| `ACK,<seq>` | `OK,ACK,<rimasti>*CS` | il Pi ha salvato tutti i record fino a `seq`: l'ESP li toglie dal buffer |
| altro | `ERR,<comando>*CS` | comando sconosciuto |

Riga di misura:

```text
M,<boot>,<seq>,<eta_ms>,<esito>,<temperatura>,<umidita>,<pressione>*CS
M,3FA2C011,57,61042,0,18.43,71.20,1009.87*34
```

- `boot`: 8 cifre esadecimali;
- `eta_ms`: da quanti millisecondi è stata fatta la misura;
- `esito`: 0 ok, 1 sensore assente, 2 timeout della conversione, 3 valori fuori scala, 4 BMP280 (manca l'umidità);
- temperatura in °C, umidità in %, pressione in hPa, con due decimali. Un valore non disponibile è un campo vuoto.

Anche le misure fallite finiscono nel buffer con il loro esito: così sul Pi si vede quando il sensore non ha funzionato.

Riga di evento della camera:

```text
E,<boot>,<seq>,<eta_ms>,<wake>,<percento>,<differenza>*CS
E,3FA2C011,122,41200,1,8.85,23.40*37
```

- `wake`: 1 se l'evento ha mandato l'impulso WAKE, 0 se no (Pi già acceso o wake troppo ravvicinato);
- `percento`: percentuale dei blocchi dell'immagine cambiati rispetto allo sfondo;
- `differenza`: differenza media di luminosità rispetto allo sfondo, da 0 a 255.

Misure ed eventi usano lo stesso contatore `seq`, quindi un solo `ACK` li conferma tutti e due.

## Una sessione tipica

```text
Pi:  HELLO
ESP: INFO,3FA2C011,7260345,60,76,4,0,1*54
Pi:  TIME,1795776000
ESP: OK,TIME*3D
Pi:  GET
ESP: M,3FA2C011,119,180512,0,17.92,72.01,1009.90*34
ESP: M,3FA2C011,120,120511,0,17.95,71.88,1009.88*3B
ESP: M,3FA2C011,121,60510,0,18.01,71.60,1009.85*07
ESP: E,3FA2C011,122,41200,1,8.85,23.40*37
ESP: END,4*57
     (il Pi scrive le misure in bme280.csv e l'evento in camera_events.csv, poi fsync)
Pi:  ACK,122
ESP: OK,ACK,0*7D
```

## Cosa succede se qualcosa va storto

| Caso | Comportamento |
|---|---|
| il Pi si spegne prima dell'ACK | l'ESP tiene le misure e le rimanda al prossimo GET; il Pi scarta quelle già salvate guardando `(boot, seq)` in `bme280.csv` |
| una riga `M` arriva corrotta | il Pi la scarta e manda l'ACK solo fino alla misura prima di quella rovinata; le successive le salva lo stesso, e al giro dopo arriva anche quella mancante |
| l'ESP non risponde | `esp_link.sync()` restituisce l'errore, che finisce nella colonna `esp_error` del CSV della foto; le misure restano nell'ESP |
| il buffer si riempie (Pi spento per più di 48 ore) | si perde il record più vecchio e aumenta il contatore `persi` mandato con `INFO` |
| l'ESP si riavvia | il buffer in RAM si perde; il nuovo `boot` permette di vedere nel CSV dove c'è il buco |

## Prova a mano

Con il firmware compilato con `DIAGNOSTICA 1`, il comando `u` collega la UART del Pi al monitor USB. Sul Pi:

```bash
picocom -b 115200 /dev/ttyAMA0      # per uscire: Ctrl+A poi Ctrl+X
```

Anche senza ponte si può scrivere `HELLO` o `GET` direttamente in picocom e vedere le risposte. Oppure, dalla cartella `raspberry_pi/`:

```bash
.venv/bin/python -m smartcam.esp_link
```
