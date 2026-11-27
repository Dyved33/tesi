/**
 * Firmware dell'ESP32-S3-CAM della smart camera.
 *
 * Cosa fa:
 * - misura il BME280 ogni minuto, anche quando il Pi è spento;
 * - guarda la scena con la camera OV3660 della scheda e, se vede un
 *   movimento, accende il Pi con un impulso su WAKE;
 * - tiene misure ed eventi in un buffer finché il Pi non conferma di averli
 *   salvati (protocollo UART in docs/protocollo-uart.md);
 * - accetta comandi dal monitor USB a 115200 baud ('h' per l'elenco).
 *
 * Cosa non fa ancora: forecaster e decider. Per ora ogni movimento sveglia
 * il Pi (con una pausa minima tra due wake).
 *
 * Si apre e si carica con Arduino IDE, impostazioni in docs/setup-risveglio.md
 * (scheda "ESP32S3 Dev Module", PSRAM "OPI PSRAM", libreria SparkFun BME280).
 *
 * Il file è diviso in sezioni:
 *   1. configurazione         5. collegamento con il Pi
 *   2. buffer                 6. diagnostica (solo con DIAGNOSTICA = 1)
 *   3. BME280                 7. comandi dal monitor USB
 *   4. camera e movimento     8. setup() e loop()
 *
 * Provenienza:
 * - BME280: inizializzazione e forced mode dagli esempi Example2_I2CAddress e
 *   Example6_LowPower della libreria SparkFun BME280 (MIT); tempi di
 *   conversione, registro 0xD0 e limiti di misura dal datasheet Bosch
 *   BST-BME280-DS002.
 * - Camera: configurazione di camera_config_t e pin del modello ESP32S3_EYE
 *   dall'esempio CameraWebServer di Arduino-ESP32 (Apache-2.0).
 * - Rilevamento del movimento (differenza a blocchi con sfondo che si
 *   aggiorna lentamente), buffer, protocollo e macchina a stati del wake:
 *   scritti da noi. Il checksum delle righe UART è quello delle frasi NMEA.
 */

// Con 1 si aggiungono i comandi di prova per il cablaggio (sezione 6).
// Il firmware di campo va caricato con 0.
#ifndef DIAGNOSTICA
#define DIAGNOSTICA 0
#endif

#include <SparkFunBME280.h>
#include <Wire.h>
#include <esp_camera.h>
#include <esp_random.h>

// ===========================================================================
// 1. CONFIGURAZIONE
// Tutti i numeri da cambiare al banco stanno qui. La mappa completa dei
// collegamenti è in docs/pinout.md: se cambiate un pin, aggiornate anche quella.
// ===========================================================================

// --- Collegamento con il Pi e BME280 ---
constexpr int PIN_WAKE = 42;     // uscita: LED del PC817 che chiude i pad J2 del Pi
constexpr int PIN_ALIVE = 1;     // ingresso: GPIO17 del Pi, alto quando il Pi è acceso
constexpr int PIN_UART_TX = 2;   // ESP TX -> Pi GPIO15 (RXD)
constexpr int PIN_UART_RX = 41;  // ESP RX <- Pi GPIO14 (TXD)
constexpr int PIN_I2C_SDA = 47;  // BME280 SDA
constexpr int PIN_I2C_SCL = 21;  // BME280 SCL (il GPIO48 su queste schede pilota il LED RGB)

// --- Camera OV3660 sul connettore della scheda (pin del modello ESP32S3_EYE) ---
// La camera usa la seconda periferica I2C (porta 1) per la configurazione,
// il BME280 la prima (Wire, porta 0): i due bus non si disturbano.
constexpr int CAM_PIN_PWDN = -1;
constexpr int CAM_PIN_RESET = -1;
constexpr int CAM_PIN_XCLK = 15;
constexpr int CAM_PIN_SIOD = 4;
constexpr int CAM_PIN_SIOC = 5;
constexpr int CAM_PIN_D0 = 11;  // Y2
constexpr int CAM_PIN_D1 = 9;   // Y3
constexpr int CAM_PIN_D2 = 8;   // Y4
constexpr int CAM_PIN_D3 = 10;  // Y5
constexpr int CAM_PIN_D4 = 12;  // Y6
constexpr int CAM_PIN_D5 = 18;  // Y7
constexpr int CAM_PIN_D6 = 17;  // Y8
constexpr int CAM_PIN_D7 = 16;  // Y9
constexpr int CAM_PIN_VSYNC = 6;
constexpr int CAM_PIN_HREF = 7;
constexpr int CAM_PIN_PCLK = 13;

// --- BME280 ---
// 0x76 con SDO a massa, 0x77 con SDO a 3,3 V: il firmware prova entrambi.
constexpr uint8_t BME_INDIRIZZI[] = {0x76, 0x77};
constexpr uint32_t I2C_FREQUENZA_HZ = 100000;  // abbassare a 50000 con cavi lunghi

