/**
 * Bozza firmware per ESP32-CAM (AI-Thinker): trigger di prova e wake del Pi 5.
 *
 * Stato attuale: inizializza la camera ESP, ma eventDetected() è uno stub che
 * scarta ogni frame e restituisce sempre false. Il wake è quindi provabile dal
 * monitor seriale con 'w'. Non implementa ancora BME280, forecaster o decider.
 * Il target di progetto è un ESP sempre alimentato che legge il BME280 e applica
 * la politica di wake;
 *
 * Collegamento di prova (vedi ../config$awakening.md):
 *   WAKE: GPIO14 comanda il circuito che chiude brevemente i due pad J2.
 *         Il progetto al momento non prevede un optoisolatore; il collegamento
 *         diretto è da definire e verificare elettricamente prima del cablaggio.
 *   ALIVE: Pi GPIO17 → ESP GPIO13, pulldown 10kΩ lato ESP e massa comune.
 *          HIGH indica che GPIO17 è attivo; LOW che non lo è. Questo segnale
 *          non distingue il normale funzionamento dalla fase di shutdown.
 *          ensurePiOn() non invia wake se ALIVE è HIGH.
 *
 * Con POWER_OFF_ON_HALT=1 il rail 3,3V del Pi si spegne in halt; ESP e BME280
 * devono quindi essere alimentati separatamente (ad esempio dal 5V del Pi,
 * se disponibile nella configurazione usata). L'impulso breve evita di
 * mantenere chiusi i pad J2: seguire i limiti elettrici documentati per il Pi.
 *
 * La cattura del frame ESP serve solo al rilevamento provvisorio: nessuna immagine
 * viene inviata al Pi. Nel sistema previsto, le foto di campo sono acquisite
 * dalle fotocamere collegate al Raspberry. 
 */

#include <Arduino.h>
#include "esp_camera.h"

// Pinout fisico della camera integrata sulla ESP32-CAM AI-Thinker.
// Ogni nome viene usato sotto per associare un segnale del sensore al GPIO
// corrispondente. Non vanno cambiati questi numeri senza verificare la scheda e il
// cablaggio: valori errati possono impedire l'inizializzazione della camera.
// PWDN = power-down; RESET = reset (qui non collegato, quindi -1).
#define PWDN_GPIO_NUM     32
#define RESET_GPIO_NUM    -1
// XCLK è il clock generato dall'ESP32 per il sensore della camera.
#define XCLK_GPIO_NUM      0
// SIOD/SIOC sono le linee dati/clock del bus di configurazione della camera.
#define SIOD_GPIO_NUM     26
#define SIOC_GPIO_NUM     27
// Y2...Y9 sono gli otto bit del bus parallelo che trasporta i pixel.
#define Y9_GPIO_NUM       35
#define Y8_GPIO_NUM       34
#define Y7_GPIO_NUM       39
#define Y6_GPIO_NUM       36
#define Y5_GPIO_NUM       21
#define Y4_GPIO_NUM       19
#define Y3_GPIO_NUM       18
#define Y2_GPIO_NUM        5
// Segnali di temporizzazione del flusso immagine: sincronismo frame, riga e pixel.
#define VSYNC_GPIO_NUM    25
#define HREF_GPIO_NUM     23
#define PCLK_GPIO_NUM     22

// GPIO usati dal circuito esterno ESP32-Pi. WAKE comanda la chiusura breve J2;
// il collegamento diretto senza optoisolatore va verificato prima del cablaggio.
// ALIVE legge il livello proveniente dal GPIO17 del Pi, con pulldown esterno.
constexpr int PIN_WAKE = 14;
constexpr int PIN_ALIVE = 13;

// Durata dell'impulso che simula una pressione breve sui pad J2.
constexpr uint32_t WAKE_PULSE_MS = 200;
// Tempo massimo per osservare ALIVE HIGH dopo aver inviato l'impulso.
constexpr uint32_t ALIVE_WAIT_MS = 15000;
// Intervallo minimo fra due tentativi accettati di gestione evento.
constexpr uint32_t EVENT_COOLDOWN_MS = 30000;

// Timestamp dell'ultimo evento. Il primo evento viene accettato subito.
static uint32_t lastEventMs = 0;
static bool hasHandledEvent = false;

// ALIVE legge il livello del GPIO17 configurato sul Pi; HIGH significa che il
// GPIO è attivo. Non distingue il funzionamento normale dallo shutdown in corso.
bool piAlive() {
  // digitalRead restituisce HIGH o LOW; qui non viene fatta alcuna attesa o filtro.
  return digitalRead(PIN_ALIVE) == HIGH;
}

