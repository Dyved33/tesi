/**
 * Firmware di prova per ESP32-CAM (AI-Thinker): risveglio del Raspberry Pi 5.
 *
 * Cosa fa oggi:
 * - inizializza la camera della ESP32-CAM e a ogni giro acquisisce un frame,
 *   ma eventDetected() è ancora uno stub e restituisce sempre false: niente
 *   wake automatici;
 * - se dal monitor seriale si invia 'w', prova a svegliare il Pi;
 * - per svegliarlo dà un impulso su WAKE (GPIO14) e poi aspetta che il Pi
 *   alzi ALIVE (GPIO13).
 * Non c'è ancora niente di BME280, forecaster o decider: l'obiettivo finale
 * è un ESP sempre acceso che legge il BME280 e decide quando svegliare il Pi.
 *
 * Collegamenti (schema in hardware/pi5->esp32/ nella root del repository):
 *   WAKE:  GPIO14 -> resistenza 330 Ω -> LED dell'optoisolatore PC817; il
 *          transistor del PC817 chiude i due pad J2 del Pi, come se si
 *          premesse il pulsante di accensione.
 *   ALIVE: GPIO17 del Pi -> GPIO13 dell'ESP, con pulldown da 10 kΩ verso massa
 *          e massa in comune. HIGH = il GPIO17 del Pi è alto. Non distingue
 *          "acceso e operativo" da "in fase di spegnimento".
 *
 * Con POWER_OFF_ON_HALT=1 il Pi in halt spegne il suo 3,3 V: ESP e BME280
 * vanno quindi alimentati per conto loro. L'impulso è breve apposta, per
 * simulare un "click" sul pulsante e non una pressione prolungata.
 *
 * La camera della ESP32-CAM qui serve solo per un eventuale rilevamento
 * provvisorio: nessuna immagine viene inviata al Pi. Le foto "vere" le fanno
 * le fotocamere collegate al Raspberry.
 *
 * Provenienza:
 * - La logica WAKE/ALIVE (piAlive, pulseJ2, waitForAlive, ensurePiOn,
 *   onEvent, comando 'w') è scritta da noi.
 * - I #define dei pin della camera sono quelli del modello CAMERA_MODEL_AI_THINKER
 *   nel file camera_pins.h dell'esempio CameraWebServer di Espressif (Apache-2.0):
 *   https://github.com/espressif/arduino-esp32/blob/master/libraries/ESP32/examples/Camera/CameraWebServer/camera_pins.h
 * - Il riempimento di camera_config_t in initCamera() (assegnazione dei pin,
 *   xclk a 20 MHz, JPEG, scelta di frame_size/fb_count in base alla PSRAM,
 *   esp_camera_init) è adattato da CameraWebServer.ino dello stesso esempio:
 *   https://github.com/espressif/arduino-esp32/blob/master/libraries/ESP32/examples/Camera/CameraWebServer/CameraWebServer.ino
 * - L'uso di esp_camera_fb_get()/esp_camera_fb_return() segue il README del
 *   driver esp32-camera: https://github.com/espressif/esp32-camera
 * - Il confronto "millis() - t0 < timeout" per gestire il riavvolgimento di
 *   millis() è l'idioma standard Arduino (vedi l'esempio BlinkWithoutDelay:
 *   https://docs.arduino.cc/built-in-examples/digital/BlinkWithoutDelay/).
 */

#include <Arduino.h>
#include "esp_camera.h"