// --- Rilevamento del movimento ---
// L'immagine in scala di grigi 160x120 viene divisa in blocchi 10x10 (16x12
// = 192 blocchi). Un blocco è "cambiato" se la sua luminosità media si
// discosta dallo sfondo di più di SOGLIA_BLOCCO livelli (su 255). C'è un
// evento se i blocchi cambiati sono almeno SOGLIA_MIN_PERCENTO. Oltre
// SOGLIA_MAX_PERCENTO consideriamo che sia cambiata la luce (nuvola,
// esposizione) e non un insetto. Tutti i valori sono da tarare in campo
// con il comando 'c' della diagnostica.
constexpr int BLOCCO_PX = 10;
constexpr int SOGLIA_BLOCCO = 20;
constexpr float SOGLIA_MIN_PERCENTO = 3.0f;
constexpr float SOGLIA_MAX_PERCENTO = 60.0f;
constexpr float SFONDO_ALFA = 0.10f;  // quanto in fretta lo sfondo segue la scena (0..1)
constexpr int FRAME_DA_SCARTARE = 10; // all'avvio esposizione e bilanciamento si assestano

// --- Tempi (millisecondi) ---
constexpr uint32_t BME_PERIODO_MS = 60000;        // una misura al minuto
constexpr uint32_t BME_RIPROVA_MS = 10000;        // nuovo tentativo se il sensore non risponde
constexpr uint32_t CAMERA_PERIODO_MS = 500;       // un fotogramma ogni mezzo secondo
constexpr uint32_t CAMERA_RIPROVA_MS = 30000;     // nuovo tentativo se la camera non parte
constexpr uint32_t EVENTO_PAUSA_MS = 10000;       // un movimento continuo conta come un solo evento
constexpr uint32_t WAKE_IMPULSO_MS = 200;         // durata della "pressione" su J2
constexpr uint32_t WAKE_ATTESA_ALIVE_MS = 15000;  // dopo il wake, attesa massima di ALIVE
constexpr uint32_t WAKE_PAUSA_MIN_MS = 30000;     // tempo minimo tra due wake

// --- UART e buffer ---
constexpr uint32_t UART_BAUD = 115200;
constexpr size_t UART_RIGA_MAX = 64;
// 2880 posti = 48 ore di misure a una al minuto (più gli eventi). Ogni
// record occupa 24 byte, circa 68 KB di RAM. A buffer pieno si sovrascrive
// il record più vecchio e lo si conta come perso.
constexpr size_t BUFFER_CAPACITA = 2880;

// ===========================================================================
// Tipi (stanno tutti qui in alto perché Arduino IDE genera i prototipi delle
// funzioni prima della prima funzione, e lì i tipi devono essere già noti)
// ===========================================================================

// Esito di una misura del BME280. Il numero viene mandato al Pi così com'è:
// se si aggiunge un valore va aggiunto anche in raspberry_pi/smartcam/esp_link.py.
enum EsitoMisura : uint8_t {
  MISURA_OK = 0,
  MISURA_SENSORE_ASSENTE = 1,  // il sensore non ha risposto all'inizializzazione
  MISURA_TIMEOUT = 2,          // il sensore non ha finito la conversione in tempo
  MISURA_FUORI_SCALA = 3,      // valori NaN o fuori dai limiti del datasheet
  MISURA_SENZA_UMIDITA = 4,    // il chip è un BMP280: niente umidità
};

// Un elemento del buffer: una misura del BME280 ('M') o un evento della camera ('E').
struct Record {
  uint32_t seq;        // numero progressivo, riparte da 1 a ogni avvio dell'ESP
  uint32_t istanteMs;  // millis() quando è successo
  char tipo;           // 'M' oppure 'E'
  uint8_t esito;       // M: EsitoMisura; E: 1 se l'evento ha acceso il Pi
  float v1, v2, v3;    // M: temperatura °C, umidità %, pressione hPa
                       // E: % di blocchi cambiati, differenza media, non usato
};

enum class StatoWake { RIPOSO, IMPULSO, ATTESA_ALIVE };

// ===========================================================================
// 2. BUFFER
// Misure ed eventi restano qui finché il Pi non li scarica con GET e ne
// conferma la ricezione con ACK. Un record si cancella solo quando è già
// salvato sul Pi.
// ===========================================================================

static Record buffer[BUFFER_CAPACITA];
static size_t bufTesta = 0;   // indice del record più vecchio
static size_t bufQuanti = 0;
static uint32_t prossimoSeq = 1;
static uint32_t recordPersi = 0;

const Record &bufferAggiungi(char tipo, uint8_t esito, float v1, float v2, float v3) {
  if (bufQuanti == BUFFER_CAPACITA) {
    bufTesta = (bufTesta + 1) % BUFFER_CAPACITA;
    bufQuanti--;
    recordPersi++;
  }
  Record &r = buffer[(bufTesta + bufQuanti) % BUFFER_CAPACITA];
  r = {prossimoSeq++, millis(), tipo, esito, v1, v2, v3};
  bufQuanti++;
  return r;
}

