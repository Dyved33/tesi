/**
 * Firmware della ESP32-CAM (pinout AI-Thinker): risveglio del Raspberry Pi 5
 * quando la camera vede un evento, risveglio manuale per le prove e misure
 * del BME280 da mandare al Pi.
 *
 * Cosa fa:
 * - a ogni giro acquisisce un frame dalla camera e chiede a eventDetected()
 *   se è successo qualcosa (ad esempio un insetto che passa davanti alla
 *   camera); se sì sveglia il Pi. Il rilevamento è ancora uno stub che
 *   restituisce sempre false: niente wake automatici;
 * - dal monitor seriale USB: 'w' sveglia il Pi a mano, 'r' fa una misura del
 *   BME280 e la stampa;
 * - per svegliare il Pi dà un impulso su WAKE e aspetta che il Pi alzi ALIVE;
 * - quando ALIVE sale (il Pi si sta accendendo, per qualsiasi motivo) fa
 *   subito una misura del BME280, aspetta PI_BOOT_DELAY_MS perché il Pi
 *   finisca il boot e gliela manda via UART. Poi, finché il Pi resta acceso,
 *   gli manda una misura ogni BME_PERIOD_MS.
 * Se la camera o il BME280 non partono, il resto del firmware continua a
 * funzionare.
 *
 * Collegamenti (tabella completa e motivazioni in docs/setup-risveglio.md).
 * La ESP32-CAM non va modificata: si usano solo pin già disponibili sui
 * connettori laterali, che vanno alla board di collegamento con il Pi.
 *   WAKE:   GPIO12 -> 330 Ω -> LED dell'optoisolatore PC817; il transistor
 *           del PC817 chiude i due pad J2 del Pi, come se si premesse il
 *           pulsante di accensione.
 *   ALIVE:  GPIO17 del Pi -> GPIO2 dell'ESP, con pulldown da 10 kΩ verso
 *           massa e massa in comune. HIGH = il GPIO17 del Pi è alto. Non
 *           distingue "acceso e operativo" da "in fase di spegnimento".
 *   UART:   GPIO14 dell'ESP (TX) -> 1 kΩ -> GPIO15 del Pi (RXD, pin 10).
 *           Solo in direzione ESP -> Pi: non avanzano pin per la RX.
 *   BME280: SDA -> GPIO13, SCL -> GPIO15, indirizzo 0x76.
 * Due di questi pin hanno vincoli all'avvio (pin di strapping):
 *   GPIO12 deve essere basso al reset, altrimenti l'ESP imposta la flash a
 *          1,8 V e non parte: per questo ci va WAKE, che il LED del PC817
 *          verso massa tiene basso;
 *   GPIO2  deve essere basso per caricare il firmware: con il Pi spento
 *          ALIVE è basso, quindi l'upload va fatto a Pi spento o con la
 *          board di collegamento staccata.
 * I pin usati sono quelli dello slot microSD: la microSD non va inserita.
 *
 * Con POWER_OFF_ON_HALT=1 il Pi in halt spegne il suo 3,3 V: l'ESP va quindi
 * alimentato per conto suo. Per lo stesso motivo la UART verso il Pi resta
 * chiusa (TX in alta impedenza) finché ALIVE è basso: una linea TX a riposo è
 * alta e alimenterebbe il Pi spento attraverso il suo RXD.
 *
 * Formato delle righe mandate al Pi (115200 8N1, terminate da '\n'):
 *   BME,<seq>,<tipo>,<age_ms>,<temp_C>,<rh_%>,<press_hPa>
 *   <seq>    cresce di 1 a ogni misura e riparte da 1 a ogni reset dell'ESP;
 *   <tipo>   W = misura fatta al risveglio del Pi, P = misura periodica;
 *   <age_ms> quanti millisecondi fa è stata fatta la misura. L'ESP non ha un
 *            orologio vero: il Pi ricava l'ora della misura come
 *            (ora di ricezione - age_ms).
 *
 * La camera della ESP32-CAM serve solo al rilevamento: nessuna immagine viene
 * inviata al Pi. Le foto "vere" le fanno le fotocamere collegate al Raspberry.
 *
 * Provenienza:
 * - La logica WAKE/ALIVE (piAlive, pulseJ2, waitForAlive, ensurePiOn,
 *   onEvent, comando 'w'), l'invio delle misure al Pi e la gestione della
 *   UART sono scritti da noi.
 * - I #define dei pin della camera sono quelli del modello CAMERA_MODEL_AI_THINKER
 *   nel file camera_pins.h dell'esempio CameraWebServer di Espressif (Apache-2.0):
 *   https://github.com/espressif/arduino-esp32/blob/master/libraries/ESP32/examples/Camera/CameraWebServer/camera_pins.h
 * - Il riempimento di camera_config_t in initCamera() (assegnazione dei pin,
 *   xclk a 20 MHz, JPEG, scelta di frame_size/fb_count in base alla PSRAM,
 *   esp_camera_init) è adattato da CameraWebServer.ino dello stesso esempio:
 *   https://github.com/espressif/arduino-esp32/blob/master/libraries/ESP32/examples/Camera/CameraWebServer/CameraWebServer.ino
 * - L'uso di esp_camera_fb_get()/esp_camera_fb_return() e di sccb_i2c_port
 *   seguono il README e esp_camera.h del driver esp32-camera:
 *   https://github.com/espressif/esp32-camera
 * - L'inizializzazione del BME280 e la misura in forced mode (beginI2C,
 *   setMode(MODE_FORCED), attesa di isMeasuring(), lettura) seguono gli
 *   esempi Example2_I2CAddress e Example6_LowPower della libreria SparkFun
 *   BME280 (licenza MIT): https://github.com/sparkfun/SparkFun_BME280_Arduino_Library
 *   Rispetto all'esempio abbiamo aggiunto un timeout all'attesa. Oversampling
 *   x1 e filtro spento sono la configurazione consigliata dal datasheet Bosch
 *   per il monitoraggio meteo (sezione 3.5.1).
 *   Non usiamo la libreria Adafruit BME280 perché la sua dipendenza
 *   Adafruit Unified Sensor definisce un tipo sensor_t che va in conflitto
 *   con quello del driver della camera (il firmware non compila).
 * - Serial2.begin(baud, config, rx, tx) per scegliere i pin della UART è
 *   l'API di HardwareSerial di arduino-esp32; rx = -1 vuol dire "nessun pin
 *   RX": https://github.com/espressif/arduino-esp32/blob/master/cores/esp32/HardwareSerial.cpp
 * - Il confronto "millis() - t0 < timeout" per gestire il riavvolgimento di
 *   millis() è l'idioma standard Arduino (vedi l'esempio BlinkWithoutDelay:
 *   https://docs.arduino.cc/built-in-examples/digital/BlinkWithoutDelay/).
 */