// Pin della camera integrata sulla ESP32-CAM AI-Thinker.
// Fonte: camera_pins.h dell'esempio CameraWebServer di Espressif (vedi sopra).
// Non vanno toccati: sono saldati sulla scheda.
#define PWDN_GPIO_NUM     32   // power-down della camera
#define RESET_GPIO_NUM    -1   // reset non collegato
#define XCLK_GPIO_NUM      0   // clock che l'ESP32 fornisce al sensore
#define SIOD_GPIO_NUM     26   // SIOD/SIOC: bus di configurazione (tipo I2C)
#define SIOC_GPIO_NUM     27
// Y2...Y9: gli 8 bit del bus parallelo su cui arrivano i pixel.
#define Y9_GPIO_NUM       35
#define Y8_GPIO_NUM       34
#define Y7_GPIO_NUM       39
#define Y6_GPIO_NUM       36
#define Y5_GPIO_NUM       21   // per questo GPIO21 non è libero per l'I2C del BME280
#define Y4_GPIO_NUM       19
#define Y3_GPIO_NUM       18
#define Y2_GPIO_NUM        5
// Sincronismi: inizio frame, inizio riga, clock dei pixel.
#define VSYNC_GPIO_NUM    25
#define HREF_GPIO_NUM     23
#define PCLK_GPIO_NUM     22

// Pin verso il Raspberry (vedi intestazione).
constexpr int PIN_WAKE = 14;
constexpr int PIN_ALIVE = 13;

// Durata dell'impulso su WAKE: simula un "click" breve sul pulsante.
constexpr uint32_t WAKE_PULSE_MS = 200;
// Quanto aspettare al massimo ALIVE alto dopo l'impulso.
constexpr uint32_t ALIVE_WAIT_MS = 15000;
// Tempo minimo tra due eventi gestiti, per non bombardare il Pi di impulsi.
constexpr uint32_t EVENT_COOLDOWN_MS = 30000;

// Quando abbiamo gestito l'ultimo evento. Il flag serve per accettare
// subito il primo evento dopo l'accensione, senza aspettare il cooldown.
static uint32_t lastEventMs = 0;
static bool hasHandledEvent = false;

// true se il GPIO17 del Pi è alto. Lettura secca, senza filtri o debounce.
bool piAlive() {
  return digitalRead(PIN_ALIVE) == HIGH;
}

// Impulso su WAKE: il PC817 chiude i pad J2 per WAKE_PULSE_MS millisecondi.
// GPIO14 non va mai collegato direttamente ai pad J2.
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

// Inizializza la camera. Adattato da CameraWebServer.ino di Espressif.
bool initCamera() {
  camera_config_t config;
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
  config.pin_sscb_sda = SIOD_GPIO_NUM;
  config.pin_sscb_scl = SIOC_GPIO_NUM;
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
  return true;
}

/**
 * Qui andrà il rilevamento (computer vision o una soglia).
 * Per ora prende un frame, non lo guarda e lo restituisce: sempre false.
 */
bool eventDetected() {
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

void setup() {
  // Seriale a 115200 baud per i log e per il comando 'w'.
  Serial.begin(115200);
  delay(500);
  Serial.println("ESP32-CAM wake node starting");

  // WAKE parte basso, così il PC817 non chiude J2 per sbaglio.
  pinMode(PIN_WAKE, OUTPUT);
  digitalWrite(PIN_WAKE, LOW);
  // ALIVE come ingresso con il pulldown interno, oltre a quello esterno da 10 kΩ:
  // se il filo è scollegato leggiamo LOW.
  pinMode(PIN_ALIVE, INPUT_PULLDOWN);

  // Senza camera ci fermiamo qui. Attenzione: in questo caso anche il
  // comando manuale 'w' smette di funzionare (vedi issues.md).
  if (!initCamera()) {
    Serial.println("Halting: camera required for event path");
    while (true) {
      delay(1000);
    }
  }

  Serial.printf("Pins: WAKE=%d ALIVE=%d | piAlive=%d\n", PIN_WAKE, PIN_ALIVE,
                piAlive() ? 1 : 0);
}

void loop() {
  // Percorso automatico: con lo stub attuale non scatta mai.
  if (eventDetected()) {
    onEvent();
  }

  // Prova manuale: aprire il monitor seriale (pio device monitor), scrivere
  // w e premere Invio. Leggiamo un carattere per giro; l'Invio viene ignorato.
  if (Serial.available()) {
    const char c = Serial.read();
    if (c == 'w' || c == 'W') {
      Serial.println("Manual wake request");
      onEvent();
    }
  }

  delay(200);
}
