# Collegamento del BME280 all'ESP32

Per temperatura, umidità e pressione usiamo il modulo **GY-BME280**, una schedina che monta il sensore Bosch BME280 insieme a regolatore e resistenze di pull-up. Lo colleghiamo all'ESP32 in **I2C**, che richiede solo due fili di segnale.

## I pin del modulo

- **VCC**: alimentazione a 3,3 V.
- **GND**: massa.
- **SCL** (Serial CLock): il clock del bus I2C, generato dall'ESP32. Va sul **GPIO 15** della ESP32-CAM.
- **SDA** (Serial DAta): la linea dati, bidirezionale. Ci passano sia i comandi dell'ESP32 sia le misure del sensore. Va sul **GPIO 13** della ESP32-CAM.
- **CSB** (Chip Select): sceglie il protocollo. Se è alto il sensore lavora in I2C, se è basso in SPI. Sul modulo c'è già una resistenza di pull-up che lo tiene alto, quindi si può lasciare scollegato. Noi comunque lo colleghiamo a 3,3 V per essere sicuri.
- **SDO** (Serial Data Out): in I2C decide l'indirizzo del sensore sul bus. A massa l'indirizzo è `0x76`, a 3,3 V è `0x77`. Torna utile se un giorno volessimo due BME280 sullo stesso ESP32.

<div style="display: flex; justify-content: center;">
  <img src="output.png">
</div>

## Riepilogo dei collegamenti

| Modulo GY-BME280 | Pin ESP32 | A cosa serve |
| :--- | :--- | :--- |
| **VCC** | **3.3V** | alimentazione |
| **GND** | **GND** | massa comune |
| **SCL** | **GPIO 15** | clock I2C |
| **SDA** | **GPIO 13** | dati I2C |
| **CSB** | **3.3V** | forza la modalità I2C |
| **SDO** | **GND** | indirizzo I2C `0x76` |

## Da tenere a mente

- Lo schema KiCad e l'immagine qui sopra usano ancora GPIO 21 e 22, i pin I2C di default di un ESP32 "classico". Sulla **ESP32-CAM** che usiamo quei pin servono alla camera, quindi il BME280 va su GPIO 13 (SDA) e GPIO 15 (SCL), e lo schema va aggiornato. Le motivazioni sono nella [guida di configurazione](../../../docs/setup-risveglio.md#22-i-pin-disponibili).
- Anche il firmware (`firmware/esp32/src/main.cpp`) usa `0x76`.
- Il sensore andrà in una custodia stampata in 3D fuori dal box, quindi il cavo I2C sarà lungo. Va verificato che il bus funzioni bene con la lunghezza reale del cavo, ed eventualmente si abbassa la frequenza I2C.
- Nella cartella c'è anche il [datasheet del modulo](GY-BME280%20Breakout%20Board%203in1%20sensor%20for%20temperature%20humidity%20and%20air%20pressure-GY-BME280.pdf).
