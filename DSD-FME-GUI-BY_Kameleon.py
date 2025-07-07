import sys
import os
import wave
from datetime import datetime, timedelta
from collections import Counter
import subprocess
import json
import shlex
import threading
import csv
import socket

# --- Sprawdzanie zależności ---
def import_or_fail(module_name, package_name=None):
    if package_name is None: package_name = module_name
    try:
        __import__(module_name)
        print(f"[OK] Library '{module_name}' loaded successfully.")
        return True
    except ImportError as e:
        print("-" * 60); print(f"[CRITICAL ERROR] Could not import library: '{module_name}'."); print(f"Please ensure the package '{package_name}' is installed in the correct Python environment."); print(f"System error details: {e}"); print("-" * 60)
        input("Press Enter to exit..."); sys.exit(1)

print("--- Checking dependencies ---")
import_or_fail("numpy"); import_or_fail("pyqtgraph"); import_or_fail("sounddevice"); import_or_fail("cffi"); import_or_fail("scipy")
print("--- All dependencies found. Starting application... ---")


from PyQt5.QtWidgets import *
from PyQt5.QtGui import QFont, QPalette, QColor, QTextCursor, QKeySequence
from PyQt5.QtMultimedia import QSound
from PyQt5.QtCore import Qt, QThread, pyqtSignal, QObject, pyqtSlot, QTimer, QDir, QFileSystemWatcher, QDate, QEvent

import numpy as np
import pyqtgraph as pg
import sounddevice as sd
from scipy import signal

try:
    import winsound
    WINSOUND_AVAILABLE = True
except ImportError:
    WINSOUND_AVAILABLE = False

try:
    from rtlsdr import RtlSdr
    RTLSDR_AVAILABLE = True
except ImportError:
    RTLSDR_AVAILABLE = False
    print("[WARNING] Library 'pyrtlsdr' not found. RTL-SDR device detection will be disabled.")
    print("          To enable it, run: python -m pip install pyrtlsdr")


# --- Konfiguracja ---
CONFIG_FILE = 'dsd-fme-gui-config.json'
ALIASES_FILE = 'dsd-fme-aliases.json'
UDP_IP = "127.0.0.1"; UDP_PORT = 23456
CHUNK_SAMPLES = 1024; SPEC_WIDTH = 400
MIN_DB = -70; MAX_DB = 50
AUDIO_RATE = 16000; AUDIO_DTYPE = np.int16
WAV_CHANNELS = 1; WAV_SAMPWIDTH = 2


# --- Klasy pomocnicze ---
class ProcessReader(QObject):
    line_read = pyqtSignal(str); finished = pyqtSignal()
    def __init__(self, process): super().__init__(); self.process = process
    @pyqtSlot()
    def run(self):
        if self.process and self.process.stdout:
            for line in iter(self.process.stdout.readline, ''): self.line_read.emit(line)
        self.finished.emit()

class UdpListener(QObject):
    data_ready = pyqtSignal(bytes)
    def __init__(self, ip, port): super().__init__(); self.ip, self.port, self.running = ip, port, True
    @pyqtSlot()
    def run(self):
        sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        try:
            sock.bind((self.ip, self.port)); sock.settimeout(1)
        except OSError as e:
            self.data_ready.emit(f"ERROR: Port {self.port} is already in use. {e}".encode()); return
        while self.running:
            try:
                data, addr = sock.recvfrom(CHUNK_SAMPLES * 2)
                if data: self.data_ready.emit(data)
            except socket.timeout:
                continue
        sock.close()

class NumericTableWidgetItem(QTableWidgetItem):
    def __lt__(self, other):
        try: return int(self.text()) < int(other.text())
        except ValueError: return super().__lt__(other)