#include <Arduino.h>
#include <Wire.h>
#include <SparkFunBME280.h>
#include "esp_camera.h"

// Pin della camera integrata sulla ESP32-CAM AI-Thinker.
// Fonte: camera_pins.h dell'esempio CameraWebServer di Espressif (vedi sopra).
// Non vanno toccati: sono saldati sulla scheda.
#define PWDN_GPIO_NUM     32   // power-down della camera
#define RESET_GPIO_NUM    -1   // reset non collegato
#define XCLK_GPIO_NUM      0   // clock che l'ESP32 fornisce al sensore
#define SIOD_GPIO_NUM     26   // SIOD/SIOC: bus I2C di configurazione
#define SIOC_GPIO_NUM     27   // della camera
// Y2...Y9: gli 8 bit del bus parallelo su cui arrivano i pixel.
#define Y9_GPIO_NUM       35
#define Y8_GPIO_NUM       34
#define Y7_GPIO_NUM       39
#define Y6_GPIO_NUM       36
#define Y5_GPIO_NUM       21
#define Y4_GPIO_NUM       19
#define Y3_GPIO_NUM       18
#define Y2_GPIO_NUM        5
// Sincronismi: inizio frame, inizio riga, clock dei pixel.
#define VSYNC_GPIO_NUM    25
#define HREF_GPIO_NUM     23
#define PCLK_GPIO_NUM     22

// Pin verso la board di collegamento con il Raspberry (vedi intestazione).
constexpr int PIN_WAKE = 12;
constexpr int PIN_ALIVE = 2;
constexpr int PIN_PI_TX = 14;  // TX dell'ESP -> RXD del Pi (GPIO15)

