/**
 * Firmware ESP32-S3: collegamento con Raspberry Pi 5 e lettura BME280.
 *
 * Scheda identificata dalla foto: variante ESP32-S3-CAM con modulo N16R8,
 * camera OV3660, due USB-C, slot SD e header a 40 pin. La camera è presente,
 * ma questo firmware per ora non la inizializza: non contiene un pinout DVP.
 *
 * Funzioni:
 * - comando seriale 'w': genera un impulso WAKE e attende il segnale ALIVE;
 * - legge il BME280 via I2C, riprovando l'inizializzazione se manca;
 * - invia le misure al Pi via UART quando ALIVE è alto.
 *
 * La serigrafia del PCB è V1695 / 127294G_Y1127_231016. I GPIO scelti sotto
 * evitano quelli riportati per la camera (GPIO 4–18) e la PSRAM octal
 * (GPIO 33–37); restano comunque da verificare sul cablaggio prima di alimentare.
 * WAKE deve pilotare un optoisolatore collegato a J2, mai i pad J2 direttamente.
 */

#include <Arduino.h>       // API Arduino: GPIO, millis(), delay(), Serial.
#include <Wire.h>          // Bus I2C usato per comunicare con il BME280.
#include <SparkFunBME280.h> // Driver SparkFun del sensore BME280.

// GPIO scelti per questa variante S3-CAM e visibili sugli header della foto.
// La camera occupa altri GPIO: non riutilizzare i pin 4–18 assegnati al DVP.
constexpr int PIN_WAKE = 42;     // Uscita verso optoisolatore e pulsante J2.
constexpr int PIN_ALIVE = 1;     // Ingresso dal segnale che indica Pi acceso.
constexpr int PIN_UART_TX = 2;   // Trasmissione UART ESP -> ricezione UART Pi.
constexpr int PIN_BME_SDA = 47;  // Linea dati I2C del BME280.
constexpr int PIN_BME_SCL = 21;  // Linea clock I2C del BME280.

// SDO a GND sul modulo imposta normalmente 0x76; SDO a 3V3 imposta 0x77.
constexpr uint8_t BME_ADDRESS = 0x77;

// Tempi della logica di wake e del collegamento dati. Le durate sono in ms.
constexpr uint32_t WAKE_PULSE_MS = 200;       // Durata dell'impulso sul PC817.
constexpr uint32_t ALIVE_WAIT_MS = 15000;     // Attesa massima dopo il wake.
constexpr uint32_t EVENT_COOLDOWN_MS = 30000; // Intervallo minimo tra wake.
constexpr uint32_t PI_BOOT_DELAY_MS = 60000;  // Attesa stimata per il boot Pi.
constexpr uint32_t BME_PERIOD_MS = 60000;     // Periodo delle misure inviate.
constexpr uint32_t BME_RETRY_MS = 10000;      // Intervallo tra tentativi I2C.
constexpr uint32_t UART_BAUD = 9600;          // Velocità della UART verso il Pi.

// Driver del sensore e porta UART hardware numero 2 dell'ESP32-S3.
static BME280 bme;
static HardwareSerial piUart(2);

// Stato corrente di inizializzazione del sensore e della UART verso il Pi.
static bool bmeReady = false;
static bool linkWasAlive = false;
static bool wakePending = false;
static bool wakeSent = false;

// Timestamp rispetto a millis(): servono a gestire le scadenze senza timer
// hardware. La sottrazione tra uint32_t gestisce anche il wrap di millis().
static uint32_t wakeAtMs = 0;
static uint32_t lastBmeMs = 0;
static uint32_t lastBmeAttemptMs = 0;
static uint32_t lastEventMs = 0;
static bool handledEvent = false;

/** Ritorna true quando l'ingresso ALIVE è a livello logico alto. */
bool piAlive() {
  return digitalRead(PIN_ALIVE) == HIGH;
}

/**
 * Diagnostica I2C: prova tutti gli indirizzi e stampa quelli che rispondono.
 * Per ogni dispositivo legge anche il registro 0xD0 (ID chip): 0x60 = BME280,
 * 0x56-0x58 = BMP280 (senza umidita', rifiutato dal driver SparkFun).
 * Restituisce il numero di dispositivi trovati.
 */
static int scanBus() {
  int found = 0;
  for (uint8_t a = 1; a < 127; a++) {
    Wire.beginTransmission(a);
    if (Wire.endTransmission() != 0) continue;
    found++;
    Serial.printf("  trovato dispositivo a 0x%02X", a);
    Wire.beginTransmission(a);
    Wire.write(0xD0);
    if (Wire.endTransmission(false) == 0 && Wire.requestFrom(a, (uint8_t)1) == 1) {
      Serial.printf(", ID chip 0x%02X", Wire.read());
    }
    Serial.println();
  }
  return found;
}

