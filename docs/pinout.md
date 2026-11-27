# Mappa dei pin

In questo file ci sono tutti i collegamenti tra Raspberry Pi 5, ESP32-S3-CAM, BME280 e sensori del Pi. Quando cambiamo un pin nel codice va cambiato anche qui. I pin sono definiti in:

- `firmware/esp32/main/main.ino`, sezione 1 (ESP32: collegamento con il Pi, BME280 e camera)
- `raspberry_pi/smartcam/sensors.py` e `raspberry_pi/smartcam/config.py` (Pi)

Stato: il 27/11/2026 abbiamo provato WAKE (il Pi si accende con il comando `w`). Tutto il resto è ancora da provare al banco. Le righe con "da verificare" si basano su schede simili alla nostra e non su uno schema ufficiale.

Per i GPIO usiamo sempre il numero del GPIO (numerazione BCM sul Pi), non il numero del pin fisico. Il pin fisico lo scriviamo a parte.

## 1. Collegamenti filo per filo

### ESP32 ↔ Raspberry Pi

| Segnale | Da | Componenti in mezzo | A |
|---|---|---|---|
| WAKE | ESP GPIO42 | 330 Ω → PC817 pin 1 (anodo); PC817 pin 2 (catodo) → GND ESP | PC817 pin 4 (collettore) → pad J2 di segnale, PC817 pin 3 (emettitore) → pad J2 di massa |
| ALIVE | Pi GPIO17 (pin 11) | 1 kΩ in serie (contro il back-powering, vedi sotto); 10 kΩ verso GND lato ESP | ESP GPIO1 |
| UART Pi → ESP | Pi GPIO14 TXD (pin 8) | 1 kΩ in serie | ESP GPIO41 (RX) |
| UART ESP → Pi | ESP GPIO2 (TX) | 1 kΩ in serie | Pi GPIO15 RXD (pin 10) |
| Massa | Pi GND (pin 6) | | ESP GND |

Le resistenze in serie sulle linee di segnale limitano la corrente se una delle due schede è spenta e l'altra tiene il pin alto (back-powering): senza, la corrente passerebbe dai diodi di protezione del pin e alimenterebbe la scheda spenta. Vanno verificate con la prova 8 di [setup-risveglio.md](setup-risveglio.md#b-schede-collegate). L'ESP non va alimentato dal Pi: ha il suo alimentatore USB, perché deve restare acceso quando il Pi è in halt.

Quale dei due pad J2 è la massa va misurato con il multimetro a Pi spento.

### ESP32 ↔ BME280 (modulo GY-BME280)

| Pin del modulo | ESP32-S3-CAM | Note |
|---|---|---|
| VCC | 3V3 | il modulo va alimentato a 3,3 V |
| GND | GND | |
| SCL | GPIO21 | era GPIO48, spostato perché su queste schede il 48 pilota il LED RGB |
| SDA | GPIO47 | |
| CSB | 3V3 | alto = modalità I2C |
| SDO | GND | indirizzo 0x76 (a 3V3 diventa 0x77; il firmware prova entrambi) |

Il modulo ha già i pull-up da 10 kΩ su SDA e SCL. Con il cavo lungo verso la custodia esterna, se le letture sono instabili si può abbassare `I2C_FREQUENZA_HZ` in `main.ino`.

Attenzione: molti moduli venduti come "GY-BME280" montano in realtà un BMP280, che non misura l'umidità. Si riconosce dal chip ID (0x60 = BME280, 0x58 = BMP280): il firmware lo stampa all'avvio e lo manda al Pi.

### Raspberry Pi ↔ sensori