const Record &bufferRecord(size_t i) { return buffer[(bufTesta + i) % BUFFER_CAPACITA]; }

// Toglie tutti i record con seq <= ultimoSeq (sono in ordine di seq).
void bufferConferma(uint32_t ultimoSeq) {
  while (bufQuanti > 0 && buffer[bufTesta].seq <= ultimoSeq) {
    bufTesta = (bufTesta + 1) % BUFFER_CAPACITA;
    bufQuanti--;
  }
}

// ===========================================================================
// 3. BME280
// ===========================================================================

static BME280 bme;
static bool bmePronto = false;
static uint8_t bmeIndirizzo = 0;
static uint8_t bmeChipId = 0;  // 0x60 = BME280, 0x58 = BMP280, 0 = non trovato
static uint32_t bmeUltimaMisuraMs = 0;
static uint32_t bmeUltimoTentativoMs = 0;
static bool bmePrimaMisuraFatta = false;

// Legge il registro dell'ID chip (0xD0) senza passare dalla libreria.
// Restituisce 0 se all'indirizzo non risponde nessuno.
uint8_t leggiChipId(uint8_t addr) {
  Wire.beginTransmission(addr);
  Wire.write(0xD0);
  if (Wire.endTransmission(false) != 0) return 0;
  if (Wire.requestFrom(addr, (uint8_t)1) != 1) return 0;
  return Wire.read();
}

// Cerca il sensore agli indirizzi di BME_INDIRIZZI. Il chip ID lo
// controlliamo noi perché la libreria accetta anche il BMP280, che non ha
// l'umidità.
bool bmeInizializza() {
  bmeUltimoTentativoMs = millis();
  bmePronto = false;
  bmeIndirizzo = bmeChipId = 0;
  for (uint8_t addr : BME_INDIRIZZI) {
    const uint8_t id = leggiChipId(addr);
    if (id != 0x60 && id != 0x58) continue;
    bme.setI2CAddress(addr);
    if (!bme.beginI2C(Wire)) continue;
    // beginI2C() lascia il sensore in normal mode: lo mettiamo a dormire,
    // si sveglia solo quando bmeMisura() chiede una misura forced.
    bme.setMode(MODE_SLEEP);
    bmePronto = true;
    bmeIndirizzo = addr;
    bmeChipId = id;
    Serial.printf("BME280 trovato: indirizzo 0x%02X, chip ID 0x%02X%s\n", addr, id,
                  id == 0x58 ? " (BMP280, senza umidità)" : "");
    return true;
  }
  return false;
}

// Una misura in forced mode. I valori non disponibili valgono NAN.
EsitoMisura bmeMisura(float &t, float &h, float &p) {
  t = h = p = NAN;
  if (!bmePronto) return MISURA_SENSORE_ASSENTE;

  // Con oversampling x1 (il default della libreria) la conversione dura al
  // massimo 9,3 ms (datasheet, sezione 9.1): aspettiamo 10 ms e poi il bit
  // "measuring", con un limite di 100 ms.
  bme.setMode(MODE_FORCED);
  delay(10);
  const uint32_t inizio = millis();
  while (bme.isMeasuring()) {
    if (millis() - inizio > 100) {
      // Con il bus scollegato il registro di stato si legge 0xFF e il bit
      // resta a 1: segniamo il sensore come perso, verrà reinizializzato.
      bmePronto = false;
      return MISURA_TIMEOUT;
    }
    delay(1);
  }

  t = bme.readTempC();
  p = bme.readFloatPressure() / 100.0f;  // la libreria restituisce Pa
  if (bmeChipId == 0x60) h = bme.readFloatHumidity();

  // Limiti di funzionamento del datasheet: -40..85 °C, 300..1100 hPa, 0..100 %.
  const bool tOk = isfinite(t) && t >= -40 && t <= 85;
  const bool pOk = isfinite(p) && p >= 300 && p <= 1100;
  const bool hOk = isfinite(h) && h >= 0 && h <= 100;
  if (!tOk || !pOk || (bmeChipId == 0x60 && !hOk)) {
    t = h = p = NAN;
    return MISURA_FUORI_SCALA;
  }
  return bmeChipId == 0x60 ? MISURA_OK : MISURA_SENZA_UMIDITA;
}

// Misura e mette il risultato nel buffer. Anche una misura fallita viene
// salvata con il suo esito: così sul Pi si vede quando il sensore non andava.
void bmeMisuraESalva() {
  float t, h, p;
  const EsitoMisura esito = bmeMisura(t, h, p);
  const Record &r = bufferAggiungi('M', esito, t, h, p);
  Serial.printf("Misura %lu: esito %u, %.2f C, %.2f %%, %.2f hPa\n",
                static_cast<unsigned long>(r.seq), esito, t, h, p);
  bmeUltimaMisuraMs = millis();
  bmePrimaMisuraFatta = true;
}

