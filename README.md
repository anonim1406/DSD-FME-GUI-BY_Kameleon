
# DSD-FME GUI by Kameleon – Version 1.0

*A modern, feature-rich graphical interface for the powerful DSD-FME digital voice decoder – built for people, not just terminals.*

---

## 🚀 What's New in v1.0

### 🎧 Integrated "Audio Analysis" Tab

- **Real-time Spectrogram:** Military-styled, high-performance audio spectrum display.
- **Oscilloscope:** Live waveform visualization.
- **Live Signal Meters:** RMS signal strength and dominant frequency (Peak Freq).
- **Audio Output Control:** Select output device, control volume, and mute directly from the GUI.
- **Built-in Filters:** Adjustable Low-pass and High-pass filters to clean up the signal.

### 📓 Advanced "Logbook"

- **New Logbook Tab:** Replaces the basic event table with a more powerful logger.
- **Sortable Columns:** Sort entries by Time, TG, or ID.
- **Searchable Entries:** Real-time filtering/search.
- **Import/Export:** Load and save logs to/from CSV files.

### 🛠 Additional Tools

- **Recorder Tab:** Manage the built-in voice-activated recorder from DSD-FME.
- **Alerts Tab:** Configure custom two-tone sound alerts for specific TGs or Radio IDs.
- **Mini-Oscilloscope in Main Panel:** Quick signal preview in the config tab.
- **Log Search Function:** Search live output logs with ease.

### 📦 .exe Application

The entire project is bundled into a standalone **.exe** executable – no need to run from Python. Just double-click and go!

---

## ⚠️ Requirements

Before running the script version, install dependencies:

```bash
pip install PyQt5 numpy pyqtgraph sounddevice scipy
```

---

## 🧠 What Is This?

This is a Python-based GUI frontend for `dsd-fme`, an advanced digital signal decoder (DMR, P25, NXDN, YSF, etc.). It simplifies usage by offering graphical configuration instead of long command-line arguments.

---

## 🔧 Features

- Full tab-based configuration GUI.
- Real-time spectrum and oscilloscope.
- Logbook with CSV support and dynamic search.
- Voice-activated recorder manager.
- Customizable alerts.
- Audio filters (Low-pass, High-pass).
- Mini-signal display and log terminal search.
- Dark theme UI.

---

## 📦 How to Install & Run

1. **Install dependencies:**
   ```bash
   pip install PyQt5 numpy pyqtgraph sounddevice scipy
   ```

2. **Download DSD-FME:**
   [https://github.com/lwvmobile/dsd-fme](https://github.com/lwvmobile/dsd-fme)

3. **Extract the ZIP archive.**

4. **Place the GUI script** (`DSD-FME-GUI-BY_Kameleon.py`) in the same folder as `dsd-fme.exe`.

5. **Open terminal in that folder** and run:
   ```bash
   python3 DSD-FME-GUI-BY_Kameleon.py
   ```

Or simply launch the `.exe` version if available.

---

## 📜 License

- This GUI **does not include** or modify the `dsd-fme` code.
- DSD-FME is licensed under **GPLv2**, so this GUI is also open-source.

---

## 👤 Author

- **GUI Developer:** Kameleon   
- **Contact:** parrotos.desktop@protonmail.com

---

## ❤️ Want to Help?

- Report a bug 🐞  
- Suggest a feature 💡  
- Or... send a good DMR stream for testing 😄

---

# 🇵🇱 DSD-FME GUI by Kameleon – Wersja 1.0

*Nowoczesny, rozbudowany interfejs graficzny do potężnego dekodera DSD-FME — zaprojektowany z myślą o użytkowniku, nie tylko terminalu.*

---

## 🚀 Co nowego w wersji 1.0

### 🎧 Zintegrowana zakładka "Audio Analysis"

- **Spektrogram czasu rzeczywistego:** Stylizowany na „militarny” analizator widma.
- **Oscyloskop:** Podgląd fali dźwiękowej na żywo.
- **Mierniki RMS i Peak Freq:** Pomiar siły sygnału i dominującej częstotliwości.
- **Regulacja audio:** Wybór wyjścia, kontrola głośności i wyciszenie.
- **Filtry audio:** Filtry dolno- i górnoprzepustowe z regulacją częstotliwości odcięcia.

### 📓 Zaawansowany "Logbook"

- **Nowa zakładka logbook:** Zastępuje prostą listę zdarzeń.
- **Sortowanie kolumn:** Po czasie, TG i ID.
- **Wyszukiwanie:** Dynamiczne filtrowanie wpisów.
- **Import/Eksport CSV:** Zapis i wczytywanie historii transmisji.

### 🛠 Narzędzia Dodatkowe

- **Zakładka "Recorder":** Łatwe zarządzanie funkcją nagrywania.
- **Zakładka "Alerts":** Dwutonowe alerty dźwiękowe dla TG i ID.
- **Mini-oscyloskop:** Szybki podgląd sygnału.
- **Wyszukiwarka logów:** Szukanie w danych wyjściowych terminala.

### 📦 Wersja .exe

Projekt dostępny jako niezależny plik **.exe** — nie wymaga uruchamiania przez Pythona.

---

## ⚠️ Wymagania

Przed uruchomieniem wersji skryptowej zainstaluj zależności:

```bash
pip install PyQt5 numpy pyqtgraph sounddevice scipy
```

---

## 🧠 Co to jest?

GUI w Pythonie do `dsd-fme` – dekodera sygnałów cyfrowych (DMR, P25, NXDN, YSF itd.). Dzięki interfejsowi graficznemu nie musisz wpisywać długich komend ręcznie.

---

## 🔧 Funkcje

- Konfiguracja przez zakładki.
- Spektrogram i oscyloskop.
- Logbook z CSV i wyszukiwaniem.
- Nagrywanie aktywowane głosem.
- Alerty dźwiękowe.
- Filtry audio.
- Mini-podgląd sygnału i terminal.
- Ciemny motyw.

---

## 📦 Instalacja i uruchamianie

1. **Zainstaluj zależności:**
   ```bash
   pip install PyQt5 numpy pyqtgraph sounddevice scipy
   ```

2. **Pobierz DSD-FME:**
   [https://github.com/lwvmobile/dsd-fme](https://github.com/lwvmobile/dsd-fme)

3. **Wypakuj archiwum ZIP.**

4. **Umieść skrypt GUI** (`DSD-FME-GUI-BY_Kameleon.py`) w tym samym folderze co `dsd-fme.exe`.

5. **Otwórz terminal w tym folderze** i uruchom:
   ```bash
   python3 DSD-FME-GUI-BY_Kameleon.py
   ```

Lub uruchom wersję `.exe`, jeśli ją posiadasz.

---

## 📜 Licencja

GUI **nie zawiera** ani nie modyfikuje kodu `dsd-fme`.

`dsd-fme` działa na licencji **GPLv2**, więc GUI również jest **open-source**.

---

## 👤 Autor

- **Autor GUI:** Kameleon  
- **Kontakt:** parrotos.desktop@protonmail.com

---

## ❤️ Wsparcie

- Zgłoś błąd 🐞  
- Zaproponuj nową funkcję 💡  
- A może... podeślij dobry stream DMR do testów 😄
