# Awakening: ESP32 che risveglia un Raspberry Pi 5 in halt

Guida al software necessario sull'ESP32 e sul Raspberry Pi 5, collegati via cavo, per risvegliare il Pi dallo stato di halt.

## Come funziona il risveglio

Il Pi 5 in halt non esegue software, quindi non può ricevere dati via seriale. Il risveglio è un evento hardware: il Pi si riavvia quando il GPIO3 (pin fisico 5) viene portato a massa. La UART serve solo dopo il boot, per scambiare messaggi.

1. L'ESP32 rileva l'evento.
2. L'ESP32 porta GPIO3 del Pi a LOW per circa 100-200 ms.
3. Il Pi si avvia (circa 20-30 secondi) e parte il tuo servizio.
4. Da qui in poi la comunicazione avviene via UART.

I messaggi inviati dall'ESP32 durante il boot vanno persi. Se servono, l'ESP32 deve rimandarli finché non riceve una conferma dal Pi.

## Software sull'ESP32

### Strumenti

- Arduino IDE con il pacchetto "esp32 by Espressif", oppure PlatformIO. Sono la scelta più semplice.
- Driver USB-seriale (CP210x o CH340), a seconda della scheda.
- Libreria `esp_camera` (inclusa nel pacchetto esp32) se leggi la camera dell'ESP32-CAM.

### Firmware

Esempio in Arduino, adatta i pin alla tua scheda.

```cpp
const int WAKE_PIN = 14;      // collegato a GPIO3 del Pi
const int UART_RX  = 13;      // da TX del Pi (GPIO14)
const int UART_TX  = 15;      // verso RX del Pi (GPIO15)

void setup() {
  pinMode(WAKE_PIN, INPUT);   // alta impedenza: non pilota mai HIGH
  Serial2.begin(115200, SERIAL_8N1, UART_RX, UART_TX);
}

void wakePi() {
  pinMode(WAKE_PIN, OUTPUT);
  digitalWrite(WAKE_PIN, LOW);
  delay(200);
  pinMode(WAKE_PIN, INPUT);   // rilascia la linea
}

void loop() {
  if (eventoRilevato()) {     // la tua logica di detection
    wakePi();
    Serial2.println("EVENT");
    // attendi che il Pi sia pronto prima di inviare altro
  }
}
```

Il pin va rilasciato (INPUT) dopo l'impulso, mai tenuto a HIGH, perché sul Pi c'è già un pull-up verso 3,3 V.

Sull'ESP32-CAM molti pin sono occupati da camera e microSD. Se usi la scheda in modalità 1-bit, restano liberi alcuni GPIO tra 12, 13, 14 e 15. Serve il modello esatto della scheda per indicare i pin sicuri.

## Software sul Raspberry Pi 5

### 1. Abilitare la UART

```bash
sudo raspi-config
```

Interface Options, Serial Port: login shell su seriale NO, hardware seriale SÌ. Dopo il riavvio la porta è `/dev/serial0` (collegata a GPIO14/15).

### 2. Configurare l'EEPROM (opzionale)

```bash
sudo rpi-eeprom-config --edit
```

`WAKE_ON_GPIO=1` è già il valore predefinito, quindi il wake da GPIO3 funziona senza modifiche. `POWER_OFF_ON_HALT=1` serve solo se vuoi il minimo consumo in halt, perché spegne anche le porte USB. Non è un requisito per il wake.

### 3. Pacchetti

```bash
sudo apt install python3-serial
```

Se usi la Camera Module 3 sul Pi, serve anche `python3-picamera2`, già presente in Raspberry Pi OS Bookworm.

### 4. Servizio che ascolta l'ESP32

```python
# /home/pi/listener.py
import serial

with serial.Serial("/dev/serial0", 115200, timeout=1) as s:
    s.write(b"READY\n")                 # conferma all'ESP32 che il Pi è sveglio
    while True:
        line = s.readline().decode().strip()
        if line == "EVENT":
            print("Evento ricevuto")    # qui la tua logica
```

Per avviarlo automaticamente al boot, crea `/etc/systemd/system/listener.service`:

```ini
[Unit]
Description=Listener ESP32

[Service]
ExecStart=/usr/bin/python3 /home/pi/listener.py
Restart=always
User=pi

[Install]
WantedBy=multi-user.target
```

Poi attivalo con:

```bash
sudo systemctl enable --now listener.service
```

### 5. Tornare in halt

Quando il Pi ha finito, può spegnersi con `sudo shutdown -h now`, magari dopo aver mandato un messaggio all'ESP32 per segnalare che è di nuovo in halt.

## Verifiche consigliate

- Prima testa il wake da solo: collega manualmente GPIO3 a GND con un filo, con il Pi in halt, e controlla che si riavvii.
- Poi testa la UART con un loopback o con `screen /dev/serial0 115200`.
- Se usi I2C sul Pi, ricorda che GPIO3 è anche SCL (I2C1): evita di collegarci altri dispositivi.
