# 🎛️ DSD-FME GUI by Kameleon v2.2

> ⚠️ **IMPORTANT NOTICE:**  
> I am **not the author** of DSD-FME. This GUI is only a graphical frontend that works on top of it. All credit for the decoder itself goes to the original creators of DSD and DSD-FME.

> ⚠️ **FIRST RUN INSTRUCTIONS:**  
> Please **run the app as Administrator** the first time you launch it.  
> If you're using the installer, you may need to **temporarily disable your antivirus** to avoid false positives.

> ⚠️ **Note:** This project is still under active development. Some features might not work yet or could behave unpredictably.

> ✅ **Good news:** The **latest installer includes the required `dsd-fme.exe` files** – you don’t need to download them separately.

---

DSD-FME GUI by Kameleon is a modern graphical interface for the powerful DSD-FME digital voice decoder. No more terminal commands – just configure, monitor, analyze, and archive transmissions in an intuitive environment.

## 🚀 Features

- **Complete GUI Configuration:** All DSD-FME options available via interactive tabs and toggles.
- **Real-Time Signal Analysis:**
  - Audio Spectrogram
  - Oscilloscope
  - Signal Meters (RMS & Peak Frequency)
- **Advanced Logbook:**
  - Records every transmission with timestamps
  - Add your own notes and tags
  - Filter by date or text, sort by columns
  - Export/import to `.csv`
- **Live Map Integration:**
  - Based on OpenStreetMap
  - Auto-markers using LRRP/GPS data
  - Dark theme consistent with the GUI
- **Alias System:** Rename Talkgroups and Radio IDs for easier identification.
- **Stats & Charts:** Activity graphs based on logbook data.
- **Recording Manager:** Automatically records detected transmissions.
- **Custom Alerts:** Set `.wav` alerts for specific TGs or Radio IDs.
- **Theme Options:** Light/dark themes included for user comfort.

## 📋 Requirements

### Compiled Version (.exe)
- Windows 64-bit
- ✅ Includes `dsd-fme.exe`

### Script Version (.py)
- Python 3.x
- Required packages:
  ```bash
  pip install PyQt5 numpy pyqtgraph sounddevice scipy folium PyQtWebEngine
  ```
- `dsd-fme.exe` must be in the same folder or configured in settings.

## 🛠️ Installation

### Recommended (Installer)
1. Download the latest `DSD-FME-GUI_v2.2_Installer.exe` from the [Releases](https://github.com/).
2. Temporarily **disable antivirus** during installation.
3. Run the installer and follow the steps.
4. **Right-click and run as Administrator** on first launch.
5. Start decoding! `dsd-fme.exe` is already included.

### Manual (Python Script)
1. Install dependencies as shown above.
2. Place `DSD-FME-GUI-BY_Kameleon.py` and `dsd-fme.exe` in the same folder.
3. Run:
   ```bash
   python DSD-FME-GUI-BY_Kameleon.py
   ```

## 📜 License

- **DSD-FME Core:** ISC + GNU GPLv2
- **GUI Interface:** GNU General Public License, Version 2 (GPLv2)

## 🏆 Credits

Huge thanks to **lwvmobile** and the entire community behind DSD and DSD-FME. Without their work, this frontend wouldn’t exist.

---

# 🎛️ DSD-FME GUI by Kameleon v2.2 (PL)

> ⚠️ **WAŻNE:**  
> Nie jestem autorem DSD-FME – stworzyłem tylko graficzną nakładkę na ten dekoder. Cała zasługa należy do twórców oryginalnego DSD i DSD-FME.

> ⚠️ **PIERWSZE URUCHOMIENIE:**  
> **Uruchom aplikację jako Administrator** przy pierwszym starcie.  
> Jeśli używasz instalatora – **tymczasowo wyłącz antywirusa**, aby uniknąć problemów z uruchomieniem.

> ⚠️ **Projekt w budowie:** Niektóre funkcje mogą jeszcze nie działać lub być testowane.

> ✅ **Dobra wiadomość:** Najnowszy instalator **zawiera pliki `dsd-fme.exe`**, więc nie trzeba ich szukać osobno.

---

DSD-FME GUI by Kameleon to zaawansowany interfejs graficzny dla dekodera mowy cyfrowej DSD-FME. Umożliwia łatwą konfigurację i analizę sygnału bez znajomości terminala.

## 🚀 Główne Funkcje

- **Pełna konfiguracja przez GUI** – wszystkie opcje DSD-FME dostępne przez zakładki.
- **Analiza sygnału na żywo:**
  - Spektrogram
  - Oscyloskop
  - Mierniki RMS i częstotliwości
- **Logbook (dziennik transmisji):**
  - Czas rozpoczęcia i zakończenia każdej transmisji
  - Możliwość dodawania notatek i tagów
  - Filtrowanie, sortowanie, eksport/import `.csv`
- **Widok Mapy:**
  - OpenStreetMap w ciemnym motywie
  - Automatyczne znaczniki z GPS/LRRP
- **Aliasowanie:** Własne nazwy dla Talkgroupów i Radio ID
- **Statystyki i wykresy:** Najaktywniejsze grupy i użytkownicy
- **Menedżer nagrań:** Nagrywanie po wykryciu transmisji
- **Alerty dźwiękowe:** Obsługa plików `.wav` dla wybranych TG/ID
- **Personalizacja interfejsu:** Ciemne i jasne motywy do wyboru

## 📋 Wymagania

### Wersja .exe
- Windows 64-bit
- ✅ `dsd-fme.exe` dołączony

### Wersja skryptowa (.py)
- Python 3.x
- Wymagane biblioteki:
  ```bash
  pip install PyQt5 numpy pyqtgraph sounddevice scipy folium PyQtWebEngine
  ```
- Plik `dsd-fme.exe` w tym samym folderze lub ustawiony w konfiguracji.

## 🛠️ Instalacja

### Instalator (zalecany)
1. Pobierz `DSD-FME-GUI_v2.2_Installer.exe` z sekcji [Releases](https://github.com/).
2. Tymczasowo **wyłącz antywirusa**.
3. Uruchom instalator i zainstaluj program.
4. Przy pierwszym starcie – **uruchom jako Administrator**.
5. Gotowe! Wszystko jest już na miejscu, w tym `dsd-fme.exe`.

### Skrypt Python
1. Zainstaluj wymagane biblioteki.
2. Umieść `DSD-FME-GUI-BY_Kameleon.py` oraz `dsd-fme.exe` w tym samym katalogu.
3. Uruchom w terminalu:
   ```bash
   python DSD-FME-GUI-BY_Kameleon.py
   ```

## 📜 Licencja

- **DSD-FME:** licencje ISC oraz GNU GPLv2
- **GUI:** na licencji GNU GPLv2 (wolne oprogramowanie)

## 🏆 Podziękowania

Ogromne dzięki dla **lwvmobile** i wszystkich kontrybutorów DSD i DSD-FME. Bez ich dekodera ta nakładka by nie powstała 🙌