# --- Główna klasa aplikacji ---
class DSDApp(QMainWindow):
    def __init__(self):
        super().__init__()
        self.process = None; self.reader_thread = None; self.reader_worker = None
        self.udp_listener_thread = None; self.udp_listener = None
        self.is_in_transmission = False; self.alerts = []; self.recording_dir = ""
        self.is_recording = False; self.wav_file = None; self.is_resetting = False
        self.transmission_log = {}; self.last_logged_id = None
        self.output_stream = None; self.volume = 0.7
        self.filter_lp_state = None; self.filter_hp_state = None
        self.aliases = {'tg': {}, 'id': {}}
        self.current_tg = None; self.current_id = None; self.current_cc = None
        self.fs_watcher = QFileSystemWatcher(); self.fs_watcher.directoryChanged.connect(self.update_recording_list)
        self.setWindowTitle("DSD-FME GUI Suite by Kameleon v2.2 (stable)"); self.setGeometry(100, 100, 1400, 950)
        
        self.widgets = {}; self.inverse_widgets = {}
        self.live_labels_conf = {}; self.live_labels_dash = {}
        
        self._create_theme_manager()
        
        self.dsd_fme_path = self._load_config_or_prompt()
        if self.dsd_fme_path: 
            self._init_ui()
            self._load_app_config()
            self.load_aliases()
        else: 
            QTimer.singleShot(100, self.close)

    #<editor-fold desc="Zarządzanie Motywami">
    def _create_theme_manager(self):
        self.themes = {
            "Domyślny (Kameleon Dark)": { "palette": self._get_dark_palette, "stylesheet": self._get_dark_stylesheet, "pg_background": "#15191c", "pg_foreground": "#e0e0e0", "spec_colormap": "Amber Alert" },
            "Tryb Nocny (Astro Red)": { "palette": self._get_red_palette, "stylesheet": self._get_red_stylesheet, "pg_background": "#0a0000", "pg_foreground": "#ff4444", "spec_colormap": "Tryb Nocny (Czerwony)" },
            "Oceaniczny (Deep Blue)": { "palette": self._get_blue_palette, "stylesheet": self._get_blue_stylesheet, "pg_background": "#0B1D28", "pg_foreground": "#E0FFFF", "spec_colormap": "Oceaniczny (Niebieski)" },
            "Jasny (High Contrast)": { "palette": self._get_light_palette, "stylesheet": self._get_light_stylesheet, "pg_background": "#E8E8E8", "pg_foreground": "#000000", "spec_colormap": "Skala Szarości (Mono)" },
        }
        self.current_theme_name = "Domyślny (Kameleon Dark)"

    def apply_theme(self, theme_name):
        if theme_name not in self.themes: return
        self.current_theme_name = theme_name
        theme = self.themes[theme_name]
        app = QApplication.instance()
        if not app: return
        
        app.setPalette(theme["palette"]())
        app.setStyleSheet(theme["stylesheet"]())

        pg.setConfigOption('background', theme["pg_background"])
        pg.setConfigOption('foreground', theme["pg_foreground"])

        if hasattr(self, 'imv'): self.imv.setColorMap(self.colormaps[theme["spec_colormap"]])
        if hasattr(self, 'scope_curve'): self.scope_curve.setPen(app.palette().highlight().color())
    
    def _get_dark_palette(self):
        p = QPalette(); p.setColor(QPalette.Window, QColor(21, 25, 28)); p.setColor(QPalette.WindowText, QColor(224, 224, 224)); p.setColor(QPalette.Base, QColor(30, 35, 40)); p.setColor(QPalette.AlternateBase, QColor(44, 52, 58)); p.setColor(QPalette.ToolTipBase, Qt.white); p.setColor(QPalette.ToolTipText, Qt.black); p.setColor(QPalette.Text, QColor(224, 224, 224)); p.setColor(QPalette.Button, QColor(44, 52, 58)); p.setColor(QPalette.ButtonText, QColor(224, 224, 224)); p.setColor(QPalette.BrightText, Qt.red); p.setColor(QPalette.Link, QColor(255, 170, 0)); p.setColor(QPalette.Highlight, QColor(255, 170, 0)); p.setColor(QPalette.HighlightedText, Qt.black); p.setColor(QPalette.Disabled, QPalette.Text, Qt.darkGray); p.setColor(QPalette.Disabled, QPalette.ButtonText, Qt.darkGray); return p
    def _get_dark_stylesheet(self): 
        return """
            QWidget{color:#e0e0e0;font-size:9pt}
            QGroupBox{font-weight:bold;border:1px solid #3a4149;border-radius:6px;margin-top:1ex}
            QGroupBox::title{subcontrol-origin:margin;subcontrol-position:top left;padding:0 5px;left:10px;background-color:#15191c}
            QPushButton{font-weight:bold;border-radius:5px;padding:6px 12px;border:1px solid #3a4149;background-color:qlineargradient(x1:0,y1:0,x2:0,y2:1,stop:0 #2c343a,stop:1 #242b30)}
            QPushButton:hover{background-color:#3e4850;border:1px solid #ffaa00}
            QPushButton:pressed{background-color:#242b30}
            QPushButton:disabled{color:#777;background-color:#242b30;border:1px solid #3a4149}
            QTabWidget::pane{border-top:2px solid #3a4149}
            QTabBar::tab{font-weight:bold;font-size:9pt;padding:8px;min-width:130px;max-width:130px;background-color:#1e2328;border:1px solid #3a4149;border-bottom:none;border-top-left-radius:5px;border-top-right-radius:5px}
            QTabBar::tab:selected{background-color:#2c343a;border:1px solid #ffaa00;border-bottom:none}
            QTabBar::tab:!selected:hover{background-color:#353e44}
            QLineEdit,QSpinBox,QComboBox,QTableWidget,QDateEdit{border-radius:4px;border:1px solid #3a4149;padding:4px}
            QPlainTextEdit{border-radius:4px;border:1px solid #3a4149;padding:4px;background-color:#1E2328;color:#33FF33;font-family:Consolas,monospace}
            QSlider::groove:horizontal{border:1px solid #3a4149;height:8px;background:#242b30;border-radius:4px}
            QSlider::handle:horizontal{background:#ffaa00;border:1px solid #ffaa00;width:18px;margin:-2px 0;border-radius:9px}
            QHeaderView::section{background-color:#2c343a;color:#e0e0e0;padding:4px;border:1px solid #3a4149;font-weight:bold}
        """
    def _get_red_palette(self):
        p = QPalette(); p.setColor(QPalette.Window, QColor("#100000")); p.setColor(QPalette.WindowText, QColor("#ff4444")); p.setColor(QPalette.Base, QColor("#180000")); p.setColor(QPalette.AlternateBase, QColor("#281010")); p.setColor(QPalette.ToolTipBase, Qt.white); p.setColor(QPalette.ToolTipText, Qt.black); p.setColor(QPalette.Text, QColor("#ff4444")); p.setColor(QPalette.Button, QColor("#400000")); p.setColor(QPalette.ButtonText, QColor("#ff6666")); p.setColor(QPalette.BrightText, QColor("#ff8888")); p.setColor(QPalette.Link, QColor("#ff2222")); p.setColor(QPalette.Highlight, QColor("#D00000")); p.setColor(QPalette.HighlightedText, Qt.white); p.setColor(QPalette.Disabled, QPalette.Text, QColor("#805050")); p.setColor(QPalette.Disabled, QPalette.ButtonText, QColor("#805050")); return p
    def _get_red_stylesheet(self): 
        return """
            QWidget{color:#ff4444;font-size:9pt}
            QGroupBox{font-weight:bold;border:1px solid #502020;border-radius:6px;margin-top:1ex}
            QGroupBox::title{subcontrol-origin:margin;subcontrol-position:top left;padding:0 5px;left:10px;background-color:#100000}
            QPushButton{font-weight:bold;border-radius:5px;padding:6px 12px;border:1px solid #502020;background-color:qlineargradient(x1:0,y1:0,x2:0,y2:1,stop:0 #400000,stop:1 #300000)}
            QPushButton:hover{background-color:#600000;border:1px solid #ff4444}
            QPushButton:pressed{background-color:#300000}
            QPushButton:disabled{color:#805050;background-color:#200000;border:1px solid #402020}
            QTabWidget::pane{border-top:2px solid #502020}
            QTabBar::tab{font-weight:bold;font-size:9pt;padding:8px;min-width:130px;max-width:130px;background-color:#300000;border:1px solid #502020;border-bottom:none;border-top-left-radius:5px;border-top-right-radius:5px}
            QTabBar::tab:selected{background-color:#400000;border:1px solid #ff4444;border-bottom:none}
            QTabBar::tab:!selected:hover{background-color:#500000}
            QLineEdit,QSpinBox,QComboBox,QTableWidget,QDateEdit{border-radius:4px;border:1px solid #502020;padding:4px;background-color:#180000}
            QPlainTextEdit{border-radius:4px;border:1px solid #502020;padding:4px;background-color:#180000;color:#FF5555;font-family:Consolas,monospace}
            QSlider::groove:horizontal{border:1px solid #502020;height:8px;background:#300000;border-radius:4px}
            QSlider::handle:horizontal{background:#D00000;border:1px solid #ff4444;width:18px;margin:-2px 0;border-radius:9px}
            QHeaderView::section{background-color:#400000;color:#ff6666;padding:4px;border:1px solid #502020;font-weight:bold}
        """
    def _get_blue_palette(self):
        p = QPalette(); p.setColor(QPalette.Window, QColor("#0B1D28")); p.setColor(QPalette.WindowText, QColor("#E0FFFF")); p.setColor(QPalette.Base, QColor("#112A3D")); p.setColor(QPalette.AlternateBase, QColor("#183852")); p.setColor(QPalette.ToolTipBase, Qt.white); p.setColor(QPalette.ToolTipText, Qt.black); p.setColor(QPalette.Text, QColor("#E0FFFF")); p.setColor(QPalette.Button, QColor("#113048")); p.setColor(QPalette.ButtonText, QColor("#E0FFFF")); p.setColor(QPalette.BrightText, QColor("#90EE90")); p.setColor(QPalette.Link, QColor("#00BFFF")); p.setColor(QPalette.Highlight, QColor("#007BA7")); p.setColor(QPalette.HighlightedText, Qt.white); p.setColor(QPalette.Disabled, QPalette.Text, QColor("#607A8B")); p.setColor(QPalette.Disabled, QPalette.ButtonText, QColor("#607A8B")); return p
    def _get_blue_stylesheet(self): 
        return """
            QWidget{color:#E0FFFF;font-size:9pt}
            QGroupBox{font-weight:bold;border:1px solid #204D6B;border-radius:6px;margin-top:1ex}
            QGroupBox::title{subcontrol-origin:margin;subcontrol-position:top left;padding:0 5px;left:10px;background-color:#0B1D28}
            QPushButton{font-weight:bold;border-radius:5px;padding:6px 12px;border:1px solid #204D6B;background-color:qlineargradient(x1:0,y1:0,x2:0,y2:1,stop:0 #183852,stop:1 #112A3D)}
            QPushButton:hover{background-color:#204D6B;border:1px solid #00BFFF}
            QPushButton:pressed{background-color:#112A3D}
            QPushButton:disabled{color:#607A8B;background-color:#112A3D;border:1px solid #204D6B}
            QTabWidget::pane{border-top:2px solid #204D6B}
            QTabBar::tab{font-weight:bold;font-size:9pt;padding:8px;min-width:130px;max-width:130px;background-color:#112A3D;border:1px solid #204D6B;border-bottom:none;border-top-left-radius:5px;border-top-right-radius:5px}
            QTabBar::tab:selected{background-color:#183852;border:1px solid #00BFFF;border-bottom:none}
            QTabBar::tab:!selected:hover{background-color:#204D6B}
            QLineEdit,QSpinBox,QComboBox,QTableWidget,QDateEdit{border-radius:4px;border:1px solid #204D6B;padding:4px;background-color:#112A3D}
            QPlainTextEdit{border-radius:4px;border:1px solid #204D6B;padding:4px;background-color:#08141b;color:#A0FFFF;font-family:Consolas,monospace}
            QSlider::groove:horizontal{border:1px solid #204D6B;height:8px;background:#112A3D;border-radius:4px}
            QSlider::handle:horizontal{background:#007BA7;border:1px solid #00BFFF;width:18px;margin:-2px 0;border-radius:9px}
            QHeaderView::section{background-color:#183852;color:#E0FFFF;padding:4px;border:1px solid #204D6B;font-weight:bold}
        """
    def _get_light_palette(self):
        p = QPalette(); p.setColor(QPalette.Window, QColor("#F0F0F0")); p.setColor(QPalette.WindowText, QColor("#000000")); p.setColor(QPalette.Base, QColor("#FFFFFF")); p.setColor(QPalette.AlternateBase, QColor("#E8E8E8")); p.setColor(QPalette.ToolTipBase, QColor("#333333")); p.setColor(QPalette.ToolTipText, QColor("#FFFFFF")); p.setColor(QPalette.Text, QColor("#000000")); p.setColor(QPalette.Button, QColor("#E0E0E0")); p.setColor(QPalette.ButtonText, QColor("#000000")); p.setColor(QPalette.BrightText, Qt.red); p.setColor(QPalette.Link, QColor("#0000FF")); p.setColor(QPalette.Highlight, QColor("#0078D7")); p.setColor(QPalette.HighlightedText, Qt.white); p.setColor(QPalette.Disabled, QPalette.Text, QColor("#A0A0A0")); p.setColor(QPalette.Disabled, QPalette.ButtonText, QColor("#A0A0A0")); return p
    def _get_light_stylesheet(self): 
        return """
            QWidget{color:#000000;font-size:9pt}
            QGroupBox{font-weight:bold;border:1px solid #C0C0C0;border-radius:6px;margin-top:1ex;background-color:#F0F0F0}
            QGroupBox::title{subcontrol-origin:margin;subcontrol-position:top left;padding:0 5px;left:10px;background-color:#F0F0F0}
            QPushButton{font-weight:bold;border-radius:5px;padding:6px 12px;border:1px solid #C0C0C0;background-color:qlineargradient(x1:0,y1:0,x2:0,y2:1,stop:0 #FDFDFD,stop:1 #E8E8E8)}
            QPushButton:hover{background-color:#E0E8F0;border:1px solid #0078D7}
            QPushButton:pressed{background-color:#D8E0E8}
            QPushButton:disabled{color:#A0A0A0;background-color:#E8E8E8;border:1px solid #D0D0D0}
            QTabWidget::pane{border-top:2px solid #C0C0C0}
            QTabBar::tab{font-weight:bold;font-size:9pt;padding:8px;min-width:130px;max-width:130px;background-color:#E8E8E8;border:1px solid #C0C0C0;border-bottom:none;border-top-left-radius:5px;border-top-right-radius:5px}
            QTabBar::tab:selected{background-color:#FFFFFF;border:1px solid #0078D7;border-bottom-color:#FFFFFF}
            QTabBar::tab:!selected:hover{background-color:#F0F8FF}
            QLineEdit,QSpinBox,QComboBox,QTableWidget,QDateEdit{border-radius:4px;border:1px solid #C0C0C0;padding:4px;background-color:#FFFFFF}
            QPlainTextEdit{border-radius:4px;border:1px solid #C0C0C0;padding:4px;background-color:#F8FFF8;color:#006400;font-family:Consolas,monospace}
            QSlider::groove:horizontal{border:1px solid #C0C0C0;height:8px;background:#E8E8E8;border-radius:4px}
            QSlider::handle:horizontal{background:#0078D7;border:1px solid #0078D7;width:18px;margin:-2px 0;border-radius:9px}
            QHeaderView::section{background-color:#E0E0E0;color:#000000;padding:4px;border:1px solid #C0C0C0;font-weight:bold}
        """
    #</editor-fold>
    
    #<editor-fold desc="Zarządzanie Konfiguracją">
    def _load_config_or_prompt(self):
        config = {}
        if os.path.exists(CONFIG_FILE):
            try:
                with open(CONFIG_FILE, 'r') as f: config = json.load(f)
            except json.JSONDecodeError: pass
        
        self.current_theme_name = config.get('current_theme', "Domyślny (Kameleon Dark)")
        
        path = config.get('dsd_fme_path')
        if path and os.path.exists(path): return path
        QMessageBox.information(self, "Setup", "Please locate your 'dsd-fme.exe' file.")
        path, _ = QFileDialog.getOpenFileName(self, "Select dsd-fme.exe", "", "Executable Files (dsd-fme.exe dsd-fme)")
        if path and ("dsd-fme" in os.path.basename(path).lower()):
            config_to_save = {'dsd_fme_path': path, 'current_theme': self.current_theme_name}
            with open(CONFIG_FILE, 'w') as f: json.dump(config_to_save, f, indent=4)
            return path
        else:
            QMessageBox.critical(self, "Error", "DSD-FME not selected. The application cannot function without it."); return None

    def _load_app_config(self):
        config = {}
        if os.path.exists(CONFIG_FILE):
            try:
                with open(CONFIG_FILE, 'r') as f: config = json.load(f)
            except json.JSONDecodeError: config = {}
        
        self.current_theme_name = config.get('current_theme', "Domyślny (Kameleon Dark)")
        if hasattr(self, 'theme_combo'): self.theme_combo.setCurrentText(self.current_theme_name)
        self.apply_theme(self.current_theme_name)
        
        self.alerts = config.get('alerts', [])
        self.update_alerts_list()
        
        ui_settings = config.get('ui_settings', {})
        for key, value in ui_settings.items():
            if key in self.widgets:
                widget = self.widgets[key]
                try:
                    if isinstance(widget, QCheckBox): widget.setChecked(value)
                    elif isinstance(widget, QLineEdit): widget.setText(value)
                    elif isinstance(widget, QComboBox): widget.setCurrentText(value)
                    elif isinstance(widget, QSpinBox): widget.setValue(value)
                except Exception as e:
                    print(f"Warning: Could not load UI setting for '{key}': {e}")
        
        if hasattr(self, 'recorder_dir_edit'): self.recorder_dir_edit.setText(ui_settings.get('recorder_dir_edit', ''))
        if hasattr(self, 'volume_slider'): self.volume_slider.setValue(ui_settings.get('volume_slider', 70))


    def _save_app_config(self):
        ui_settings = {}
        for key, widget in self.widgets.items():
            try:
                if isinstance(widget, QCheckBox): ui_settings[key] = widget.isChecked()
                elif isinstance(widget, QLineEdit): ui_settings[key] = widget.text()
                elif isinstance(widget, QComboBox): ui_settings[key] = widget.currentText()
                elif isinstance(widget, QSpinBox): ui_settings[key] = widget.value()
            except Exception: pass
        
        if hasattr(self, 'recorder_dir_edit'): ui_settings['recorder_dir_edit'] = self.recorder_dir_edit.text()
        if hasattr(self, 'volume_slider'): ui_settings['volume_slider'] = self.volume_slider.value()

        config = {
            'dsd_fme_path': self.dsd_fme_path,
            'current_theme': self.current_theme_name,
            'alerts': self.alerts,
            'ui_settings': ui_settings
        }
        with open(CONFIG_FILE, 'w') as f: json.dump(config, f, indent=4)
        self.save_aliases()

    def reset_all_settings(self):
        reply = QMessageBox.warning(self, "Reset Ustawień",
                                    "Czy na pewno chcesz zresetować WSZYSTKIE ustawienia aplikacji?\n"
                                    "Usunięte zostaną pliki konfiguracyjne i aliasy.\n"
                                    "Aplikacja zostanie zamknięta.",
                                    QMessageBox.Yes | QMessageBox.No, QMessageBox.No)
        if reply == QMessageBox.Yes:
            self.is_resetting = True
            try:
                if os.path.exists(CONFIG_FILE): os.remove(CONFIG_FILE)
                if os.path.exists(ALIASES_FILE): os.remove(ALIASES_FILE)
                QMessageBox.information(self, "Reset Zakończony", "Ustawienia zostały zresetowane. Uruchom aplikację ponownie.")
            except OSError as e:
                QMessageBox.critical(self, "Błąd", f"Nie udało się usunąć plików konfiguracyjnych: {e}")
            self.close()
    #</editor-fold>

    #<editor-fold desc="Tworzenie UI">
    def _init_ui(self):
        central_widget = QWidget(); self.setCentralWidget(central_widget)
        main_layout = QVBoxLayout(central_widget)
        
        self.menu_bar = self.menuBar()
        view_menu = self.menu_bar.addMenu("Widok")
        self.fullscreen_action = QAction("Pełny Ekran", self, checkable=True)
        self.fullscreen_action.setShortcut(QKeySequence("F11"))
        self.fullscreen_action.triggered.connect(self.toggle_fullscreen)
        view_menu.addAction(self.fullscreen_action)

        root_tabs = QTabWidget(); main_layout.addWidget(root_tabs)
        root_tabs.tabBar().setExpanding(True)
        root_tabs.addTab(self._create_config_tab(), "Configuration")
        root_tabs.addTab(self._create_dashboard_tab(), "Dashboard")
        root_tabs.addTab(self._create_logbook_tab(), "Logbook")
        root_tabs.addTab(self._create_aliases_tab(), "Aliases")
        root_tabs.addTab(self._create_statistics_tab(), "Statistics")
        root_tabs.addTab(self._create_recorder_tab(), "Recorder")
        root_tabs.addTab(self._create_alerts_tab(), "Alerts")
        if not self.dsd_fme_path and hasattr(self, 'btn_start'): self.btn_start.setEnabled(False); self.statusBar().showMessage("DSD-FME path not set!")

    def changeEvent(self, event):
        if event.type() == QEvent.WindowStateChange:
            self.sync_fullscreen_action(self.windowState())
        super(DSDApp, self).changeEvent(event)

    def toggle_fullscreen(self, checked):
        if checked: self.showFullScreen()
        else: self.showNormal()

    def sync_fullscreen_action(self, state):
        if hasattr(self, 'fullscreen_action'):
            self.fullscreen_action.setChecked(state == Qt.WindowFullScreen)

    def _create_config_tab(self):
        config_widget = QWidget(); config_layout = QVBoxLayout(config_widget)
        main_splitter = QSplitter(Qt.Vertical); config_layout.addWidget(main_splitter)
        options_container_widget = QWidget(); scroll_area = QScrollArea(); scroll_area.setWidgetResizable(True); scroll_area.setWidget(options_container_widget)
        container_layout = QVBoxLayout(options_container_widget)
        options_tabs = QTabWidget(); container_layout.addWidget(options_tabs)
        options_tabs.tabBar().setExpanding(True)
        options_tabs.addTab(self._create_io_tab(), "Input / Output"); options_tabs.addTab(self._create_decoder_tab(), "Decoder Modes"); options_tabs.addTab(self._create_advanced_tab(), "Advanced & Crypto"); options_tabs.addTab(self._create_trunking_tab(), "Trunking")
        cmd_group = QGroupBox("Execution"); cmd_layout = QGridLayout(cmd_group)
        self.cmd_preview = self._add_widget('cmd_preview', QLineEdit()); self.cmd_preview.setReadOnly(False); self.cmd_preview.setFont(QFont("Consolas", 9))
        self.btn_build_cmd = QPushButton("Generate Command"); self.btn_build_cmd.clicked.connect(self.build_command)
        self.btn_start = QPushButton("START"); self.btn_stop = QPushButton("STOP"); self.btn_stop.setEnabled(False)
        self.btn_start.clicked.connect(self.start_process); self.btn_stop.clicked.connect(self.stop_process)
        self.btn_reset = QPushButton("Resetuj Wszystkie Ustawienia"); self.btn_reset.clicked.connect(self.reset_all_settings)
        cmd_layout.addWidget(self.btn_start, 0, 0); cmd_layout.addWidget(self.btn_stop, 0, 1)
        cmd_layout.addWidget(self.btn_build_cmd, 1, 0, 1, 2)
        cmd_layout.addWidget(QLabel("Command to Execute:"), 2, 0, 1, 2); cmd_layout.addWidget(self.cmd_preview, 3, 0, 1, 2)
        cmd_layout.addWidget(self.btn_reset, 4, 0, 1, 2)
        container_layout.addWidget(cmd_group)
        terminal_container = QWidget(); terminal_main_layout = QVBoxLayout(terminal_container)
        self.live_analysis_group_config = self._create_live_analysis_group(self.live_labels_conf); terminal_main_layout.addWidget(self.live_analysis_group_config)
        terminal_group = self._create_terminal_group(); terminal_main_layout.addWidget(terminal_group)
        main_splitter.addWidget(scroll_area); main_splitter.addWidget(terminal_container)
        main_splitter.setSizes([450, 450])
        return config_widget

    def _create_dashboard_tab(self):
        widget = QWidget(); main_layout = QHBoxLayout(widget); main_splitter = QSplitter(Qt.Horizontal)
        self.imv = pg.ImageView(); self.imv.ui.roiBtn.hide(); self.imv.ui.menuBtn.hide(); self.imv.ui.histogram.hide()
        self.colormaps = {
            "Amber Alert": pg.ColorMap(pos=np.linspace(0.0,1.0,3),color=[(0,0,0),(150,80,0),(255,170,0)]), "Tryb Nocny (Czerwony)": pg.ColorMap(pos=np.linspace(0.0,1.0,3),color=[(0,0,0),(130,0,0),(255,50,50)]),
            "Inferno (Wysoki Kontrast)": pg.ColorMap(pos=np.linspace(0.0,1.0,4),color=[(0,0,0),(120,0,0),(255,100,0),(255,255,100)]), "Oceaniczny (Niebieski)": pg.ColorMap(pos=np.linspace(0.0,1.0,3),color=[(0,0,20),(0,80,130),(100,200,200)]),
            "Skala Szarości (Mono)": pg.ColorMap(pos=np.linspace(0.0,1.0,3),color=[(0,0,0),(128,128,128),(255,255,255)]), "Military Green": pg.ColorMap(pos=np.linspace(0.0,1.0,3),color=[(0,0,0),(0,120,0),(0,255,0)]),
            "Night Vision": pg.ColorMap(pos=np.linspace(0.0,1.0,3),color=[(0,20,0),(0,180,80),(100,255,150)]), "Arctic Blue": pg.ColorMap(pos=np.linspace(0.0,1.0,3),color=[(0,0,0),(0,0,150),(100,180,255)])
        }
        self.spec_data = np.full((SPEC_WIDTH, CHUNK_SAMPLES // 2), MIN_DB, dtype=np.float32)
        self.histogram = pg.HistogramLUTWidget(); self.histogram.setImageItem(self.imv.imageItem); self.histogram.item.gradient.loadPreset('viridis'); main_splitter.addWidget(self.histogram)
        right_panel_splitter = QSplitter(Qt.Vertical); right_panel_splitter.addWidget(self.imv)
        self.scope_widget = pg.PlotWidget(title=""); self.scope_widget.getAxis('left').setWidth(50)
        self.scope_curve = self.scope_widget.plot(); self.scope_widget.setYRange(-32768, 32767); right_panel_splitter.addWidget(self.scope_widget)
        bottom_area = QSplitter(Qt.Horizontal); left_panel_splitter = QSplitter(Qt.Vertical); controls_and_stats_widget = QWidget(); controls_and_stats_layout = QHBoxLayout(controls_and_stats_widget)
        self.live_analysis_group_dash = self._create_live_analysis_group(self.live_labels_dash); audio_controls_group_dash = self._create_audio_controls_group(is_dashboard=True)
        controls_and_stats_layout.addWidget(self.live_analysis_group_dash); controls_and_stats_layout.addWidget(audio_controls_group_dash); left_panel_splitter.addWidget(controls_and_stats_widget)
        self.mini_logbook_table = QTableWidget(); self.mini_logbook_table.setColumnCount(6); self.mini_logbook_table.setHorizontalHeaderLabels(["Start", "End", "Duration", "TG", "ID", "CC"])
        self.mini_logbook_table.setEditTriggers(QAbstractItemView.NoEditTriggers); self.mini_logbook_table.horizontalHeader().setSectionResizeMode(QHeaderView.Stretch); self.mini_logbook_table.verticalHeader().setVisible(False); left_panel_splitter.addWidget(self.mini_logbook_table)
        bottom_area.addWidget(left_panel_splitter)
        self.terminal_output_dash = QPlainTextEdit(); self.terminal_output_dash.setReadOnly(True); bottom_area.addWidget(self.terminal_output_dash)
        right_panel_splitter.addWidget(bottom_area); main_splitter.addWidget(right_panel_splitter)
        main_splitter.setSizes([200, 1200]); right_panel_splitter.setSizes([450, 200, 300]); main_layout.addWidget(main_splitter)
        return widget

    def _create_audio_controls_group(self, is_dashboard=False):
        group = QGroupBox("Audio & System Controls"); control_layout = QGridLayout(group)
        self.device_combo = QComboBox(); self.populate_audio_devices()
        self.volume_slider = QSlider(Qt.Horizontal); self.volume_slider.setRange(0, 100)
        self.mute_check = QCheckBox("Mute"); self._add_widget('mute_check', self.mute_check)
        self.lp_filter_check = QCheckBox("Low-pass"); self._add_widget('lp_filter_check', self.lp_filter_check)
        self.hp_filter_check = QCheckBox("High-pass"); self._add_widget('hp_filter_check', self.hp_filter_check)
        self.lp_cutoff_spin = QSpinBox(); self.lp_cutoff_spin.setRange(1000, 8000); self.lp_cutoff_spin.setSuffix(" Hz"); self._add_widget('lp_cutoff_spin', self.lp_cutoff_spin)
        self.hp_cutoff_spin = QSpinBox(); self.hp_cutoff_spin.setRange(100, 1000); self.hp_cutoff_spin.setSuffix(" Hz"); self._add_widget('hp_cutoff_spin', self.hp_cutoff_spin)
        self.rms_label = QLabel("RMS Level: --"); self.peak_freq_label = QLabel("Peak Freq: --")
        row_idx = 0
        control_layout.addWidget(QLabel("Audio Output:"), row_idx, 0); control_layout.addWidget(self.device_combo, row_idx, 1, 1, 2)
        row_idx += 1; control_layout.addWidget(QLabel("Volume:"), row_idx, 0); control_layout.addWidget(self.volume_slider, row_idx, 1, 1, 2); control_layout.addWidget(self.mute_check, 0, 3)
        row_idx += 1; control_layout.addWidget(self.hp_filter_check, row_idx, 0); control_layout.addWidget(self.hp_cutoff_spin, row_idx, 1); control_layout.addWidget(self.rms_label, row_idx, 2)
        row_idx += 1; control_layout.addWidget(self.lp_filter_check, row_idx, 0); control_layout.addWidget(self.lp_cutoff_spin, row_idx, 1); control_layout.addWidget(self.peak_freq_label, row_idx, 2)
        if is_dashboard:
            row_idx += 1; self.theme_combo = QComboBox(); self.theme_combo.addItems(self.themes.keys()); self.theme_combo.currentTextChanged.connect(self.apply_theme)
            control_layout.addWidget(QLabel("Motyw Aplikacji:"), row_idx, 0); control_layout.addWidget(self.theme_combo, row_idx, 1, 1, 2)
            row_idx += 1; self.colormap_combo = QComboBox(); self.colormap_combo.addItems(self.colormaps.keys()); self.colormap_combo.currentTextChanged.connect(lambda name: self.imv.setColorMap(self.colormaps[name]))
            control_layout.addWidget(QLabel("Motyw Spektrogramu:"), row_idx, 0); control_layout.addWidget(self.colormap_combo, row_idx, 1, 1, 2)
            row_idx += 1; self.recorder_enabled_check_dash = QCheckBox("Enable Recording"); self.recorder_enabled_check_dash.toggled.connect(lambda state: self.recorder_enabled_check.setChecked(state)); self._add_widget('recorder_enabled_check_dash', self.recorder_enabled_check_dash)
            control_layout.addWidget(self.recorder_enabled_check_dash, row_idx, 0, 1, 2)
            row_idx += 1; self.btn_start_dash = QPushButton("START"); self.btn_start_dash.clicked.connect(self.start_process)
            self.btn_stop_dash = QPushButton("STOP"); self.btn_stop_dash.setEnabled(False); self.btn_stop_dash.clicked.connect(self.stop_process)
            control_layout.addWidget(self.btn_start_dash, row_idx, 0); control_layout.addWidget(self.btn_stop_dash, row_idx, 1)
        self.device_combo.currentIndexChanged.connect(self.restart_audio_stream); self.volume_slider.valueChanged.connect(self.set_volume); return group
    
    def _create_alerts_tab(self):
        widget = QWidget(); layout = QGridLayout(widget)
        form_group = QGroupBox("Add/Edit Alert"); form_layout = QGridLayout(form_group)
        self.alert_type_combo = QComboBox(); self.alert_type_combo.addItems(["Talkgroup (TG)", "Radio ID"])
        self.alert_value_edit = QLineEdit(); self.alert_value_edit.setPlaceholderText("Enter TG or ID value...")
        self.alert_sound_edit = QLineEdit(); self.alert_sound_edit.setPlaceholderText("Default Beep")
        self.alert_sound_browse_btn = QPushButton("Browse..."); self.alert_sound_browse_btn.clicked.connect(self.browse_for_alert_sound)
        self.alert_add_btn = QPushButton("Add/Update Alert"); self.alert_add_btn.clicked.connect(self.add_alert)
        form_layout.addWidget(QLabel("Alert Type:"), 0, 0); form_layout.addWidget(self.alert_type_combo, 0, 1)
        form_layout.addWidget(QLabel("Value:"), 1, 0); form_layout.addWidget(self.alert_value_edit, 1, 1)
        form_layout.addWidget(QLabel("Sound File (.wav):"), 2, 0); form_layout.addWidget(self.alert_sound_edit, 2, 1); form_layout.addWidget(self.alert_sound_browse_btn, 2, 2)
        form_layout.addWidget(self.alert_add_btn, 3, 1, 1, 2)
        
        self.alerts_table = QTableWidget(); self.alerts_table.setColumnCount(3); self.alerts_table.setHorizontalHeaderLabels(["Type", "Value", "Sound Path"])
        self.alerts_table.setEditTriggers(QAbstractItemView.NoEditTriggers); self.alerts_table.setSelectionBehavior(QAbstractItemView.SelectRows); self.alerts_table.horizontalHeader().setSectionResizeMode(QHeaderView.Stretch)
        self.alerts_table.itemClicked.connect(self.populate_alert_form)
        self.alert_remove_btn = QPushButton("Remove Selected Alert"); self.alert_remove_btn.clicked.connect(self.remove_alert)
        layout.addWidget(form_group, 0, 0); layout.addWidget(self.alerts_table, 1, 0); layout.addWidget(self.alert_remove_btn, 2, 0); layout.setRowStretch(1, 1)
        return widget

    def browse_for_alert_sound(self):
        path, _ = QFileDialog.getOpenFileName(self, "Select Alert Sound", "", "WAV Files (*.wav)")
        if path: self.alert_sound_edit.setText(path)
    #</editor-fold>
    
    #<editor-fold desc="Pozostała logika aplikacji">
    def closeEvent(self, event):
        if not self.is_resetting:
            self._save_app_config()
        self.stop_process()
        event.accept()

    def _create_io_tab(self):
        tab = QWidget(); layout = QVBoxLayout(tab)
        g1 = QGroupBox("Input (-i)"); l1 = QGridLayout(g1)
        input_type_combo = self._add_widget("-i_type", QComboBox()); input_type_combo.addItems(["rtl", "tcp", "wav", "pulse"])
        self._add_widget("-i_tcp", QLineEdit("127.0.0.1:7355")); self._add_widget("-i_wav", QLineEdit())
        l1.addWidget(QLabel("Type:"), 0, 0); l1.addWidget(self.widgets["-i_type"], 0, 1); l1.addWidget(QLabel("TCP Addr:Port:"), 1, 0); l1.addWidget(self.widgets["-i_tcp"], 1, 1); l1.addWidget(QLabel("WAV File:"), 2, 0); l1.addWidget(self.widgets["-i_wav"], 2, 1); l1.addWidget(self._create_browse_button(self.widgets["-i_wav"]), 2, 2); layout.addWidget(g1)
        self.rtl_group = QGroupBox("RTL-SDR Options"); l_rtl = QGridLayout(self.rtl_group)
        self._add_widget("rtl_dev", QComboBox())
        self.rtl_refresh_btn = QPushButton("Refresh List"); self.rtl_refresh_btn.clicked.connect(self._populate_rtl_devices)
        self._add_widget("rtl_freq", QLineEdit("433.175")); self._add_widget("rtl_unit", QComboBox()); self.widgets["rtl_unit"].addItems(["MHz", "KHz", "GHz", "Hz"])
        self._add_widget("rtl_gain", QLineEdit("0")); self._add_widget("rtl_ppm", QLineEdit("0"))
        l_rtl.addWidget(QLabel("Device:"), 0, 0); l_rtl.addWidget(self.widgets["rtl_dev"], 0, 1); l_rtl.addWidget(self.rtl_refresh_btn, 0, 2)
        l_rtl.addWidget(QLabel("Frequency:"), 1, 0); l_rtl.addWidget(self.widgets["rtl_freq"], 1, 1); l_rtl.addWidget(self.widgets["rtl_unit"], 1, 2)
        l_rtl.addWidget(QLabel("Gain (0=auto):"), 2, 0); l_rtl.addWidget(self.widgets["rtl_gain"], 2, 1); l_rtl.addWidget(QLabel("PPM Error:"), 3, 0); l_rtl.addWidget(self.widgets["rtl_ppm"], 3, 1)
        layout.addWidget(self.rtl_group); self.rtl_group.setVisible(True); self._populate_rtl_devices()
        input_type_combo.currentTextChanged.connect(lambda text: self.rtl_group.setVisible(text == 'rtl'))
        bottom_layout = QGridLayout(); g3 = QGroupBox("File Outputs"); l3 = QGridLayout(g3)
        self._add_widget("-w", QLineEdit()); self._add_widget("-6", QLineEdit()); self._add_widget("-c", QLineEdit())
        l3.addWidget(QLabel("Synth Speech [-w]:"), 0, 0); l3.addWidget(self.widgets["-w"], 0, 1); l3.addWidget(self._create_browse_button(self.widgets["-w"]), 0, 2)
        l3.addWidget(QLabel("Raw Audio [-6]:"), 1, 0); l3.addWidget(self.widgets["-6"], 1, 1); l3.addWidget(self._create_browse_button(self.widgets["-6"]), 1, 2)
        l3.addWidget(QLabel("Symbol Capture [-c]:"), 2, 0); l3.addWidget(self.widgets["-c"], 2, 1); l3.addWidget(self._create_browse_button(self.widgets["-c"]), 2, 2)
        g4 = QGroupBox("Other"); l4 = QGridLayout(g4)
        self._add_widget("-s", QLineEdit("48000")); self._add_widget("-g", QLineEdit("0")); self._add_widget("-V", QLineEdit("3"))
        l4.addWidget(QLabel("WAV Sample Rate [-s]:"), 0, 0); l4.addWidget(self.widgets["-s"], 0, 1); l4.addWidget(QLabel("Digital Gain [-g]:"), 1, 0); l4.addWidget(self.widgets["-g"], 1, 1); l4.addWidget(QLabel("TDMA Slot Synth [-V]:"), 2, 0); l4.addWidget(self.widgets["-V"], 2, 1)
        bottom_layout.addWidget(g3, 0, 0); bottom_layout.addWidget(g4, 0, 1); layout.addLayout(bottom_layout); layout.addStretch(); return tab
    def _populate_rtl_devices(self):
        combo = self.widgets.get("rtl_dev")
        if not combo: return
        combo.clear()
        if not RTLSDR_AVAILABLE:
            combo.addItem("pyrtlsdr not found!")
            combo.setEnabled(False)
            self.rtl_refresh_btn.setEnabled(False)
            return
        try:
            devices = RtlSdr.get_device_serial_addresses()
            if not devices:
                combo.addItem("No RTL-SDR devices found.")
                return
            for i, serial in enumerate(devices):
                combo.addItem(f"#{i}: {serial}", userData=i)
        except Exception as e:
            combo.addItem("Error querying devices")
            print(f"Error enumerating RTL-SDR devices: {e}")
    def _create_decoder_tab(self):
        tab = QWidget(); scroll = QScrollArea(); scroll.setWidgetResizable(True); layout = QVBoxLayout(tab); layout.addWidget(scroll); container = QWidget(); scroll.setWidget(container); grid = QGridLayout(container)
        self.decoder_mode_group = QButtonGroup()
        g1 = QGroupBox("Decoder Mode (-f...)"); l1 = QVBoxLayout(g1)
        modes = {"-fa":"Auto","-fA":"Analog","-ft":"Trunk P25/DMR","-fs":"DMR Simplex","-f1":"P25 P1","-f2":"P25 P2","-fd":"D-STAR","-fx":"X2-TDMA","-fy":"YSF","-fz":"M17","-fi":"NXDN48","-fn":"NXDN96","-fp":"ProVoice","-fe":"EDACS EA"}
        for flag, name in modes.items(): rb = QRadioButton(name); self._add_widget(flag, rb); self.decoder_mode_group.addButton(rb); l1.addWidget(rb)
        g2 = QGroupBox("Decoder Options"); l2 = QVBoxLayout(g2); l2.addWidget(self._add_widget("-l", QCheckBox("Disable Input Filtering"))); l2.addWidget(self._add_widget("-xx", QCheckBox("Invert X2-TDMA"))); l2.addWidget(self._add_widget("-xr", QCheckBox("Invert DMR")))
        l2.addWidget(self._add_widget("-xd", QCheckBox("Invert dPMR"))); l2.addWidget(self._add_widget("-xz", QCheckBox("Invert M17"))); l2.addStretch()
        grid.addWidget(g1, 0, 0); grid.addWidget(g2, 0, 1); return tab
    def _create_advanced_tab(self):
        tab = QWidget(); layout = QGridLayout(tab); g1 = QGroupBox("Modulation (-m...) & Display"); l1 = QVBoxLayout(g1); self.mod_group = QButtonGroup()
        mods = {"-ma":"Auto","-mc":"C4FM (default)","-mg":"GFSK","-mq":"QPSK","-m2":"P25p2 QPSK"}
        for flag, name in mods.items(): rb = QRadioButton(name); self._add_widget(flag, rb); self.mod_group.addButton(rb); l1.addWidget(rb)
        l1.addSpacing(20); l1.addWidget(self._add_widget("-N", QCheckBox("Use NCurses Emulation [-N]"))); l1.addWidget(self._add_widget("-Z", QCheckBox("Log Payloads to Console [-Z]")))
        g2 = QGroupBox("Encryption Keys"); l2 = QGridLayout(g2)
        l2.addWidget(QLabel("Basic Privacy Key [-b]:"), 0, 0); l2.addWidget(self._add_widget("-b", QLineEdit()), 0, 1); l2.addWidget(QLabel("RC4 Key [-1]:"), 1, 0); l2.addWidget(self._add_widget("-1", QLineEdit()), 1, 1)
        l2.addWidget(QLabel("Hytera BP Key [-H]:"), 2, 0); l2.addWidget(self._add_widget("-H", QLineEdit()), 2, 1); l2.addWidget(QLabel("Keys from .csv [-K]:"), 3, 0); self._add_widget("-K", QLineEdit()); l2.addWidget(self.widgets["-K"], 3, 1); l2.addWidget(self._create_browse_button(self.widgets["-K"]), 3, 2)
        g3 = QGroupBox("Force Options"); l3 = QVBoxLayout(g3); l3.addWidget(self._add_widget("-4", QCheckBox("Force BP Key"))); l3.addWidget(self._add_widget("-0", QCheckBox("Force RC4 Key"))); l3.addWidget(self._add_widget("-3", QCheckBox("Disable DMR Late Entry Enc."))); l3.addWidget(self._add_widget("-F", QCheckBox("Relax CRC Checksum")))
        layout.addWidget(g1, 0, 0); layout.addWidget(g2, 0, 1); layout.addWidget(g3, 1, 0, 1, 2); return tab
    def _create_trunking_tab(self):
        tab = QWidget(); layout = QVBoxLayout(tab); g1 = QGroupBox("Trunking Options"); l1 = QGridLayout(g1)
        l1.addWidget(self._add_widget("-T", QCheckBox("Enable Trunking")), 0, 0); l1.addWidget(self._add_widget("-Y", QCheckBox("Enable Scanning")), 0, 1)
        l1.addWidget(QLabel("Channel Map [-C]:"), 1, 0); self._add_widget("-C", QLineEdit()); l1.addWidget(self.widgets["-C"], 1, 1); l1.addWidget(self._create_browse_button(self.widgets["-C"]), 1, 2)
        l1.addWidget(QLabel("Group List [-G]:"), 2, 0); self._add_widget("-G", QLineEdit()); l1.addWidget(self.widgets["-G"], 2, 1); l1.addWidget(self._create_browse_button(self.widgets["-G"]), 2, 2)
        l1.addWidget(QLabel("RigCtl Port [-U]:"), 3, 0); l1.addWidget(self._add_widget("-U", QLineEdit("")), 3, 1)
        g2 = QGroupBox("Tuning Control"); l2 = QVBoxLayout(g2); l2.addWidget(self._add_widget("-p", QCheckBox("Disable Tune to Private Calls"))); l2.addWidget(self._add_widget("-E", QCheckBox("Disable Tune to Group Calls"))); l2.addWidget(self._add_widget("-e", QCheckBox("Enable Tune to Data Calls")))
        layout.addWidget(g1); layout.addWidget(g2); layout.addStretch(); return tab
    def _create_logbook_tab(self):
        widget = QWidget(); layout = QGridLayout(widget)
        self.logbook_search_input = QLineEdit(); self.logbook_search_input.setPlaceholderText("Search Logbook...")
        self.logbook_search_input.textChanged.connect(self.filter_logbook)
        self.logbook_table = QTableWidget(); self.logbook_table.setColumnCount(6); self.logbook_table.setHorizontalHeaderLabels(["Start Time","End Time","Duration","Talkgroup","Radio ID","Color Code"])
        self.logbook_table.setEditTriggers(QAbstractItemView.NoEditTriggers); self.logbook_table.setSelectionBehavior(QAbstractItemView.SelectRows); self.logbook_table.setSortingEnabled(True)
        self.logbook_table.horizontalHeader().setSectionResizeMode(QHeaderView.Stretch); self.logbook_table.verticalHeader().setVisible(False)
        self.import_csv_button = QPushButton("Import CSV"); self.import_csv_button.clicked.connect(self.import_csv_to_logbook)
        self.save_csv_button = QPushButton("Save to CSV"); self.save_csv_button.clicked.connect(self.save_history_to_csv)
        button_layout = QHBoxLayout(); button_layout.addWidget(self.import_csv_button); button_layout.addWidget(self.save_csv_button)
        layout.addWidget(self.logbook_search_input, 0, 0); layout.addLayout(button_layout, 0, 1); layout.addWidget(self.logbook_table, 1, 0, 1, 2); return widget
    def _create_aliases_tab(self):
        widget = QWidget(); main_layout = QHBoxLayout(widget); splitter = QSplitter(Qt.Horizontal)
        tg_group = QGroupBox("Talkgroup (TG) Aliases"); tg_layout = QVBoxLayout(tg_group)
        tg_controls_layout = QHBoxLayout()
        self.tg_search_input = QLineEdit(); self.tg_search_input.setPlaceholderText("Filter TG by ID or Alias...")
        self.tg_search_input.textChanged.connect(lambda text: self._filter_alias_table(self.tg_alias_table, text)); tg_controls_layout.addWidget(self.tg_search_input)
        self.tg_alias_table = QTableWidget(0, 2); self.tg_alias_table.setHorizontalHeaderLabels(["TG ID", "Alias"]); self.tg_alias_table.horizontalHeader().setSectionResizeMode(QHeaderView.Stretch)
        self.tg_alias_table.setSortingEnabled(True); self.tg_alias_table.itemChanged.connect(lambda item: self.update_alias(self.tg_alias_table, 'tg', item))
        tg_btn_layout = QHBoxLayout()
        add_tg_btn = QPushButton("Add"); add_tg_btn.clicked.connect(lambda: self.add_alias_row(self.tg_alias_table))
        remove_tg_btn = QPushButton("Remove"); remove_tg_btn.clicked.connect(lambda: self.remove_alias_row(self.tg_alias_table, 'tg'))
        import_tg_btn = QPushButton("Import CSV"); import_tg_btn.clicked.connect(lambda: self._import_aliases_from_csv('tg'))
        export_tg_btn = QPushButton("Export CSV"); export_tg_btn.clicked.connect(lambda: self._export_aliases_to_csv('tg'))
        tg_btn_layout.addWidget(add_tg_btn); tg_btn_layout.addWidget(remove_tg_btn); tg_btn_layout.addWidget(import_tg_btn); tg_btn_layout.addWidget(export_tg_btn)
        tg_layout.addLayout(tg_controls_layout); tg_layout.addWidget(self.tg_alias_table); tg_layout.addLayout(tg_btn_layout)
        id_group = QGroupBox("Radio ID Aliases"); id_layout = QVBoxLayout(id_group)
        id_controls_layout = QHBoxLayout()
        self.id_search_input = QLineEdit(); self.id_search_input.setPlaceholderText("Filter ID by ID or Alias...")
        self.id_search_input.textChanged.connect(lambda text: self._filter_alias_table(self.id_alias_table, text)); id_controls_layout.addWidget(self.id_search_input)
        self.id_alias_table = QTableWidget(0, 2); self.id_alias_table.setHorizontalHeaderLabels(["Radio ID", "Alias"]); self.id_alias_table.horizontalHeader().setSectionResizeMode(QHeaderView.Stretch)
        self.id_alias_table.setSortingEnabled(True); self.id_alias_table.itemChanged.connect(lambda item: self.update_alias(self.id_alias_table, 'id', item))
        id_btn_layout = QHBoxLayout()
        add_id_btn = QPushButton("Add"); add_id_btn.clicked.connect(lambda: self.add_alias_row(self.id_alias_table))
        remove_id_btn = QPushButton("Remove"); remove_id_btn.clicked.connect(lambda: self.remove_alias_row(self.id_alias_table, 'id'))
        import_id_btn = QPushButton("Import CSV"); import_id_btn.clicked.connect(lambda: self._import_aliases_from_csv('id'))
        export_id_btn = QPushButton("Export CSV"); export_id_btn.clicked.connect(lambda: self._export_aliases_to_csv('id'))
        id_btn_layout.addWidget(add_id_btn); id_btn_layout.addWidget(remove_id_btn); id_btn_layout.addWidget(import_id_btn); id_btn_layout.addWidget(export_id_btn)
        id_layout.addLayout(id_controls_layout); id_layout.addWidget(self.id_alias_table); id_layout.addLayout(id_btn_layout)
        splitter.addWidget(tg_group); splitter.addWidget(id_group); main_layout.addWidget(splitter); return widget
    def _create_statistics_tab(self):
        widget = QWidget(); main_layout = QVBoxLayout(widget)
        controls_group = QGroupBox("Report Generation"); controls_layout = QGridLayout(controls_group)
        self.stats_start_date = QDateEdit(datetime.now().date()); self.stats_start_date.setCalendarPopup(True)
        self.stats_end_date = QDateEdit(datetime.now().date()); self.stats_end_date.setCalendarPopup(True)
        self.generate_report_btn = QPushButton("Generate Report"); self.generate_report_btn.clicked.connect(self.update_statistics)
        controls_layout.addWidget(QLabel("Start Date:"), 0, 0); controls_layout.addWidget(self.stats_start_date, 0, 1); controls_layout.addWidget(QLabel("End Date:"), 0, 2); controls_layout.addWidget(self.stats_end_date, 0, 3)
        controls_layout.addWidget(self.generate_report_btn, 0, 4, 1, 2); controls_layout.setColumnStretch(5, 1); main_layout.addWidget(controls_group)
        summary_group = QGroupBox("Summary"); self.summary_layout = QGridLayout(summary_group)
        self.total_calls_label = QLabel("---"); self.total_duration_label = QLabel("---"); self.most_active_tg_label = QLabel("---"); self.most_active_id_label = QLabel("---")
        self.summary_layout.addWidget(QLabel("<b>Total Calls:</b>"), 0, 0); self.summary_layout.addWidget(self.total_calls_label, 0, 1); self.summary_layout.addWidget(QLabel("<b>Total Duration:</b>"), 1, 0); self.summary_layout.addWidget(self.total_duration_label, 1, 1)
        self.summary_layout.addWidget(QLabel("<b>Most Active TG:</b>"), 0, 2); self.summary_layout.addWidget(self.most_active_tg_label, 0, 3); self.summary_layout.addWidget(QLabel("<b>Most Active ID:</b>"), 1, 2); self.summary_layout.addWidget(self.most_active_id_label, 1, 3)
        self.summary_layout.setColumnStretch(1, 1); self.summary_layout.setColumnStretch(3, 1); main_layout.addWidget(summary_group)
        splitter = QSplitter(Qt.Horizontal)
        self.tg_chart = pg.PlotWidget(title="Top 10 Talkgroups by Call Count"); self.id_chart = pg.PlotWidget(title="Top 10 Radio IDs by Call Count"); self.time_chart = pg.PlotWidget(title="Calls per Hour")
        splitter.addWidget(self.tg_chart); splitter.addWidget(self.id_chart); splitter.addWidget(self.time_chart); main_layout.addWidget(splitter)
        return widget
    def _create_recorder_tab(self):
        widget = QWidget(); layout = QGridLayout(widget)
        self.recorder_enabled_check = QCheckBox("Enable Voice-Activated Recording to Directory"); self.recorder_enabled_check.toggled.connect(lambda state: self.recorder_enabled_check_dash.setChecked(state)); self._add_widget('recorder_enabled_check', self.recorder_enabled_check)
        self.recorder_dir_edit = QLineEdit(); self.recorder_dir_edit.setPlaceholderText("Select directory for WAV files...")
        self.recorder_browse_btn = QPushButton("Browse..."); self.recorder_browse_btn.clicked.connect(self.browse_for_recording_dir)
        self.recording_list = QListWidget(); self.recording_list.itemDoubleClicked.connect(self.play_recording)
        play_btn = QPushButton("Play Selected Recording"); play_btn.clicked.connect(self.play_recording)
        layout.addWidget(self.recorder_enabled_check, 0, 0, 1, 2); layout.addWidget(QLabel("Recording Directory:"), 1, 0); layout.addWidget(self.recorder_dir_edit, 1, 1); layout.addWidget(self.recorder_browse_btn, 1, 2)
        layout.addWidget(self.recording_list, 2, 0, 1, 3); layout.addWidget(play_btn, 3, 0, 1, 3)
        return widget
    def _create_live_analysis_group(self, labels_dict):
        group = QGroupBox("Live Analysis"); layout = QGridLayout(group); font = QFont(); font.setBold(True)
        labels = {"status":"Status:","recording":"Recording:","tg":"Talkgroup (TG):","id":"Radio ID (ID):","cc":"Color Code (CC):","last_sync":"Last Sync:","last_voice":"Last Voice:","duration":"Last Duration:"}
        positions = [(0,0),(0,2),(1,0),(2,0),(1,2),(2,2),(3,0),(3,2)]
        for (key, text), pos in zip(labels.items(), positions):
            labels_dict[key] = QLabel("---"); labels_dict[key].setFont(font)
            layout.addWidget(QLabel(text), pos[0], pos[1]); layout.addWidget(labels_dict[key], pos[0], pos[1]+1)
        labels_dict['recording'].setText("INACTIVE"); labels_dict['recording'].setStyleSheet("color: gray;"); layout.setColumnStretch(1, 1); layout.setColumnStretch(3, 1)
        return group
    def _create_terminal_group(self):
        group = QGroupBox("Terminal Log"); layout = QGridLayout(group)
        self.terminal_output_conf = QPlainTextEdit(); self.terminal_output_conf.setReadOnly(True)
        self.search_input = QLineEdit(); self.search_input.setPlaceholderText("Search in log...")
        self.search_button = QPushButton("Find Next"); self.search_button.clicked.connect(self.search_in_log)
        self.search_input.returnPressed.connect(self.search_in_log)
        layout.addWidget(self.terminal_output_conf, 0, 0, 1, 2); layout.addWidget(self.search_input, 1, 0); layout.addWidget(self.search_button, 1, 1)
        return group
    def _add_widget(self, key, widget):
        self.widgets[key] = widget
        if isinstance(widget, QRadioButton): self.inverse_widgets[widget] = key
        return widget
    def _create_browse_button(self, line_edit_widget, is_dir=False): button = QPushButton("Browse..."); button.clicked.connect(lambda: self._browse_for_path(line_edit_widget, is_dir)); return button
    def _browse_for_path(self, line_edit_widget, is_dir):
        path = QFileDialog.getExistingDirectory(self, "Select Directory") if is_dir else QFileDialog.getOpenFileName(self, "Select File")[0]
        if path: line_edit_widget.setText(path)
    def start_udp_listener(self): self.udp_listener_thread = QThread(); self.udp_listener = UdpListener(UDP_IP, UDP_PORT); self.udp_listener.moveToThread(self.udp_listener_thread); self.udp_listener_thread.started.connect(self.udp_listener.run); self.udp_listener.data_ready.connect(self.process_audio_data); self.udp_listener_thread.start()
    def stop_udp_listener(self):
        if self.udp_listener: self.udp_listener.running = False
        if self.udp_listener_thread: self.udp_listener_thread.quit(); self.udp_listener_thread.wait()
    def build_command(self):
        if not self.dsd_fme_path: self.cmd_preview.setText("ERROR: DSD-FME path not set!"); return []
        command = [self.dsd_fme_path, "-o", f"udp:{UDP_IP}:{UDP_PORT}"]
        in_type = self.widgets["-i_type"].currentText()
        if in_type == "tcp": command.extend(["-i", f"tcp:{self.widgets['-i_tcp'].text()}" if self.widgets['-i_tcp'].text() else "tcp"])
        elif in_type == "wav": self.widgets['-i_wav'].text() and command.extend(["-i", self.widgets['-i_wav'].text()])
        elif in_type == "rtl":
            dev_index = self.widgets["rtl_dev"].currentData()
            if dev_index is None: QMessageBox.critical(self, "Error", "No RTL-SDR device selected or found."); return []
            try:
                dev = str(dev_index)
                freq_val = float(self.widgets["rtl_freq"].text()); unit = self.widgets["rtl_unit"].currentText(); gain = self.widgets["rtl_gain"].text(); ppm = self.widgets["rtl_ppm"].text()
                freq_map = {"MHz": "M", "KHz": "K", "GHz": "G"}; freq_str = f"{freq_val}{freq_map.get(unit, '')}"
                command.extend(["-i", f"rtl:{dev}:{freq_str}:{gain}:{ppm}"])
            except ValueError: QMessageBox.critical(self, "Error", "Invalid frequency value."); return []
        else: command.extend(["-i", in_type])
        for flag in ["-s","-g","-V","-w","-6","-c","-b","-1","-H","-K","-C","-G","-U"]:
            if self.widgets.get(flag) and self.widgets[flag].text(): command.extend([flag, self.widgets[flag].text()])
        for flag in ["-l","-xx","-xr","-xd","-xz","-N","-Z","-4","-0","-3","-F","-T","-Y","-p","-E","-e"]:
            if self.widgets.get(flag) and self.widgets[flag].isChecked(): command.append(flag)
        for btn, flag in self.inverse_widgets.items():
            if flag and btn.isChecked(): command.append(flag)
        final_command = list(filter(None, (str(item).strip() for item in command))); self.cmd_preview.setText(subprocess.list2cmdline(final_command)); return final_command
    def start_process(self):
        if self.process: return
        self.logbook_table.setRowCount(0); self.mini_logbook_table.setRowCount(0); self.is_in_transmission = False; self.last_logged_id = None; self.transmission_log.clear()
        command = self.build_command()
        if not command: return
        self.start_udp_listener(); self.restart_audio_stream()
        log_start_msg = f"$ {subprocess.list2cmdline(command)}\n\n"
        for term in [self.terminal_output_conf, self.terminal_output_dash]: term.clear(); term.appendPlainText(log_start_msg)
        try:
            si = subprocess.STARTUPINFO(); si.dwFlags |= subprocess.STARTF_USESHOWWINDOW; si.wShowWindow = subprocess.SW_HIDE
            self.process = subprocess.Popen(command, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, stdin=subprocess.DEVNULL, universal_newlines=True, encoding='utf-8', errors='ignore', startupinfo=si, creationflags=subprocess.CREATE_NO_WINDOW if os.name == 'nt' else 0)
            self.reader_thread = QThread(); self.reader_worker = ProcessReader(self.process)
            self.reader_worker.moveToThread(self.reader_thread); self.reader_worker.line_read.connect(self.update_terminal_log); self.reader_worker.finished.connect(self.on_process_finished)
            self.reader_thread.started.connect(self.reader_worker.run); self.reader_thread.start()
            self.btn_start.setEnabled(False); self.btn_stop.setEnabled(True); self.btn_start_dash.setEnabled(False); self.btn_stop_dash.setEnabled(True)
        except Exception as e: error_msg = f"\nERROR: Failed to start process: {e}"; self.terminal_output_conf.appendPlainText(error_msg); self.terminal_output_dash.appendPlainText(error_msg); self.reset_ui_state()
    def stop_process(self):
        if self.is_recording: self.stop_internal_recording()
        self.stop_udp_listener()
        if self.output_stream: self.output_stream.stop(); self.output_stream.close(); self.output_stream = None
        if self.process and self.process.poll() is None:
            self.btn_stop.setEnabled(False); self.btn_stop_dash.setEnabled(False)
            stop_msg = "\n--- SENDING STOP SIGNAL ---\n"; self.terminal_output_conf.appendPlainText(stop_msg); self.terminal_output_dash.appendPlainText(stop_msg)
            self.process.terminate()
            try: self.process.wait(timeout=2)
            except subprocess.TimeoutExpired: self.process.kill()
    def on_process_finished(self): self.end_all_transmissions(); self.reader_thread.quit(); self.reader_thread.wait(); self.reset_ui_state()
    def reset_ui_state(self):
        self.process = None; self.reader_thread = None; self.reader_worker = None
        self.btn_start.setEnabled(True); self.btn_stop.setEnabled(False); self.btn_start_dash.setEnabled(True); self.btn_stop_dash.setEnabled(False)
        ready_msg = "\n--- READY ---\n"
        if hasattr(self, 'terminal_output_conf'): self.terminal_output_conf.appendPlainText(ready_msg); self.terminal_output_dash.appendPlainText(ready_msg)
    def update_terminal_log(self, text):
        self.parse_and_display_log(text)
        for term in [self.terminal_output_conf, self.terminal_output_dash]: term.moveCursor(QTextCursor.End); term.insertPlainText(text)
    def parse_and_display_log(self, text):
        try:
            if "TGT=" in text and "SRC=" in text:
                self.current_tg = text.split("TGT=")[1].split(" ")[0].strip(); self.current_id = text.split("SRC=")[1].split(" ")[0].strip()
                for panel in [self.live_labels_conf, self.live_labels_dash]: panel and (panel['tg'].setText(self.aliases['tg'].get(self.current_tg, self.current_tg)), panel['id'].setText(self.aliases['id'].get(self.current_id, self.current_id)))
                return
            if "Sync:" in text:
                if "Color Code=" in text:
                    self.current_cc = text.split("Color Code=")[1].split(" ")[0].strip()
                    for panel in [self.live_labels_conf, self.live_labels_dash]: panel and panel['cc'].setText(self.current_cc)
                is_voice = "VC" in text or "VLC" in text
                timestamp = text[:8] if (len(text) > 8 and text[2] == ':') else None
                if is_voice:
                    self.is_in_transmission = True
                    for panel in [self.live_labels_conf, self.live_labels_dash]:
                        if panel: panel['status'].setText("VOICE CALL"); panel['duration'].setText("In Progress..."); timestamp and panel['last_voice'].setText(timestamp)
                    if self.current_id and self.current_id != self.last_logged_id:
                        self.end_all_transmissions(end_current=False); self.start_new_log_entry(self.current_id, self.current_tg, self.current_cc)
                        self.last_logged_id = self.current_id
                        if self.recorder_enabled_check.isChecked(): self.is_recording and self.stop_internal_recording(); self.start_internal_recording(self.current_id)
                        self.check_for_alerts(self.current_tg, self.current_id)
                elif not self.is_in_transmission:
                     for panel in [self.live_labels_conf, self.live_labels_dash]: panel and (panel['status'].setText(text.strip().replace("Sync: ", "")), timestamp and panel['last_sync'].setText(timestamp))
            if "Sync: no sync" in text and self.is_in_transmission: 
                self.is_in_transmission = False; self.end_all_transmissions()
                for panel in [self.live_labels_conf, self.live_labels_dash]: panel and panel['status'].setText("No Sync")
                if self.is_recording: self.stop_internal_recording()
                self.current_id = None; self.current_tg = None; self.last_logged_id = None
        except Exception as e: print(f"Log parse error: {e}")
    def start_new_log_entry(self, id_val, tg_val, cc_val):
        start_time = datetime.now(); start_time_str = start_time.strftime("%H:%M:%S"); tg_alias = self.aliases['tg'].get(tg_val, tg_val) or "N/A"; id_alias = self.aliases['id'].get(id_val, id_val) or "N/A"
        row_items = [QTableWidgetItem(start_time_str), QTableWidgetItem(""), QTableWidgetItem(""), QTableWidgetItem(tg_alias), QTableWidgetItem(id_alias), QTableWidgetItem(cc_val or "N/A")]
        self.logbook_table.insertRow(0)
        for i, item in enumerate(row_items): (item.setData(Qt.UserRole, tg_val) if i == 3 else item.setData(Qt.UserRole, id_val) if i == 4 else None); self.logbook_table.setItem(0, i, item)
        self.mini_logbook_table.insertRow(0); [self.mini_logbook_table.setItem(0, i, item.clone()) for i, item in enumerate(row_items)]; self.mini_logbook_table.rowCount() > 10 and self.mini_logbook_table.removeRow(10)
        self.transmission_log[id_val] = {'start_time': start_time, 'tg': tg_val, 'id_alias': id_alias}
    def end_all_transmissions(self, end_current=True):
        end_time = datetime.now(); end_time_str = end_time.strftime("%H:%M:%S")
        for log_data in self.transmission_log.values():
            duration = end_time - log_data['start_time']; duration_str = str(duration).split('.')[0]
            for panel in [self.live_labels_conf, self.live_labels_dash]: panel and panel['duration'].setText(duration_str)
            for r in range(self.logbook_table.rowCount()):
                if self.logbook_table.item(r,4) and self.logbook_table.item(r,4).text() == log_data['id_alias'] and (not self.logbook_table.item(r,1) or not self.logbook_table.item(r,1).text()): self.logbook_table.setItem(r,1,QTableWidgetItem(end_time_str)); self.logbook_table.setItem(r,2,QTableWidgetItem(duration_str)); break
            for r in range(self.mini_logbook_table.rowCount()):
                if self.mini_logbook_table.item(r,4) and self.mini_logbook_table.item(r,4).text() == log_data['id_alias'] and (not self.mini_logbook_table.item(r,1) or not self.mini_logbook_table.item(r,1).text()): self.mini_logbook_table.setItem(r,1,QTableWidgetItem(end_time_str)); self.mini_logbook_table.setItem(r,2,QTableWidgetItem(duration_str)); break
        if end_current: self.transmission_log.clear(); self.last_logged_id = None; hasattr(self, 'scope_curve') and self.scope_curve.setData([])
    def start_internal_recording(self, id_):
        rec_dir = self.recorder_dir_edit.text();_id=id_.replace('/','-')
        if not rec_dir or not os.path.isdir(rec_dir): return
        filepath = os.path.join(rec_dir, datetime.now().strftime("%Y-%m-%d_%H%M%S") + f"_ID_{_id}.wav")
        try:
            self.wav_file = wave.open(filepath, 'wb'); self.wav_file.setnchannels(WAV_CHANNELS); self.wav_file.setsampwidth(WAV_SAMPWIDTH); self.wav_file.setframerate(AUDIO_RATE); self.is_recording = True
            for panel in [self.live_labels_conf, self.live_labels_dash]: panel and (panel['recording'].setText("ACTIVE"), panel['recording'].setStyleSheet("color: #ffaa00; font-weight: bold;"))
        except Exception as e: print(f"Error starting recording: {e}"); self.wav_file = None; self.is_recording = False
    def stop_internal_recording(self):
        if self.wav_file:
            try: self.wav_file.close()
            except Exception as e: print(f"Error closing wav file: {e}")
        self.wav_file = None; self.is_recording = False
        for panel in [self.live_labels_conf, self.live_labels_dash]: panel and (panel['recording'].setText("INACTIVE"), panel['recording'].setStyleSheet("color: gray;"))
    def process_audio_data(self, raw_data):
        if raw_data.startswith(b"ERROR:"): QMessageBox.critical(self, "UDP Error", raw_data.decode()); self.close(); return
        clean_num_bytes = (len(raw_data) // np.dtype(AUDIO_DTYPE).itemsize) * np.dtype(AUDIO_DTYPE).itemsize
        if clean_num_bytes == 0: return
        audio_samples = np.frombuffer(raw_data[:clean_num_bytes], dtype=AUDIO_DTYPE)
        if self.is_recording and self.wav_file: self.wav_file.writeframes(audio_samples.tobytes())
        filtered_samples = self.apply_filters(audio_samples.copy())
        if not self.mute_check.isChecked() and self.output_stream:
            try: self.output_stream.write((filtered_samples * self.volume).astype(AUDIO_DTYPE))
            except Exception: pass
        self.scope_curve.setData(audio_samples)
        audio_samples_float = audio_samples.astype(np.float32) / 32768.0
        self.rms_label.setText(f"RMS Level: {np.sqrt(np.mean(audio_samples_float**2)):.4f}")
        if len(audio_samples_float) < CHUNK_SAMPLES: audio_samples_float = np.pad(audio_samples_float, (0, CHUNK_SAMPLES - len(audio_samples_float)))
        with np.errstate(divide='ignore', invalid='ignore'):
            magnitude = np.abs(np.fft.fft(audio_samples_float)[:CHUNK_SAMPLES // 2]); log_magnitude = 20 * np.log10(magnitude + 1e-12)
        log_magnitude = np.nan_to_num(log_magnitude, nan=MIN_DB, posinf=MAX_DB, neginf=MIN_DB)
        self.peak_freq_label.setText(f"Peak Freq: {np.argmax(log_magnitude) * (AUDIO_RATE / CHUNK_SAMPLES):.0f} Hz")
        self.spec_data = np.roll(self.spec_data, -1, axis=0); self.spec_data[-1, :] = log_magnitude
        self.imv.setImage(np.rot90(self.spec_data), autoLevels=False, levels=(MIN_DB, MAX_DB))
    def search_in_log(self):
        if self.terminal_output_conf.find(self.search_input.text()): return
        cursor = self.terminal_output_conf.textCursor(); cursor.movePosition(QTextCursor.Start); self.terminal_output_conf.setTextCursor(cursor)
        if not self.terminal_output_conf.find(self.search_input.text()): QMessageBox.information(self, "Search", f"Phrase '{self.search_input.text()}' not found.")
    def filter_logbook(self):
        search_text = self.logbook_search_input.text().lower()
        for row in range(self.logbook_table.rowCount()): self.logbook_table.setRowHidden(row, not any(item and search_text in item.text().lower() for item in (self.logbook_table.item(row, col) for col in range(self.logbook_table.columnCount()))))
    def load_aliases(self):
        if os.path.exists(ALIASES_FILE):
            try:
                with open(ALIASES_FILE, 'r') as f: self.aliases = json.load(f)
                self.aliases.setdefault('tg', {}); self.aliases.setdefault('id', {})
            except (json.JSONDecodeError, TypeError): self.aliases = {'tg': {}, 'id': {}}
        self.update_alias_tables()
    def save_aliases(self):
        with open(ALIASES_FILE, 'w') as f: json.dump(self.aliases, f, indent=4)
    def add_alias_row(self, table): table.insertRow(table.rowCount())
    def remove_alias_row(self, table, alias_type):
        current_row = table.currentRow()
        if current_row < 0: return
        key_item = table.item(current_row, 0)
        if key_item and key_item.text() in self.aliases[alias_type]: del self.aliases[alias_type][key_item.text()]
        table.removeRow(current_row)
    def update_alias_tables(self):
        self.tg_alias_table.blockSignals(True); self.id_alias_table.blockSignals(True)
        self.tg_alias_table.setRowCount(0); self.id_alias_table.setRowCount(0)
        for key, val in self.aliases.get('tg', {}).items(): row = self.tg_alias_table.rowCount(); self.tg_alias_table.insertRow(row); self.tg_alias_table.setItem(row, 0, QTableWidgetItem(key)); self.tg_alias_table.setItem(row, 1, QTableWidgetItem(val))
        for key, val in self.aliases.get('id', {}).items(): row = self.id_alias_table.rowCount(); self.id_alias_table.insertRow(row); self.id_alias_table.setItem(row, 0, QTableWidgetItem(key)); self.id_alias_table.setItem(row, 1, QTableWidgetItem(val))
        self.tg_alias_table.blockSignals(False); self.id_alias_table.blockSignals(False)
    def update_alias(self, table, alias_type, item):
        row = item.row(); key_item, val_item = table.item(row, 0), table.item(row, 1)
        if key_item and val_item:
            key, val = key_item.text().strip(), val_item.text().strip()
            if key: self.aliases[alias_type][key] = val
    def update_statistics(self):
        start_date, end_date = self.stats_start_date.date().toPyDate(), self.stats_end_date.date().toPyDate()
        tg_counts, id_counts, hour_counts, total_duration, filtered_rows = Counter(), Counter(), Counter(), timedelta(), 0
        for row in range(self.logbook_table.rowCount()):
            if not (start_date <= datetime.now().date() <= end_date): continue
            filtered_rows += 1
            tg_item, id_item = self.logbook_table.item(row, 3), self.logbook_table.item(row, 4)
            if tg_item and tg_item.data(Qt.UserRole): tg_counts[tg_item.data(Qt.UserRole)] += 1
            if id_item and id_item.data(Qt.UserRole): id_counts[id_item.data(Qt.UserRole)] += 1
            if self.logbook_table.item(row, 0):
                try: hour_counts[datetime.strptime(self.logbook_table.item(row, 0).text(), "%H:%M:%S").hour] += 1
                except ValueError: pass
            if self.logbook_table.item(row, 2) and self.logbook_table.item(row, 2).text():
                try: h,m,s = map(int, self.logbook_table.item(row, 2).text().split(':')); total_duration += timedelta(hours=h,minutes=m,seconds=s)
                except: pass
        self.total_calls_label.setText(f"<b>{filtered_rows}</b>"); self.total_duration_label.setText(f"<b>{total_duration}</b>")
        self.most_active_tg_label.setText(f"<b>{self.aliases['tg'].get(tg_counts.most_common(1)[0][0], tg_counts.most_common(1)[0][0])}</b> ({tg_counts.most_common(1)[0][1]} calls)" if tg_counts else "---")
        self.most_active_id_label.setText(f"<b>{self.aliases['id'].get(id_counts.most_common(1)[0][0], id_counts.most_common(1)[0][0])}</b> ({id_counts.most_common(1)[0][1]} calls)" if id_counts else "---")
        for chart, data, alias_type in [(self.tg_chart, tg_counts.most_common(10), 'tg'), (self.id_chart, id_counts.most_common(10), 'id')]:
            chart.clear();
            if data:
                labels = [self.aliases[alias_type].get(item[0], item[0]) for item in data]
                bar = pg.BarGraphItem(x=range(len(data)), height=[item[1] for item in data], width=0.6, brush=self.palette().highlight().color())
                chart.addItem(bar); chart.getAxis('bottom').setTicks([list(enumerate(labels))])
        self.time_chart.clear()
        if hour_counts: hours, counts = zip(*sorted(hour_counts.items())); self.time_chart.plot(list(hours), list(counts), pen=pg.mkPen(color=self.palette().highlight().color(), width=2), symbol='o', symbolBrush=self.palette().highlight().color())
    def browse_for_recording_dir(self):
        path = QFileDialog.getExistingDirectory(self, "Select Recording Directory")
        if path: self.recorder_dir_edit.setText(path); self.fs_watcher.addPath(path); self.update_recording_list()
    def update_recording_list(self):
        self.recording_list.clear(); rec_dir = self.recorder_dir_edit.text()
        if rec_dir and os.path.exists(rec_dir): self.recording_list.addItems(QDir(rec_dir).entryList(["*.wav"], QDir.Files | QDir.NoDotAndDotDot, QDir.Time))
    def play_recording(self):
        selected = self.recording_list.selectedItems()
        path = os.path.join(self.recorder_dir_edit.text(), (selected[0] if selected else self.recording_list.item(0)).text()) if self.recording_list.count() > 0 else None
        if path and os.path.exists(path): QSound.play(path)
    def import_csv_to_logbook(self):
        path, _ = QFileDialog.getOpenFileName(self, "Import CSV", "", "CSV Files (*.csv)"); 
        if path:
            with open(path, 'r', newline='', encoding='utf-8') as f:
                reader = csv.reader(f); self.logbook_table.setRowCount(0); next(reader, None); self.logbook_table.setSortingEnabled(False)
                for row_data in reader: row = self.logbook_table.rowCount(); self.logbook_table.insertRow(row); [self.logbook_table.setItem(row, i, QTableWidgetItem(data)) for i, data in enumerate(row_data)]
                self.logbook_table.setSortingEnabled(True)
    def save_history_to_csv(self):
        path, _ = QFileDialog.getSaveFileName(self, "Save CSV", "", "CSV Files (*.csv)"); 
        if path:
            with open(path, 'w', newline='', encoding='utf-8') as f:
                writer = csv.writer(f); writer.writerow([self.logbook_table.horizontalHeaderItem(i).text() for i in range(self.logbook_table.columnCount())])
                for row in range(self.logbook_table.rowCount()): writer.writerow([self.logbook_table.item(row, col).text() if self.logbook_table.item(row, col) else "" for col in range(self.logbook_table.columnCount())])
            QMessageBox.information(self, "Success", f"Logbook successfully saved to {os.path.basename(path)}")
    def add_alert(self):
        alert_type = "TG" if self.alert_type_combo.currentText() == "Talkgroup (TG)" else "ID"; value = self.alert_value_edit.text().strip(); sound = self.alert_sound_edit.text().strip() or "Default"
        if not value: QMessageBox.warning(self, "Input Error", "Value cannot be empty."); return
        existing_alert_index = next((i for i, alert in enumerate(self.alerts) if alert['type'] == alert_type and alert['value'] == value), None)
        if existing_alert_index is not None: self.alerts[existing_alert_index]['sound'] = sound
        else: self.alerts.append({"type": alert_type, "value": value, "sound": sound})
        self.update_alerts_list(); self.alert_value_edit.clear(); self.alert_sound_edit.clear()
    def remove_alert(self):
        current_row = self.alerts_table.currentRow()
        if current_row >= 0: self.alerts.pop(current_row); self.update_alerts_list()
    def update_alerts_list(self):
        self.alerts_table.setRowCount(0)
        for alert in self.alerts:
            row = self.alerts_table.rowCount(); self.alerts_table.insertRow(row)
            self.alerts_table.setItem(row, 0, QTableWidgetItem(alert['type'])); self.alerts_table.setItem(row, 1, QTableWidgetItem(alert['value'])); self.alerts_table.setItem(row, 2, QTableWidgetItem(alert['sound']))
    def populate_alert_form(self, item):
        row = item.row()
        self.alert_type_combo.setCurrentText(f"Talkgroup (TG)" if self.alerts[row]['type'] == 'TG' else "Radio ID")
        self.alert_value_edit.setText(self.alerts[row]['value'])
        self.alert_sound_edit.setText(self.alerts[row]['sound'] if self.alerts[row]['sound'] != "Default" else "")
    def play_alert_sound(self, sound_path):
        if sound_path == "Default" or not sound_path:
            if WINSOUND_AVAILABLE: threading.Thread(target=lambda: (winsound.Beep(1200, 150), winsound.Beep(1000, 150))).start()
            else: print('\a', flush=True)
        elif os.path.exists(sound_path):
            QSound.play(sound_path)
    def check_for_alerts(self, tg, id):
        if not tg or not id: return
        for alert in self.alerts:
            if (alert['type'] == 'TG' and alert['value'] == tg) or (alert['type'] == 'ID' and alert['value'] == id): self.play_alert_sound(alert['sound']); break
    def populate_audio_devices(self):
        try:
            devices = sd.query_devices(); default_out = sd.default.device[1]
            for i, device in enumerate(devices):
                if device['max_output_channels'] > 0: self.device_combo.addItem(f"{device['name']}{' (Default)' if i == default_out else ''}", userData=i)
        except Exception as e: print(f"Could not query audio devices: {e}")
    def restart_audio_stream(self):
        if self.output_stream: self.output_stream.stop(); self.output_stream.close()
        try:
            self.output_stream = sd.OutputStream(samplerate=AUDIO_RATE, device=self.device_combo.currentData(), channels=1, dtype=AUDIO_DTYPE); self.output_stream.start()
        except Exception as e: print(f"Error opening audio stream: {e}")
    def set_volume(self, value): self.volume = value / 100.0
    def apply_filters(self, samples):
        if self.hp_filter_check.isChecked():
            b, a = signal.butter(4, self.hp_cutoff_spin.value(), 'highpass', fs=AUDIO_RATE)
            if self.filter_hp_state is None: self.filter_hp_state = signal.lfilter_zi(b,a)
            samples, self.filter_hp_state = signal.lfilter(b, a, samples, zi=self.filter_hp_state)
        if self.lp_filter_check.isChecked():
            b, a = signal.butter(4, self.lp_cutoff_spin.value(), 'lowpass', fs=AUDIO_RATE)
            if self.filter_lp_state is None: self.filter_lp_state = signal.lfilter_zi(b,a)
            samples, self.filter_lp_state = signal.lfilter(b, a, samples, zi=self.filter_lp_state)
        return samples.astype(AUDIO_DTYPE)
    #</editor-fold>

if __name__ == '__main__':
    if hasattr(Qt, 'AA_EnableHighDpiScaling'): QApplication.setAttribute(Qt.AA_EnableHighDpiScaling, True)
    if hasattr(Qt, 'AA_UseHighDpiPixmaps'): QApplication.setAttribute(Qt.AA_UseHighDpiPixmaps, True)
    
    app = QApplication(sys.argv)
    
    main_window = DSDApp()
    
    if main_window.dsd_fme_path:
        main_window.show()
        sys.exit(app.exec_())
    else:
        sys.exit(0)