void bmeAggiorna() {
  const uint32_t adesso = millis();
  if (!bmePronto && adesso - bmeUltimoTentativoMs >= BME_RIPROVA_MS) bmeInizializza();
  if (!bmePrimaMisuraFatta || adesso - bmeUltimaMisuraMs >= BME_PERIODO_MS) bmeMisuraESalva();
}

void scansionaI2c() {
  Serial.printf("Scansione I2C (SDA=%d SCL=%d)\n", PIN_I2C_SDA, PIN_I2C_SCL);
  int trovati = 0;
  for (uint8_t addr = 1; addr < 127; addr++) {
    Wire.beginTransmission(addr);
    if (Wire.endTransmission() != 0) continue;
    trovati++;
    Serial.printf("  0x%02X risponde, chip ID 0x%02X\n", addr, leggiChipId(addr));
  }
  if (trovati == 0) Serial.println("  nessun dispositivo (con DIAGNOSTICA = 1: comandi p e a)");
}

// ===========================================================================
// 4. CAMERA E MOVIMENTO
// ===========================================================================

constexpr int IMG_W = 160, IMG_H = 120;  // FRAMESIZE_QQVGA
constexpr int BLOCCHI_X = IMG_W / BLOCCO_PX, BLOCCHI_Y = IMG_H / BLOCCO_PX;
constexpr int BLOCCHI = BLOCCHI_X * BLOCCHI_Y;

static bool cameraPronta = false;
static uint32_t cameraUltimoTentativoMs = 0;
static uint32_t cameraUltimoFrameMs = 0;
static int frameVisti = 0;
static float sfondo[BLOCCHI];
static uint32_t ultimoEventoMs = 0;
static bool eventoMaiVisto = true;
static float ultimaPercentuale = 0, ultimaDifferenza = 0;  // per 's' e per la diagnostica

bool cameraInizializza() {
  cameraUltimoTentativoMs = millis();
  camera_config_t cfg = {};
  cfg.pin_pwdn = CAM_PIN_PWDN;
  cfg.pin_reset = CAM_PIN_RESET;
  cfg.pin_xclk = CAM_PIN_XCLK;
  cfg.pin_sccb_sda = CAM_PIN_SIOD;
  cfg.pin_sccb_scl = CAM_PIN_SIOC;
  cfg.sccb_i2c_port = 1;  // la porta 0 è di Wire (BME280)
  cfg.pin_d0 = CAM_PIN_D0;
  cfg.pin_d1 = CAM_PIN_D1;
  cfg.pin_d2 = CAM_PIN_D2;
  cfg.pin_d3 = CAM_PIN_D3;
  cfg.pin_d4 = CAM_PIN_D4;
  cfg.pin_d5 = CAM_PIN_D5;
  cfg.pin_d6 = CAM_PIN_D6;
  cfg.pin_d7 = CAM_PIN_D7;
  cfg.pin_vsync = CAM_PIN_VSYNC;
  cfg.pin_href = CAM_PIN_HREF;
  cfg.pin_pclk = CAM_PIN_PCLK;
  cfg.xclk_freq_hz = 20000000;
  cfg.ledc_timer = LEDC_TIMER_0;
  cfg.ledc_channel = LEDC_CHANNEL_0;
  // Scala di grigi a bassa risoluzione: per il movimento basta, ed è veloce
  // da elaborare. La foto vera la fa il Pi.
  cfg.pixel_format = PIXFORMAT_GRAYSCALE;
  cfg.frame_size = FRAMESIZE_QQVGA;
  cfg.fb_count = 2;
  cfg.fb_location = CAMERA_FB_IN_PSRAM;
  cfg.grab_mode = CAMERA_GRAB_LATEST;  // vogliamo sempre il fotogramma più recente

  const esp_err_t err = esp_camera_init(&cfg);
  cameraPronta = err == ESP_OK;
  frameVisti = 0;
  if (cameraPronta) {
    Serial.println("Camera pronta");
  } else {
    Serial.printf("Camera non inizializzata (errore 0x%x), riprovo tra 30 s\n", err);
  }
  return cameraPronta;
}

// Media della luminosità di ogni blocco 10x10.
void calcolaBlocchi(const uint8_t *px, float *blocchi) {
  for (int by = 0; by < BLOCCHI_Y; by++) {
    for (int bx = 0; bx < BLOCCHI_X; bx++) {
      uint32_t somma = 0;
      for (int y = by * BLOCCO_PX; y < (by + 1) * BLOCCO_PX; y++) {
        const uint8_t *riga = px + y * IMG_W + bx * BLOCCO_PX;
        for (int x = 0; x < BLOCCO_PX; x++) somma += riga[x];
      }
      blocchi[by * BLOCCHI_X + bx] = somma / float(BLOCCO_PX * BLOCCO_PX);
    }
  }
}