// Bus I2C del BME280 (Wire, porta I2C 0). La camera usa l'altra porta
// I2C dell'ESP32 (la 1) sui suoi pin SIOD/SIOC.
constexpr int PIN_I2C_SDA = 13;
constexpr int PIN_I2C_SCL = 15;
constexpr int CAMERA_I2C_PORT = 1;
// 0x76 con SDO a massa, come nel nostro schema (0x77 con SDO a 3,3 V).
constexpr uint8_t BME_ADDRESS = 0x76;
// 100 kHz è la velocità standard dell'I2C. Con il cavo lungo verso la
// custodia esterna, se le letture falliscono, provare ad abbassarla.
constexpr uint32_t I2C_FREQ_HZ = 100000;
// Se il BME280 non risponde, ogni quanto riprovare a inizializzarlo.
constexpr uint32_t BME_RETRY_MS = 10000;
// Con oversampling x1 una misura dura meno di 10 ms (datasheet Bosch,
// appendice B): se dopo 100 ms non ha finito, il sensore non risponde.
constexpr uint32_t BME_MEASURE_TIMEOUT_MS = 100;

constexpr uint32_t PI_UART_BAUD = 115200;
// Dopo che ALIVE sale, quanto aspettare prima di mandare la misura del
// risveglio: il programma sul Pi che la riceve deve essere già partito.
// Va tarato sul tempo di boot reale del Pi.
constexpr uint32_t PI_BOOT_DELAY_MS = 60000;
// Con il Pi acceso, una misura al minuto (come propone il piano).
// 0 = mandare solo la misura del risveglio.
constexpr uint32_t BME_PERIOD_MS = 60000;

// Durata dell'impulso su WAKE: simula un "click" breve sul pulsante.
constexpr uint32_t WAKE_PULSE_MS = 200;
// Quanto aspettare al massimo ALIVE alto dopo l'impulso.
constexpr uint32_t ALIVE_WAIT_MS = 15000;
// Tempo minimo tra due eventi gestiti, per non bombardare il Pi di impulsi.
constexpr uint32_t EVENT_COOLDOWN_MS = 30000;

// Una misura del BME280. ms è il millis() del momento della misura.
struct Reading {
  uint32_t seq;
  uint32_t ms;
  float temperature;  // °C
  float humidity;     // % UR
  float pressure;     // hPa
};

static bool cameraReady = false;

static BME280 bme;
static bool bmeReady = false;
static uint32_t lastBmeInitMs = 0;
static bool hasBmeInitAttempt = false;
static uint32_t nextSeq = 1;

// Stato del collegamento con il Pi (vedi servicePiLink()).
static HardwareSerial& piSerial = Serial2;
static bool piLinkOpen = false;
static uint32_t aliveSinceMs = 0;      // quando ALIVE è salito
static bool wakeReadingValid = false;  // abbiamo la misura del risveglio
static bool wakeReadingSent = false;   // l'abbiamo già mandata
static Reading wakeReading;
static uint32_t lastPeriodicMs = 0;

// Quando abbiamo gestito l'ultimo evento. Il flag serve per accettare
// subito il primo evento dopo l'accensione, senza aspettare il cooldown.
static uint32_t lastEventMs = 0;
static bool hasHandledEvent = false;

// ---------------------------------------------------------------------------
// Risveglio del Pi (WAKE / ALIVE)
// ---------------------------------------------------------------------------

// true se il GPIO17 del Pi è alto. Lettura secca, senza filtri o debounce.
bool piAlive() {
  return digitalRead(PIN_ALIVE) == HIGH;
}

// Impulso su WAKE: il PC817 chiude i pad J2 per WAKE_PULSE_MS millisecondi.
// GPIO12 non va mai collegato direttamente ai pad J2.
void pulseJ2() {
  digitalWrite(PIN_WAKE, HIGH);
  delay(WAKE_PULSE_MS);
  digitalWrite(PIN_WAKE, LOW);
}

// Controlla ALIVE ogni 250 ms finché non va alto o scade il tempo.
// La sottrazione tra unsigned funziona anche quando millis() riparte da zero
// (circa ogni 49 giorni).
bool waitForAlive(uint32_t timeoutMs) {
  const uint32_t t0 = millis();
  while (millis() - t0 < timeoutMs) {
    if (piAlive()) {
      // ALIVE alto vuol dire solo che il GPIO17 è alto, non che Linux abbia
      // finito il boot o che il Pi sia raggiungibile.
      return true;
    }
    delay(250);
  }
  return false;
}

