#include "bme_reader.h"

#include <Wire.h>

// Il driver Adafruit (MIT) legge e compensa i valori del sensore:
// https://github.com/adafruit/Adafruit_BME280_Library

namespace {
Adafruit_BME280 sensor;
bool initialized = false;
}

bool beginBme280(int sdaPin, int sclPin, uint8_t address) {
  Wire.begin(sdaPin, sclPin);
  initialized = sensor.begin(address, &Wire);
  return initialized;
}

bool readBme280(float &temperatureC, float &humidityPct, float &pressureHpa) {
  if (!initialized) {
    return false;
  }

  temperatureC = sensor.readTemperature();
  humidityPct = sensor.readHumidity();
  pressureHpa = sensor.readPressure() / 100.0F;
  return true;
}