// Confronta il fotogramma con lo sfondo e aggiorna lo sfondo.
// Restituisce la percentuale di blocchi cambiati, o -1 se non c'è un fotogramma valido.
float cameraConfronta() {
  camera_fb_t *fb = esp_camera_fb_get();
  if (!fb) return -1;
  if (fb->width != IMG_W || fb->height != IMG_H || fb->format != PIXFORMAT_GRAYSCALE) {
    esp_camera_fb_return(fb);
    return -1;
  }
  float blocchi[BLOCCHI];
  calcolaBlocchi(fb->buf, blocchi);
  esp_camera_fb_return(fb);

  frameVisti++;
  if (frameVisti <= FRAME_DA_SCARTARE) {
    // Durante l'assestamento lo sfondo è semplicemente l'ultimo fotogramma.
    memcpy(sfondo, blocchi, sizeof(sfondo));
    return 0;
  }

  int cambiati = 0;
  float sommaDiff = 0;
  for (int i = 0; i < BLOCCHI; i++) {
    const float diff = fabsf(blocchi[i] - sfondo[i]);
    sommaDiff += diff;
    if (diff > SOGLIA_BLOCCO) cambiati++;
    // Lo sfondo segue lentamente la scena: assorbe i cambi di luce graduali
    // ma non un insetto che passa in pochi fotogrammi.
    sfondo[i] += SFONDO_ALFA * (blocchi[i] - sfondo[i]);
  }
  ultimaDifferenza = sommaDiff / BLOCCHI;
  ultimaPercentuale = 100.0f * cambiati / BLOCCHI;

  if (ultimaPercentuale > SOGLIA_MAX_PERCENTO) {
    // Cambio di luce improvviso: ripartiamo da questo fotogramma.
    memcpy(sfondo, blocchi, sizeof(sfondo));
  }
  return ultimaPercentuale;
}

bool linkRichiediWake();  // sezione 5

void cameraAggiorna() {
  const uint32_t adesso = millis();
  if (!cameraPronta) {
    if (adesso - cameraUltimoTentativoMs >= CAMERA_RIPROVA_MS) cameraInizializza();
    return;
  }
  if (adesso - cameraUltimoFrameMs < CAMERA_PERIODO_MS) return;
  cameraUltimoFrameMs = adesso;

  const float percento = cameraConfronta();
  if (percento < SOGLIA_MIN_PERCENTO || percento > SOGLIA_MAX_PERCENTO) return;
  if (!eventoMaiVisto && adesso - ultimoEventoMs < EVENTO_PAUSA_MS) return;

  ultimoEventoMs = adesso;
  eventoMaiVisto = false;
  Serial.printf("Movimento: %.1f %% dei blocchi, differenza media %.1f\n", percento,
                ultimaDifferenza);
  // Qui in futuro ci sarà il decider: per ora ogni evento prova a svegliare il Pi.
  const bool wake = linkRichiediWake();
  bufferAggiungi('E', wake ? 1 : 0, percento, ultimaDifferenza, 0);
}

// ===========================================================================
// 5. COLLEGAMENTO CON IL PI
//
// WAKE  ESP -> PC817 -> pad J2: un impulso accende il Pi in halt.
// ALIVE Pi GPIO17 -> ESP: alto mentre il Pi è acceso. Con POWER_OFF_ON_HALT=1
//       torna basso quando l'arresto è finito.
// UART  aperta solo con ALIVE alto. Il Pi fa le domande, l'ESP risponde:
//
//   Pi -> ESP        ESP -> Pi
//   HELLO            INFO,<boot>,<uptime_ms>,<chip_id>,<indirizzo>,<in_buffer>,<persi>,<camera>*CS
//   TIME,<epoch_s>   OK,TIME*CS
//   GET              M,<boot>,<seq>,<eta_ms>,<esito>,<temp>,<umid>,<press>*CS
//                    E,<boot>,<seq>,<eta_ms>,<wake>,<percento>,<differenza>*CS
//                    END,<numero_righe>*CS
//   ACK,<seq>        OK,ACK,<rimasti>*CS
//
// <eta_ms> è da quanto tempo esiste il record: il Pi ricava l'ora come
// ora_di_ricezione - eta_ms. *CS è lo XOR dei caratteri prima di '*'.
// ===========================================================================

static HardwareSerial uartPi(1);  // la UART0 è il monitor USB
static StatoWake statoWake = StatoWake::RIPOSO;
static uint32_t inizioWakeMs = 0;
static bool nessunWake = true;  // nessun wake dall'avvio: la pausa minima non si applica
static bool aliveVecchio = false;
static uint32_t bootId = 0;
static uint32_t epochAllAvvio = 0;  // ora UNIX ricevuta dal Pi riportata a millis() = 0
static char riga[UART_RIGA_MAX];
static size_t lunghezzaRiga = 0;

void inviaRiga(const char *testo) {
  uint8_t cs = 0;
  for (const char *c = testo; *c; c++) cs ^= static_cast<uint8_t>(*c);
  uartPi.printf("%s*%02X\n", testo, cs);
}

// Un float con due decimali, oppure campo vuoto se è NaN.
void formatta(char *dest, size_t n, float v) {
  if (isnan(v)) dest[0] = '\0';
  else snprintf(dest, n, "%.2f", v);
}