/** Scansiona il bus; se e' vuoto riprova con SDA e SCL scambiati. */
void scanI2c() {
  Serial.printf("Scansione I2C con SDA=%d SCL=%d\n", PIN_BME_SDA, PIN_BME_SCL);
  if (scanBus() > 0) return;

  Serial.println("  nessun dispositivo; provo con SDA e SCL invertiti");
  Wire.end();
  Wire.begin(PIN_BME_SCL, PIN_BME_SDA, 100000);
  if (scanBus() > 0) {
    Serial.println("  -> risponde a pin invertiti: scambia i due fili SDA/SCL");
  } else {
    Serial.println("  -> nulla anche invertendo: controlla 3V3, GND, saldature, pull-up");
  }
  // Ripristina la configurazione normale.
  Wire.end();
  Wire.begin(PIN_BME_SDA, PIN_BME_SCL, 100000);
}

/**
 * Inizializza il BME280 all'indirizzo I2C scelto. In caso di errore lascia
 * bmeReady falso; serviceBme() tenterà di nuovo dopo BME_RETRY_MS.
 */
void initBme() {
  lastBmeAttemptMs = millis();
  // SparkFun richiede di impostare l'indirizzo prima di beginI2C().
  bme.setI2CAddress(BME_ADDRESS);
  bmeReady = bme.beginI2C(Wire);
  if (bmeReady) {
    // In sleep il sensore resta inattivo finché measure() non richiede
    // esplicitamente una nuova acquisizione forced.
    bme.setMode(MODE_SLEEP);
    Serial.printf("BME280 pronto, indirizzo 0x%02X\n", BME_ADDRESS);
  } else {
    Serial.println("BME280 non trovato; nuovo tentativo tra 10 secondi");
  }
}

/**
 * Esegue una misura e riempie i tre valori di uscita: temperatura in °C,
 * umidità relativa in percentuale e pressione in hPa. Il driver fornisce la
 * pressione in Pa, quindi la conversione in hPa divide il valore per 100.
 * Restituisce false se il sensore non è pronto o i valori non sono validi.
 */
bool measure(float &temperature, float &humidity, float &pressure) {
  if (!bmeReady) return false;

  // Il driver SparkFun avvia una misura forzata impostando questa modalità.
  // Il BME280 torna poi automaticamente in sleep al termine dell'acquisizione.
  bme.setMode(MODE_FORCED);

  // Attende l'inizio della misura e poi la sua conclusione. I timeout evitano
  // di bloccare il firmware indefinitamente se il sensore o il bus non risponde.
  const uint32_t startedAt = millis();
  while (!bme.isMeasuring() && millis() - startedAt < 100) delay(1);
  if (!bme.isMeasuring()) return false;
  while (bme.isMeasuring() && millis() - startedAt < 1000) delay(1);
  if (bme.isMeasuring()) return false;

  temperature = bme.readTempC();
  humidity = bme.readFloatHumidity();
  pressure = bme.readFloatPressure() / 100.0f; // Pa -> hPa.

  // isfinite scarta NaN e infinito in caso di letture corrotte.
  return isfinite(temperature) && isfinite(humidity) && isfinite(pressure);
}

/**
 * Legge il sensore e invia una riga al Pi.
 * Formato: BME,uptime_ms,temperatura_C,umidita_percento,pressione_hPa
 * Stampa anche i valori sul monitor USB per facilitare il collaudo.
 */
void sendReading() {
  float temperature, humidity, pressure;
  if (!measure(temperature, humidity, pressure)) {
    Serial.println("Misura BME280 non riuscita");
    return;
  }

  // millis() è il tempo trascorso dall'avvio dell'ESP, non l'ora civile.
  piUart.printf("BME,%lu,%.2f,%.2f,%.2f\n",
                static_cast<unsigned long>(millis()), temperature, humidity,
                pressure);
  Serial.printf("BME %.2f C, %.2f%%, %.2f hPa\n", temperature, humidity,
                pressure);
  lastBmeMs = millis();
}

/** Riprova a inizializzare il sensore se non era disponibile all'avvio. */
void serviceBme() {
  const uint32_t now = millis();
  if (!bmeReady && now - lastBmeAttemptMs >= BME_RETRY_MS) {
    initBme();
  }
}

/**
 * Attiva per un breve impulso l'ingresso del circuito optoisolato che simula
 * la pressione del pulsante J2 del Raspberry Pi. Il GPIO ESP non deve mai
 * essere collegato direttamente ai pad J2.
 */
void pulseJ2() {
  digitalWrite(PIN_WAKE, HIGH);
  delay(WAKE_PULSE_MS);
  digitalWrite(PIN_WAKE, LOW);
}

/**
 * Controlla ALIVE fino al timeout, con pause da 100 ms tra i controlli.
 * Restituisce true appena ALIVE diventa HIGH, altrimenti false alla scadenza.
 */