| Sensore | Pin del sensore | Raspberry Pi 5 | Note |
|---|---|---|---|
| GPS (UART2) | VCC | pin 1 (3V3) o pin 2 (5V) | dipende dal modulo |
| | GND | pin 9 | |
| | TX | GPIO5 RXD2 (pin 29) | |
| | RX | GPIO4 TXD2 (pin 7) | serve solo per configurare il modulo |
| MCP3008 (ADC su SPI0) | 16 VDD, 15 VREF | pin 17 (3V3) | VREF = 3,3 V, come `adc_vref` in `sensors.py` |
| | 14 AGND, 9 DGND | pin 20 (GND) | |
| | 13 CLK | GPIO11 SCLK (pin 23) | |
| | 12 DOUT | GPIO9 MISO (pin 21) | |
| | 11 DIN | GPIO10 MOSI (pin 19) | |
| | 10 CS | GPIO8 CE0 (pin 24) | |
| | 1 CH0 | uscita analogica del sensore di suolo | |
| | 2 CH1 | uscita analogica del sensore di metano | tramite partitore, vedi sotto |
| Umidità del suolo | VCC / GND / AOUT | 3V3 / GND / MCP3008 CH0 | alimentato a 3,3 V l'uscita non supera VREF |
| Metano (MQ-4) | VCC / GND / AO | 5V (pin 4) / GND (pin 14) / MCP3008 CH1 | il riscaldatore vuole 5 V e l'uscita arriva a 5 V: partitore prima del CH1, vedi sotto |
| Sensore acqua | contatto | GPIO27 (pin 13) e GND (pin 25) | pull-up interno, bagnato = livello basso |
| Suolo, uscita digitale (alternativa) | DO | GPIO22 (pin 15) | usata solo con `interface: "digital"` |
| Metano, uscita digitale (alternativa) | DO | GPIO23 (pin 16) | anche DO è a 5 V: stesso partitore |

Partitore del metano. L'MCP3008 con VREF a 3,3 V non deve vedere più di 3,3 V, mentre l'uscita del modulo MQ-4 arriva a 5 V:

```text
MQ-4 AO ──[10 kΩ]──┬──► MCP3008 CH1
                 [18 kΩ]
                    │
                   GND
```