void rispondiGet() {
  char testo[96], a[12], b[12], c[12];
  const uint32_t adesso = millis();
  for (size_t i = 0; i < bufQuanti; i++) {
    const Record &r = bufferRecord(i);
    const unsigned long eta = adesso - r.istanteMs;
    formatta(a, sizeof(a), r.v1);
    formatta(b, sizeof(b), r.v2);
    if (r.tipo == 'M') {
      formatta(c, sizeof(c), r.v3);
      snprintf(testo, sizeof(testo), "M,%08lX,%lu,%lu,%u,%s,%s,%s", (unsigned long)bootId,
               (unsigned long)r.seq, eta, r.esito, a, b, c);
    } else {
      snprintf(testo, sizeof(testo), "E,%08lX,%lu,%lu,%u,%s,%s", (unsigned long)bootId,
               (unsigned long)r.seq, eta, r.esito, a, b);
    }
    inviaRiga(testo);
  }
  snprintf(testo, sizeof(testo), "END,%u", (unsigned)bufQuanti);
  inviaRiga(testo);
  Serial.printf("Inviati al Pi %u record\n", (unsigned)bufQuanti);
}

void eseguiComandoPi(char *cmd) {
  char *asterisco = strchr(cmd, '*');  // il Pi non manda checksum: se c'è lo ignoriamo
  if (asterisco) *asterisco = '\0';
  char testo[96];

  if (strcmp(cmd, "HELLO") == 0) {
    snprintf(testo, sizeof(testo), "INFO,%08lX,%lu,%02X,%02X,%u,%lu,%d", (unsigned long)bootId,
             (unsigned long)millis(), bmeChipId, bmeIndirizzo, (unsigned)bufQuanti,
             (unsigned long)recordPersi, cameraPronta ? 1 : 0);
    inviaRiga(testo);
  } else if (strncmp(cmd, "TIME,", 5) == 0) {
    const unsigned long epoch = strtoul(cmd + 5, nullptr, 10);
    if (epoch < 1767225600UL) {  // prima del 2026: l'orologio del Pi non è sincronizzato
      inviaRiga("ERR,TIME");
      return;
    }
    epochAllAvvio = epoch - millis() / 1000;
    inviaRiga("OK,TIME");
  } else if (strcmp(cmd, "GET") == 0) {
    rispondiGet();
  } else if (strncmp(cmd, "ACK,", 4) == 0) {
    bufferConferma(strtoul(cmd + 4, nullptr, 10));
    snprintf(testo, sizeof(testo), "OK,ACK,%u", (unsigned)bufQuanti);
    inviaRiga(testo);
  } else if (cmd[0] != '\0') {
    snprintf(testo, sizeof(testo), "ERR,%.60s", cmd);
    inviaRiga(testo);
  }
}

void leggiComandiPi() {
  while (uartPi.available()) {
    const char c = uartPi.read();
    if (c == '\r') continue;
    if (c == '\n') {
      riga[lunghezzaRiga] = '\0';
      eseguiComandoPi(riga);
      lunghezzaRiga = 0;
    } else if (lunghezzaRiga < UART_RIGA_MAX - 1) {
      riga[lunghezzaRiga++] = c;
    } else {
      lunghezzaRiga = 0;  // riga troppo lunga: la scartiamo
    }
  }
}

void apriUart() {
  uartPi.begin(UART_BAUD, SERIAL_8N1, PIN_UART_RX, PIN_UART_TX);
  lunghezzaRiga = 0;
  Serial.println("ALIVE alto: Pi acceso, UART aperta");
}

void chiudiUart() {
  uartPi.end();
  // TX torna un ingresso: una linea TX a riposo è alta e alimenterebbe il Pi
  // spento attraverso il suo RXD.
  pinMode(PIN_UART_TX, INPUT);
  Serial.println("ALIVE basso: Pi spento, UART chiusa");
}

// Chiede di accendere il Pi. Non fa niente se il Pi è già acceso (un'altra
// pressione di J2 lo spegnerebbe), se c'è già un wake in corso o se l'ultimo
// è troppo recente. Restituisce true se l'impulso è partito.
bool linkRichiediWake() {
  const uint32_t adesso = millis();
  if (statoWake != StatoWake::RIPOSO) {
    Serial.println("Wake ignorato: ce n'è già uno in corso");
    return false;
  }
  if (!nessunWake && adesso - inizioWakeMs < WAKE_PAUSA_MIN_MS) {
    Serial.println("Wake ignorato: l'ultimo è troppo recente");
    return false;
  }
  if (digitalRead(PIN_ALIVE) == HIGH) {
    Serial.println("Wake ignorato: il Pi è già acceso");
    return false;
  }
  Serial.println("Impulso WAKE");
  digitalWrite(PIN_WAKE, HIGH);
  statoWake = StatoWake::IMPULSO;
  inizioWakeMs = adesso;
  nessunWake = false;
  return true;
}

