# LEGACY — wake stile Pi 4 (GPIO3 + UART)

> **Non applicare al Raspberry Pi 5 né al piano operativo attuale.**
>
> Documento storico. Sul Pi 5 il wake usa **pad J2 + optoaccoppiatore** e la linea **ALIVE**;
> l'ESP decide il wake con **forecaster/decider** sui dati **BME280** (non con UART di evento come qui sotto).
>
> **Perché non si usa sul Pi 5:** sul Pi 4 il wake si faceva portando GPIO3 a massa; sul Pi 5 quel pin non ha questa funzione e l'accensione avviene tramite pad J2 o pulsante fisico. Inoltre il Pi 5 non supporta `WAKE_ON_GPIO=1`. Questo documento è solo un riferimento storico.
>
> Documentazione corrente:
> - Piano: [`plan.pdf`](../plan.pdf)
> - Panoramica: [README.md](../README.md)
> - ESP: [espconfig.md](espconfig.md)
> - Pi: [piconfig.md](piconfig.md)
> - Firmware: [`esp32/src/main.cpp`](../esp32/src/main.cpp)

---

## Contenuto originale (riferimento Pi 4)

### Come funzionava il risveglio (Pi 4)

Il Pi 4 in halt non esegue software: il risveglio è hardware quando **GPIO3** (pin 5) va a massa. La UART serve solo dopo il boot.

1. L’ESP rileva l’evento.
2. Porta GPIO3 del Pi a LOW per ~100–200 ms.
3. Il Pi si avvia (~20–30 s).
4. Poi comunicazione via UART.

I messaggi durante il boot vanno persi: l’ESP deve ritrasmettere fino a conferma.

### Firmware ESP (versione Pi 4)

Strumenti: Arduino IDE / PlatformIO, driver USB-seriale, eventuali librerie camera.

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
  if (eventoRilevato()) {
    wakePi();
    Serial2.println("EVENT");
  }
}
```

Rilasciare il pin (INPUT) dopo l’impulso; non tenerlo HIGH (pull-up 3,3 V sul Pi).

### Lato Raspberry (versione storica)

1. `raspi-config` → Serial: login shell No, hardware Sì → `/dev/serial0`.
2. EEPROM: su Pi 4 `WAKE_ON_GPIO=1` di default. Su Pi 5 questo path **non** vale.
3. Listener Python su UART + unità systemd (esempio storico omesso nei dettagli di deploy: non usare in produzione Pi 5).

### Verifiche (solo se si ripete un banco Pi 4)

- Wake manuale GPIO3→GND a Pi in halt.
- Loopback UART / `screen /dev/serial0 115200`.
- Attenzione: GPIO3 è anche SCL I2C1.
