# Configurazione Raspberry Pi ed ESP32

Questa guida raccoglie le configurazioni e le prove previste per il prototipo. Per obiettivi e requisiti fa fede [il piano operativo](plan.pdf); il manoscritto [main.pdf](main.pdf) descrive il controllo biology-aware di riferimento. Le istruzioni hardware qui riportate sono proposte da verificare sul banco e sul modello esatto delle schede.

## Stato attuale

Il firmware in `esp32/src/main.cpp` è una bozza per AI-Thinker ESP32-CAM: inizializza la camera, ma scarta i frame e `eventDetected()` restituisce sempre `false`. Il wake è provabile solo dal monitor seriale con `w`. Il firmware non legge il BME280 e non implementa forecaster o decider. Il circuito che collega WAKE ai pad J2 non è definito. Non collegare GPIO14 direttamente a J2.

Il Pi dispone di uno script di cattura e di uno script di lettura sensori, ma i sensori dichiarati non sono una configurazione di campo verificata. Database, acquisizione completa continuativa e analisi visiva sono ancora da sviluppare.

## 1. Raspberry Pi 5

### Stati e configurazione di halt

Nel progetto si usa l’arresto del sistema operativo (halt), mantenendo il Pi collegato all’alimentazione, così che il pulsante o un’interfaccia corretta sui pad J2 possano riavviarlo. Il Pi non è riaccendibile tramite J2 se la sua alimentazione viene rimossa. ESP32 e BME280 devono restare alimentati durante il riposo del Pi.

Per configurare l’EEPROM, seguire la documentazione Raspberry Pi relativa alla versione installata. Le impostazioni previste dal progetto sono:

```ini
POWER_OFF_ON_HALT=1
WAKE_ON_GPIO=0
```

Verificare le opzioni effettive con `sudo rpi-eeprom-config` e misurare i livelli elettrici prima di collegare altre schede. Il consumo indicato nei documenti è una stima di progetto, non una misura garantita per ogni alimentatore e configurazione.

### Segnale ALIVE proposto

La configurazione documentata usa GPIO17 sul Pi come uscita e GPIO13 sull’ESP come ingresso. Nel file `/boot/firmware/config.txt` è proposta la riga:

```ini
gpio=17=op,dh
```

Il collegamento proposto è GPIO17 Pi → GPIO13 ESP, con massa comune e pulldown lato ESP. Verificare il comportamento in avvio, funzionamento, shutdown e halt. ALIVE indica solo il livello del GPIO, non che Linux abbia completato l’avvio o sia pronto.

### Esempio di configurazione software

Il servizio [insect-capture.service](raspberry_pi/insect-capture.service) è configurato per l’installazione `/home/rpi5-03/tesi`. Prima di installarlo, aggiornare utente, directory di lavoro, file ambiente e percorso dello script in base al Pi effettivo. Il servizio fa una cattura singola e richiede `poweroff` dopo il completamento riuscito.

```bash
sudo cp raspberry_pi/insect-capture.service /etc/systemd/system/
sudo systemctl daemon-reload
sudo systemctl enable insect-capture.service
```

Non abilitarlo durante prove di wake o raccolte continuative: il Pi si spegnerebbe dopo la cattura. Per eseguire manualmente il flusso singolo dalla root del progetto:

```bash
bash raspberry_pi/capture_rpi.sh --oneshot
```

Il wrapper richiede un ambiente Python configurato tramite pyenv o `PYENV_ROOT`. Copiare [`.env.systemd.example`](raspberry_pi/.env.systemd.example) in `.env.systemd` nella root del progetto sul Pi e impostare i percorsi locali. Il modello contiene valori di esempio, non una configurazione pronta per tutte le installazioni.

## 2. ESP32 e BME280

La board selezionata in `esp32/platformio.ini` è al momento `esp32cam`. Il firmware usa GPIO14 per WAKE e GPIO13 per ALIVE. Questi pin e il pinout camera valgono per la configurazione di lavoro attuale; vanno rivalutati se cambia scheda. GPIO21 è occupato dal segnale camera Y5 su AI-Thinker ESP32-CAM, quindi non è disponibile per I²C in questa configurazione.