// Macchina a stati del wake: così loop() non resta mai bloccato.
void aggiornaWake(bool alive) {
  const uint32_t trascorso = millis() - inizioWakeMs;
  switch (statoWake) {
    case StatoWake::RIPOSO:
      break;
    case StatoWake::IMPULSO:
      if (trascorso >= WAKE_IMPULSO_MS) {
        digitalWrite(PIN_WAKE, LOW);
        statoWake = StatoWake::ATTESA_ALIVE;
      }
      break;
    case StatoWake::ATTESA_ALIVE:
      if (alive) {
        Serial.printf("Wake riuscito: ALIVE alto dopo %lu ms\n", (unsigned long)trascorso);
        statoWake = StatoWake::RIPOSO;
      } else if (trascorso >= WAKE_ATTESA_ALIVE_MS) {
        Serial.println("Wake fallito: ALIVE ancora basso");
        statoWake = StatoWake::RIPOSO;
      }
      break;
  }
}

void linkAggiorna() {
  const bool alive = digitalRead(PIN_ALIVE) == HIGH;
  if (alive && !aliveVecchio) apriUart();
  if (!alive && aliveVecchio) chiudiUart();
  aliveVecchio = alive;
  aggiornaWake(alive);
  if (alive) leggiComandiPi();
}

// Ora UNIX ricevuta dal Pi (0 se non ancora ricevuta). Servirà a forecaster
// e decider per i gradi-giorno e l'ora del giorno.
uint32_t oraUnix() { return epochAllAvvio ? epochAllAvvio + millis() / 1000 : 0; }

// ===========================================================================
// 6. DIAGNOSTICA (compilata solo con DIAGNOSTICA = 1)
// Prove di cablaggio al banco. Alcune sono bloccanti (durano qualche
// secondo): per questo non stanno nel firmware di campo.
// ===========================================================================
#if DIAGNOSTICA

// GPIO liberi su cui cercare il BME280 se non risponde dove ce lo aspettiamo.
// Esclusi: WAKE, ALIVE, UART, camera (4-18), USB (19-20), PSRAM (35-37),
// UART0 (43-44) e strapping (0, 3, 45, 46).
constexpr int PIN_CANDIDATI[] = {21, 47, 48, 14, 38, 39, 40};

int scansionaSilenziosa() {
  int trovati = 0;
  for (uint8_t addr = 1; addr < 127; addr++) {
    Wire.beginTransmission(addr);
    if (Wire.endTransmission() == 0) trovati++;
  }
  return trovati;
}

void ripristinaI2c() {
  Wire.end();
  Wire.begin(PIN_I2C_SDA, PIN_I2C_SCL, I2C_FREQUENZA_HZ);
}

// Con il pulldown interno (circa 45 kΩ) una linea collegata al modulo
// alimentato legge HIGH, perché il pull-up da 10 kΩ del modulo è più forte.
void diagLineeI2c() {
  Wire.end();
  const int pin[] = {PIN_I2C_SDA, PIN_I2C_SCL};
  const char *nome[] = {"SDA", "SCL"};
  for (int i = 0; i < 2; i++) {
    pinMode(pin[i], INPUT_PULLDOWN);
    delay(5);
    const bool alto = digitalRead(pin[i]) == HIGH;
    Serial.printf("  %s (GPIO%d): %s\n", nome[i], pin[i],
                  alto ? "HIGH, il modulo è collegato e alimentato"
                       : "LOW, filo staccato o modulo non alimentato");
  }
  ripristinaI2c();
}

void diagTutteLeCoppie() {
  int coppie = 0;
  for (int sda : PIN_CANDIDATI) {
    for (int scl : PIN_CANDIDATI) {
      if (sda == scl) continue;
      Wire.end();
      Wire.begin(sda, scl, 100000);
      Wire.setTimeOut(20);
      if (scansionaSilenziosa() > 0) {
        Serial.printf("  qualcosa risponde con SDA=%d SCL=%d\n", sda, scl);
        coppie++;
      }
    }
  }
  if (coppie == 0) Serial.println("  nessuna coppia risponde: controllare alimentazione e massa");
  ripristinaI2c();
}

void diagSeguiAlive(uint32_t durataMs) {
  const uint32_t inizio = millis();
  int vecchio = -1;
  while (millis() - inizio < durataMs) {
    const int livello = digitalRead(PIN_ALIVE);
    if (livello != vecchio) {
      Serial.printf("  t=%5lu ms  ALIVE %s\n", (unsigned long)(millis() - inizio),
                    livello ? "HIGH" : "LOW");
      vecchio = livello;
    }
    delay(100);
  }
}