/**
 * Accende il Pi se serve.
 * Se ALIVE è già alto non manda l'impulso (il Pi è acceso, o si sta
 * spegnendo: non possiamo distinguerlo). Altrimenti manda l'impulso e
 * aspetta ALIVE. Restituisce true se alla fine ALIVE è alto.
 */
bool ensurePiOn() {
  if (piAlive()) {
    Serial.println("ALIVE HIGH: Pi already on (or shutting down) — skip WAKE");
    return true;
  }

  Serial.println("ALIVE LOW: pulsing J2 WAKE");
  pulseJ2();

  if (!waitForAlive(ALIVE_WAIT_MS)) {
    Serial.println("Timeout waiting for ALIVE after WAKE");
    return false;
  }

  Serial.println("ALIVE HIGH: Pi booting");
  return true;
}

// Gestisce un evento (automatico o manuale) rispettando il cooldown.
void onEvent() {
  const uint32_t now = millis();  // millisecondi dall'accensione dell'ESP
  if (hasHandledEvent && now - lastEventMs < EVENT_COOLDOWN_MS) {
    Serial.println("Event ignored (cooldown)");
    return;
  }
  // Il cooldown parte da adesso, anche se poi il wake non riesce.
  lastEventMs = now;
  hasHandledEvent = true;

  Serial.println("Event: ensuring Pi is on");
  if (!ensurePiOn()) {
    Serial.println("Event: wake failed");
  }
}

// ---------------------------------------------------------------------------
// Camera e rilevamento
// ---------------------------------------------------------------------------

// Inizializza la camera. Adattato da CameraWebServer.ino di Espressif.
bool initCamera() {
  // = {} azzera i campi che non assegniamo (issues.md #24).
  camera_config_t config = {};
  // Canale e timer LEDC: il driver li usa per generare il clock XCLK.
  config.ledc_channel = LEDC_CHANNEL_0;
  config.ledc_timer = LEDC_TIMER_0;
  // Collegamento dei pin definiti sopra (d0 = Y2, ..., d7 = Y9).
  config.pin_d0 = Y2_GPIO_NUM;
  config.pin_d1 = Y3_GPIO_NUM;
  config.pin_d2 = Y4_GPIO_NUM;
  config.pin_d3 = Y5_GPIO_NUM;
  config.pin_d4 = Y6_GPIO_NUM;
  config.pin_d5 = Y7_GPIO_NUM;
  config.pin_d6 = Y8_GPIO_NUM;
  config.pin_d7 = Y9_GPIO_NUM;
  config.pin_xclk = XCLK_GPIO_NUM;
  config.pin_pclk = PCLK_GPIO_NUM;
  config.pin_vsync = VSYNC_GPIO_NUM;
  config.pin_href = HREF_GPIO_NUM;
  config.pin_sccb_sda = SIOD_GPIO_NUM;
  config.pin_sccb_scl = SIOC_GPIO_NUM;
  // La porta I2C 0 è già di Wire (BME280): la camera usa la 1.
  config.sccb_i2c_port = CAMERA_I2C_PORT;
  config.pin_pwdn = PWDN_GPIO_NUM;
  config.pin_reset = RESET_GPIO_NUM;
  config.xclk_freq_hz = 20000000;  // 20 MHz, il valore dell'esempio Espressif
  config.pixel_format = PIXFORMAT_JPEG;
  // Impostazioni prudenti di partenza: QVGA (320x240), un solo buffer.
  // jpeg_quality va da 0 a 63: più è basso, migliore è la qualità.
  config.frame_size = FRAMESIZE_QVGA;
  config.jpeg_quality = 12;
  config.fb_count = 1;
  // Se i frame arrivano più in fretta di quanto li usiamo, teniamo sempre
  // l'ultimo invece di accumulare quelli vecchi.
  config.grab_mode = CAMERA_GRAB_LATEST;

  // La AI-Thinker di solito ha 4 MB di PSRAM (RAM esterna): se c'è, possiamo
  // permetterci una risoluzione più alta (SVGA, 800x600) e due buffer.
  if (psramFound()) {
    config.frame_size = FRAMESIZE_SVGA;
    config.jpeg_quality = 10;
    config.fb_count = 2;
    config.fb_location = CAMERA_FB_IN_PSRAM;
  } else {
    config.fb_location = CAMERA_FB_IN_DRAM;
  }

  esp_err_t err = esp_camera_init(&config);
  if (err != ESP_OK) {
    Serial.printf("Camera init failed: 0x%x\n", err);
    return false;
  }
  Serial.println("Camera ready");
  return true;
}