Il piano colloca il BME280 all’esterno del box, nella sua custodia, collegato **solo all’ESP32**. Alimentazione, livelli logici, SDA/SCL e indirizzo `0x76`/`0x77` vanno verificati sul modulo reale. Il codice ESP non contiene ancora il driver BME. Protocollo ESP–Pi, formato dei dati e sincronizzazione dei timestamp non sono definiti.

## 3. Interfaccia WAKE/J2

Il firmware porta GPIO14 alto per 200 ms. Questo è un segnale logico per un circuito esterno; non costituisce il circuito di interfaccia. Prima del collegamento occorre progettare un dispositivo che simuli il pulsante sui pad J2, verificarne schema e livelli elettrici e provare separatamente l’impulso. Non applicare tensioni ai pad e non assumere che uno dei due sia massa senza verifica. Una chiusura prolungata può avere effetti diversi da una pressione breve.

Il codice evita di inviare WAKE quando ALIVE è alto, ma tale controllo dipende dal corretto funzionamento del GPIO e non equivale a un controllo di stato del sistema operativo.

## 4. Prove al banco

Procedere per sottosistemi e annotare scheda, pin, alimentazioni, misure e risultato:

1. Verificare il boot e lo shutdown del Pi da solo, e controllare le impostazioni EEPROM.
2. Verificare che ESP e BME siano alimentati in modo indipendente dallo stato del Pi.
3. Provare il BME280 sull’ESP quando il relativo firmware sarà disponibile; controllare indirizzo e plausibilità delle misure.
4. Misurare ALIVE sul Pi acceso e in halt prima di collegarlo all’ingresso ESP.
5. Progettare e verificare il circuito J2 isolatamente dal GPIO dell’ESP.
6. Con l’interfaccia verificata, provare il comando seriale `w` con Pi acceso: ALIVE alto dovrebbe far saltare l’impulso.
7. Provare il wake da halt e verificare forma e durata dell’impulso, boot del Pi e comportamento ALIVE.
8. Verificare la cattura della camera ESP. Questo non verifica il rilevamento: lo stub non classifica i frame.
9. Solo dopo l’implementazione del rilevamento, verificare casi positivi/negativi, cooldown e comportamento con Pi acceso e in halt.
10. Attivare il servizio di cattura selettiva solo dopo aver verificato acquisizione e spegnimento pulito.

Per build e test seriale, dalla cartella `esp32/`:

```bash
pio run
pio run -t upload
pio device monitor
```

Il monitor usa 115200 baud. Inviare `w` è una prova manuale del percorso di wake, non una prova di rilevamento automatico.

## 5. Sensori sul Pi e modalità di acquisizione

Secondo il piano, GPS, acqua, suolo e metano sono collegati al Pi; il BME280 ambientale è collegato solo all’ESP. Le interfacce previste (UART per GPS, ADC/SPI per sensori analogici e GPIO per ingresso digitale) dipendono dai modelli acquistati e vanno verificate. I valori di pin e calibrazione in `raspberry_pi/sensors.py` sono configurazione d’esempio.

Il flusso `--oneshot` esegue una foto, poi una lettura sequenziale dei sensori abilitati e termina; il servizio può quindi spegnere il Pi. La modalità continuativa prevista dal piano richiede cadenze indipendenti per misure e fotografie, un database e una finestra di attività. Queste funzioni non sono ancora implementate come servizio completo.

## 6. Organizzazione dei file

- `esp32/`: firmware e configurazione PlatformIO.
- `raspberry_pi/`: script di acquisizione, sensori, unità systemd, esempio ambiente e CSV.
- `backend/`: helper Python GPS, BME280 da banco e metadati.
- `configurazioni_fisiche/`: schemi e documenti hardware presenti nel repository; il contenuto di questa cartella è rimasto invariato.
- `README.md`: contesto, architettura e stato del progetto.
- `CODE_GUIDE.md`: descrizione del codice e note sulla provenienza.

## Riferimenti

- [Piano operativo](plan.pdf)
- [Manoscritto scientifico](main.pdf)
- [Documentazione Raspberry Pi](https://www.raspberrypi.com/documentation/computers/raspberry-pi.html)
- [Codice firmware ESP32](esp32/src/main.cpp)
- [Guida al codice](CODE_GUIDE.md)