// Collega la UART del Pi al monitor USB, finché non si scrive '~'.
// Sul Pi: picocom -b 115200 /dev/ttyAMA0
void diagPonteUart() {
  if (!aliveVecchio) uartPi.begin(UART_BAUD, SERIAL_8N1, PIN_UART_RX, PIN_UART_TX);
  Serial.println("  ponte UART attivo, '~' per uscire");
  while (true) {
    while (uartPi.available()) Serial.write(uartPi.read());
    while (Serial.available()) {
      const char c = Serial.read();
      if (c == '~') {
        if (!aliveVecchio) chiudiUart();
        Serial.println("\n  ponte chiuso");
        return;
      }
      uartPi.write(c);
    }
    delay(1);
  }
}

// Stampa per 10 s la percentuale di blocchi cambiati: serve a tarare le soglie
// muovendo una mano o un oggetto davanti alla camera.
void diagCamera() {
  if (!cameraPronta) {
    Serial.println("  camera non pronta");
    return;
  }
  const uint32_t inizio = millis();
  while (millis() - inizio < 10000) {
    const float p = cameraConfronta();
    Serial.printf("  %5.1f %% blocchi cambiati, differenza media %5.1f %s\n", p,
                  ultimaDifferenza,
                  p >= SOGLIA_MIN_PERCENTO && p <= SOGLIA_MAX_PERCENTO ? "<- evento" : "");
    delay(CAMERA_PERIODO_MS);
  }
}

void diagAiuto() {
  Serial.println("Diagnostica: p linee I2C, a scansione su tutte le coppie di pin,");
  Serial.println("             l segui ALIVE 20 s, u ponte UART, c movimento 10 s");
}

bool eseguiComandoDiagnostica(char c) {
  switch (c) {
    case 'p': diagLineeI2c(); return true;
    case 'a': diagTutteLeCoppie(); return true;
    case 'l': diagSeguiAlive(20000); return true;
    case 'u': diagPonteUart(); return true;
    case 'c': diagCamera(); return true;
    default: return false;
  }
}

#endif  // DIAGNOSTICA

// ===========================================================================
// 7. COMANDI DAL MONITOR USB
// ===========================================================================

void stampaStato() {
  Serial.printf("Boot ID %08lX, acceso da %lu s, ora UNIX dal Pi %lu\n", (unsigned long)bootId,
                (unsigned long)(millis() / 1000), (unsigned long)oraUnix());
  Serial.printf("Pi: %s\n", aliveVecchio ? "acceso (ALIVE alto)" : "spento");
  if (bmePronto) Serial.printf("BME280: indirizzo 0x%02X, chip ID 0x%02X\n", bmeIndirizzo, bmeChipId);
  else Serial.println("BME280: non trovato");
  Serial.printf("Camera: %s, ultimo confronto %.1f %%\n", cameraPronta ? "pronta" : "non pronta",
                ultimaPercentuale);
  Serial.printf("Buffer: %u record, %lu persi\n", (unsigned)bufQuanti, (unsigned long)recordPersi);
}

void stampaAiuto() {
  Serial.println("Comandi: w wake Pi, r misura subito, s stato, i scansione I2C, h aiuto");
#if DIAGNOSTICA
  diagAiuto();
#endif
}

void leggiComandiUsb() {
  while (Serial.available()) {
    const char c = tolower(Serial.read());
#if DIAGNOSTICA
    if (eseguiComandoDiagnostica(c)) continue;
#endif
    switch (c) {
      case 'w': linkRichiediWake(); break;
      case 'r': bmeMisuraESalva(); break;
      case 's': stampaStato(); break;
      case 'i': scansionaI2c(); break;
      case 'h': stampaAiuto(); break;
      default: break;  // invio, spazi, caratteri sconosciuti
    }
  }
}

// ===========================================================================
// 8. SETUP E LOOP
// ===========================================================================

void setup() {
  Serial.begin(115200);
  delay(500);  // tempo per aprire il monitor

  pinMode(PIN_WAKE, OUTPUT);
  digitalWrite(PIN_WAKE, LOW);         // PC817 spento
  pinMode(PIN_ALIVE, INPUT_PULLDOWN);  // basso se il Pi è spento o scollegato
  pinMode(PIN_UART_TX, INPUT);         // TX non pilotato finché il Pi è spento
  do bootId = esp_random(); while (bootId == 0);

  Serial.printf("\nFirmware smart camera%s, boot ID %08lX\n",
                DIAGNOSTICA ? " (DIAGNOSTICA)" : "", (unsigned long)bootId);
  Serial.printf("Pin: WAKE=%d ALIVE=%d UART TX=%d RX=%d I2C SDA=%d SCL=%d\n", PIN_WAKE, PIN_ALIVE,
                PIN_UART_TX, PIN_UART_RX, PIN_I2C_SDA, PIN_I2C_SCL);

  Wire.begin(PIN_I2C_SDA, PIN_I2C_SCL, I2C_FREQUENZA_HZ);
  if (!bmeInizializza()) {
    Serial.println("BME280 non trovato, riprovo ogni 10 s");
    scansionaI2c();
  }
  cameraInizializza();
  stampaAiuto();
}

void loop() {
  bmeAggiorna();
  cameraAggiorna();
  linkAggiorna();
  leggiComandiUsb();
  delay(10);
}
