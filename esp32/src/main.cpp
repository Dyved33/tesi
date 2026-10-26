/**
 * ESP32-CAM (AI-Thinker): rilevazione evento + wake Raspberry Pi 5.
 *
 * SCELTA DEFINITIVA: J2 pads + optocoupler (PC817) + ALIVE line
 * ============================================================
 *
 * CABLAGGIO WAKE (ESP → Pi):
 *   ESP GPIO14 (PIN_WAKE) ──[330Ω]──►| PC817 LED anode
 *                              PC817 LED cathode ──► GND (ESP)
 *                              PC817 transistor: emitter → J2 pad GND, collector → J2 pad signal
 *   Impulso: HIGH per 200ms → optocoupler chiude J2 → Pi si riavvia
 *   MAI tenere HIGH >1s (hard off sul Pi)
 *
 * CABLAGGIO ALIVE (Pi → ESP):
 *   Pi GPIO17 (config.txt: gpio=17=op,dh) ──► ESP GPIO13 (PIN_ALIVE)
 *   Pulldown 10kΩ su GPIO13 verso GND (lato ESP)
 *   GND COMUNE tra Pi ed ESP (necessario per ALIVE)
 *   ALIVE HIGH = Pi acceso (rail 3.3V su)
 *   ALIVE LOW  = Pi in halt (rail 3.3V spento con POWER_OFF_ON_HALT=1)
 *
 * ALIMENTAZIONE ESP:
 *   Con POWER_OFF_ON_HALT=1, il rail 3.3V del Pi si spegne in halt.
 *   Il pin 5V del Pi resta tipicamente alimentato.
 *   Alimentare l'ESP dal 5V del Pi (pin 2/4) o da alimentatore condiviso a monte.
 *
 * LOGICA FIRMWARE:
 *   1. Init camera AI-Thinker
 *   2. PIN_WAKE output LOW a riposo; PIN_ALIVE input pulldown
 *   3. Su evento (eventDetected()):
 *      - Se ALIVE LOW → impulso WAKE → attendi ALIVE HIGH (timeout 15s)
 *      - Se ALIVE HIGH → NON dare impulso (Pi già acceso o in shutdown)
 *   4. Cooldown 30s tra eventi per evitare wake ripetuti
 *
 * Nessun trasferimento HTTP di immagini verso il Pi: il Pi scatta da solo
 * con Camera Module 3 dopo il boot. Vedi ../espconfig.md e ../piconfig.md.
 */

#include <Arduino.h>
#include "esp_camera.h"

// Pinout AI-Thinker ESP32-CAM (CameraWebServer)
#define PWDN_GPIO_NUM     32
#define RESET_GPIO_NUM    -1
#define XCLK_GPIO_NUM      0
#define SIOD_GPIO_NUM     26
#define SIOC_GPIO_NUM     27
#define Y9_GPIO_NUM       35
#define Y8_GPIO_NUM       34
#define Y7_GPIO_NUM       39
#define Y6_GPIO_NUM       36
#define Y5_GPIO_NUM       21
#define Y4_GPIO_NUM       19
#define Y3_GPIO_NUM       18
#define Y2_GPIO_NUM        5
#define VSYNC_GPIO_NUM    25
#define HREF_GPIO_NUM     23
#define PCLK_GPIO_NUM     22

constexpr int PIN_WAKE = 14;
constexpr int PIN_ALIVE = 13;

constexpr uint32_t WAKE_PULSE_MS = 200;
constexpr uint32_t ALIVE_WAIT_MS = 15000;
constexpr uint32_t EVENT_COOLDOWN_MS = 30000;

static uint32_t lastEventMs = 0;

// ALIVE is a board-level status hint: HIGH means the observed 3.3 V rail is up.
// It cannot distinguish normal operation from an in-progress shutdown.
bool piAlive() {
  return digitalRead(PIN_ALIVE) == HIGH;
}

void pulseJ2() {
  // The PC817 transistor briefly shorts the J2 button pads. Keep this pulse
  // short: holding the button for about a second can request a hard-off.
  digitalWrite(PIN_WAKE, HIGH);
  delay(WAKE_PULSE_MS);
  digitalWrite(PIN_WAKE, LOW);
}

bool waitForAlive(uint32_t timeoutMs) {
  // Poll instead of blocking on one long delay so the timeout stays bounded.
  const uint32_t t0 = millis();
  while (millis() - t0 < timeoutMs) {
    if (piAlive()) {
      return true;
    }
    delay(250);
  }
  return false;
}

/**
 * Impulso WAKE solo se il Pi risulta spento (ALIVE basso).
 * Se ALIVE è già alto (acceso o in shutdown), non ritentare.
 */
bool ensurePiOn() {
  if (piAlive()) {
    Serial.println("ALIVE high: Pi already on (or shutting down) — skip WAKE");
    return true;
  }

  Serial.println("ALIVE low: pulsing J2 WAKE");
  pulseJ2();

  if (!waitForAlive(ALIVE_WAIT_MS)) {
    Serial.println("Timeout waiting for ALIVE after WAKE");
    return false;
  }

  Serial.println("ALIVE high: Pi booting");
  return true;
}

bool initCamera() {
  // The ESP32-CAM camera is currently used only as an event-detection input;
  // the Raspberry Pi camera remains responsible for saved field photographs.
  camera_config_t config;
  config.ledc_channel = LEDC_CHANNEL_0;
  config.ledc_timer = LEDC_TIMER_0;
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
  config.xclk_freq_hz = 20000000;
  config.pixel_format = PIXFORMAT_JPEG;
  config.frame_size = FRAMESIZE_QVGA;
  config.jpeg_quality = 12;
  config.fb_count = 1;
  config.grab_mode = CAMERA_GRAB_LATEST;

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
 * Hook computer vision / soglia evento.
 * Sostituire con il modello scelto per la tesi.
 * Per ora: legge un frame (scarta) e restituisce false — nessun wake spurio.
 */
bool eventDetected() {
  camera_fb_t* fb = esp_camera_fb_get();
  if (!fb) {
    Serial.println("eventDetected: capture failed");
    return false;
  }

  // TODO: inferenza / soglia su fb->buf (JPEG) o frame RGB convertito.
  // Esempio placeholder: mai triggerare automaticamente.
  const bool hit = false;

  esp_camera_fb_return(fb);
  return hit;
}

void onEvent() {
  const uint32_t now = millis();
  // Unsigned subtraction remains valid across millis() counter rollover.
  // Since lastEventMs starts at zero, events during the first cooldown window
  // after boot are ignored as well.
  if (now - lastEventMs < EVENT_COOLDOWN_MS) {
    Serial.println("Event ignored (cooldown)");
    return;
  }
  lastEventMs = now;

  Serial.println("Event: ensuring Pi is on");
  if (!ensurePiOn()) {
    Serial.println("Event: wake failed");
  }
}

void setup() {
  Serial.begin(115200);
  delay(500);
  Serial.println("ESP32-CAM wake node starting");

  pinMode(PIN_WAKE, OUTPUT);
  digitalWrite(PIN_WAKE, LOW);
  pinMode(PIN_ALIVE, INPUT_PULLDOWN);

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
  if (eventDetected()) {
    onEvent();
  }

  // Test manuale da seriale: digita 'w' + Enter per forzare un wake attempt.
  if (Serial.available()) {
    const char c = Serial.read();
    if (c == 'w' || c == 'W') {
      Serial.println("Manual wake request");
      onEvent();
    }
  }

  delay(200);
}
