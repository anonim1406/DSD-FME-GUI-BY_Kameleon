
# DSD-FME GUI by Kameleon – Version 0.9

*A modern and user-friendly graphical interface for the powerful DSD-FME digital voice decoder – built for people, not just terminals.*

---

## 🚀 What's New in v0.9

- **Voice Event History:** Logs detected digital voice transmissions in a clear table.
- **Voice-Activated Recorder:** Manage recordings based on voice activity.
- **Audio Alerts:** Play custom sounds for specific Talkgroups (TG) or Radio IDs.
- **CSV Export:** Save the voice log for further analysis.
- **Log Search:** Quickly search within terminal output.
- **Dark Mode:** Eyes-friendly dark UI theme.

---

## ⚠️ Notes and Limitations

- **Run from Terminal Only:** Currently, double-clicking the script may not work properly due to audio handling. Use the terminal.
- **Recording Feature is Experimental:** The recording function (in the "Recorder" tab) might not work in all situations.

---

## 🧠 What Is This?

This is a Python-based GUI frontend for `dsd-fme`, an advanced digital signal decoder (DMR, P25, NXDN, YSF, etc.). It simplifies usage by offering graphical configuration instead of long command-line arguments.

---

## 🔧 Features

- Tab-based full configuration panel.
- Live status display: TG, ID, Color Code, signal info.
- History of decoded voice events with export option.
- Configurable voice-activated recording system.
- Custom sound alerts for TG/ID events.
- Integrated log search.
- Dark mode for comfortable use.

---

## 📦 How to Install & Run

1. **Install PyQt5:**
   ```bash
   pip install PyQt5
   ```

2. **Download DSD-FME:**
   [https://github.com/lwvmobile/dsd-fme](https://github.com/lwvmobile/dsd-fme)

3. **Extract the ZIP archive.**

4. **Place the GUI script** in the same directory as `dsd-fme.exe`.

5. **Open Terminal in that directory**, then run:
   ```bash
   python3 DSD-FME_GUI.py
   ```

---

## 📜 License

- This GUI **does not include** or modify the `dsd-fme` code.
- DSD-FME is GPLv2 licensed, so this GUI is also **open-source**.

---

## 👤 Author

- **GUI Developer:** Kameleon (formerly SP8UEV)  
- **Contact:** parrotos.desktop@protonmail.com  
- *Note:* I did not create `dsd-fme` – I just made this GUI to make it easier to use.

---

## ❤️ Want to Help?

- Report a bug 🐞  
- Suggest a new feature 💡  
- Or... send a clean DMR stream for testing 😄

---

# 🇵🇱 DSD-FME GUI by Kameleon – Wersja 0.9

*Nowoczesny interfejs graficzny do potężnego dekodera DSD-FME — zaprojektowany z myślą o użytkowniku, nie tylko terminalu.*

---

## 🚀 Co nowego w wersji 0.9

- **Historia zdarzeń głosowych:** Automatyczne logowanie transmisji w czytelnej tabeli.
- **Nagrywanie aktywowane głosem:** Prosty manager nagrań z aktywacją głosem.
- **Alerty dźwiękowe:** Powiadomienia dźwiękowe dla konkretnych TG lub ID.
- **Eksport do CSV:** Zapis historii transmisji do pliku CSV.
- **Wyszukiwanie w logu:** Szybkie znajdowanie informacji w konsoli.
- **Ciemny motyw:** Przyjazny dla oczu interfejs graficzny.

---

## ⚠️ Ważne Uwagi

- **Uruchamianie tylko z terminala:** Kliknięcie dwukrotne może nie działać poprawnie (problem z obsługą dźwięku). Użyj terminala.
- **Nagrywanie jest eksperymentalne:** Funkcja nagrywania może nie działać w każdej sytuacji.

---

## 🧠 Co to jest?

GUI w Pythonie do `dsd-fme` — zaawansowanego dekodera cyfrowych sygnałów radiowych (DMR, P25, NXDN, YSF itd.). Dzięki GUI konfiguracja i uruchamianie są proste i nie wymagają znajomości długich komend.

---

## 🔧 Funkcje

- Pełna konfiguracja przez zakładki.
- Panel stanu z informacjami: TG, ID, CC, sygnał.
- Historia zdarzeń z eksportem do CSV.
- Manager nagrywania aktywowanego głosem.
- Alerty dźwiękowe konfigurowane przez użytkownika.
- Przeszukiwanie logu i ciemny motyw.

---

## 📦 Jak zainstalować i uruchomić?

1. **Zainstaluj PyQt5:**
   ```bash
   pip install PyQt5
   ```

2. **Pobierz DSD-FME z:**
   [https://github.com/lwvmobile/dsd-fme](https://github.com/lwvmobile/dsd-fme)

3. **Wypakuj archiwum ZIP.**

4. **Umieść ten skrypt GUI** w tym samym folderze co `dsd-fme.exe`.

5. **Otwórz terminal** w tym folderze i uruchom GUI:
   ```bash
   python3 DSD-FME_GUI.py
   ```

---

## 📜 Licencja

- GUI **nie zawiera** ani nie modyfikuje kodu `dsd-fme`.
- DSD-FME działa na licencji **GPLv2**, więc to GUI także jest **open-source**.

---

## 👤 Autor

- **Twórca GUI:** Kameleon (dawniej SP8UEV)  
- **Kontakt:** parrotos.desktop@protonmail.com  
- *Uwaga:* Nie jestem autorem `dsd-fme` – tylko zrobiłem GUI, by korzystanie było prostsze.

---

## ❤️ Wesprzyj projekt

- Zgłoś błąd 🐞  
- Zaproponuj nową funkcję 💡  
- A może... podeślij dobry stream DMR do testów 😄
