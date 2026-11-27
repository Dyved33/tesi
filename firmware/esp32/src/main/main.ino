/**
 * Firmware per ESP32-S3-WROOM: risveglio del Raspberry Pi 5.
 *
 * Cosa fa:
 * - se dal monitor seriale si invia 'w', prova a svegliare il Pi;
 * - per svegliarlo dà un impulso su WAKE (GPIO14) e poi aspetta che il Pi
 *   alzi ALIVE (GPIO13).
 * Il driver BME280 è in bme_reader.cpp, ma non viene inizializzato qui:
 * i pin I2C vanno scelti in base al cablaggio della scheda S3 effettiva.
 * Mancano ancora integrazione del sensore, forecaster e decider: l'obiettivo finale
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
 * Provenienza:
 * - La logica WAKE/ALIVE (piAlive, pulseJ2, waitForAlive, ensurePiOn,
 *   onEvent, comando 'w') è scritta da noi.
 * - Il confronto "millis() - t0 < timeout" per gestire il riavvolgimento di
 *   millis() è l'idioma standard Arduino (vedi l'esempio BlinkWithoutDelay:
 *   https://docs.arduino.cc/built-in-examples/digital/BlinkWithoutDelay/).
 */

#include <Arduino.h>

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

// Gestisce un evento manuale rispettando il cooldown.
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
  Serial.println("ESP32-S3-WROOM wake node starting");

  // WAKE parte basso, così il PC817 non chiude J2 per sbaglio.
  pinMode(PIN_WAKE, OUTPUT);
  digitalWrite(PIN_WAKE, LOW);
  // ALIVE come ingresso con il pulldown interno, oltre a quello esterno da 10 kΩ:
  // se il filo è scollegato leggiamo LOW.
  pinMode(PIN_ALIVE, INPUT_PULLDOWN);

  Serial.printf("Pins: WAKE=%d ALIVE=%d | piAlive=%d\n", PIN_WAKE, PIN_ALIVE,
                piAlive() ? 1 : 0);
}

void loop() {
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