// Attiva WAKE per 200 ms. Il circuito esterno deve chiudere i due contatti J2.
// Non collegare GPIO14 direttamente a J2 senza aver verificato schema e livelli.
void pulseJ2() {
  digitalWrite(PIN_WAKE, HIGH);
  delay(WAKE_PULSE_MS);
  digitalWrite(PIN_WAKE, LOW);
}

bool waitForAlive(uint32_t timeoutMs) {
  // Memorizza il tempo iniziale. La sottrazione unsigned gestisce anche il
  // riavvolgimento di millis(), purché il timeout sia molto inferiore al suo periodo.
  const uint32_t t0 = millis();
  while (millis() - t0 < timeoutMs) {
    if (piAlive()) {
      // Il livello è comparso: non significa necessariamente che il sistema
      // operativo del Pi abbia terminato il boot o sia pronto a ricevere comandi.
      return true;
    }
    // Interroga ALIVE ogni 250 ms invece di attendere tutto il timeout in un colpo.
    delay(250);
  }
  // Scaduto il tempo senza aver letto ALIVE HIGH.
  return false;
}

/**
 * Se ALIVE è LOW, invia l'impulso WAKE a J2, che simula il pulsante di
 * accensione, poi attende ALIVE HIGH. ALIVE HIGH non distingue boot, uso e
 * shutdown, quindi in quel caso evita un altro impulso.
 */
bool ensurePiOn() {
  // true significa che ALIVE è HIGH, non che Linux abbia finito l'avvio.
  if (piAlive()) {
    Serial.println("ALIVE HIGH: Pi already on (or shutting down) — skip WAKE");
    return true;
  }

  Serial.println("ALIVE LOW: pulsing J2 WAKE");
  pulseJ2();

  // Dopo l'impulso il firmware attende il segnale elettrico, non la disponibilità
  // del Pi via rete né il completamento dei servizi Linux.
  if (!waitForAlive(ALIVE_WAIT_MS)) {
    Serial.println("Timeout waiting for ALIVE after WAKE");
    return false;
  }

  Serial.println("ALIVE HIGH: Pi booting");
  return true;
}

bool initCamera() {
  // La camera ESP32-CAM rileva un evento; le foto di campo restano affidate
  // alle fotocamere sul Raspberry. Anche il BME280 sarà collegato all'ESP32.
  // GPIO21 è già camera Y5, quindi non può essere SDA mentre la camera è attiva.
  camera_config_t config;
  // camera_config_t e le funzioni esp_camera_* sono dichiarate da esp_camera.h,
  // parte del componente esp32-camera incluso nel framework ESP32/PlatformIO.
  // Assegna al driver i GPIO definiti sopra, seguendo la nomenclatura del bus
  // parallelo della camera: d0 corrisponde a Y2, d7 a Y9.
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
  // Clock del sensore: 20 MHz.
  config.xclk_freq_hz = 20000000;
  // I frame vengono codificati dalla camera in JPEG; questa bozza non li salva
  // né li trasmette, ma li acquisisce per predisporre il punto di rilevamento.
  config.pixel_format = PIXFORMAT_JPEG;
  // Configurazione prudente iniziale: QVGA (320×240), qualità JPEG 12,
  // un buffer. Il numero qualità è specifico del driver: valore più basso
  // normalmente significa compressione minore e file più grandi.
  config.frame_size = FRAMESIZE_QVGA;
  config.jpeg_quality = 12;
  config.fb_count = 1;
  // Se arrivano frame più rapidamente di quanto il firmware li usi, preferisce
  // il più recente invece di accumulare frame vecchi.
  // CAMERA_GRAB_LATEST è un valore di camera_grab_mode_t in esp_camera.h:
  // quando i buffer si riempiono, il driver privilegia il frame più recente.
  config.grab_mode = CAMERA_GRAB_LATEST;

  // PSRAM (pseudo-static RAM) è memoria aggiuntiva esterna montata su alcune
  // schede. psramFound() appartiene al core Arduino-ESP32 e la rileva; la
  // AI-Thinker ESP32-CAM normalmente monta 4 MB.
  if (psramFound()) {
    // Se è disponibile PSRAM, si può usare una risoluzione più alta e mantenere
    // due buffer in memoria esterna, evitando di occupare la RAM interna.
    config.frame_size = FRAMESIZE_SVGA;
    config.jpeg_quality = 10;
    config.fb_count = 2;
    config.fb_location = CAMERA_FB_IN_PSRAM;
  } else {
    // Senza PSRAM si usa la RAM interna; la configurazione resta a QVGA e un buffer.
    config.fb_location = CAMERA_FB_IN_DRAM;
  }

  // Avvia il driver con la configurazione. In caso di errore il chiamante
  // blocca il firmware perché il percorso evento attuale richiede la camera.
  // esp_camera_init(), dichiarata in esp_camera.h, inizializza il driver camera.
  esp_err_t err = esp_camera_init(&config);
  if (err != ESP_OK) {
    Serial.printf("Camera init failed: 0x%x\n", err);
    return false;
  }
  return true;
}

