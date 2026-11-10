"""Software della smart camera lato Raspberry Pi.

Moduli del package:

- ``capture_client``: scatta le foto con rpicam-still e aggiunge il GPS;
- ``sensors``: legge una volta i sensori del Pi e aggiunge una riga al CSV;
- ``gps_reader``: legge una posizione dal GPS via seriale (frasi NMEA);
- ``bme_reader``: legge un BME280 collegato direttamente al Pi (solo prove al banco);
- ``photo_metadata``: scrive e rilegge il file JSON "sidecar" accanto a ogni foto.

I moduli eseguibili si lanciano dalla cartella ``raspberry_pi/`` con
``python3 -m smartcam.<modulo>``: lanciarli come file
(``python3 smartcam/sensors.py``) non funziona, perché usano import relativi.
"""

# Provenienza: file scritto da noi, serve solo a rendere ``smartcam`` un
# package Python. Le fonti esterne sono indicate all'inizio di ogni modulo.
