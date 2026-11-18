#pragma once

#include <Adafruit_BME280.h>

// Inizializza il BME280 sul bus I2C indicato. SDA/SCL vanno scelti in base
// alla scheda ESP32 effettiva e non devono essere condivisi con la camera.
bool beginBme280(int sdaPin, int sclPin, uint8_t address = 0x76);

// Legge i valori compensati dal driver e li restituisce nelle unità indicate.
bool readBme280(float &temperatureC, float &humidityPct, float &pressureHpa);