/**
 * Punto d'inserimento per la computer vision o per una soglia di evento.
 * Per ora legge e scarta un fotogramma, poi restituisce false: niente wake automatici.
 */
bool eventDetected() {
  // Richiede un frame al driver. Il puntatore restituito è nullo se la cattura
  // non è riuscita; in quel caso non viene generato alcun evento.
  // camera_fb_t è dichiarato in esp_camera.h. fb significa frame buffer:
  // puntatore alla struttura con byte immagine, dimensione e metadati. Dopo
  // l'uso va restituito al driver con esp_camera_fb_return().
  camera_fb_t* fb = esp_camera_fb_get();
  if (!fb) {
    Serial.println("eventDetected: capture failed");
    return false;
  }

  // Segnaposto intenzionale: nessun algoritmo legge ancora fb->buf, quindi hit
  // resta sempre false. Quando si implementerà l'analisi, usare i dati del frame
  // e restituire sempre il buffer al driver, anche dopo l'elaborazione.
  const bool hit = false;

  // Restituisce il buffer alla camera, che potrà riutilizzarlo per una cattura futura.
  esp_camera_fb_return(fb);
  return hit;
}

void onEvent() {
  // millis() conta i millisecondi trascorsi dal boot; non è un orario assoluto.
  const uint32_t now = millis();
  // Il cooldown si applica solo dopo il primo evento; la sottrazione unsigned
  // gestisce anche il riavvolgimento del contatore millis().
  if (hasHandledEvent && now - lastEventMs < EVENT_COOLDOWN_MS) {
    Serial.println("Event ignored (cooldown)");
    return;
  }
  // Aggiorna il cooldown prima del tentativo di wake: anche un tentativo fallito
  // impedisce un nuovo tentativo fino alla fine dell'intervallo.
  lastEventMs = now;
  hasHandledEvent = true;

  Serial.println("Event: ensuring Pi is on");
  if (!ensurePiOn()) {
    Serial.println("Event: wake failed");
  }
}

void setup() {
  // Inizializza la porta USB-seriale per log e comandi; il monitor seriale
  // del computer deve usare la stessa velocità, 115200 bit/s.
  Serial.begin(115200);
  delay(500);
  Serial.println("ESP32-CAM wake node starting");

  // pinMode(..., OUTPUT) configura GPIO14 come uscita digitale; LOW lo porta
  // subito al livello di riposo prima di iniziare il ciclo principale.
  pinMode(PIN_WAKE, OUTPUT);
  digitalWrite(PIN_WAKE, LOW);
  // pinMode(..., INPUT_PULLDOWN) configura GPIO13 come ingresso digitale e
  // abilita una debole resistenza interna verso massa, così scollegato tende
  // a LOW. È previsto anche un pulldown esterno da 10 kΩ.
  pinMode(PIN_ALIVE, INPUT_PULLDOWN);

  // In questa versione la camera è obbligatoria: se non parte, resta in attesa
  // indefinita e non esegue loop() né accetta il comando seriale 'w'.
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
  // Percorso automatico: acquisisce un frame e, solo se eventDetected() è true,
  // applica cooldown e procedura di wake. Con lo stub attuale non si attiva mai.
  if (eventDetected()) {
    onEvent();
  }

  // Prova manuale: aprire il monitor USB-seriale del computer a 115200 baud,
  // digitare w e premere Invio per inviare il carattere alla ESP32.
  if (Serial.available()) {
    // Legge un solo byte per iterazione; il terminatore Enter viene ignorato.
    const char c = Serial.read();
    if (c == 'w' || c == 'W') {
      Serial.println("Manual wake request");
      onEvent();
    }
  }

  // Pausa breve fra iterazioni: limita il polling della camera e della seriale.
  delay(200);
}
