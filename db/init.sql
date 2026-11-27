CREATE SCHEMA IF NOT EXISTS metadati;

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
