"""Package Python della smart camera, eseguito sul Raspberry Pi.

In Python, ``__init__.py`` marca la cartella ``smartcam`` come package e
viene eseguito quando si importa ``smartcam`` o uno dei suoi moduli. Questo
file non avvia la camera, non legge sensori e non contiene il programma
principale: documenta il package e consente gli import relativi (per esempio
``from .gps_reader import get_gps_fix``). Per questo gli script si lanciano
come moduli, dalla cartella ``raspberry_pi/`` con ``python3 -m smartcam...``.

Moduli del package:

- ``capture_client``: scatta le foto con rpicam-still e aggiunge il GPS;
- ``sensors``: legge una volta i sensori del Pi e aggiunge una riga al CSV;
- ``gps_reader``: legge una posizione dal GPS via seriale (frasi NMEA);
- Il BME280 è gestito dal firmware ESP32 in ``firmware/esp32/src/`` (non è un modulo di questo package);
- ``photo_metadata``: scrive e rilegge il file JSON "sidecar" accanto a ogni foto.

I moduli eseguibili si lanciano dalla cartella ``raspberry_pi/`` con
``python3 -m smartcam.<modulo>``: lanciarli come file
(``python3 smartcam/sensors.py``) non funziona, perché usano import relativi.
"""

# Provenienza: file scritto da noi. Serve a documentare il package Python
# ``smartcam`` e a consentire gli import relativi; non contiene codice di
# avvio o lettura dei sensori. Le fonti esterne sono indicate nei moduli.