bool waitForAlive(uint32_t timeoutMs) {
  const uint32_t start = millis();
  while (!piAlive() && millis() - start < timeoutMs) {
    delay(100);
  }
  return piAlive();
}

/**
 * Gestisce una richiesta di wake. Applica il cooldown, evita l'impulso se il
 * Pi risulta già acceso e attende ALIVE dopo l'impulso. Per ora viene chiamata
 * dal comando seriale 'w'; in futuro potrà essere richiamata da un rilevatore.
 */
void onEvent() {
  const uint32_t now = millis();
  if (handledEvent && now - lastEventMs < EVENT_COOLDOWN_MS) {
    Serial.println("Richiesta ignorata: cooldown attivo");
    return;
  }
  handledEvent = true;
  lastEventMs = now;

  if (piAlive()) {
    Serial.println("ALIVE alto: il Pi risulta gia' acceso");
    return;
  }

  Serial.println("Invio impulso WAKE al Pi");
  pulseJ2();
  if (waitForAlive(ALIVE_WAIT_MS)) {
    Serial.println("ALIVE alto: il Pi ha iniziato l'avvio");
  } else {
    Serial.println("Timeout in attesa di ALIVE");
  }
}

/**
 * Gestisce il collegamento UART in base al segnale ALIVE.
 * La UART viene aperta solo mentre il Pi è acceso, per evitare che il TX alto
 * alimenti il Pi spento attraverso il pin RX. Alla prima salita di ALIVE si
 * attende il boot; poi si manda una misura subito e una ogni minuto.
 */
void servicePiLink() {
  const bool alive = piAlive();

  // Fronte di salita: abilita UART e avvia il conto per la misura iniziale.
  if (alive && !linkWasAlive) {
    // RX=-1 disabilita la ricezione; il quarto argomento specifica il TX.
    piUart.begin(UART_BAUD, SERIAL_8N1, -1, PIN_UART_TX);
    wakePending = true;
    wakeSent = false;
    wakeAtMs = millis();
    Serial.println("Pi ALIVE; attendo il termine del boot prima della misura");
  }

  // Fronte di discesa: chiude UART e azzera lo stato della sessione corrente.
  if (!alive && linkWasAlive) {
    piUart.end();
    wakePending = false;
    wakeSent = false;
    Serial.println("Pi non piu' ALIVE; UART chiusa");
  }
  linkWasAlive = alive;

  // Invia la misura iniziale solo dopo il ritardo previsto per il boot Pi.
  if (alive && wakePending && millis() - wakeAtMs >= PI_BOOT_DELAY_MS) {
    wakePending = false;
    sendReading();
    wakeSent = true;
  }

  // Dopo la misura iniziale, mantiene l'invio periodico finché ALIVE resta alto.
  if (alive && wakeSent && millis() - lastBmeMs >= BME_PERIOD_MS) {
    sendReading();
  }
}

/** Imposta i GPIO, apre I2C e tenta la prima inizializzazione del BME280. */
void setup() {
  Serial.begin(115200); // Monitor seriale USB per log e comandi di prova.
  delay(500);           // Breve attesa per permettere al monitor di collegarsi.

  pinMode(PIN_WAKE, OUTPUT);
  digitalWrite(PIN_WAKE, LOW); // Stato inattivo: optoisolatore non attivato.
  pinMode(PIN_ALIVE, INPUT_PULLDOWN); // Stato di default basso se Pi spento.

  // Avvia I2C a 100 kHz sui pin indicati; su ESP32 si possono rimappare GPIO.
  Wire.begin(PIN_BME_SDA, PIN_BME_SCL, 100000);
  initBme();
  if (!bmeReady) scanI2c(); // Diagnostica: cosa vede il bus?

  Serial.printf("Pin ESP32-S3-CAM: WAKE=%d ALIVE=%d UART_TX=%d SDA=%d SCL=%d\n",
                PIN_WAKE, PIN_ALIVE, PIN_UART_TX, PIN_BME_SDA, PIN_BME_SCL);
}

/**
 * Ciclo principale: controlla sensore e collegamento al Pi, poi processa i
 * caratteri arrivati dal monitor seriale. 'w' richiede wake; 'r' legge il
 * BME280 e mostra la misura sul monitor USB (oltre a inviarla se UART è attiva).
 */
void loop() {
  serviceBme();
  servicePiLink();

  while (Serial.available()) {
    const char command = Serial.read();
    if (command == 'w' || command == 'W') onEvent();
    if (command == 'r' || command == 'R') sendReading();
    if (command == 'i' || command == 'I') scanI2c(); // Ripete la scansione I2C.
  }

  delay(200); // Riduce il busy loop e limita la frequenza dei controlli.
}
