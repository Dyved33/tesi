-- Schema del database della smart camera (PostgreSQL).
--
-- Requisiti dal piano operativo (docs/plan.pdf, "monitoraggio e costruzione
-- del dataset"):
--   - collegare misure, immagini, GPS, log e risultati dell'analisi tramite
--     identificativi e timestamp coerenti;
--   - tenere distinto l'orario della misura (measured_at) da quello in cui il
--     Pi l'ha ricevuta (received_at), perché il BME280 arriva dall'ESP32;
--   - registrare disponibilità e qualità della posizione, configurazione della
--     camera, provenienza delle misure ed eventuali errori;
--   - campioni dei sensori e scatti in tabelle separate, con cadenze proprie;
--   - versione del modello e risultati, risalendo all'immagine analizzata;
--   - sincronizzazione verso un sistema remoto senza duplicati: le chiavi sono
--     UUID generati sul Pi e ogni riga ha synced_at (NULL = non ancora inviata).
--
-- Tutti i timestamp sono TIMESTAMPTZ e vanno scritti in UTC.

CREATE EXTENSION IF NOT EXISTS pgcrypto;  -- gen_random_uuid() su PostgreSQL < 13

CREATE SCHEMA IF NOT EXISTS metadati;
SET search_path TO metadati;


-- ---------------------------------------------------------------------------
-- Tipi enumerati
-- ---------------------------------------------------------------------------

-- Le due applicazioni descritte nel README.
CREATE TYPE app_mode AS ENUM ('selettiva', 'continuativa');

-- Chi ha prodotto la misura: il BME280 passa dall'ESP32, gli altri sensori
-- sono letti direttamente dal Pi; 'dummy' per le prove al banco.
CREATE TYPE reading_source AS ENUM ('esp32', 'rpi', 'dummy');

CREATE TYPE log_level AS ENUM ('debug', 'info', 'warning', 'error', 'critical');


-- ---------------------------------------------------------------------------
-- Dispositivi e configurazione
-- ---------------------------------------------------------------------------

-- Una riga per ogni smart camera (es. hostname 'rpi5-03'). Serve a distinguere
-- i dati quando più box o il Pi sul drone confluiscono nello stesso archivio.
CREATE TABLE device (
    id          UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    hostname    TEXT NOT NULL UNIQUE,
    esp_board   TEXT,                 -- es. 'ESP32-CAM AI-Thinker' (provvisoria)
    description TEXT,
    created_at  TIMESTAMPTZ NOT NULL DEFAULT now()
);

-- Sensori installati sulla morsettiera. La configurazione (bus, pin, canale ADC,
-- libreria...) è quella di SENSORS_CONFIG in smartcam/sensors.py, salvata in
-- JSON perché cambia da un modello all'altro.
CREATE TABLE sensor (
    id           UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    device_id    UUID NOT NULL REFERENCES device(id),
    kind         TEXT NOT NULL,       -- bme280 | gps | water | soil_moisture | methane
    model        TEXT,                -- es. 'GY-BME280', 'MQ-4'
    interface    TEXT,                -- i2c | uart | adc | gpio_digital
    config       JSONB NOT NULL DEFAULT '{}',
    installed_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    removed_at   TIMESTAMPTZ,
    CHECK (removed_at IS NULL OR removed_at > installed_at)
);

-- Fotocamere collegate al Pi (Camera Module 3 + seconda ottica da scegliere).
CREATE TABLE camera (
    id         UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    device_id  UUID NOT NULL REFERENCES device(id),
    name       TEXT NOT NULL,         -- es. 'cam0', 'cam1'
    model      TEXT,                  -- es. 'Camera Module 3 (IMX708)'
    lens       TEXT,
    notes      TEXT,
    UNIQUE (device_id, name)
);


-- ---------------------------------------------------------------------------
-- Sessioni e risvegli
-- ---------------------------------------------------------------------------

-- Una sessione è un periodo in cui il Pi è acceso: un singolo risveglio
-- nell'app selettiva, oppure la finestra giornaliera nell'app continuativa.
-- Le cadenze e le impostazioni usate vanno in config per poterle ricostruire.
CREATE TABLE session (
    id          UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    device_id   UUID NOT NULL REFERENCES device(id),
    mode        app_mode NOT NULL,
    started_at  TIMESTAMPTZ NOT NULL DEFAULT now(),
    ended_at    TIMESTAMPTZ,
    config      JSONB NOT NULL DEFAULT '{}',  -- cadenze, fascia oraria, profilo camera...
    code_version TEXT,                        -- es. git describe / tag 'v0.1-banco'
    synced_at   TIMESTAMPTZ,
    CHECK (ended_at IS NULL OR ended_at >= started_at)
);

-- Decisioni prese dall'ESP32 nell'app selettiva (forecaster + decider), anche
-- quando NON sveglia il Pi: servono per confrontare energia e acquisizioni
-- evitate rispetto a una raccolta periodica. Vengono scaricate dall'ESP al
-- primo risveglio utile, quindi anche qui decided_at <> received_at.
CREATE TABLE wake_event (
    id                UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    device_id         UUID NOT NULL REFERENCES device(id),
    session_id        UUID REFERENCES session(id),   -- NULL se il Pi non è stato svegliato
    decided_at        TIMESTAMPTZ NOT NULL,          -- orologio dell'ESP32
    received_at       TIMESTAMPTZ NOT NULL DEFAULT now(),
    wake              BOOLEAN NOT NULL,
    forecast_temperature_c  REAL,
    forecast_humidity_pct   REAL,
    degree_days       REAL,
    bio_rule_passed   BOOLEAN,
    classifier_score  REAL,                          -- uscita HistGBT
    decider_version   TEXT,
    synced_at         TIMESTAMPTZ
);


-- ---------------------------------------------------------------------------
-- Misure dei sensori
-- ---------------------------------------------------------------------------
-- Ogni burst di lettura (vedi glossario) crea una riga in sensor_burst; le
-- singole tabelle per sensore puntano al burst. Un sensore che fallisce non
-- ha la sua riga e compare in sensors_failed, come nel CSV attuale.

CREATE TABLE sensor_burst (
    id             UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    device_id      UUID NOT NULL REFERENCES device(id),
    session_id     UUID REFERENCES session(id),
    started_at     TIMESTAMPTZ NOT NULL DEFAULT now(),
    sensors_ok     TEXT[] NOT NULL DEFAULT '{}',
    sensors_failed TEXT[] NOT NULL DEFAULT '{}',
    synced_at      TIMESTAMPTZ
);

-- Colonne comuni a tutte le tabelle di misura:
--   measured_at  quando il sensore ha fatto la misura (orologio della scheda
--                che l'ha letta: ESP32 per il BME280, Pi per gli altri);
--   received_at  quando il Pi l'ha salvata.

-- BME280: temperatura, umidità e pressione arrivano insieme dall'ESP32.
CREATE TABLE bme280 (
    id             UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    device_id      UUID NOT NULL REFERENCES device(id),
    burst_id       UUID REFERENCES sensor_burst(id) ON DELETE CASCADE,
    sensor_id      UUID REFERENCES sensor(id),
    source         reading_source NOT NULL DEFAULT 'esp32',
    measured_at    TIMESTAMPTZ NOT NULL,
    received_at    TIMESTAMPTZ NOT NULL DEFAULT now(),
    temperature_c  REAL CHECK (temperature_c BETWEEN -40 AND 85),
    humidity_pct   REAL CHECK (humidity_pct BETWEEN 0 AND 100),
    pressure_hpa   REAL CHECK (pressure_hpa BETWEEN 300 AND 1100),
    synced_at      TIMESTAMPTZ
);

-- GPS via UART (frasi NMEA $GPGGA). fix_quality è il campo "fix quality" della
-- GGA (0 = nessun fix): le righe senza fix si salvano comunque, così resta
-- traccia della disponibilità della posizione.
CREATE TABLE gps (
    id             UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    device_id      UUID NOT NULL REFERENCES device(id),
    burst_id       UUID REFERENCES sensor_burst(id) ON DELETE CASCADE,
    sensor_id      UUID REFERENCES sensor(id),
    source         reading_source NOT NULL DEFAULT 'rpi',
    measured_at    TIMESTAMPTZ NOT NULL,
    received_at    TIMESTAMPTZ NOT NULL DEFAULT now(),
    latitude       DOUBLE PRECISION CHECK (latitude BETWEEN -90 AND 90),
    longitude      DOUBLE PRECISION CHECK (longitude BETWEEN -180 AND 180),
    altitude_m     REAL,
    fix_quality    SMALLINT NOT NULL DEFAULT 0,
    satellites     SMALLINT CHECK (satellites >= 0),
    hdop           REAL,
    synced_at      TIMESTAMPTZ,
    CHECK (fix_quality = 0 OR (latitude IS NOT NULL AND longitude IS NOT NULL))
);

-- Umidità del suolo: tensione dall'MCP3008 e percentuale calibrata, oppure
-- solo wet_bool se il modulo è collegato all'uscita digitale.
CREATE TABLE soil (
    id             UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    device_id      UUID NOT NULL REFERENCES device(id),
    burst_id       UUID REFERENCES sensor_burst(id) ON DELETE CASCADE,
    sensor_id      UUID REFERENCES sensor(id),
    source         reading_source NOT NULL DEFAULT 'rpi',
    measured_at    TIMESTAMPTZ NOT NULL,
    received_at    TIMESTAMPTZ NOT NULL DEFAULT now(),
    voltage        REAL,
    moisture_pct   REAL CHECK (moisture_pct BETWEEN 0 AND 100),
    wet_bool       BOOLEAN,
    synced_at      TIMESTAMPTZ
);

-- Metano (serie MQ). ppm_approx è una stima: senza calibrazione del sensore
-- non va trattata come misura assoluta.
CREATE TABLE gas (
    id             UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    device_id      UUID NOT NULL REFERENCES device(id),
    burst_id       UUID REFERENCES sensor_burst(id) ON DELETE CASCADE,
    sensor_id      UUID REFERENCES sensor(id),
    source         reading_source NOT NULL DEFAULT 'rpi',
    measured_at    TIMESTAMPTZ NOT NULL,
    received_at    TIMESTAMPTZ NOT NULL DEFAULT now(),
    gas            TEXT NOT NULL DEFAULT 'CH4',
    voltage        REAL,
    ppm_approx     REAL CHECK (ppm_approx >= 0),
    alarm_bool     BOOLEAN,           -- uscita digitale DO, se usata
    synced_at      TIMESTAMPTZ
);

-- Sensore acqua (contatto digitale su GPIO).
CREATE TABLE water (
    id             UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    device_id      UUID NOT NULL REFERENCES device(id),
    burst_id       UUID REFERENCES sensor_burst(id) ON DELETE CASCADE,
    sensor_id      UUID REFERENCES sensor(id),
    source         reading_source NOT NULL DEFAULT 'rpi',
    measured_at    TIMESTAMPTZ NOT NULL,
    received_at    TIMESTAMPTZ NOT NULL DEFAULT now(),
    present        BOOLEAN,
    synced_at      TIMESTAMPTZ
);


-- ---------------------------------------------------------------------------
-- Immagini
-- ---------------------------------------------------------------------------

-- Una riga per foto. Il file resta sul disco (file_path), il DB ne conserva
-- hash e impostazioni. camera_settings contiene ciò che oggi finisce nel
-- sidecar JSON (risoluzione, qualità, profilo, autofocus, zoom/ROI...).
-- La posizione non è duplicata qui: si ricava dal GPS più vicino (vista sotto).
CREATE TABLE image (
    id              UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    device_id       UUID NOT NULL REFERENCES device(id),
    camera_id       UUID REFERENCES camera(id),
    session_id      UUID REFERENCES session(id),
    wake_event_id   UUID REFERENCES wake_event(id),
    captured_at     TIMESTAMPTZ NOT NULL,
    file_path       TEXT NOT NULL UNIQUE,
    sha256          CHAR(64) UNIQUE,  -- evita doppioni durante i trasferimenti
    width           INTEGER CHECK (width > 0),
    height          INTEGER CHECK (height > 0),
    size_bytes      BIGINT,
    camera_settings JSONB NOT NULL DEFAULT '{}',
    synced_at       TIMESTAMPTZ,      -- metadati inviati al remoto
    file_uploaded_at TIMESTAMPTZ,     -- file copiato sul remoto
    local_deleted_at TIMESTAMPTZ,     -- da valorizzare solo dopo file_uploaded_at
    CHECK (local_deleted_at IS NULL OR file_uploaded_at IS NOT NULL)
);


-- ---------------------------------------------------------------------------
-- Analisi delle immagini (computer vision)
-- ---------------------------------------------------------------------------

-- Versioni dei modelli, per sapere con quale modello è stato prodotto ogni
-- risultato.
CREATE TABLE cv_model (
    id          UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    name        TEXT NOT NULL,        -- es. 'bmsb-detector', 'afide-lanigero-seg'
    version     TEXT NOT NULL,
    task        TEXT NOT NULL CHECK (task IN ('detection', 'segmentation', 'classification')),
    target      TEXT,                 -- caso di studio: BMSB, api, bombi, afide lanigero...
    file_sha256 CHAR(64),
    created_at  TIMESTAMPTZ NOT NULL DEFAULT now(),
    UNIQUE (name, version)
);

-- Un'esecuzione di un modello su un'immagine, con latenza e memoria misurate
-- sul Pi (richieste dal piano). insect_count e colony_area_* sono i risultati
-- aggregati: conteggio per gli insetti, area delle colonie per l'afide.
CREATE TABLE cv_run (
    id              UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    image_id        UUID NOT NULL REFERENCES image(id) ON DELETE CASCADE,
    model_id        UUID NOT NULL REFERENCES cv_model(id),
    started_at      TIMESTAMPTZ NOT NULL DEFAULT now(),
    latency_ms      REAL,
    peak_memory_mb  REAL,
    insect_count    INTEGER CHECK (insect_count >= 0),
    colony_area_px  BIGINT CHECK (colony_area_px >= 0),
    colony_area_cm2 REAL CHECK (colony_area_cm2 >= 0),
    error           TEXT,
    synced_at       TIMESTAMPTZ,
    UNIQUE (image_id, model_id)
);

-- Singoli rilevamenti (bounding box in pixel dell'immagine originale).
-- mask_path punta alla maschera di segmentazione, se il modello ne produce.
CREATE TABLE detection (
    id          UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    cv_run_id   UUID NOT NULL REFERENCES cv_run(id) ON DELETE CASCADE,
    label       TEXT NOT NULL,
    confidence  REAL CHECK (confidence BETWEEN 0 AND 1),
    bbox_x      INTEGER,
    bbox_y      INTEGER,
    bbox_w      INTEGER CHECK (bbox_w > 0),
    bbox_h      INTEGER CHECK (bbox_h > 0),
    area_px     BIGINT,
    mask_path   TEXT,
    verified    BOOLEAN               -- annotazione manuale per la valutazione
);


-- ---------------------------------------------------------------------------
-- Consumi ed eventi di sistema
-- ---------------------------------------------------------------------------

-- Misure di energia per fase (avvio, caricamento modello, inferenza, halt...),
-- per sostituire i termini stimati nel manoscritto TMC.
CREATE TABLE energy_measure (
    id          UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    device_id   UUID NOT NULL REFERENCES device(id),
    session_id  UUID REFERENCES session(id),
    board       TEXT NOT NULL CHECK (board IN ('rpi', 'esp32', 'totale')),
    phase       TEXT NOT NULL,        -- boot | capture | model_load | inference | transfer | shutdown | halt | idle
    started_at  TIMESTAMPTZ NOT NULL,
    ended_at    TIMESTAMPTZ NOT NULL,
    energy_j    REAL,
    avg_power_w REAL,
    instrument  TEXT,                 -- strumento usato per la misura
    synced_at   TIMESTAMPTZ,
    CHECK (ended_at >= started_at)
);

-- Log ed errori di tutti i componenti. Le colonne *_id opzionali permettono
-- di collegare un errore allo scatto o al burst che l'ha generato.
CREATE TABLE log (
    id          BIGSERIAL PRIMARY KEY,
    device_id   UUID NOT NULL REFERENCES device(id),
    session_id  UUID REFERENCES session(id),
    image_id    UUID REFERENCES image(id) ON DELETE SET NULL,
    burst_id    UUID REFERENCES sensor_burst(id) ON DELETE SET NULL,
    logged_at   TIMESTAMPTZ NOT NULL DEFAULT now(),
    level       log_level NOT NULL,
    component   TEXT NOT NULL,        -- es. 'capture_client', 'sensors.gps', 'esp32'
    message     TEXT NOT NULL,
    details     JSONB,
    synced_at   TIMESTAMPTZ
);

-- Stima dello scarto tra orologio ESP32 e orologio del Pi, registrata a ogni
-- sincronizzazione: serve a correggere measured_at a posteriori.
CREATE TABLE clock_sync (
    id           BIGSERIAL PRIMARY KEY,
    device_id    UUID NOT NULL REFERENCES device(id),
    synced_at_pi TIMESTAMPTZ NOT NULL DEFAULT now(),
    esp_time     TIMESTAMPTZ NOT NULL,
    offset_ms    INTEGER NOT NULL,    -- pi - esp
    method       TEXT                 -- es. 'uart-handshake', 'ntp'
);


-- ---------------------------------------------------------------------------
-- Indici
-- ---------------------------------------------------------------------------

CREATE INDEX ON bme280   (device_id, measured_at);
CREATE INDEX ON gps      (device_id, measured_at);
CREATE INDEX ON soil     (device_id, measured_at);
CREATE INDEX ON gas      (device_id, measured_at);
CREATE INDEX ON water    (device_id, measured_at);
CREATE INDEX ON image    (device_id, captured_at);
CREATE INDEX ON sensor_burst (device_id, started_at);
CREATE INDEX ON wake_event   (device_id, decided_at);
CREATE INDEX ON log      (device_id, logged_at);
CREATE INDEX ON detection (cv_run_id);

-- Righe ancora da sincronizzare verso il remoto.
CREATE INDEX ON image    (captured_at) WHERE synced_at IS NULL;
CREATE INDEX ON sensor_burst (started_at) WHERE synced_at IS NULL;


-- ---------------------------------------------------------------------------
-- Viste
-- ---------------------------------------------------------------------------

-- Ogni immagine con le misure ambientali e la posizione più vicine nel tempo
-- (entro 10 minuti), così foto e sensori restano in tabelle separate con
-- cadenze indipendenti ma si possono esportare insieme nel dataset.
CREATE VIEW image_context AS
SELECT
    i.id            AS image_id,
    i.captured_at,
    i.file_path,
    c.name          AS camera,
    p.temperature_c,
    p.humidity_pct,
    p.pressure_hpa,
    p.measured_at   AS bme_measured_at,
    g.latitude,
    g.longitude,
    g.altitude_m,
    g.fix_quality,
    g.measured_at   AS gps_measured_at
FROM image i
LEFT JOIN camera c ON c.id = i.camera_id
LEFT JOIN LATERAL (
    SELECT * FROM bme280
    WHERE device_id = i.device_id
      AND measured_at BETWEEN i.captured_at - interval '10 minutes'
                          AND i.captured_at + interval '10 minutes'
    ORDER BY abs(extract(epoch FROM measured_at - i.captured_at))
    LIMIT 1
) p ON true
LEFT JOIN LATERAL (
    SELECT * FROM gps
    WHERE device_id = i.device_id
      AND fix_quality > 0
      AND measured_at BETWEEN i.captured_at - interval '10 minutes'
                          AND i.captured_at + interval '10 minutes'
    ORDER BY abs(extract(epoch FROM measured_at - i.captured_at))
    LIMIT 1
) g ON true;