/**
 * Qui andrà il rilevamento: deve restituire true quando nel frame c'è
 * qualcosa per cui vale la pena svegliare il Pi (ad esempio un insetto che
 * passa davanti alla camera).
 * Per ora prende un frame, non lo guarda e lo restituisce: sempre false.
 */
bool eventDetected() {
  if (!cameraReady) {
    return false;
  }
  // fb = frame buffer: contiene i byte JPEG (fb->buf), la dimensione e altri dati.
  camera_fb_t* fb = esp_camera_fb_get();
  if (!fb) {
    Serial.println("eventDetected: capture failed");
    return false;
  }

  // Segnaposto: nessun algoritmo legge ancora fb->buf.
  const bool hit = false;

  // Il buffer va SEMPRE restituito al driver, altrimenti dopo pochi frame
  // la camera resta senza memoria.
  esp_camera_fb_return(fb);
  return hit;
}

// ---------------------------------------------------------------------------
// BME280
// ---------------------------------------------------------------------------

// Inizializza il BME280 e lo lascia in sleep: in forced mode il sensore fa
// una misura solo quando glielo chiediamo e poi torna in sleep da solo
// (consuma meno e si scalda meno). Adattato dagli esempi SparkFun (vedi
// intestazione).
bool initBme() {
  bme.setI2CAddress(BME_ADDRESS);
  // Restituisce false se all'indirizzo non risponde un BME280/BMP280.
  if (!bme.beginI2C(Wire)) {
    Serial.printf("BME280 not found at 0x%02X\n", BME_ADDRESS);
    return false;
  }
  bme.setTempOverSample(1);
  bme.setPressureOverSample(1);
  bme.setHumidityOverSample(1);
  bme.setFilter(0);  // filtro spento
  bme.setMode(MODE_SLEEP);
  Serial.printf("BME280 ready at 0x%02X\n", BME_ADDRESS);
  return true;
}

// Da chiamare a ogni giro di loop(): se il BME280 non è pronto prova a
// inizializzarlo, al massimo una volta ogni BME_RETRY_MS.
void serviceBme() {
  if (bmeReady) {
    return;
  }
  const uint32_t now = millis();
  if (hasBmeInitAttempt && now - lastBmeInitMs < BME_RETRY_MS) {
    return;
  }
  hasBmeInitAttempt = true;
  lastBmeInitMs = now;
  bmeReady = initBme();
}

// Chiede una misura in forced mode e aspetta che finisca. Restituisce false
// se il sensore non finisce entro BME_MEASURE_TIMEOUT_MS (ad esempio perché
// il cavo si è staccato: in quel caso il bit "measuring" si legge sempre a 1).
bool takeForcedMeasurement() {
  bme.setMode(MODE_FORCED);
  const uint32_t t0 = millis();
  delay(2);  // lasciamo al sensore il tempo di iniziare la misura
  while (bme.isMeasuring()) {
    if (millis() - t0 >= BME_MEASURE_TIMEOUT_MS) {
      return false;
    }
    delay(1);
  }
  return true;
}

/**
 * Fa una misura e la scrive sul monitor USB. Se la misura fallisce segna il
 * sensore come non pronto, così serviceBme() riprova a inizializzarlo.
 */
bool measure(Reading& out) {
  if (!bmeReady) {
    return false;
  }
  if (!takeForcedMeasurement()) {
    Serial.println("BME280: measurement timeout");
    bmeReady = false;
    return false;
  }
  const float t = bme.readTempC();
  const float rh = bme.readFloatHumidity();
  const float p = bme.readFloatPressure() / 100.0f;  // Pa -> hPa
  if (isnan(t) || isnan(rh) || isnan(p)) {
    Serial.println("BME280: invalid reading");
    bmeReady = false;
    return false;
  }

  out = {nextSeq++, millis(), t, rh, p};
  Serial.printf("BME280 #%lu: %.2f C  %.2f %%  %.2f hPa\n",
                (unsigned long)out.seq, t, rh, p);
  return true;
}

// ---------------------------------------------------------------------------
// UART verso il Pi
// ---------------------------------------------------------------------------

// Manda una misura al Pi nel formato BME,... (vedi intestazione).
void sendReading(const Reading& r, char kind) {
  piSerial.printf("BME,%lu,%c,%lu,%.2f,%.2f,%.2f\n", (unsigned long)r.seq,
                  kind, (unsigned long)(millis() - r.ms), r.temperature,
                  r.humidity, r.pressure);
  Serial.printf("Sent to Pi: reading #%lu (%c)\n", (unsigned long)r.seq, kind);
}

