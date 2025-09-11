# Instructions: Connecting DSD-FME GUI BY Kameleon with SDR++ via TCP
*(Polish version below / wersja polska poniżej)*

---

## 🇬🇧 Instructions in English

1. Download **SDR++** from its official repository: [SDR++ GitHub](https://github.com/AlexandreRouma/SDRPlusPlus).  
2. Download **DSD-FME GUI BY Kameleon**.  [Releases](https://github.com/anonim1406/DSD-FME-GUI-BY_Kameleon/releases/tag/DSD-FME-GUI-BY-Kameleon)
3. Download **two separate copies of DSD-FME** – link here: [DSD-FME GitHub](https://github.com/lwvmobile/dsd-fme).  
4. Place the GUI and both DSD-FME copies in the same folder.  
5. Launch **SDR++**.  
6. Go to **Module Manager**.  
7. Add and name the plugin **`network_sink`**.  
8. Open the **Sinks** tab and select **Network**.  
9. Set your receive frequency and choose **NFM** modulation with a **12.5 kHz bandwidth**.  
10. In the **Sinks** tab you will see the IP address and port (default is `127.0.0.1:7355`). Click **Start** – **important: do this before launching the GUI**.  
11. Launch the **GUI** and select the path to the DSD-FME executable.  
12. If you want to monitor **two frequencies at the same time**, configure a second independent copy of DSD-FME.  
13. In the GUI’s **Input** tab, select **TCP** and enter your IP and port in the format `ip:port` (e.g. `127.0.0.1:7355`).  
14. Configure the rest of the program as needed.  
15. Start decoding by clicking **Start**.  
16. Go back to SDR++ – in the **Sinks** tab you should see the status **Connected**.  
17. Done – everything should now work correctly.  

---

## 🇵🇱 Instrukcja po polsku

1. Pobierz **SDR++** z oficjalnego repozytorium: [SDR++ GitHub](https://github.com/AlexandreRouma/SDRPlusPlus).  
2. Pobierz **DSD-FME GUI BY Kameleon**.  [Releases](https://github.com/anonim1406/DSD-FME-GUI-BY_Kameleon/releases/tag/DSD-FME-GUI-BY-Kameleon)
3. Pobierz **dwie niezależne kopie programu DSD-FME** – link tutaj: [DSD-FME GitHub](https://github.com/lwvmobile/dsd-fme).  
4. Umieść GUI i obie kopie DSD-FME w jednym folderze.  
5. Uruchom **SDR++**.  
6. Przejdź do **Module Manager**.  
7. Dodaj i nazwij plugin **`network_sink`**.  
8. Wejdź w zakładkę **Sinks** i wybierz **Network**.  
9. Ustaw częstotliwość odbioru oraz modulację **NFM** z szerokością pasma **12500 Hz**.  
10. W zakładce **Sinks** pojawi się adres IP oraz port (domyślnie `127.0.0.1:7355`). Kliknij **Start** – **ważne: zrób to przed uruchomieniem GUI**.  
11. Uruchom **GUI** i wskaż ścieżkę do pliku wykonywalnego DSD-FME.  
12. Jeśli chcesz nasłuchiwać **dwóch częstotliwości jednocześnie**, skonfiguruj drugą, niezależną kopię DSD-FME.  
13. W zakładce **Input** w GUI wybierz **TCP** i wpisz adres IP oraz port w formacie `adres:port` (np. `127.0.0.1:7355`).  
14. Skonfiguruj resztę programu według własnych potrzeb.  
15. Uruchom dekodowanie klikając **Start**.  
16. Wróć do SDR++ – w zakładce **Sinks** powinien pojawić się status **Connected**.  
17. Gotowe – połączenie powinno działać poprawnie.  

---
