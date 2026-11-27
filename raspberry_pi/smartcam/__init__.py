"""Package Python della smart camera, eseguito sul Raspberry Pi.

Moduli:

- ``capture_client``: scatta le foto e scrive accanto a ognuna il CSV dei metadati;
  è il programma principale, sia per l'app selettiva sia per quella continuativa;
- ``esp_link``: scarica dall'ESP32 misure del BME280 ed eventi della camera
  (data/bme280.csv, data/camera_events.csv);
- ``sensors``: legge i sensori collegati al Pi (data/sensors.csv);
- ``gps_reader``: legge una posizione dal GPS (frasi NMEA);
- ``storage``: scrittura dei file CSV;
- ``config``: percorsi, porte seriali e cadenze.

Usano import relativi, quindi si lanciano come moduli dalla cartella
``raspberry_pi/``, per esempio ``python3 -m smartcam.esp_link``. Lanciarli
come file (``python3 smartcam/sensors.py``) non funziona.
"""
# Provenienza: file scritto da noi.