/**
 * Da chiamare a ogni giro di loop(). Segue ALIVE:
 * - quando sale apre la UART e fa subito la misura del risveglio;
 * - passati PI_BOOT_DELAY_MS la manda al Pi, poi manda una misura ogni
 *   BME_PERIOD_MS;
 * - quando scende chiude la UART e lascia il pin TX come ingresso, così non
 *   porta tensione al Pi spento.
 */
void servicePiLink() {
  const bool alive = piAlive();
  const uint32_t now = millis();

  if (alive && !piLinkOpen) {
    // rx = -1: nessun pin di ricezione, la UART va solo verso il Pi.
    piSerial.begin(PI_UART_BAUD, SERIAL_8N1, -1, PIN_PI_TX);
    piLinkOpen = true;
    aliveSinceMs = now;
    wakeReadingSent = false;
    wakeReadingValid = measure(wakeReading);
    Serial.println("Pi UART open: wake reading taken");
    return;
  }
  if (!alive && piLinkOpen) {
    piSerial.end();
    pinMode(PIN_PI_TX, INPUT);
    piLinkOpen = false;
    Serial.println("Pi UART closed");
    return;
  }
  if (!piLinkOpen || now - aliveSinceMs < PI_BOOT_DELAY_MS) {
    return;
  }

  if (!wakeReadingSent) {
    // Se al risveglio il BME280 non rispondeva, riproviamo adesso.
    if (!wakeReadingValid) {
      wakeReadingValid = measure(wakeReading);
    }
    if (wakeReadingValid) {
      sendReading(wakeReading, 'W');
    }
    wakeReadingSent = true;
    lastPeriodicMs = now;
    return;
  }

  if (BME_PERIOD_MS > 0 && now - lastPeriodicMs >= BME_PERIOD_MS) {
    lastPeriodicMs = now;
    Reading r;
    if (measure(r)) {
      sendReading(r, 'P');
    }
  }
}

// ---------------------------------------------------------------------------

void setup() {
  // Seriale USB a 115200 baud per i log e per i comandi 'w' e 'r'.
  Serial.begin(115200);
  delay(500);
  Serial.println("ESP32-CAM wake node starting");

  // WAKE parte basso, così il PC817 non chiude J2 per sbaglio.
  pinMode(PIN_WAKE, OUTPUT);
  digitalWrite(PIN_WAKE, LOW);
  // ALIVE come ingresso con il pulldown interno, oltre a quello esterno da 10 kΩ:
  // se il filo è scollegato leggiamo LOW.
  pinMode(PIN_ALIVE, INPUT_PULLDOWN);
  // UART verso il Pi chiusa finché ALIVE non sale.
  pinMode(PIN_PI_TX, INPUT);

  // Bus I2C del BME280.
  Wire.begin(PIN_I2C_SDA, PIN_I2C_SCL, I2C_FREQ_HZ);

  // Senza camera niente wake automatici, ma BME280, UART e comando 'w'
  // continuano a funzionare.
  cameraReady = initCamera();
  if (!cameraReady) {
    Serial.println("Camera not available: automatic wake disabled");
  }

  Serial.printf("Pins: WAKE=%d ALIVE=%d UART TX=%d I2C SDA=%d SCL=%d | piAlive=%d\n",
                PIN_WAKE, PIN_ALIVE, PIN_PI_TX, PIN_I2C_SDA, PIN_I2C_SCL,
                piAlive() ? 1 : 0);
}

void loop() {
  serviceBme();
  servicePiLink();

  // Percorso automatico: con lo stub attuale non scatta mai.
  if (eventDetected()) {
    onEvent();
  }

  // Prove manuali: aprire il monitor seriale (pio device monitor), scrivere
  // w (wake) oppure r (misura del BME280) e premere Invio. Leggiamo un
  // carattere per giro; l'Invio viene ignorato.
  if (Serial.available()) {
    const char c = Serial.read();
    if (c == 'w' || c == 'W') {
      Serial.println("Manual wake request");
      onEvent();
    } else if (c == 'r' || c == 'R') {
      Reading r;
      if (!measure(r)) {
        Serial.println("BME280 not ready");
      }
    }
  }

  delay(200);
}