Con 5 V in ingresso al CH1 arrivano 5 × 18 / (10 + 18) ≈ 3,21 V. `sensors.py` legge i valori delle due resistenze (`divider_r_top`, `divider_r_bottom`) e salva in `methane_voltage` la tensione vera del sensore, già moltiplicata per (10 + 18) / 18. Se si cambiano le resistenze vanno cambiati anche quei due valori. Prima di collegarlo va misurato (prova 17 in [setup-risveglio.md](setup-risveglio.md#c-sensori-del-pi)).

I modelli dei sensori di suolo, metano e acqua non sono ancora stati comprati: i pin sono quelli previsti, da confermare quando li avremo.

## 2. Raspberry Pi 5, header a 40 pin

| Funzione nel progetto | GPIO | Pin | Pin | GPIO | Funzione nel progetto |
|---|---|---:|---:|---|---|
| alimentazione MCP3008/GPS | 3V3 | 1 | 2 | 5V | (GPS se a 5 V) |
| libero (I2C1 SDA) | GPIO2 | 3 | 4 | 5V | metano MQ-4 |
| libero (I2C1 SCL) | GPIO3 | 5 | 6 | GND | massa comune con l'ESP |
| GPS RX (TXD2) | GPIO4 | 7 | 8 | GPIO14 | UART0 TXD → ESP GPIO41 |
| GPS GND | GND | 9 | 10 | GPIO15 | UART0 RXD ← ESP GPIO2 |
| ALIVE → ESP GPIO1 | GPIO17 | 11 | 12 | GPIO18 | libero |
| sensore acqua | GPIO27 | 13 | 14 | GND | metano GND |
| suolo DO (alternativa) | GPIO22 | 15 | 16 | GPIO23 | metano DO (alternativa) |
| MCP3008 VDD/VREF | 3V3 | 17 | 18 | GPIO24 | libero |
| MCP3008 DIN (MOSI) | GPIO10 | 19 | 20 | GND | MCP3008 AGND/DGND |
| MCP3008 DOUT (MISO) | GPIO9 | 21 | 22 | GPIO25 | libero |
| MCP3008 CLK (SCLK) | GPIO11 | 23 | 24 | GPIO8 | MCP3008 CS (CE0) |
| sensore acqua GND | GND | 25 | 26 | GPIO7 | libero (CE1, secondo ADC) |
| riservato (EEPROM HAT) | GPIO0 | 27 | 28 | GPIO1 | riservato (EEPROM HAT) |
| GPS TX (RXD2) | GPIO5 | 29 | 30 | GND | |
| libero | GPIO6 | 31 | 32 | GPIO12 | libero |
| libero | GPIO13 | 33 | 34 | GND | |
| libero | GPIO19 | 35 | 36 | GPIO16 | libero |
| libero | GPIO26 | 37 | 38 | GPIO20 | libero |
| | GND | 39 | 40 | GPIO21 | libero |

Altri connettori del Pi 5 che usiamo:

| Connettore | Uso |
|---|---|
| J2 (due pad vicino al connettore della batteria RTC) | pulsante di accensione, chiuso dal PC817 |
| BAT (J5) | batteria dell'RTC: senza, dopo un'interruzione di corrente l'ora è sbagliata finché non c'è rete |
| CAM/DISP 0 | Camera Module 3 (`--camera 0`) |
| CAM/DISP 1 | seconda camera, quando la sceglieremo (`--camera 1`) |
| USB-C | alimentazione 5 V / 5 A |

Righe da avere in `/boot/firmware/config.txt` (spiegate in `setup-risveglio.md`):

```ini
gpio=17=op,dh          # ALIVE alto appena possibile durante il boot
dtparam=uart0=on       # UART0 su GPIO14/15 -> /dev/ttyAMA0 (ESP32)
dtoverlay=uart2-pi5    # UART2 su GPIO4/5   -> /dev/ttyAMA2 (GPS)
dtparam=spi=on         # SPI0 per l'MCP3008
```

## 3. ESP32-S3-CAM

La scheda è una ESP32-S3-CAM generica con modulo ESP32-S3-N16R8, camera OV3660 collegata con il suo cavo flat, slot microSD e due USB-C (PCB `V1695` / `127294G_Y1127_231016`). Non abbiamo trovato uno schema ufficiale, quindi l'assegnazione della camera e della SD viene da schede simili (Freenove ESP32-S3 WROOM CAM e il modello `ESP32S3_EYE` di `camera_pins.h` nell'esempio CameraWebServer di Espressif). Il firmware usa questi pin per la camera: se all'avvio stampa "Camera non inizializzata", la prima cosa da controllare è questa tabella. La posizione di ogni GPIO sull'header va letta dalla serigrafia della scheda.

La Camera Module 3 del Pi non si può collegare qui: il suo cavo porta segnali MIPI CSI-2, che l'ESP32-S3 non ha.

| GPIO | Uso | Note |
|---|---|---|
| 0 | pulsante BOOT | strapping: basso all'avvio = modalità download |
| 1 | ALIVE (ingresso, pulldown) | dal Pi GPIO17 |
| 2 | UART1 TX | verso Pi GPIO15 |
| 3 | non usare | strapping (sorgente JTAG) |
| 4 | camera SIOD (SCCB SDA) | da verificare |
| 5 | camera SIOC (SCCB SCL) | da verificare |
| 6 | camera VSYNC | da verificare |
| 7 | camera HREF | da verificare |
| 8 | camera Y4 | da verificare |
| 9 | camera Y3 | da verificare |
| 10 | camera Y5 | da verificare |
| 11 | camera Y2 | da verificare |
| 12 | camera Y6 | da verificare |
| 13 | camera PCLK | da verificare |
| 14 | libero | candidato per un'altra periferica |
| 15 | camera XCLK | da verificare |
| 16 | camera Y9 | da verificare |
| 17 | camera Y8 | da verificare |
| 18 | camera Y7 | da verificare |
| 19, 20 | USB nativa D−, D+ | porta USB-C "USB" |
| 21 | I2C SCL (BME280) | |
| 35, 36, 37 | PSRAM octal | non usare: non sono neanche sull'header |
| 38, 39, 40 | slot microSD (CMD, CLK, D0) | da verificare; liberi se non usiamo la SD |
| 41 | UART1 RX | dal Pi GPIO14 |
| 42 | WAKE (uscita) | verso PC817 |
| 43, 44 | UART0 TX, RX | convertitore USB-seriale: monitor e caricamento firmware |
| 45 | non usare | strapping (tensione della flash) |
| 46 | non usare | strapping (log della ROM) |
| 47 | I2C SDA (BME280) | |
| 48 | LED RGB (WS2812) | da verificare; per questo SCL non è più qui |

Alimentazione: 5 V dalla USB-C "COM" (quella del convertitore USB-seriale), che usiamo anche per il monitor. Il 3V3 della scheda alimenta il BME280.

## 4. PC817

| Pin | Nome | Collegamento |
|---|---|---|
| 1 | anodo LED | ESP GPIO42 tramite 330 Ω |
| 2 | catodo LED | GND dell'ESP |
| 3 | emettitore | pad J2 di massa |
| 4 | collettore | pad J2 di segnale |

Con 330 Ω la corrente nel LED è circa (3,3 − 1,2) V / 330 Ω ≈ 6 mA. Lo schema KiCad in `hardware/pi5->esp32/` usa ancora un connettore ESP generico e non i GPIO di questa tabella: va aggiornato.
