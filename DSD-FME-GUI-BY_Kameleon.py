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
import time
import numpy as np

# --- AppData Storage ---
APP_NAME = "DSD-FME-GUI"
if sys.platform == "win32":
    APP_DATA_DIR = os.path.join(os.environ['APPDATA'], APP_NAME)
else:
    APP_DATA_DIR = os.path.join(os.path.expanduser('~'), '.config', APP_NAME)
os.makedirs(APP_DATA_DIR, exist_ok=True)

# +++ STT Integration +++
try:
    import whisper
    WHISPER_AVAILABLE = True
except ImportError:
    WHISPER_AVAILABLE = False

try:
    from vosk import Model as VoskModel, KaldiRecognizer
    VOSK_AVAILABLE = True
except ImportError:
    VOSK_AVAILABLE = False


def resource_path(relative_path):
    try:
        base_path = sys._MEIPASS
    except Exception:
        base_path = APP_DATA_DIR
        if relative_path in ['dsd-fme.exe', 'dsd-fme']:
             base_path = os.path.abspath(".")

    local_path = os.path.join(os.path.abspath("."), relative_path)
    appdata_path = os.path.join(base_path, relative_path)

    if not os.path.exists(appdata_path) and os.path.exists(local_path) and relative_path not in ['dsd-fme.exe', 'dsd-fme']:
        import shutil
        try:
            shutil.copy2(local_path, appdata_path)
        except Exception as e:
            print(f"Could not copy file {relative_path} to AppData: {e}")
            return local_path

    if relative_path.endswith('.json') or relative_path.endswith('.html'):
        return appdata_path

    if relative_path in ['dsd-fme.exe', 'dsd-fme']:
        return os.path.join(os.path.abspath("."), relative_path)

    return appdata_path

from PyQt5.QtWidgets import *
from PyQt5.QtGui import QFont, QPalette, QColor, QTextCursor, QKeySequence, QDesktopServices
from PyQt5.QtMultimedia import QSound
from PyQt5.QtCore import Qt, QThread, pyqtSignal, QObject, pyqtSlot, QTimer, QDir, QFileSystemWatcher, QDate, QEvent, QUrl
from PyQt5.QtWebEngineWidgets import QWebEngineView

import pyqtgraph as pg
from pyqtgraph import DateAxisItem, AxisItem
import sounddevice as sd
from scipy import signal
import folium

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

CONFIG_FILE = resource_path('dsd-fme-gui-config.json')
ALIASES_FILE = resource_path('dsd-fme-aliases.json')
MAP_FILE = resource_path('lrrp_map.html')
UDP_IP = "127.0.0.1"; UDP_PORT = 23456
CHUNK_SAMPLES = 1024; SPEC_WIDTH = 400
MIN_DB = -70; MAX_DB = 50
AUDIO_RATE = 16000; AUDIO_DTYPE = np.int16
WAV_CHANNELS = 2; WAV_SAMPWIDTH = 2

class IntegerAxis(AxisItem):
    def tickStrings(self, values, scale, spacing):
        return [f'{int(v)}' for v in values]

# +++ STT Integration: Transcription Worker +++
class TranscriptionWorker(QObject):
    finished = pyqtSignal(str, str)
    progress = pyqtSignal(str)

    def __init__(self, audio_data, radio_id, stt_settings):
        super().__init__()
        self.audio_data = audio_data
        self.radio_id = radio_id
        self.settings = stt_settings

    @pyqtSlot()
    def run(self):
        engine = self.settings.get('engine')
        result_text = f"[{engine} Error]"

        try:
            if engine == 'Whisper' and WHISPER_AVAILABLE:
                result_text = self.transcribe_whisper()
            elif engine == 'Vosk' and VOSK_AVAILABLE:
                result_text = self.transcribe_vosk()
            else:
                result_text = "[STT Engine not available]"
        except Exception as e:
            result_text = f"[Transcription failed: {e}]"
            print(f"Transcription error for ID {self.radio_id}: {e}")

        self.finished.emit(self.radio_id, result_text)

    def transcribe_whisper(self):
        model_name = self.settings.get('whisper_model', 'tiny')
        language = self.settings.get('language', 'English')
        lang_map = {'Polish': 'pl', 'English': 'en'}

        self.progress.emit(f"Loading Whisper model: {model_name}...")
        model = whisper.load_model(model_name)

        self.progress.emit(f"Transcribing audio for ID: {self.radio_id}...")
        # Whisper expects float32 array normalized to [-1.0, 1.0]
        audio_float = self.audio_data.astype(np.float32) / 32768.0
        result = model.transcribe(audio_float, language=lang_map.get(language, 'en'))

        self.progress.emit("Transcription complete.")
        return result['text'].strip()

    def transcribe_vosk(self):
        model_path = self.settings.get('vosk_model_path')
        if not model_path or not os.path.exists(model_path):
            return "[Vosk model path not set or invalid]"

        self.progress.emit(f"Loading Vosk model from: {model_path}...")
        model = VoskModel(model_path)
        rec = KaldiRecognizer(model, AUDIO_RATE)
        rec.SetWords(True)

        self.progress.emit(f"Transcribing audio for ID: {self.radio_id}...")
        rec.AcceptWaveform(self.audio_data.tobytes())
        result = json.loads(rec.FinalResult())

        self.progress.emit("Transcription complete.")
        return result.get('text', '')

class AudioProcessingWindow(QDialog):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.main_app = parent
        self.setWindowTitle("Audio-Lab")
        self.setGeometry(200, 200, 600, 700)

        main_layout = QVBoxLayout(self)
        scroll_area = QScrollArea()
        scroll_area.setWidgetResizable(True)
        main_layout.addWidget(scroll_area)

        container_widget = QWidget()
        scroll_area.setWidget(container_widget)
        container_layout = QVBoxLayout(container_widget)

        container_layout.addWidget(self._create_equalizer_group())
        container_layout.addWidget(self._create_standard_filters_group())
        container_layout.addWidget(self._create_advanced_filters_group())

        button_layout = QHBoxLayout()
        close_button = QPushButton("Close")
        close_button.clicked.connect(self.accept)
        button_layout.addStretch()
        button_layout.addWidget(close_button)
        main_layout.addLayout(button_layout)

    def _create_equalizer_group(self):
        group = QGroupBox("6-Band Equalizer")
        main_layout = QVBoxLayout(group)

        eq_layout = QHBoxLayout()
        self.main_app.eq_sliders = []
        self.main_app.eq_labels = []
        eq_bands = [100, 300, 600, 1000, 3000, 6000]

        for i, freq in enumerate(eq_bands):
            slider_v_layout = QVBoxLayout()
            label = QLabel(f"{freq / 1000 if freq >= 1000 else freq}{'k' if freq >= 1000 else ''}Hz")
            label.setAlignment(Qt.AlignCenter)

            slider = QSlider(Qt.Vertical)
            slider.setRange(-20, 20)
            slider.setValue(0)
            slider.setTickPosition(QSlider.TicksBothSides)
            slider.setTickInterval(5)
            self.main_app._add_widget(f'eq_band_{i}', slider)

            slider_v_layout.addWidget(label)
            slider_v_layout.addWidget(slider)
            eq_layout.addLayout(slider_v_layout)
            self.main_app.eq_sliders.append(slider)
        main_layout.addLayout(eq_layout)

        btn_layout = QHBoxLayout()
        reset_btn = QPushButton("Reset to Default")
        reset_btn.clicked.connect(self.reset_equalizer)
        btn_layout.addStretch()
        btn_layout.addWidget(reset_btn)
        main_layout.addLayout(btn_layout)

        return group

    def _create_standard_filters_group(self):
        group = QGroupBox("Standard Filters")
        main_layout = QVBoxLayout(group)
        l1 = QGridLayout()

        l1.addWidget(self.main_app._add_widget("hp_filter_check", QCheckBox("High-pass Filter")), 0, 0)
        l1.addWidget(self.main_app._add_widget("hp_cutoff_spin", QSpinBox(), {'range': (100, 2000), 'suffix': ' Hz', 'value': 300}), 0, 1)
        l1.addWidget(self.main_app._add_widget("lp_filter_check", QCheckBox("Low-pass Filter")), 1, 0)
        l1.addWidget(self.main_app._add_widget("lp_cutoff_spin", QSpinBox(), {'range': (1000, 8000), 'suffix': ' Hz', 'value': 3400}), 1, 1)
        l1.addWidget(self.main_app._add_widget("bp_filter_check", QCheckBox("Band-pass Filter")), 2, 0)
        l1.addWidget(self.main_app._add_widget("bp_center_spin", QSpinBox(), {'range': (300, 5000), 'suffix': ' Hz', 'value': 1500}), 2, 1)
        l1.addWidget(self.main_app._add_widget("bp_width_spin", QSpinBox(), {'range': (100, 3000), 'suffix': ' Hz', 'value': 1000}), 2, 2)
        l1.addWidget(self.main_app._add_widget("notch_filter_check", QCheckBox("Notch Filter")), 3, 0)
        l1.addWidget(self.main_app._add_widget("notch_freq_spin", QSpinBox(), {'range': (100, 8000), 'suffix': ' Hz', 'value': 1000}), 3, 1)
        l1.addWidget(self.main_app._add_widget("notch_q_spin", QSpinBox(), {'range': (1, 100), 'value': 30}), 3, 2)
        main_layout.addLayout(l1)

        btn_layout = QHBoxLayout()
        reset_btn = QPushButton("Reset to Default")
        reset_btn.clicked.connect(self.reset_standard_filters)
        btn_layout.addStretch()
        btn_layout.addWidget(reset_btn)
        main_layout.addLayout(btn_layout)

        return group

    def _create_advanced_filters_group(self):
        group = QGroupBox("Advanced Filters")
        main_layout = QVBoxLayout(group)
        l2 = QGridLayout()

        l2.addWidget(self.main_app._add_widget("agc_check", QCheckBox("Automatic Gain Control (AGC)")), 0, 0)
        l2.addWidget(QLabel("Strength:"), 0, 1)
        l2.addWidget(self.main_app._add_widget("agc_strength_slider", QSlider(Qt.Horizontal), {'range': (0, 100), 'value': 50}), 0, 2)

        l2.addWidget(self.main_app._add_widget("nr_check", QCheckBox("Noise Reduction (Simple)")), 1, 0)
        l2.addWidget(QLabel("Strength:"), 1, 1)
        l2.addWidget(self.main_app._add_widget("nr_strength_slider", QSlider(Qt.Horizontal), {'range': (0, 100), 'value': 50}), 1, 2)

        main_layout.addLayout(l2)

        btn_layout = QHBoxLayout()
        reset_btn = QPushButton("Reset to Default")
        reset_btn.clicked.connect(self.reset_advanced_filters)
        btn_layout.addStretch()
        btn_layout.addWidget(reset_btn)
        main_layout.addLayout(btn_layout)

        return group

    def reset_equalizer(self):
        for slider in self.main_app.eq_sliders:
            slider.setValue(0)

    def reset_standard_filters(self):
        self.main_app.widgets['hp_filter_check'].setChecked(False)
        self.main_app.widgets['lp_filter_check'].setChecked(False)
        self.main_app.widgets['bp_filter_check'].setChecked(False)
        self.main_app.widgets['notch_filter_check'].setChecked(False)

        self.main_app.widgets['hp_cutoff_spin'].setValue(300)
        self.main_app.widgets['lp_cutoff_spin'].setValue(3400)
        self.main_app.widgets['bp_center_spin'].setValue(1500)
        self.main_app.widgets['bp_width_spin'].setValue(1000)
        self.main_app.widgets['notch_freq_spin'].setValue(1000)
        self.main_app.widgets['notch_q_spin'].setValue(30)

    def reset_advanced_filters(self):
        self.main_app.widgets['agc_check'].setChecked(False)
        self.main_app.widgets['nr_check'].setChecked(False)
        self.main_app.widgets['agc_strength_slider'].setValue(50)
        self.main_app.widgets['nr_strength_slider'].setValue(50)

class ProcessReader(QObject):
    line_read = pyqtSignal(str)
    finished = pyqtSignal()

    def __init__(self, process):
        super().__init__()
        self.process = process

    @pyqtSlot()
    def run(self):
        if self.process and self.process.stdout:
            for line in iter(self.process.stdout.readline, ''):
                self.line_read.emit(line)
        # When the loop finishes (process terminates), emit the finished signal
        self.finished.emit()

class UdpListener(QObject):
    data_ready = pyqtSignal(int, bytes)

    def __init__(self, ip, port, channel):
        super().__init__()
        self.ip, self.port, self.channel = ip, port, channel
        self.running = True

    @pyqtSlot()
    def run(self):
        sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        try:
            sock.bind((self.ip, self.port))
            sock.settimeout(1)
        except OSError as e:
            self.data_ready.emit(self.channel, f"ERROR: Port {self.port} is already in use. {e}".encode())
            return
        while self.running:
            try:
                data, addr = sock.recvfrom(CHUNK_SAMPLES * 2)
                if data:
                    self.data_ready.emit(self.channel, data)
            except socket.timeout:
                continue
        sock.close()

class NumericTableWidgetItem(QTableWidgetItem):
    def __lt__(self, other):
        try: return int(self.text()) < int(other.text())
        except ValueError: return super().__lt__(other)


class DSDApp(QMainWindow):
    def __init__(self):
        super().__init__()
        self.processes = []
        self.reader_threads = []
        self.reader_workers = []
        self.udp_listener_threads = []
        self.udp_listeners = []
        self.is_in_transmission = False; self.alerts = []; self.recording_dir = ""
        self.is_recording = False; self.wav_file = None; self.is_resetting = False
        self.transmission_log = {}; self.last_logged_id = None
        self.output_stream = None; self.volume = 1.0
        self.filter_states = {}
        self.aliases = {'tg': {}, 'id': {}}
        self.current_tg = None; self.current_id = None; self.current_cc = None
        self.fs_watcher = QFileSystemWatcher(); self.fs_watcher.directoryChanged.connect(self.update_recording_list)
        self.lrrp_watcher = QFileSystemWatcher()
        self.lrrp_watcher.fileChanged.connect(self.update_map_from_lrrp)
        # +++ STT Integration +++
        self.stt_audio_buffer = {}
        self.stt_active_id_row = {}
        self.transcription_thread = None
        self.transcription_worker = None

        self.setWindowTitle("DSD-FME-GUI-BY Kameleon v3.0")
        self.setGeometry(100, 100, 1600, 950)

        self.widgets = {}; self.inverse_widgets = {}
        self.live_labels_conf = {}; self.live_labels_dash = {}

        self._create_theme_manager()

        self.colormaps = {
            "Amber Alert": pg.ColorMap(pos=np.linspace(0.0,1.0,3),color=[(0,0,0),(150,80,0),(255,170,0)]), "Night Mode (Red)": pg.ColorMap(pos=np.linspace(0.0,1.0,3),color=[(0,0,0),(130,0,0),(255,50,50)]),
            "Inferno (High Contrast)": pg.ColorMap(pos=np.linspace(0.0,1.0,4),color=[(0,0,0),(120,0,0),(255,100,0),(255,255,100)]), "Oceanic (Blue)": pg.ColorMap(pos=np.linspace(0.0,1.0,3),color=[(0,0,20),(0,80,130),(100,200,200)]),
            "Grayscale (Mono)": pg.ColorMap(pos=np.linspace(0.0,1.0,3),color=[(0,0,0),(128,128,128),(255,255,255)]), "Military Green": pg.ColorMap(pos=np.linspace(0.0,1.0,3),color=[(0,0,0),(0,120,0),(0,255,0)]),
            "Night Vision": pg.ColorMap(pos=np.linspace(0.0,1.0,3),color=[(0,20,0),(0,180,80),(100,255,150)]), "Arctic Blue": pg.ColorMap(pos=np.linspace(0.0,1.0,3),color=[(0,0,0),(0,0,150),(100,180,255)])
        }

        self.dsd_fme_path = self._load_config_or_prompt()
        if self.dsd_fme_path:
            self._init_ui()
            self.audio_lab_window = AudioProcessingWindow(self)
            self._load_app_config()
            self.load_aliases()
        else:
            QTimer.singleShot(100, self.close)

    def _create_theme_manager(self):
        self.themes = {
            "Default (Kameleon Dark)": { "palette": self._get_dark_palette, "stylesheet": self._get_dark_stylesheet, "pg_background": "#15191c", "pg_foreground": "#e0e0e0", "spec_colormap": "Amber Alert" },
            "Matrix": { "palette": self._get_matrix_palette, "stylesheet": self._get_matrix_stylesheet, "pg_background": "#020f03", "pg_foreground": "#00ff41", "spec_colormap": "Military Green" },
            "Cyberpunk": { "palette": self._get_cyberpunk_palette, "stylesheet": self._get_cyberpunk_stylesheet, "pg_background": "#0c0c28", "pg_foreground": "#f7f722", "spec_colormap": "Inferno (High Contrast)" },
            "Neon Noir": { "palette": self._get_neon_palette, "stylesheet": self._get_neon_stylesheet, "pg_background": "#101018", "pg_foreground": "#f000ff", "spec_colormap": "Night Vision" },
            "Retro Gaming": { "palette": self._get_retro_palette, "stylesheet": self._get_retro_stylesheet, "pg_background": "#212121", "pg_foreground": "#eeeeee", "spec_colormap": "Grayscale (Mono)" },
            "Military Ops": { "palette": self._get_military_palette, "stylesheet": self._get_military_stylesheet, "pg_background": "#1a2418", "pg_foreground": "#a2b59f", "spec_colormap": "Military Green" },
            "Arctic Ops": { "palette": self._get_arctic_palette, "stylesheet": self._get_arctic_stylesheet, "pg_background": "#e8eef2", "pg_foreground": "#1c2e4a", "spec_colormap": "Arctic Blue" },
            "Solarized Dark": { "palette": self._get_solarized_dark_palette, "stylesheet": self._get_solarized_dark_stylesheet, "pg_background": "#002b36", "pg_foreground": "#839496", "spec_colormap": "Oceanic (Blue)" },
            "Dracula": { "palette": self._get_dracula_palette, "stylesheet": self._get_dracula_stylesheet, "pg_background": "#282a36", "pg_foreground": "#f8f8f2", "spec_colormap": "Night Mode (Red)" },
            "Night Mode (Astro Red)": { "palette": self._get_red_palette, "stylesheet": self._get_red_stylesheet, "pg_background": "#0a0000", "pg_foreground": "#ff4444", "spec_colormap": "Night Mode (Red)" },
            "Oceanic (Deep Blue)": { "palette": self._get_blue_palette, "stylesheet": self._get_blue_stylesheet, "pg_background": "#0B1D28", "pg_foreground": "#E0FFFF", "spec_colormap": "Oceanic (Blue)" },
            "Light (High Contrast)": { "palette": self._get_light_palette, "stylesheet": self._get_light_stylesheet, "pg_background": "#E8E8E8", "pg_foreground": "#000000", "spec_colormap": "Grayscale (Mono)" },
        }
        self.current_theme_name = "Default (Kameleon Dark)"

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
            QWidget{color:#e0e0e0;font-size:9pt} QGroupBox{font-weight:bold;border:1px solid #3a4149;border-radius:6px;margin-top:1ex; background-color: #1e2328;} QGroupBox::title{subcontrol-origin:margin;subcontrol-position:top left;padding:0 5px;left:10px;background-color:#15191c} QPushButton{font-weight:bold;border-radius:5px;padding:6px 12px;border:1px solid #3a4149;background-color:qlineargradient(x1:0,y1:0,x2:0,y2:1,stop:0 #2c343a,stop:1 #242b30)} QPushButton:hover{background-color:#3e4850;border:1px solid #ffaa00} QPushButton:pressed{background-color:#242b30} QPushButton:disabled{color:#777;background-color:#242b30;border:1px solid #3a4149} QTabWidget::pane{border-top:2px solid #3a4149} QTabBar::tab{font-weight:bold;font-size:9pt;padding:8px;min-width:130px;max-width:130px;background-color:#1e2328;border:1px solid #3a4149;border-bottom:none;border-top-left-radius:5px;border-top-right-radius:5px} QTabBar::tab:selected{background-color:#2c343a;border:1px solid #ffaa00;border-bottom:none} QTabBar::tab:!selected:hover{background-color:#353e44} QLineEdit,QSpinBox,QComboBox,QTableWidget,QDateEdit,QPlainTextEdit,QListView{border-radius:4px;border:1px solid #3a4149;padding:4px} QPlainTextEdit{color:#33FF33;font-family:Consolas,monospace} QSlider::groove:horizontal{border:1px solid #3a4149;height:8px;background:#242b30;border-radius:4px} QSlider::handle:horizontal{background:#ffaa00;border:1px solid #ffaa00;width:18px;margin:-2px 0;border-radius:9px} QHeaderView::section{background-color:#2c343a;color:#e0e0e0;padding:4px;border:1px solid #3a4149;font-weight:bold} QTableWidget{gridline-color:#3a4149;}
        """
    def _get_matrix_palette(self):
        p = QPalette(); p.setColor(QPalette.Window, QColor("#020f03")); p.setColor(QPalette.WindowText, QColor("#00ff41")); p.setColor(QPalette.Base, QColor("#051803")); p.setColor(QPalette.AlternateBase, QColor("#0a2808")); p.setColor(QPalette.Text, QColor("#33ff77")); p.setColor(QPalette.Button, QColor("#0a2808")); p.setColor(QPalette.ButtonText, QColor("#00ff41")); p.setColor(QPalette.Highlight, QColor("#00ff41")); p.setColor(QPalette.HighlightedText, Qt.black); p.setColor(QPalette.Link, QColor("#66ff99")); p.setColor(QPalette.Disabled, QPalette.Text, Qt.darkGray); p.setColor(QPalette.Disabled, QPalette.ButtonText, Qt.darkGray); return p
    def _get_matrix_stylesheet(self):
        return "QWidget{font-family:'Courier New',monospace;color:#00ff41;background-color:#020f03;}QGroupBox{border:1px solid #00ff41;background-color:#051803;}QGroupBox::title{background-color:#020f03;}QPushButton{border:1px solid #00ff41;background-color:#103010;}QPushButton:hover{background-color:#205020;}QTabBar::tab{padding:8px;border:1px solid #008000;border-bottom:none;background:#051803;border-top-left-radius:5px;border-top-right-radius:5px;}QTabBar::tab:selected{background:#205020;border-color:#00ff41;}QTabBar::tab:!selected:hover{background:#104010;}QSlider::handle:horizontal{background:#00ff41;}QTableWidget{gridline-color:#008000;border:1px solid #00ff41;}QHeaderView::section{background-color:#103010;border:1px solid #00ff41;}"

    def _get_cyberpunk_palette(self):
        p = QPalette(); p.setColor(QPalette.Window, QColor("#0c0c28")); p.setColor(QPalette.WindowText, QColor("#f7f722")); p.setColor(QPalette.Base, QColor("#141434")); p.setColor(QPalette.AlternateBase, QColor("#222248")); p.setColor(QPalette.Text, QColor("#ffffff")); p.setColor(QPalette.Button, QColor("#141434")); p.setColor(QPalette.ButtonText, QColor("#f7f722")); p.setColor(QPalette.Highlight, QColor("#f7f722")); p.setColor(QPalette.HighlightedText, QColor("#0c0c28")); p.setColor(QPalette.Link, QColor("#ff00ff")); p.setColor(QPalette.Disabled, QPalette.Text, Qt.darkGray); p.setColor(QPalette.Disabled, QPalette.ButtonText, Qt.darkGray); return p
    def _get_cyberpunk_stylesheet(self):
        return "QWidget{color:#f7f722;background-color:#0c0c28;}QGroupBox{border:1px solid #ff00ff;background-color:#141434;}QGroupBox::title{background-color:#0c0c28;}QPushButton{border:1px solid #ff00ff;background-color:#202050;}QPushButton:hover{background-color:#303070;}QTabBar::tab{padding:8px;border:1px solid #ff00ff;border-bottom:none;background:#141434;border-top-left-radius:5px;border-top-right-radius:5px;}QTabBar::tab:selected{background:#303070;border-color:#f7f722;}QTabBar::tab:!selected:hover{background:#303070;}QSlider::handle:horizontal{background:#f7f722;}QTableWidget{gridline-color:#ff00ff;border:1px solid #f7f722;}QHeaderView::section{background-color:#202050;border:1px solid #ff00ff;}"

    def _get_neon_palette(self):
        p = QPalette(); p.setColor(QPalette.Window, QColor("#101018")); p.setColor(QPalette.WindowText, QColor("#f000ff")); p.setColor(QPalette.Base, QColor("#181828")); p.setColor(QPalette.AlternateBase, QColor("#202030")); p.setColor(QPalette.Text, QColor("#00ffff")); p.setColor(QPalette.Button, QColor("#202030")); p.setColor(QPalette.ButtonText, QColor("#f000ff")); p.setColor(QPalette.Highlight, QColor("#f000ff")); p.setColor(QPalette.HighlightedText, Qt.black); p.setColor(QPalette.Link, QColor("#00ffff")); p.setColor(QPalette.Disabled, QPalette.Text, Qt.darkGray); p.setColor(QPalette.Disabled, QPalette.ButtonText, Qt.darkGray); return p
    def _get_neon_stylesheet(self):
        return "QWidget{color:#00ffff;background-color:#101018;}QGroupBox{border:1px solid #f000ff;background-color:#181828;}QGroupBox::title{background-color:#101018;}QPushButton{border:1px solid #f000ff;background-color:#251530;}QPushButton:hover{background-color:#352040;}QTabBar::tab{padding:8px;border:1px solid #f000ff;border-bottom:none;background:#181828;border-top-left-radius:5px;border-top-right-radius:5px;}QTabBar::tab:selected{background:#251530;border-color:#00ffff;}QTabBar::tab:!selected:hover{background:#352040;}QSlider::handle:horizontal{background:#00ffff;}QTableWidget{gridline-color:#f000ff;border:1px solid #00ffff;}QHeaderView::section{background-color:#251530;border:1px solid #f000ff;}"

    def _get_retro_palette(self):
        p = QPalette(); p.setColor(QPalette.Window, QColor("#212121")); p.setColor(QPalette.WindowText, QColor("#eeeeee")); p.setColor(QPalette.Base, QColor("#303030")); p.setColor(QPalette.AlternateBase, QColor("#424242")); p.setColor(QPalette.Text, QColor("#eeeeee")); p.setColor(QPalette.Button, QColor("#424242")); p.setColor(QPalette.ButtonText, QColor("#eeeeee")); p.setColor(QPalette.Highlight, QColor("#ff5722")); p.setColor(QPalette.HighlightedText, QColor("#212121")); p.setColor(QPalette.Link, QColor("#ffc107")); p.setColor(QPalette.Disabled, QPalette.Text, Qt.darkGray); p.setColor(QPalette.Disabled, QPalette.ButtonText, Qt.darkGray); return p
    def _get_retro_stylesheet(self):
        return "QWidget{font-family:'Press Start 2P',cursive;color:#eeeeee;background-color:#212121;}QGroupBox{border:1px solid #ff5722;background-color:#303030;}QGroupBox::title{background-color:#212121;}QPushButton{border:1px solid #ffc107;background-color:#424242;}QTabBar::tab{padding:8px;border:1px solid #ffc107;border-bottom:none;background:#303030;border-top-left-radius:5px;border-top-right-radius:5px;}QTabBar::tab:selected{background:#424242;border-color:#ff5722;}QTabBar::tab:!selected:hover{background:#505050;}QSlider::handle:horizontal{background:#ffc107;}QTableWidget{gridline-color:#ff5722;border:1px solid #ffc107;}QHeaderView::section{background-color:#424242;border:1px solid #ffc107;}"

    def _get_military_palette(self):
        p = QPalette(); p.setColor(QPalette.Window, QColor("#1a2418")); p.setColor(QPalette.WindowText, QColor("#a2b59f")); p.setColor(QPalette.Base, QColor("#253522")); p.setColor(QPalette.AlternateBase, QColor("#354831")); p.setColor(QPalette.Text, QColor("#c2d0bd")); p.setColor(QPalette.Button, QColor("#354831")); p.setColor(QPalette.ButtonText, QColor("#a2b59f")); p.setColor(QPalette.Highlight, QColor("#849b80")); p.setColor(QPalette.HighlightedText, QColor("#1a2418")); p.setColor(QPalette.Link, QColor("#c2d0bd")); p.setColor(QPalette.Disabled, QPalette.Text, Qt.darkGray); p.setColor(QPalette.Disabled, QPalette.ButtonText, Qt.darkGray); return p
    def _get_military_stylesheet(self):
        return "QWidget{color:#a2b59f;background-color:#1a2418;}QGroupBox{border:1px solid #4a5e46;background-color:#253522;}QGroupBox::title{background-color:#1a2418;}QPushButton{border:1px solid #667b62;background-color:#354831;}QTabBar::tab{padding:8px;border:1px solid #4a5e46;border-bottom:none;background:#253522;border-top-left-radius:5px;border-top-right-radius:5px;}QTabBar::tab:selected{background:#354831;border-color:#849b80;}QTabBar::tab:!selected:hover{background:#354831;}QSlider::handle:horizontal{background:#849b80;}QTableWidget{gridline-color:#4a5e46;border:1px solid #667b62;}QHeaderView::section{background-color:#354831;border:1px solid #4a5e46;}"

    def _get_arctic_palette(self):
        p = QPalette(); p.setColor(QPalette.Window, QColor("#e8eef2")); p.setColor(QPalette.WindowText, QColor("#1c2e4a")); p.setColor(QPalette.Base, QColor("#fdfdfe")); p.setColor(QPalette.AlternateBase, QColor("#dce4ea")); p.setColor(QPalette.Text, QColor("#2c3e50")); p.setColor(QPalette.Button, QColor("#dce4ea")); p.setColor(QPalette.ButtonText, QColor("#1c2e4a")); p.setColor(QPalette.Highlight, QColor("#3498db")); p.setColor(QPalette.HighlightedText, Qt.white); p.setColor(QPalette.Link, QColor("#2980b9")); p.setColor(QPalette.Disabled, QPalette.Text, Qt.darkGray); p.setColor(QPalette.Disabled, QPalette.ButtonText, Qt.darkGray); return p
    def _get_arctic_stylesheet(self):
        return "QWidget{color:#2c3e50;background-color:#e8eef2;}QGroupBox{border:1px solid #bdc3c7;background-color:#f8f9fa;}QGroupBox::title{background-color:#e8eef2;}QPushButton{border:1px solid #bdc3c7;background-color:#ecf0f1;}QTabBar::tab{padding:8px;border:1px solid #bdc3c7;border-bottom:none;background:#ecf0f1;border-top-left-radius:5px;border-top-right-radius:5px;}QTabBar::tab:selected{background:white;border-color:#3498db;}QTabBar::tab:!selected:hover{background:#f0f5f9;}QSlider::handle:horizontal{background:#3498db;}QTableWidget{gridline-color:#bdc3c7;border:1px solid #bdc3c7;}QHeaderView::section{background-color:#ecf0f1;border:1px solid #bdc3c7;}"

    def _get_solarized_dark_palette(self):
        p = QPalette(); p.setColor(QPalette.Window, QColor("#002b36")); p.setColor(QPalette.WindowText, QColor("#839496")); p.setColor(QPalette.Base, QColor("#073642")); p.setColor(QPalette.AlternateBase, QColor("#002b36")); p.setColor(QPalette.Text, QColor("#839496")); p.setColor(QPalette.Button, QColor("#073642")); p.setColor(QPalette.ButtonText, QColor("#839496")); p.setColor(QPalette.Highlight, QColor("#268bd2")); p.setColor(QPalette.HighlightedText, QColor("#002b36")); p.setColor(QPalette.Link, QColor("#2aa198")); p.setColor(QPalette.Disabled, QPalette.Text, Qt.darkGray); p.setColor(QPalette.Disabled, QPalette.ButtonText, Qt.darkGray); return p
    def _get_solarized_dark_stylesheet(self):
        return "QWidget{color:#839496;background-color:#002b36;}QGroupBox{border:1px solid #586e75;background-color:#073642;}QGroupBox::title{background-color:#002b36;}QPushButton{border:1px solid #586e75;background-color:#073642;}QTabBar::tab{padding:8px;border:1px solid #586e75;border-bottom:none;background:#073642;border-top-left-radius:5px;border-top-right-radius:5px;}QTabBar::tab:selected{background:#002b36;border-color:#268bd2;}QTabBar::tab:!selected:hover{background:#08404f;}QSlider::handle:horizontal{background:#268bd2;}QTableWidget{gridline-color:#586e75;border:1px solid #586e75;}QHeaderView::section{background-color:#073642;border:1px solid #586e75;}"

    def _get_dracula_palette(self):
        p = QPalette(); p.setColor(QPalette.Window, QColor("#282a36")); p.setColor(QPalette.WindowText, QColor("#f8f8f2")); p.setColor(QPalette.Base, QColor("#1e1f29")); p.setColor(QPalette.AlternateBase, QColor("#44475a")); p.setColor(QPalette.Text, QColor("#f8f8f2")); p.setColor(QPalette.Button, QColor("#44475a")); p.setColor(QPalette.ButtonText, QColor("#f8f8f2")); p.setColor(QPalette.Highlight, QColor("#bd93f9")); p.setColor(QPalette.HighlightedText, QColor("#282a36")); p.setColor(QPalette.Link, QColor("#8be9fd")); p.setColor(QPalette.Disabled, QPalette.Text, Qt.darkGray); p.setColor(QPalette.Disabled, QPalette.ButtonText, Qt.darkGray); return p
    def _get_dracula_stylesheet(self):
        return "QWidget{color:#f8f8f2;background-color:#282a36;}QGroupBox{border:1px solid #bd93f9;background-color:#1e1f29;}QGroupBox::title{background:#282a36;}QPushButton{border:1px solid #6272a4;background-color:#44475a;}QTabBar::tab{padding:8px;border:1px solid #6272a4;border-bottom:none;background:#282a36;border-top-left-radius:5px;border-top-right-radius:5px;}QTabBar::tab:selected{background:#44475a;border-color:#bd93f9;}QTabBar::tab:!selected:hover{background:#515469;}QSlider::handle:horizontal{background:#bd93f9;}QTableWidget{gridline-color:#6272a4;border:1px solid #bd93f9;}QHeaderView::section{background-color:#44475a;border:1px solid #6272a4;}"

    def _get_red_palette(self):
        p = QPalette(); p.setColor(QPalette.Window, QColor("#100000")); p.setColor(QPalette.WindowText, QColor("#ff4444")); p.setColor(QPalette.Base, QColor("#180000")); p.setColor(QPalette.AlternateBase, QColor("#281010")); p.setColor(QPalette.ToolTipBase, Qt.white); p.setColor(QPalette.ToolTipText, Qt.black); p.setColor(QPalette.Text, QColor("#ff4444")); p.setColor(QPalette.Button, QColor("#400000")); p.setColor(QPalette.ButtonText, QColor("#ff6666")); p.setColor(QPalette.BrightText, QColor("#ff8888")); p.setColor(QPalette.Link, QColor("#ff2222")); p.setColor(QPalette.Highlight, QColor("#D00000")); p.setColor(QPalette.HighlightedText, Qt.white); p.setColor(QPalette.Disabled, QPalette.Text, QColor("#805050")); p.setColor(QPalette.Disabled, QPalette.ButtonText, QColor("#805050")); return p
    def _get_red_stylesheet(self):
        return """
            QWidget{color:#ff4444;font-size:9pt; background-color: #100000} QGroupBox{font-weight:bold;border:1px solid #502020;border-radius:6px;margin-top:1ex; background-color: #180000;} QGroupBox::title{subcontrol-origin:margin;subcontrol-position:top left;padding:0 5px;left:10px;background-color:#100000} QPushButton{font-weight:bold;border-radius:5px;padding:6px 12px;border:1px solid #502020;background-color:qlineargradient(x1:0,y1:0,x2:0,y2:1,stop:0 #400000,stop:1 #300000)} QPushButton:hover{background-color:#600000;border:1px solid #ff4444} QPushButton:pressed{background-color:#300000} QPushButton:disabled{color:#805050;background-color:#200000;border:1px solid #402020} QTabWidget::pane{border-top:2px solid #502020} QTabBar::tab{font-weight:bold;font-size:9pt;padding:8px;min-width:130px;max-width:130px;background-color:#300000;border:1px solid #502020;border-bottom:none;border-top-left-radius:5px;border-top-right-radius:5px} QTabBar::tab:selected{background-color:#400000;border:1px solid #ff4444;border-bottom:none} QTabBar::tab:!selected:hover{background-color:#500000} QLineEdit,QSpinBox,QComboBox,QTableWidget,QDateEdit{border-radius:4px;border:1px solid #502020;padding:4px;} QPlainTextEdit{border-radius:4px;border:1px solid #502020;padding:4px;color:#FF5555;font-family:Consolas,monospace} QSlider::groove:horizontal{border:1px solid #502020;height:8px;background:#300000;border-radius:4px} QSlider::handle:horizontal{background:#D00000;border:1px solid #ff4444;width:18px;margin:-2px 0;border-radius:9px} QHeaderView::section{background-color:#400000;color:#ff6666;padding:4px;border:1px solid #502020;font-weight:bold} QTableWidget{gridline-color:#502020;}
        """
    def _get_blue_palette(self):
        p = QPalette(); p.setColor(QPalette.Window, QColor("#0B1D28")); p.setColor(QPalette.WindowText, QColor("#E0FFFF")); p.setColor(QPalette.Base, QColor("#112A3D")); p.setColor(QPalette.AlternateBase, QColor("#183852")); p.setColor(QPalette.ToolTipBase, Qt.white); p.setColor(QPalette.ToolTipText, Qt.black); p.setColor(QPalette.Text, QColor("#E0FFFF")); p.setColor(QPalette.Button, QColor("#113048")); p.setColor(QPalette.ButtonText, QColor("#E0FFFF")); p.setColor(QPalette.BrightText, QColor("#90EE90")); p.setColor(QPalette.Link, QColor("#00BFFF")); p.setColor(QPalette.Highlight, QColor("#007BA7")); p.setColor(QPalette.HighlightedText, Qt.white); p.setColor(QPalette.Disabled, QPalette.Text, QColor("#607A8B")); p.setColor(QPalette.Disabled, QPalette.ButtonText, QColor("#607A8B")); return p
    def _get_blue_stylesheet(self):
        return """
            QWidget{color:#E0FFFF;font-size:9pt; background-color:#0B1D28} QGroupBox{font-weight:bold;border:1px solid #204D6B;border-radius:6px;margin-top:1ex; background-color:#112A3D} QGroupBox::title{subcontrol-origin:margin;subcontrol-position:top left;padding:0 5px;left:10px;background-color:#0B1D28} QPushButton{font-weight:bold;border-radius:5px;padding:6px 12px;border:1px solid #204D6B;background-color:qlineargradient(x1:0,y1:0,x2:0,y2:1,stop:0 #183852,stop:1 #112A3D)} QPushButton:hover{background-color:#204D6B;border:1px solid #00BFFF} QPushButton:pressed{background-color:#112A3D} QPushButton:disabled{color:#607A8B;background-color:#112A3D;border:1px solid #204D6B} QTabWidget::pane{border-top:2px solid #204D6B} QTabBar::tab{font-weight:bold;font-size:9pt;padding:8px;min-width:130px;max-width:130px;background-color:#112A3D;border:1px solid #204D6B;border-bottom:none;border-top-left-radius:5px;border-top-right-radius:5px} QTabBar::tab:selected{background-color:#183852;border:1px solid #00BFFF;border-bottom:none} QTabBar::tab:!selected:hover{background-color:#204D6B} QLineEdit,QSpinBox,QComboBox,QTableWidget,QDateEdit{border-radius:4px;border:1px solid #204D6B;padding:4px;} QPlainTextEdit{border-radius:4px;border:1px solid #204D6B;padding:4px;background-color:#08141b;color:#A0FFFF;font-family:Consolas,monospace} QSlider::groove:horizontal{border:1px solid #204D6B;height:8px;background:#112A3D;border-radius:4px} QSlider::handle:horizontal{background:#007BA7;border:1px solid #00BFFF;width:18px;margin:-2px 0;border-radius:9px} QHeaderView::section{background-color:#183852;color:#E0FFFF;padding:4px;border:1px solid #204D6B;font-weight:bold} QTableWidget{gridline-color:#204D6B;}
        """
    def _get_light_palette(self):
        p = QPalette(); p.setColor(QPalette.Window, QColor("#F0F0F0")); p.setColor(QPalette.WindowText, QColor("#000000")); p.setColor(QPalette.Base, QColor("#FFFFFF")); p.setColor(QPalette.AlternateBase, QColor("#E8E8E8")); p.setColor(QPalette.ToolTipBase, QColor("#333333")); p.setColor(QPalette.ToolTipText, QColor("#FFFFFF")); p.setColor(QPalette.Text, QColor("#000000")); p.setColor(QPalette.Button, QColor("#E0E0E0")); p.setColor(QPalette.ButtonText, QColor("#000000")); p.setColor(QPalette.BrightText, Qt.red); p.setColor(QPalette.Link, QColor("#0000FF")); p.setColor(QPalette.Highlight, QColor("#0078D7")); p.setColor(QPalette.HighlightedText, Qt.white); p.setColor(QPalette.Disabled, QPalette.Text, QColor("#A0A0A0")); p.setColor(QPalette.Disabled, QPalette.ButtonText, QColor("#A0A0A0")); return p
    def _get_light_stylesheet(self):
        return """
            QWidget{color:#000000;font-size:9pt} QGroupBox{font-weight:bold;border:1px solid #C0C0C0;border-radius:6px;margin-top:1ex;background-color:#F0F0F0} QGroupBox::title{subcontrol-origin:margin;subcontrol-position:top left;padding:0 5px;left:10px;background-color:#F0F0F0} QPushButton{font-weight:bold;border-radius:5px;padding:6px 12px;border:1px solid #C0C0C0;background-color:qlineargradient(x1:0,y1:0,x2:0,y2:1,stop:0 #FDFDFD,stop:1 #E8E8E8)} QPushButton:hover{background-color:#E0E8F0;border:1px solid #0078D7} QPushButton:pressed{background-color:#D8E0E8} QPushButton:disabled{color:#A0A0A0;background-color:#E8E8E8;border:1px solid #D0D0D0} QTabWidget::pane{border-top:2px solid #C0C0C0} QTabBar::tab{font-weight:bold;font-size:9pt;padding:8px;min-width:130px;max-width:130px;background-color:#E8E8E8;border:1px solid #C0C0C0;border-bottom:none;border-top-left-radius:5px;border-top-right-radius:5px} QTabBar::tab:selected{background-color:#FFFFFF;border:1px solid #0078D7;border-bottom-color:#FFFFFF} QTabBar::tab:!selected:hover{background-color:#F0F8FF} QLineEdit,QSpinBox,QComboBox,QTableWidget,QDateEdit{border-radius:4px;border:1px solid #C0C0C0;padding:4px;background-color:#FFFFFF} QPlainTextEdit{border-radius:4px;border:1px solid #C0C0C0;padding:4px;background-color:#F8FFF8;color:#006400;font-family:Consolas,monospace} QSlider::groove:horizontal{border:1px solid #C0C0C0;height:8px;background:#E8E8E8;border-radius:4px} QSlider::handle:horizontal{background:#0078D7;border:1px solid #0078D7;width:18px;margin:-2px 0;border-radius:9px} QHeaderView::section{background-color:#E0E0E0;color:#000000;padding:4px;border:1px solid #C0C0C0;font-weight:bold}
        """
    #</editor-fold>

    #<editor-fold desc="Configuration Management">
    def _load_config_or_prompt(self):
        config = {}
        local_config_path = os.path.join(os.path.abspath("."), 'dsd-fme-gui-config.json')
        target_config_file = local_config_path if os.path.exists(local_config_path) else CONFIG_FILE

        if os.path.exists(target_config_file):
            try:
                with open(target_config_file, 'r') as f: config = json.load(f)
            except json.JSONDecodeError: pass

        self.current_theme_name = config.get('current_theme', "Default (Kameleon Dark)")

        path = config.get('dsd_fme_path')
        if path and os.path.exists(path): return path

        local_dsd_path = os.path.join(os.path.abspath("."), 'dsd-fme.exe')
        if os.path.exists(local_dsd_path):
            path = local_dsd_path
            config_to_save = {'dsd_fme_path': path, 'current_theme': self.current_theme_name}
            with open(CONFIG_FILE, 'w') as f: json.dump(config_to_save, f, indent=4)
            return path

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

        self.current_theme_name = config.get('current_theme', "Default (Kameleon Dark)")
        if hasattr(self, 'theme_combo'): self.theme_combo.setCurrentText(self.current_theme_name)
        self.apply_theme(self.current_theme_name)

        self.alerts = config.get('alerts', [])
        self.update_alerts_list()

        ui_settings = config.get('ui_settings', {})
        for key, value in ui_settings.items():
            if key.startswith('eq_band_'):
                band_index = int(key.split('_')[-1])
                if hasattr(self, 'eq_sliders') and band_index < len(self.eq_sliders):
                    self.eq_sliders[band_index].setValue(value)
            elif key in self.widgets:
                widget = self.widgets[key]
                try:
                    if isinstance(widget, QCheckBox): widget.setChecked(value)
                    elif isinstance(widget, QLineEdit): widget.setText(value)
                    elif isinstance(widget, QComboBox): widget.setCurrentText(value)
                    elif isinstance(widget, QSpinBox): widget.setValue(int(value))
                    elif isinstance(widget, QSlider): widget.setValue(int(value))
                except Exception as e:
                    print(f"Warning: Could not load UI setting for '{key}': {e}")

        # +++ STT Integration: Load STT settings +++
        stt_settings = config.get('stt_settings', {})
        if hasattr(self, 'stt_engine_combo'): self.stt_engine_combo.setCurrentText(stt_settings.get('engine', 'Whisper'))
        if hasattr(self, 'stt_whisper_model_combo'): self.stt_whisper_model_combo.setCurrentText(stt_settings.get('whisper_model', 'tiny'))
        if hasattr(self, 'stt_vosk_path_edit'): self.stt_vosk_path_edit.setText(stt_settings.get('vosk_model_path', ''))
        if hasattr(self, 'stt_lang_combo'): self.stt_lang_combo.setCurrentText(stt_settings.get('language', 'English'))
        if hasattr(self, 'stt_enabled_check_dash'): self.stt_enabled_check_dash.setChecked(stt_settings.get('enabled', False))


        if hasattr(self, 'recorder_dir_edit'): self.recorder_dir_edit.setText(ui_settings.get('recorder_dir_edit', ''))
        if hasattr(self, 'volume_slider'): self.volume_slider.setValue(ui_settings.get('volume_slider', 100))


    def _save_app_config(self):
        ui_settings = {}
        for key, widget in self.widgets.items():
            try:
                if isinstance(widget, QCheckBox): ui_settings[key] = widget.isChecked()
                elif isinstance(widget, QLineEdit): ui_settings[key] = widget.text()
                elif isinstance(widget, QComboBox): ui_settings[key] = widget.currentText()
                elif isinstance(widget, QSpinBox): ui_settings[key] = widget.value()
                elif isinstance(widget, QSlider): ui_settings[key] = widget.value()
            except Exception: pass

        if hasattr(self, 'eq_sliders'):
            for i, slider in enumerate(self.eq_sliders):
                ui_settings[f'eq_band_{i}'] = slider.value()

        # +++ STT Integration: Save STT settings +++
        stt_settings = {}
        if hasattr(self, 'stt_engine_combo'): stt_settings['engine'] = self.stt_engine_combo.currentText()
        if hasattr(self, 'stt_whisper_model_combo'): stt_settings['whisper_model'] = self.stt_whisper_model_combo.currentText()
        if hasattr(self, 'stt_vosk_path_edit'): stt_settings['vosk_model_path'] = self.stt_vosk_path_edit.text()
        if hasattr(self, 'stt_lang_combo'): stt_settings['language'] = self.stt_lang_combo.currentText()
        if hasattr(self, 'stt_enabled_check_dash'): stt_settings['enabled'] = self.stt_enabled_check_dash.isChecked()


        if hasattr(self, 'recorder_dir_edit'): ui_settings['recorder_dir_edit'] = self.recorder_dir_edit.text()
        if hasattr(self, 'volume_slider'): ui_settings['volume_slider'] = self.volume_slider.value()

        config = {
            'dsd_fme_path': self.dsd_fme_path,
            'current_theme': self.current_theme_name,
            'alerts': self.alerts,
            'ui_settings': ui_settings,
            'stt_settings': stt_settings, # +++ STT
        }
        with open(CONFIG_FILE, 'w') as f: json.dump(config, f, indent=4)
        self.save_aliases()

    def reset_all_settings(self):
        reply = QMessageBox.warning(self, "Reset Settings",
                                    "Are you sure you want to reset ALL application settings?\n"
                                    "This will delete configuration and alias files from AppData.\n"
                                    "The application will close.",
                                    QMessageBox.Yes | QMessageBox.No, QMessageBox.No)
        if reply == QMessageBox.Yes:
            self.is_resetting = True
            try:
                if os.path.exists(CONFIG_FILE): os.remove(CONFIG_FILE)
                if os.path.exists(ALIASES_FILE): os.remove(ALIASES_FILE)
                QMessageBox.information(self, "Reset Complete", "Settings have been reset. Please restart the application.")
            except OSError as e:
                QMessageBox.critical(self, "Error", f"Could not delete configuration files: {e}")
            self.close()
    #</editor-fold>

    #<editor-fold desc="UI Creation">
    def _init_ui(self):
        central_widget = QWidget(); self.setCentralWidget(central_widget)
        main_layout = QVBoxLayout(central_widget)

        self.fullscreen_action = QAction("Fullscreen", self, checkable=True)
        self.fullscreen_action.setShortcut(QKeySequence("F11"))
        self.fullscreen_action.triggered.connect(self.toggle_fullscreen)
        self.addAction(self.fullscreen_action)

        root_tabs = QTabWidget(); main_layout.addWidget(root_tabs)
        root_tabs.tabBar().setExpanding(True)
        root_tabs.addTab(self._create_config_tab(), "Configuration")
        root_tabs.addTab(self._create_dashboard_tab(), "Dashboard")
        root_tabs.addTab(self._create_stt_tab(), "Transcription (STT)")
        root_tabs.addTab(self._create_logbook_tab(), "Logbook")
        root_tabs.addTab(self._create_aliases_tab(), "Aliases")
        root_tabs.addTab(self._create_statistics_tab(), "Statistics")
        root_tabs.addTab(self._create_recorder_tab(), "Recorder")
        root_tabs.addTab(self._create_map_tab(), "Map")
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
        options_tabs.addTab(self._create_io_tab(), "Input / Output"); options_tabs.addTab(self._create_decoder_tab(), "Decoder Modes")
        options_tabs.addTab(self._create_advanced_tab(), "Advanced & Crypto"); options_tabs.addTab(self._create_trunking_tab(), "Trunking")

        cmd_group = QGroupBox("Execution"); cmd_layout = QGridLayout(cmd_group)
        self.cmd_preview = self._add_widget('cmd_preview', QLineEdit()); self.cmd_preview.setReadOnly(False); self.cmd_preview.setFont(QFont("Consolas", 9))
        self.btn_build_cmd = QPushButton("Generate Command"); self.btn_build_cmd.clicked.connect(self.build_command)
        self.btn_start = QPushButton("START"); self.btn_stop = QPushButton("STOP"); self.btn_stop.setEnabled(False)
        self.btn_start.clicked.connect(self.start_process); self.btn_stop.clicked.connect(self.stop_process)
        self.btn_reset = QPushButton("Reset All Settings"); self.btn_reset.clicked.connect(self.reset_all_settings)
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
        widget = QWidget()
        main_layout = QHBoxLayout(widget)
        main_splitter = QSplitter(Qt.Horizontal)
        main_layout.addWidget(main_splitter)

        left_panel_widget = QWidget()
        left_panel_layout = QVBoxLayout(left_panel_widget)
        left_panel_splitter = QSplitter(Qt.Vertical)

        self.histogram = pg.HistogramLUTWidget()
        left_panel_splitter.addWidget(self.histogram)

        self.mini_logbook_table = QTableWidget()
        self.mini_logbook_table.setColumnCount(6)
        self.mini_logbook_table.setHorizontalHeaderLabels(["Start", "End", "Duration", "TG", "ID", "CC"])
        self.mini_logbook_table.setEditTriggers(QAbstractItemView.NoEditTriggers)
        self.mini_logbook_table.horizontalHeader().setSectionResizeMode(QHeaderView.Stretch)
        self.mini_logbook_table.verticalHeader().setVisible(False)
        left_panel_splitter.addWidget(self.mini_logbook_table)
        left_panel_layout.addWidget(left_panel_splitter)

        right_panel_widget = QWidget()
        right_panel_layout = QVBoxLayout(right_panel_widget)

        top_bottom_splitter = QSplitter(Qt.Vertical)
        right_panel_layout.addWidget(top_bottom_splitter)

        visuals_widget = QWidget()
        visuals_layout = QHBoxLayout(visuals_widget)
        visuals_splitter = QSplitter(Qt.Horizontal)

        self.imv = pg.ImageView()
        self.imv.ui.roiBtn.hide()
        self.imv.ui.menuBtn.hide()
        self.imv.ui.histogram.hide()
        self.histogram.setImageItem(self.imv.imageItem)
        visuals_splitter.addWidget(self.imv)

        self.scope_widget = pg.PlotWidget(title="")
        self.scope_widget.getAxis('left').setWidth(50)
        self.scope_curve = self.scope_widget.plot()
        self.scope_widget.setYRange(-32768, 32767)
        visuals_splitter.addWidget(self.scope_widget)

        visuals_layout.addWidget(visuals_splitter)
        top_bottom_splitter.addWidget(visuals_widget)

        bottom_area = QSplitter(Qt.Horizontal)

        controls_and_stats_widget = QWidget()
        controls_and_stats_layout = QVBoxLayout(controls_and_stats_widget)
        self.live_analysis_group_dash = self._create_live_analysis_group(self.live_labels_dash)
        audio_controls_group_dash = self._create_audio_controls_group(is_dashboard=True)
        controls_and_stats_layout.addWidget(self.live_analysis_group_dash)
        controls_and_stats_layout.addWidget(audio_controls_group_dash)
        controls_and_stats_layout.addStretch()
        bottom_area.addWidget(controls_and_stats_widget)

        self.terminal_output_dash = QPlainTextEdit()
        self.terminal_output_dash.setReadOnly(True)
        bottom_area.addWidget(self.terminal_output_dash)

        top_bottom_splitter.addWidget(bottom_area)

        main_splitter.addWidget(left_panel_widget)
        main_splitter.addWidget(right_panel_widget)

        main_splitter.setSizes([300, 1300])
        top_bottom_splitter.setSizes([600, 300])
        visuals_splitter.setSizes([800, 500])
        bottom_area.setSizes([500, 800])

        self.spec_data = np.full((SPEC_WIDTH, CHUNK_SAMPLES // 2), MIN_DB, dtype=np.float32)

        return widget

    def _create_audio_controls_group(self, is_dashboard=False):
        group = QGroupBox("Audio & System Controls")
        main_layout = QGridLayout(group)

        self.device_combo = QComboBox(); self.populate_audio_devices()
        self.volume_slider = QSlider(Qt.Horizontal); self.volume_slider.setRange(0, 150)
        self.mute_check = QCheckBox("Mute"); self._add_widget('mute_check', self.mute_check)
        self.rms_label = QLabel("RMS: --"); self.peak_freq_label = QLabel("Peak Freq: --")

        main_layout.addWidget(QLabel("Audio Output:"), 0, 0); main_layout.addWidget(self.device_combo, 0, 1)
        main_layout.addWidget(self.mute_check, 0, 2)
        main_layout.addWidget(QLabel("Volume:"), 1, 0); main_layout.addWidget(self.volume_slider, 1, 1, 1, 2)
        main_layout.addWidget(self.rms_label, 2, 0); main_layout.addWidget(self.peak_freq_label, 2, 1)

        if is_dashboard:
            self.audio_lab_btn = QPushButton("Open Audio-Lab")
            self.audio_lab_btn.clicked.connect(self.open_audio_lab)
            main_layout.addWidget(self.audio_lab_btn, 3, 0, 1, 3)

            self.theme_combo = QComboBox(); self.theme_combo.addItems(self.themes.keys()); self.theme_combo.currentTextChanged.connect(self.apply_theme)
            main_layout.addWidget(QLabel("Theme:"), 4, 0); main_layout.addWidget(self.theme_combo, 4, 1, 1, 2)

            self.colormap_combo = QComboBox(); self.colormap_combo.addItems(self.colormaps.keys()); self.colormap_combo.currentTextChanged.connect(lambda name: self.imv.setColorMap(self.colormaps[name]))
            main_layout.addWidget(QLabel("Spectrogram:"), 5, 0); main_layout.addWidget(self.colormap_combo, 5, 1, 1, 2)

            self.stt_enabled_check_dash = QCheckBox("Enable Transcription (STT)"); self._add_widget('stt_enabled_check_dash', self.stt_enabled_check_dash)
            main_layout.addWidget(self.stt_enabled_check_dash, 6, 0)

            self.recorder_enabled_check_dash = QCheckBox("Enable Rec."); self.recorder_enabled_check_dash.toggled.connect(lambda state: self.recorder_enabled_check.setChecked(state)); self._add_widget('recorder_enabled_check_dash', self.recorder_enabled_check_dash)
            main_layout.addWidget(self.recorder_enabled_check_dash, 7, 0)

            self.btn_start_dash = QPushButton("START"); self.btn_start_dash.clicked.connect(self.start_process)
            self.btn_stop_dash = QPushButton("STOP"); self.btn_stop_dash.setEnabled(False); self.btn_stop_dash.clicked.connect(self.stop_process)
            main_layout.addWidget(self.btn_start_dash, 7, 1); main_layout.addWidget(self.btn_stop_dash, 7, 2)

        self.device_combo.currentIndexChanged.connect(self.restart_audio_stream); self.volume_slider.valueChanged.connect(self.set_volume)
        return group

    def open_audio_lab(self):
        if hasattr(self, 'audio_lab_window'):
            self.audio_lab_window.exec_()

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
        self.alert_beep_check = self._add_widget("-a", QCheckBox("Enable Call Alert Beep (-a)"))

        layout.addWidget(form_group, 0, 0); layout.addWidget(self.alerts_table, 1, 0); layout.addWidget(self.alert_remove_btn, 2, 0); layout.addWidget(self.alert_beep_check, 3, 0); layout.setRowStretch(1, 1)
        return widget

    def browse_for_alert_sound(self):
        path, _ = QFileDialog.getOpenFileName(self, "Select Alert Sound", "", "WAV Files (*.wav)")
        if path: self.alert_sound_edit.setText(path)

    def _create_map_tab(self):
        widget = QWidget(); layout = QVBoxLayout(widget)
        self.map_view = QWebEngineView()

        if not os.path.exists(MAP_FILE):
            self.create_initial_map()
        self.map_view.setUrl(QUrl.fromLocalFile(os.path.abspath(MAP_FILE)))

        layout.addWidget(self.map_view)
        return widget

    def create_initial_map(self):
        map_obj = folium.Map(location=[52.237, 21.017], zoom_start=6, tiles="CartoDB dark_matter")
        map_obj.save(MAP_FILE)
        if hasattr(self, 'map_view'):
            self.map_view.setUrl(QUrl.fromLocalFile(os.path.abspath(MAP_FILE)))
            self.map_view.reload()

    def update_map_from_lrrp(self, path):
        print(f"LRRP file changed: {path}")
        locations = []
        try:
            with open(path, 'r') as f:
                for line in f:
                    parts = line.strip().split(',')
                    if len(parts) >= 3:
                        try:
                            radio_id = parts[0]
                            lat = float(parts[1])
                            lon = float(parts[2])
                            timestamp = parts[3] if len(parts) > 3 else "N/A"
                            locations.append({'id': radio_id, 'lat': lat, 'lon': lon, 'time': timestamp})
                        except (ValueError, IndexError):
                            continue

            if not locations:
                return

            last_location = locations[-1]
            map_obj = folium.Map(location=[last_location['lat'], last_location['lon']], zoom_start=14, tiles="CartoDB dark_matter")

            for loc in locations:
                alias = self.aliases['id'].get(loc['id'], loc['id'])
                popup_text = f"<b>ID:</b> {alias}<br><b>Time:</b> {loc['time']}"
                folium.Marker(
                    location=[loc['lat'], loc['lon']],
                    popup=popup_text,
                    tooltip=alias
                ).add_to(map_obj)

            map_obj.save(MAP_FILE)
            self.map_view.setUrl(QUrl.fromLocalFile(os.path.abspath(MAP_FILE)))
            self.map_view.reload()

        except Exception as e:
            print(f"Error updating map: {e}")

    def _create_stt_tab(self):
        widget = QWidget()
        main_layout = QHBoxLayout(widget)

        settings_panel = QWidget()
        settings_layout = QVBoxLayout(settings_panel)
        settings_panel.setMaximumWidth(400)

        engine_group = QGroupBox("STT Engine Settings")
        engine_layout = QGridLayout(engine_group)

        self.stt_engine_combo = QComboBox()
        if WHISPER_AVAILABLE: self.stt_engine_combo.addItem("Whisper")
        if VOSK_AVAILABLE: self.stt_engine_combo.addItem("Vosk")
        self.stt_engine_combo.currentTextChanged.connect(self._toggle_stt_engine_options)

        self.stt_lang_combo = QComboBox()
        self.stt_lang_combo.addItems(["English", "Polish"])

        engine_layout.addWidget(QLabel("Engine:"), 0, 0)
        engine_layout.addWidget(self.stt_engine_combo, 0, 1)
        engine_layout.addWidget(QLabel("Language:"), 1, 0)
        engine_layout.addWidget(self.stt_lang_combo, 1, 1)
        settings_layout.addWidget(engine_group)

        self.whisper_group = QGroupBox("OpenAI-Whisper Settings")
        whisper_layout = QGridLayout(self.whisper_group)
        self.stt_whisper_model_combo = QComboBox()
        self.stt_whisper_model_combo.addItems(['tiny', 'base', 'small', 'medium', 'large'])
        self.stt_download_whisper_btn = QPushButton("Download/Verify Model")
        self.stt_download_whisper_btn.clicked.connect(self._download_whisper_model)
        whisper_info = QLabel('<small>Models are downloaded automatically on first use.<br><i>medium</i> and <i>large</i> models require significant RAM and disk space.</small>')
        whisper_info.setWordWrap(True)

        whisper_layout.addWidget(QLabel("Model:"), 0, 0)
        whisper_layout.addWidget(self.stt_whisper_model_combo, 0, 1)
        whisper_layout.addWidget(self.stt_download_whisper_btn, 1, 0, 1, 2)
        whisper_layout.addWidget(whisper_info, 2, 0, 1, 2)
        settings_layout.addWidget(self.whisper_group)

        self.vosk_group = QGroupBox("Vosk Settings")
        vosk_layout = QGridLayout(self.vosk_group)
        self.stt_vosk_path_edit = QLineEdit()
        self.stt_vosk_path_edit.setPlaceholderText("Path to the model folder")
        self.stt_browse_vosk_btn = QPushButton("Browse...")
        self.stt_browse_vosk_btn.clicked.connect(self._browse_for_vosk_model)
        vosk_link = QLabel('<a href="https://alphacephei.com/vosk/models">Download Vosk models (PL/EN)</a>')
        vosk_link.setOpenExternalLinks(True)

        vosk_layout.addWidget(QLabel("Model Path:"), 0, 0)
        vosk_layout.addWidget(self.stt_vosk_path_edit, 1, 0)
        vosk_layout.addWidget(self.stt_browse_vosk_btn, 1, 1)
        vosk_layout.addWidget(vosk_link, 2, 0, 1, 2)
        settings_layout.addWidget(self.vosk_group)

        history_group = QGroupBox("Transcription History")
        history_layout = QHBoxLayout(history_group)
        self.stt_import_btn = QPushButton("Import History")
        self.stt_export_btn = QPushButton("Export History")
        self.stt_import_btn.clicked.connect(self.import_stt_history)
        self.stt_export_btn.clicked.connect(self.export_stt_history)
        history_layout.addWidget(self.stt_import_btn)
        history_layout.addWidget(self.stt_export_btn)
        settings_layout.addWidget(history_group)

        settings_layout.addStretch()

        table_panel = QWidget()
        table_layout = QVBoxLayout(table_panel)
        self.stt_table = QTableWidget()
        self.stt_table.setColumnCount(3)
        self.stt_table.setHorizontalHeaderLabels(["Time", "Radio ID", "Transcription Text"])
        self.stt_table.setEditTriggers(QAbstractItemView.NoEditTriggers)
        self.stt_table.horizontalHeader().setSectionResizeMode(2, QHeaderView.Stretch)
        self.stt_table.verticalHeader().setVisible(False)

        self.stt_status_bar = QStatusBar()

        table_layout.addWidget(self.stt_table)
        table_layout.addWidget(self.stt_status_bar)

        main_layout.addWidget(settings_panel)
        main_layout.addWidget(table_panel)

        self._toggle_stt_engine_options(self.stt_engine_combo.currentText())

        return widget

    def _toggle_stt_engine_options(self, engine_name):
        is_whisper = (engine_name == 'Whisper')
        is_vosk = (engine_name == 'Vosk')
        if hasattr(self, 'whisper_group'): self.whisper_group.setVisible(is_whisper)
        if hasattr(self, 'vosk_group'): self.vosk_group.setVisible(is_vosk)

    def _browse_for_vosk_model(self):
        path = QFileDialog.getExistingDirectory(self, "Select Vosk Model Folder")
        if path:
            self.stt_vosk_path_edit.setText(path)

    def _download_whisper_model(self):
        if not WHISPER_AVAILABLE:
            QMessageBox.critical(self, "Error", "The Whisper library is not installed.")
            return

        model_name = self.stt_whisper_model_combo.currentText()

        reply = QMessageBox.information(self, "Download Model",
            f"You are about to download the Whisper model: '{model_name}'.\n"
            f"This might take a while and consume disk space. The model will be cached for future use.\n\nContinue?",
            QMessageBox.Yes | QMessageBox.No, QMessageBox.No)

        if reply == QMessageBox.Yes:
            self.stt_status_bar.showMessage(f"Downloading Whisper model: {model_name}...")
            QApplication.processEvents()

            try:
                # This should be in a thread for a better UX, but for now, it's a simple implementation
                whisper.load_model(model_name)
                self.stt_status_bar.showMessage(f"Model '{model_name}' is available locally.", 5000)
                QMessageBox.information(self, "Success", f"Model '{model_name}' was successfully downloaded/verified.")
            except Exception as e:
                self.stt_status_bar.showMessage(f"Error during model download: {e}", 5000)
                QMessageBox.critical(self, "Download Error", f"Could not download model '{model_name}':\n{e}")

    #</editor-fold>

    #<editor-fold desc="Application Logic">
    def closeEvent(self, event):
        if not self.is_resetting:
            self._save_app_config()
        self.stop_process()

        if os.path.exists(MAP_FILE):
            try:
                os.remove(MAP_FILE)
            except OSError as e:
                print(f"Could not remove map file: {e}")

        event.accept()

    def _create_io_tab(self):
        tab = QWidget(); layout = QVBoxLayout(tab)

        g1 = QGroupBox("Input (-i)"); l1 = QGridLayout(g1)
        input_type_combo = self._add_widget("-i_type", QComboBox())
        input_type_combo.addItems(["tcp", "rtl", "audio", "wav", "pulse", "m17udp"])
        input_type_combo.setCurrentText("tcp")

        self._add_widget("-i_tcp", QLineEdit("127.0.0.1:7355"))
        self._add_widget("-i_tcp2", QLineEdit("127.0.0.1:7356"))
        self._add_widget("-i_wav", QLineEdit())
        self._add_widget("-i_m17udp", QLineEdit("127.0.0.1:17000"))
        self._add_widget("dual_tcp", QCheckBox("Dual TCP"))

        l1.addWidget(QLabel("Type:"), 0, 0); l1.addWidget(self.widgets["-i_type"], 0, 1)
        l1.addWidget(QLabel("TCP Addr:Port:"), 1, 0); l1.addWidget(self.widgets["-i_tcp"], 1, 1)
        self.i_tcp2_label = QLabel("TCP2 Addr:Port:")
        l1.addWidget(self.i_tcp2_label, 2, 0); l1.addWidget(self.widgets["-i_tcp2"], 2, 1)
        l1.addWidget(self.widgets["dual_tcp"], 3, 0, 1, 2)
        l1.addWidget(QLabel("WAV File:"), 4, 0); l1.addWidget(self.widgets["-i_wav"], 4, 1); l1.addWidget(self._create_browse_button(self.widgets["-i_wav"]), 4, 2)
        l1.addWidget(QLabel("M17 UDP Addr:Port:"), 5, 0); l1.addWidget(self.widgets["-i_m17udp"], 5, 1)
        layout.addWidget(g1)

        self.audio_input_group = QGroupBox("Audio Input Options")
        l_audio = QGridLayout(self.audio_input_group)
        self._add_widget("audio_in_dev", QComboBox())
        self.audio_refresh_btn = QPushButton("Refresh List")
        self.audio_refresh_btn.clicked.connect(self._populate_audio_input_devices)
        self._populate_audio_input_devices()
        l_audio.addWidget(QLabel("Device:"), 0, 0)
        l_audio.addWidget(self.widgets["audio_in_dev"], 0, 1)
        l_audio.addWidget(self.audio_refresh_btn, 0, 2)
        layout.addWidget(self.audio_input_group)

        self.rtl_group = QGroupBox("RTL-SDR Options"); l_rtl = QGridLayout(self.rtl_group)
        self._add_widget("rtl_dev", QComboBox())
        self.rtl_refresh_btn = QPushButton("Refresh List"); self.rtl_refresh_btn.clicked.connect(self._populate_rtl_devices)
        self._add_widget("rtl_freq", QLineEdit("433.175")); self._add_widget("rtl_unit", QComboBox()); self.widgets["rtl_unit"].addItems(["MHz", "KHz", "GHz", "Hz"])
        self._add_widget("rtl_gain", QLineEdit("0")); self._add_widget("rtl_ppm", QLineEdit("0"))
        self._add_widget("rtl_bw", QComboBox()); self.widgets["rtl_bw"].addItems(["12", "4", "6", "8", "16", "24"])
        self._add_widget("rtl_sq", QLineEdit("0")); self._add_widget("rtl_vol", QLineEdit("2"))
        l_rtl.addWidget(QLabel("Device:"), 0, 0); l_rtl.addWidget(self.widgets["rtl_dev"], 0, 1); l_rtl.addWidget(self.rtl_refresh_btn, 0, 2)
        l_rtl.addWidget(QLabel("Frequency:"), 1, 0); l_rtl.addWidget(self.widgets["rtl_freq"], 1, 1); l_rtl.addWidget(self.widgets["rtl_unit"], 1, 2)
        l_rtl.addWidget(QLabel("Gain (0=auto):"), 2, 0); l_rtl.addWidget(self.widgets["rtl_gain"], 2, 1); l_rtl.addWidget(QLabel("PPM Error:"), 3, 0); l_rtl.addWidget(self.widgets["rtl_ppm"], 3, 1)
        l_rtl.addWidget(QLabel("Bandwidth (kHz):"), 4, 0); l_rtl.addWidget(self.widgets["rtl_bw"], 4, 1)
        l_rtl.addWidget(QLabel("Squelch Level:"), 5, 0); l_rtl.addWidget(self.widgets["rtl_sq"], 5, 1)
        l_rtl.addWidget(QLabel("Sample Volume:"), 6, 0); l_rtl.addWidget(self.widgets["rtl_vol"], 6, 1)
        layout.addWidget(self.rtl_group)
        self._populate_rtl_devices()

        def toggle_input_options(text):
            is_rtl = (text == 'rtl')
            is_audio = (text == 'audio')
            is_tcp = (text == 'tcp')
            self.rtl_group.setVisible(is_rtl)
            self.audio_input_group.setVisible(is_audio)
            self.widgets['-i_tcp'].setEnabled(is_tcp)
            self.widgets['dual_tcp'].setVisible(is_tcp)
            self.widgets['dual_tcp'].setEnabled(is_tcp)
            dual = is_tcp and self.widgets['dual_tcp'].isChecked()
            self.widgets['-i_tcp2'].setVisible(dual)
            self.widgets['-i_tcp2'].setEnabled(dual)
            self.i_tcp2_label.setVisible(dual)
            self.widgets["-i_wav"].setEnabled(text == 'wav')
            self.widgets["-i_m17udp"].setEnabled(text == 'm17udp')

        self.widgets['dual_tcp'].toggled.connect(lambda _: toggle_input_options(self.widgets['-i_type'].currentText()))
        input_type_combo.currentTextChanged.connect(toggle_input_options)
        toggle_input_options(input_type_combo.currentText())

        bottom_layout = QGridLayout()
        g3 = QGroupBox("File Outputs"); l3 = QGridLayout(g3)
        self._add_widget("-w", QLineEdit()); self._add_widget("-6", QLineEdit()); self._add_widget("-c", QLineEdit())
        self._add_widget("-d", QLineEdit()); self._add_widget("-r", QLineEdit())
        self._add_widget("-L", QLineEdit()); self._add_widget("-Q", QLineEdit())
        l3.addWidget(QLabel("Synth Speech [-w]:"), 0, 0); l3.addWidget(self.widgets["-w"], 0, 1); l3.addWidget(self._create_browse_button(self.widgets["-w"]), 0, 2)
        l3.addWidget(QLabel("Raw Audio [-6]:"), 1, 0); l3.addWidget(self.widgets["-6"], 1, 1); l3.addWidget(self._create_browse_button(self.widgets["-6"]), 1, 2)
        l3.addWidget(QLabel("Symbol Capture [-c]:"), 2, 0); l3.addWidget(self.widgets["-c"], 2, 1); l3.addWidget(self._create_browse_button(self.widgets["-c"]), 2, 2)
        l3.addWidget(QLabel("MBE Data Dir [-d]:"), 3, 0); l3.addWidget(self.widgets["-d"], 3, 1); l3.addWidget(self._create_browse_button(self.widgets["-d"], is_dir=True), 3, 2)
        l3.addWidget(QLabel("Read MBE File [-r]:"), 4, 0); l3.addWidget(self.widgets["-r"], 4, 1); l3.addWidget(self._create_browse_button(self.widgets["-r"]), 4, 2)
        l3.addWidget(QLabel("LRRP Output [-L]:"), 5, 0); l3.addWidget(self.widgets["-L"], 5, 1); l3.addWidget(self._create_browse_button(self.widgets["-L"]), 5, 2)
        l3.addWidget(QLabel("OK-DMRlib/M17 Output [-Q]:"), 6, 0); l3.addWidget(self.widgets["-Q"], 6, 1); l3.addWidget(self._create_browse_button(self.widgets["-Q"]), 6, 2)
        g4 = QGroupBox("Other"); l4 = QGridLayout(g4)
        self._add_widget("-s", QLineEdit("48000")); self._add_widget("-g", QLineEdit("0")); self._add_widget("-V", QLineEdit("3"))
        self._add_widget("-n", QLineEdit("0"))
        self._add_widget("-q", QCheckBox("Reverse Mute"))
        self._add_widget("-z", QCheckBox("TDMA Voice Slot Preference"))
        self._add_widget("-y", QCheckBox("Pulse Audio Float Output"))
        self._add_widget("-8", QCheckBox("Source Audio Monitor"))
        l4.addWidget(QLabel("WAV Sample Rate [-s]:"), 0, 0); l4.addWidget(self.widgets["-s"], 0, 1)
        l4.addWidget(QLabel("Digital Gain [-g]:"), 1, 0); l4.addWidget(self.widgets["-g"], 1, 1)
        l4.addWidget(QLabel("Analog Gain [-n]:"), 2, 0); l4.addWidget(self.widgets["-n"], 2, 1)
        l4.addWidget(QLabel("TDMA Slot Synth [-V]:"), 3, 0); l4.addWidget(self.widgets["-V"], 3, 1)
        l4.addWidget(self.widgets["-q"], 4, 0, 1, 2)
        l4.addWidget(self.widgets["-z"], 5, 0, 1, 2)
        l4.addWidget(self.widgets["-y"], 6, 0, 1, 2)
        l4.addWidget(self.widgets["-8"], 7, 0, 1, 2)
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
            QMessageBox.critical(self, "RTL-SDR Error", f"Could not list RTL-SDR devices.\nMake sure drivers (e.g., Zadig) are correctly installed and libusb is accessible.\n\nError: {e}")

    def _populate_audio_input_devices(self):
        combo = self.widgets.get("audio_in_dev")
        if not combo: return
        combo.clear()
        try:
            devices = sd.query_devices()
            default_in = sd.default.device[0]
            found_devices = False
            for i, device in enumerate(devices):
                if device['max_input_channels'] > 0:
                    combo.addItem(f"{device['name']}{' (Default)' if i == default_in else ''}", userData=i)
                    found_devices = True
            if not found_devices:
                combo.addItem("No audio input devices found.")
        except Exception as e:
            combo.addItem("Error querying devices")
            print(f"Error querying audio input devices: {e}")
            QMessageBox.warning(self, "Audio Error", f"Could not list audio input devices.\n\nError: {e}")

    def _create_decoder_tab(self):
        tab = QWidget(); scroll = QScrollArea(); scroll.setWidgetResizable(True); layout = QVBoxLayout(tab); layout.addWidget(scroll); container = QWidget(); scroll.setWidget(container); grid = QGridLayout(container)
        self.decoder_mode_group = QButtonGroup()
        g1 = QGroupBox("Decoder Mode (-f...)"); l1 = QVBoxLayout(g1)
        modes = {
            "-fa":"Auto", "-fA":"Analog", "-ft":"Trunk P25/DMR", "-fs":"DMR Simplex",
            "-f1":"P25 P1", "-f2":"P25 P2", "-fd":"D-STAR", "-fx":"X2-TDMA",
            "-fy":"YSF", "-fz":"M17", "-fU": "M17 UDP Frame", "-fi":"NXDN48", "-fn":"NXDN96",
            "-fp":"ProVoice", "-fe":"EDACS EA", "-fE":"EDACS EA w/ESK", "-fh": "EDACS Std/PV", "-fH": "EDACS Std/PV w/ESK",
            "-fm": "dPMR", "-fZ": "M17 Stream Encoder", "-fP": "M17 Packet Encoder", "-fB": "M17 BERT Encoder"
        }
        for flag, name in modes.items():
            rb = QRadioButton(name); self._add_widget(flag, rb); self.decoder_mode_group.addButton(rb); l1.addWidget(rb)

        g2 = QGroupBox("Decoder Options"); l2 = QGridLayout(g2)
        l2.addWidget(self._add_widget("-l", QCheckBox("Disable Input Filtering")), 0, 0)
        l2.addWidget(self._add_widget("-xx", QCheckBox("Invert X2-TDMA")), 1, 0)
        l2.addWidget(self._add_widget("-xr", QCheckBox("Invert DMR")), 2, 0)
        l2.addWidget(self._add_widget("-xd", QCheckBox("Invert dPMR")), 3, 0)
        l2.addWidget(self._add_widget("-xz", QCheckBox("Invert M17")), 4, 0)
        l2.addWidget(QLabel("Unvoiced Quality [-u]:"), 5, 0); l2.addWidget(self._add_widget("-u", QLineEdit("3")), 5, 1)
        l2.setRowStretch(6, 1)

        g_m17_encoder = QGroupBox("M17 Encoder Options"); l_m17 = QGridLayout(g_m17_encoder)
        l_m17.addWidget(QLabel("M17 Config [-M]:"), 0, 0); l_m17.addWidget(self._add_widget("-M", QLineEdit()), 0, 1)
        l_m17.addWidget(QLabel("M17 SMS [-S]:"), 1, 0); l_m17.addWidget(self._add_widget("-S", QLineEdit()), 1, 1)

        grid.addWidget(g1, 0, 0); grid.addWidget(g2, 0, 1); grid.addWidget(g_m17_encoder, 1, 0, 1, 2)
        return tab

    def _create_advanced_tab(self):
        tab = QWidget(); layout = QGridLayout(tab)
        g1 = QGroupBox("Modulation (-m...) & Display"); l1 = QVBoxLayout(g1); self.mod_group = QButtonGroup()
        mods = {"-ma":"Auto","-mc":"C4FM (default)","-mg":"GFSK","-mq":"QPSK","-m2":"P25p2 QPSK"}
        for flag, name in mods.items():
            rb = QRadioButton(name); self._add_widget(flag, rb); self.mod_group.addButton(rb); l1.addWidget(rb)
        l1.addSpacing(10)
        l1.addWidget(self._add_widget("-N", QCheckBox("Use NCurses Emulation [-N]")))
        l1.addWidget(self._add_widget("-Z", QCheckBox("Log Payloads to Console [-Z]")))
        g2 = QGroupBox("Encryption Keys"); l2 = QGridLayout(g2)
        l2.addWidget(QLabel("Basic Privacy Key [-b]:"), 0, 0); l2.addWidget(self._add_widget("-b", QLineEdit()), 0, 1)
        l2.addWidget(QLabel("RC4 Key [-1]:"), 1, 0); l2.addWidget(self._add_widget("-1", QLineEdit()), 1, 1)
        l2.addWidget(QLabel("Hytera BP Key [-H]:"), 2, 0); l2.addWidget(self._add_widget("-H", QLineEdit()), 2, 1)
        l2.addWidget(QLabel("dPMR/NXDN Scrambler [-R]:"), 3, 0); l2.addWidget(self._add_widget("-R", QLineEdit()), 3, 1)
        self._add_widget("-K", QLineEdit()); self._add_widget("-k", QLineEdit())
        l2.addWidget(QLabel("Keys from .csv (Hex) [-K]:"), 4, 0); l2.addWidget(self.widgets["-K"], 4, 1); l2.addWidget(self._create_browse_button(self.widgets["-K"]), 4, 2)
        l2.addWidget(QLabel("Keys from .csv (Dec) [-k]:"), 5, 0); l2.addWidget(self.widgets["-k"], 5, 1); l2.addWidget(self._create_browse_button(self.widgets["-k"]), 5, 2)
        g3 = QGroupBox("Force & Advanced Options"); l3 = QGridLayout(g3)
        l3.addWidget(self._add_widget("-4", QCheckBox("Force BP Key")), 0, 0)
        l3.addWidget(self._add_widget("-0", QCheckBox("Force RC4 Key")), 1, 0)
        l3.addWidget(self._add_widget("-3", QCheckBox("Disable DMR Late Entry Enc.")), 2, 0)
        l3.addWidget(self._add_widget("-F", QCheckBox("Relax CRC Checksum")), 3, 0)
        l3.addWidget(QLabel("P2 Params [-X]:"), 0, 1); l3.addWidget(self._add_widget("-X", QLineEdit()), 0, 2)
        l3.addWidget(QLabel("DMR TIII Area [-D]:"), 1, 1); l3.addWidget(self._add_widget("-D", QLineEdit()), 1, 2)
        l3.addWidget(QLabel("Filter Bitmap [-v]:"), 2, 1); l3.addWidget(self._add_widget("-v", QLineEdit()), 2, 2)
        layout.addWidget(g1, 0, 0); layout.addWidget(g2, 0, 1); layout.addWidget(g3, 1, 0, 1, 2)
        return tab

    def _create_trunking_tab(self):
        tab = QWidget(); layout = QVBoxLayout(tab)
        g1 = QGroupBox("Trunking Options"); l1 = QGridLayout(g1)
        l1.addWidget(self._add_widget("-T", QCheckBox("Enable Trunking")), 0, 0); l1.addWidget(self._add_widget("-Y", QCheckBox("Enable Scanning")), 0, 1)
        l1.addWidget(self._add_widget("-W", QCheckBox("Use Group List as Whitelist")), 0, 2)
        l1.addWidget(QLabel("Channel Map [-C]:"), 1, 0); self._add_widget("-C", QLineEdit()); l1.addWidget(self.widgets["-C"], 1, 1); l1.addWidget(self._create_browse_button(self.widgets["-C"]), 1, 2)
        l1.addWidget(QLabel("Group List [-G]:"), 2, 0); self._add_widget("-G", QLineEdit()); l1.addWidget(self.widgets["-G"], 2, 1); l1.addWidget(self._create_browse_button(self.widgets["-G"]), 2, 2)
        l1.addWidget(QLabel("RigCtl Port [-U]:"), 3, 0); l1.addWidget(self._add_widget("-U", QLineEdit("")), 3, 1)
        l1.addWidget(QLabel("Hold TG [-I]:"), 4, 0); l1.addWidget(self._add_widget("-I", QLineEdit()), 4, 1)
        g2 = QGroupBox("Tuning Control"); l2 = QGridLayout(g2)
        l2.addWidget(self._add_widget("-p", QCheckBox("Disable Tune to Private Calls")), 0, 0)
        l2.addWidget(self._add_widget("-E", QCheckBox("Disable Tune to Group Calls")), 1, 0)
        l2.addWidget(self._add_widget("-e", QCheckBox("Enable Tune to Data Calls")), 2, 0)
        l2.addWidget(QLabel("RigCtl BW (Hz) [-B]:"), 0, 1); l2.addWidget(self._add_widget("-B", QLineEdit("0")), 0, 2)
        l2.addWidget(QLabel("Hangtime (s) [-t]:"), 1, 1); l2.addWidget(self._add_widget("-t", QLineEdit("1")), 1, 2)
        layout.addWidget(g1); layout.addWidget(g2); layout.addStretch(); return tab

    def _create_logbook_tab(self):
        widget = QWidget(); layout = QGridLayout(widget)

        filter_group = QGroupBox("Filtering and Search")
        filter_layout = QGridLayout(filter_group)

        self.logbook_search_input = QLineEdit(); self.logbook_search_input.setPlaceholderText("Search visible entries...")
        self.logbook_start_date = QDateEdit(QDate.currentDate().addMonths(-1)); self.logbook_start_date.setCalendarPopup(True)
        self.logbook_end_date = QDateEdit(QDate.currentDate()); self.logbook_end_date.setCalendarPopup(True)
        self.logbook_filter_btn = QPushButton("Filter"); self.logbook_filter_btn.clicked.connect(self.filter_logbook)

        filter_layout.addWidget(QLabel("Search:"), 0, 0); filter_layout.addWidget(self.logbook_search_input, 0, 1)
        filter_layout.addWidget(QLabel("From:"), 1, 0); filter_layout.addWidget(self.logbook_start_date, 1, 1)
        filter_layout.addWidget(QLabel("To:"), 2, 0); filter_layout.addWidget(self.logbook_end_date, 2, 1)
        filter_layout.addWidget(self.logbook_filter_btn, 3, 0, 1, 2)

        self.logbook_table = QTableWidget()
        self.logbook_table.setColumnCount(8)
        self.logbook_table.setHorizontalHeaderLabels(["Start Time","End Time","Duration","Talkgroup","Radio ID","Color Code", "Tags", "Notes"])
        self.logbook_table.setEditTriggers(QAbstractItemView.DoubleClicked)
        self.logbook_table.setSelectionBehavior(QAbstractItemView.SelectRows)
        self.logbook_table.setSortingEnabled(True)
        self.logbook_table.horizontalHeader().setSectionResizeMode(QHeaderView.Interactive)
        self.logbook_table.verticalHeader().setVisible(False)

        header = self.logbook_table.horizontalHeader()
        header.setSectionResizeMode(7, QHeaderView.Stretch)

        button_layout = QHBoxLayout()
        self.import_csv_button = QPushButton("Import CSV"); self.import_csv_button.clicked.connect(self.import_csv_to_logbook)
        self.save_csv_button = QPushButton("Save to CSV"); self.save_csv_button.clicked.connect(self.save_history_to_csv)
        button_layout.addWidget(self.import_csv_button); button_layout.addWidget(self.save_csv_button)

        layout.addWidget(filter_group, 0, 0)
        layout.addLayout(button_layout, 0, 1)
        layout.addWidget(self.logbook_table, 1, 0, 1, 2)

        return widget

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
        self.stats_start_date = QDateEdit(datetime.now().date().replace(day=1)); self.stats_start_date.setCalendarPopup(True)
        self.stats_end_date = QDateEdit(datetime.now().date()); self.stats_end_date.setCalendarPopup(True)
        self.generate_report_btn = QPushButton("Generate Report from Logbook"); self.generate_report_btn.clicked.connect(self.update_statistics)
        self.export_stats_btn = QPushButton("Export Statistics"); self.export_stats_btn.clicked.connect(self.export_statistics)
        self.import_stats_btn = QPushButton("Import Statistics"); self.import_stats_btn.clicked.connect(self.import_statistics)

        controls_layout.addWidget(QLabel("Start Date:"), 0, 0); controls_layout.addWidget(self.stats_start_date, 0, 1)
        controls_layout.addWidget(QLabel("End Date:"), 0, 2); controls_layout.addWidget(self.stats_end_date, 0, 3)
        controls_layout.addWidget(self.generate_report_btn, 1, 0, 1, 2)
        controls_layout.addWidget(self.export_stats_btn, 1, 2)
        controls_layout.addWidget(self.import_stats_btn, 1, 3)
        controls_layout.setColumnStretch(4, 1); main_layout.addWidget(controls_group)

        summary_group = QGroupBox("Summary"); self.summary_layout = QGridLayout(summary_group)
        self.total_calls_label = QLabel("---"); self.total_duration_label = QLabel("---"); self.most_active_tg_label = QLabel("---"); self.most_active_id_label = QLabel("---")
        self.summary_layout.addWidget(QLabel("<b>Total Calls:</b>"), 0, 0); self.summary_layout.addWidget(self.total_calls_label, 0, 1)
        self.summary_layout.addWidget(QLabel("<b>Total Duration:</b>"), 1, 0); self.summary_layout.addWidget(self.total_duration_label, 1, 1)
        self.summary_layout.addWidget(QLabel("<b>Most Active TG:</b>"), 0, 2); self.summary_layout.addWidget(self.most_active_tg_label, 0, 3)
        self.summary_layout.addWidget(QLabel("<b>Most Active ID:</b>"), 1, 2); self.summary_layout.addWidget(self.most_active_id_label, 1, 3)
        self.summary_layout.setColumnStretch(1, 1); self.summary_layout.setColumnStretch(3, 1); main_layout.addWidget(summary_group)

        splitter = QSplitter(Qt.Horizontal)
        integer_axis_left_tg = IntegerAxis(orientation='left')
        integer_axis_left_id = IntegerAxis(orientation='left')
        date_axis_bottom = DateAxisItem(orientation='bottom')

        self.tg_chart = pg.PlotWidget(title="Top 10 Talkgroups by Call Count", axisItems={'left': integer_axis_left_tg})
        self.id_chart = pg.PlotWidget(title="Top 10 Radio IDs by Call Count", axisItems={'left': integer_axis_left_id})
        self.time_chart = pg.PlotWidget(title="Calls over Time", axisItems={'bottom': date_axis_bottom})
        self.time_chart.getAxis('left').setLabel('Call Count')

        splitter.addWidget(self.tg_chart); splitter.addWidget(self.id_chart); splitter.addWidget(self.time_chart)
        main_layout.addWidget(splitter)
        return widget


    def _create_recorder_tab(self):
        widget = QWidget(); layout = QGridLayout(widget)
        self.recorder_enabled_check = QCheckBox("Enable Voice-Activated Recording to Directory"); self.recorder_enabled_check.toggled.connect(lambda state: self.recorder_enabled_check_dash.setChecked(state)); self._add_widget('recorder_enabled_check', self.recorder_enabled_check)
        self.recorder_dir_edit = QLineEdit(); self.recorder_dir_edit.setPlaceholderText("Select directory for WAV files...")
        self.recorder_browse_btn = QPushButton("Browse..."); self.recorder_browse_btn.clicked.connect(self.browse_for_recording_dir)
        self.recording_list = QListWidget(); self.recording_list.itemDoubleClicked.connect(self.play_recording)
        play_btn = QPushButton("Play Selected Recording"); play_btn.clicked.connect(self.play_recording)
        self.per_call_check = self._add_widget("-P", QCheckBox("Enable Per-Call WAV Saving (-P)"))
        self.per_call_dir_edit = self._add_widget("-7", QLineEdit())
        self.per_call_dir_browse_btn = QPushButton("Browse...")
        self.per_call_dir_browse_btn.clicked.connect(lambda: self._browse_for_path(self.per_call_dir_edit, is_dir=True))
        layout.addWidget(self.recorder_enabled_check, 0, 0, 1, 3)
        layout.addWidget(QLabel("Recording Directory:"), 1, 0); layout.addWidget(self.recorder_dir_edit, 1, 1); layout.addWidget(self.recorder_browse_btn, 1, 2)
        layout.addWidget(self.recording_list, 2, 0, 1, 3); layout.addWidget(play_btn, 3, 0, 1, 3)
        layout.addWidget(self.per_call_check, 4, 0, 1, 3)
        layout.addWidget(QLabel("Per-Call Dir [-7]:"), 5, 0); layout.addWidget(self.per_call_dir_edit, 5, 1); layout.addWidget(self.per_call_dir_browse_btn, 5, 2)
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

    def _add_widget(self, key, widget, properties=None):
        self.widgets[key] = widget
        if isinstance(widget, QRadioButton): self.inverse_widgets[widget] = key

        if properties:
            if 'range' in properties: widget.setRange(*properties['range'])
            if 'suffix' in properties: widget.setSuffix(properties['suffix'])
            if 'value' in properties: widget.setValue(properties['value'])

        return widget

    def _create_browse_button(self, line_edit_widget, is_dir=False): button = QPushButton("Browse..."); button.clicked.connect(lambda: self._browse_for_path(line_edit_widget, is_dir)); return button

    def _browse_for_path(self, line_edit_widget, is_dir):
        path = QFileDialog.getExistingDirectory(self, "Select Directory") if is_dir else QFileDialog.getOpenFileName(self, "Select File")[0]
        if path: line_edit_widget.setText(path)

    def start_udp_listeners(self):
        ports = [UDP_PORT]
        if (self.widgets.get('dual_tcp') and self.widgets['dual_tcp'].isChecked() and
                self.widgets.get('-i_type') and self.widgets['-i_type'].currentText() == 'tcp'):
            ports.append(UDP_PORT + 1)
        for idx, port in enumerate(ports, start=1):
            thread = QThread()
            listener = UdpListener(UDP_IP, port, idx)
            listener.moveToThread(thread)
            thread.started.connect(listener.run)
            listener.data_ready.connect(self.process_audio_data)
            thread.start()
            self.udp_listener_threads.append(thread)
            self.udp_listeners.append(listener)

    def stop_udp_listeners(self):
        for listener in self.udp_listeners:
            listener.running = False
        for thread in self.udp_listener_threads:
            thread.quit(); thread.wait()
        self.udp_listeners.clear(); self.udp_listener_threads.clear()

    def build_command(self):
        if not self.dsd_fme_path:
            self.cmd_preview.setText("ERROR: DSD-FME path not set!")
            return []

        in_type = self.widgets["-i_type"].currentText()
        dual = self.widgets.get('dual_tcp') and self.widgets['dual_tcp'].isChecked() and in_type == 'tcp'

        inputs = []
        if in_type == 'tcp':
            inputs.append(self.widgets['-i_tcp'].text())
            if dual:
                inputs.append(self.widgets['-i_tcp2'].text())
        else:
            inputs.append(None)

        common_flags = []
        for flag in ["-s","-g","-V","-w","-6","-c","-b","-1","-H","-K","-C","-G","-U","-d","-r","-n","-u","-L","-Q","-M","-S","-X","-D","-v","-R","-k","-7","-I","-B","-t"]:
            widget = self.widgets.get(flag)
            if widget and hasattr(widget, 'text') and widget.text():
                common_flags.extend([flag, widget.text()])
            elif widget and isinstance(widget, QCheckBox) and widget.isChecked():
                common_flags.append(flag)

        for flag in ["-l","-xx","-xr","-xd","-xz","-N","-Z","-4","-0","-3","-F","-T","-Y","-p","-E","-e","-q","-z","-y","-8","-P","-a","-W"]:
            if self.widgets.get(flag) and self.widgets[flag].isChecked():
                common_flags.append(flag)

        for btn, flag in self.inverse_widgets.items():
            if flag and btn.isChecked():
                common_flags.append(flag)

        commands = []
        for idx, tcp_addr in enumerate(inputs):
            cmd = [self.dsd_fme_path, "-o", f"udp:{UDP_IP}:{UDP_PORT + idx}"]
            if in_type == 'tcp':
                cmd.extend(["-i", f"tcp:{tcp_addr}" if tcp_addr else "tcp"])
            elif in_type == 'wav':
                if self.widgets['-i_wav'].text():
                    cmd.extend(["-i", self.widgets['-i_wav'].text()])
            elif in_type == 'm17udp':
                addr = self.widgets['-i_m17udp'].text()
                cmd.extend(["-i", f"m17udp:{addr}" if addr else "m17udp"])
            elif in_type == 'audio':
                dev_index = self.widgets["audio_in_dev"].currentData()
                if dev_index is not None:
                    cmd.extend(["-i", f"pa:{dev_index}"])
                else:
                    QMessageBox.critical(self, "Error", "No audio input device selected.")
                    return []
            elif in_type == 'rtl':
                dev_index = self.widgets["rtl_dev"].currentData()
                if dev_index is None:
                    QMessageBox.critical(self, "Error", "No RTL-SDR device selected or found.")
                    return []
                try:
                    dev = str(dev_index)
                    freq_val = float(self.widgets["rtl_freq"].text())
                    unit = self.widgets["rtl_unit"].currentText()
                    gain = self.widgets["rtl_gain"].text()
                    ppm = self.widgets["rtl_ppm"].text()
                    bw = self.widgets["rtl_bw"].currentText()
                    sq = self.widgets["rtl_sq"].text()
                    vol = self.widgets["rtl_vol"].text()
                    freq_map = {"MHz": "M", "KHz": "K", "GHz": "G"}
                    freq_str = f"{freq_val}{freq_map.get(unit, '')}"
                    rtl_params = [dev, freq_str, gain, ppm, bw, sq, vol]
                    cmd.extend(["-i", f"rtl:{':'.join(p for p in rtl_params if p)}"])
                except ValueError:
                    QMessageBox.critical(self, "Error", "Invalid frequency value.")
                    return []
            else:
                cmd.extend(["-i", in_type])

            cmd.extend(common_flags)
            commands.append(list(filter(None, (str(item).strip() for item in cmd))))

        self.cmd_preview.setText("\n".join(subprocess.list2cmdline(c) for c in commands))
        return commands

    def start_process(self):
        if self.processes:
            return
        self.create_initial_map()
        self.logbook_table.setRowCount(0)
        self.mini_logbook_table.setRowCount(0)
        self.is_in_transmission = False
        self.last_logged_id = None
        self.transmission_log.clear()
        if hasattr(self, 'stt_table'):
            self.stt_table.setRowCount(0)
        self.stt_active_id_row.clear()

        commands = self.build_command()
        if not commands:
            return

        lrrp_file_path = self.widgets["-L"].text()
        if lrrp_file_path:
            if self.lrrp_watcher.files():
                self.lrrp_watcher.removePaths(self.lrrp_watcher.files())
            self.lrrp_watcher.addPath(lrrp_file_path)

        self.restart_audio_stream()
        self.start_udp_listeners()
        log_start_msg = "\n".join(f"$ {subprocess.list2cmdline(cmd)}" for cmd in commands) + "\n\n"
        for term in [self.terminal_output_conf, self.terminal_output_dash]:
            term.clear()
            term.appendPlainText(log_start_msg)
        try:
            si = subprocess.STARTUPINFO()
            si.dwFlags |= subprocess.STARTF_USESHOWWINDOW
            si.wShowWindow = subprocess.SW_HIDE
            for cmd in commands:
                process = subprocess.Popen(
                    cmd,
                    stdout=subprocess.PIPE,
                    stderr=subprocess.STDOUT,
                    stdin=subprocess.DEVNULL,
                    universal_newlines=True,
                    encoding='utf-8',
                    errors='ignore',
                    startupinfo=si,
                    creationflags=subprocess.CREATE_NO_WINDOW if os.name == 'nt' else 0,
                )
                self.processes.append(process)
                thread = QThread()
                worker = ProcessReader(process)
                worker.moveToThread(thread)
                worker.line_read.connect(self.update_terminal_log)
                thread.started.connect(worker.run)
                worker.finished.connect(self._on_reader_finished)
                thread.start()
                self.reader_threads.append(thread)
                self.reader_workers.append(worker)
            self.set_ui_running_state(True)

        except Exception as e:
            error_msg = f"\nERROR: Failed to start process: {e}"
            self.terminal_output_conf.appendPlainText(error_msg)
            self.terminal_output_dash.appendPlainText(error_msg)
            self.set_ui_running_state(False)

    def stop_process(self):
        if self.is_recording:
            self.stop_internal_recording()
        self.stop_udp_listeners()
        if self.output_stream:
            self.output_stream.stop()
            self.output_stream.close()
            self.output_stream = None

        if self.processes:
            self.set_ui_running_state(False)  # Update UI immediately
            stop_msg = "\n--- SENDING STOP SIGNAL ---\n"
            self.terminal_output_conf.appendPlainText(stop_msg)
            self.terminal_output_dash.appendPlainText(stop_msg)
            for p in self.processes:
                if p and p.poll() is None:
                    p.terminate()

    @pyqtSlot()
    def _on_reader_finished(self):
        if any(p.poll() is None for p in self.processes):
            return
        self.end_all_transmissions()
        self.set_ui_running_state(False)
        for thread in self.reader_threads:
            thread.quit()
            thread.wait()
        self.processes.clear()
        self.reader_workers.clear()
        self.reader_threads.clear()

        ready_msg = "\n--- READY ---\n"
        if hasattr(self, 'terminal_output_conf'):
            self.terminal_output_conf.appendPlainText(ready_msg)
            self.terminal_output_dash.appendPlainText(ready_msg)


    def set_ui_running_state(self, is_running):
        self.btn_start.setEnabled(not is_running)
        self.btn_stop.setEnabled(is_running)
        self.btn_start_dash.setEnabled(not is_running)
        self.btn_stop_dash.setEnabled(is_running)


    def update_terminal_log(self, text):
        try:
            self.parse_and_display_log(text)
            for term in [self.terminal_output_conf, self.terminal_output_dash]: term.moveCursor(QTextCursor.End); term.insertPlainText(text)
        except RuntimeError as e:
            # This can happen if a widget is deleted while a signal is still in the queue
            print(f"RuntimeError in update_terminal_log: {e}")

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
        start_time = datetime.now()
        start_time_str = start_time.strftime("%Y-%m-%d %H:%M:%S")
        tg_alias = self.aliases['tg'].get(tg_val, tg_val) or "N/A"
        id_alias = self.aliases['id'].get(id_val, id_val) or "N/A"

        row_items = [
            QTableWidgetItem(start_time_str), QTableWidgetItem(""), QTableWidgetItem(""),
            QTableWidgetItem(tg_alias), QTableWidgetItem(id_alias), QTableWidgetItem(cc_val or "N/A"),
            QTableWidgetItem(""), QTableWidgetItem("")
        ]

        for i in range(len(row_items)):
            if i < 6:
                row_items[i].setFlags(row_items[i].flags() & ~Qt.ItemIsEditable)

        self.logbook_table.insertRow(0)
        for i, item in enumerate(row_items):
            if i == 3: item.setData(Qt.UserRole, tg_val)
            elif i == 4: item.setData(Qt.UserRole, id_val)
            self.logbook_table.setItem(0, i, item)

        self.mini_logbook_table.insertRow(0)
        for i in range(6):
            self.mini_logbook_table.setItem(0, i, row_items[i].clone())
        if self.mini_logbook_table.rowCount() > 10:
            self.mini_logbook_table.removeRow(10)

        self.transmission_log[id_val] = {'start_time': start_time, 'tg': tg_val, 'id_alias': id_alias}

        if hasattr(self, 'stt_enabled_check_dash') and self.stt_enabled_check_dash.isChecked():
            self.stt_audio_buffer[id_val] = bytearray()
            if id_val not in self.stt_active_id_row:
                row_pos = self.stt_table.rowCount()
                self.stt_table.insertRow(row_pos)
                self.stt_table.setItem(row_pos, 0, QTableWidgetItem(start_time.strftime("%H:%M:%S")))
                id_display = self.aliases['id'].get(id_val, id_val)
                self.stt_table.setItem(row_pos, 1, QTableWidgetItem(id_display))
                self.stt_table.setItem(row_pos, 2, QTableWidgetItem("..."))
                self.stt_active_id_row[id_val] = row_pos
                self.stt_table.scrollToBottom()


    def end_all_transmissions(self, end_current=True):
        end_time = datetime.now()
        end_time_str = end_time.strftime("%Y-%m-%d %H:%M:%S")

        if hasattr(self, 'stt_enabled_check_dash') and self.stt_enabled_check_dash.isChecked() and self.stt_audio_buffer:
             for radio_id, audio_buffer in self.stt_audio_buffer.items():
                if len(audio_buffer) > AUDIO_RATE * 1: # Transcribe only if there's enough audio (e.g., > 0.5s)
                    audio_data = np.frombuffer(audio_buffer, dtype=AUDIO_DTYPE)
                    self.start_transcription(audio_data, radio_id)
        if end_current:
            self.stt_audio_buffer.clear()
            self.stt_active_id_row.clear()

        for log_data in self.transmission_log.values():
            duration = end_time - log_data['start_time']; duration_str = str(duration).split('.')[0]
            for panel in [self.live_labels_conf, self.live_labels_dash]: panel and panel['duration'].setText(duration_str)
            for r in range(self.logbook_table.rowCount()):
                if self.logbook_table.item(r,4) and self.logbook_table.item(r,4).text() == log_data['id_alias'] and (not self.logbook_table.item(r,1) or not self.logbook_table.item(r,1).text()):
                    end_item = QTableWidgetItem(end_time_str)
                    end_item.setFlags(end_item.flags() & ~Qt.ItemIsEditable)
                    self.logbook_table.setItem(r, 1, end_item)

                    dur_item = QTableWidgetItem(duration_str)
                    dur_item.setFlags(dur_item.flags() & ~Qt.ItemIsEditable)
                    self.logbook_table.setItem(r, 2, dur_item)
                    break
            for r in range(self.mini_logbook_table.rowCount()):
                if self.mini_logbook_table.item(r,4) and self.mini_logbook_table.item(r,4).text() == log_data['id_alias'] and (not self.mini_logbook_table.item(r,1) or not self.mini_logbook_table.item(r,1).text()):
                    self.mini_logbook_table.setItem(r,1,QTableWidgetItem(end_time_str.split(" ")[1]))
                    self.mini_logbook_table.setItem(r,2,QTableWidgetItem(duration_str))
                    break
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

    def process_audio_data(self, channel, raw_data):
        if raw_data.startswith(b"ERROR:"):
            QMessageBox.critical(self, "UDP Error", raw_data.decode())
            self.close()
            return

        clean_num_bytes = (len(raw_data) // np.dtype(AUDIO_DTYPE).itemsize) * np.dtype(AUDIO_DTYPE).itemsize
        if clean_num_bytes == 0:
            return
        audio_samples = np.frombuffer(raw_data[:clean_num_bytes], dtype=AUDIO_DTYPE)

        try:
            filtered_samples = self.apply_filters(audio_samples.copy())
        except KeyError as e:
            print(f"Filter widget not ready, skipping filtering. Error: {e}")
            filtered_samples = audio_samples

        if self.is_in_transmission and self.last_logged_id and self.last_logged_id in self.stt_audio_buffer:
            self.stt_audio_buffer[self.last_logged_id].extend(filtered_samples.tobytes())

        # buffer per channel
        self.channel_buffers[channel] = np.concatenate(
            (self.channel_buffers[channel], filtered_samples)
        )

        frames = []
        n = min(len(self.channel_buffers[1]), len(self.channel_buffers[2]))
        if n > 0:
            left = self.channel_buffers[1][:n]
            right = self.channel_buffers[2][:n]
            self.channel_buffers[1] = self.channel_buffers[1][n:]
            self.channel_buffers[2] = self.channel_buffers[2][n:]
            frames.append(np.column_stack((left, right)))

        for ch in (1, 2):
            other = 2 if ch == 1 else 1
            if len(self.channel_buffers[ch]) > 0 and len(self.channel_buffers[other]) == 0:
                data = self.channel_buffers[ch]
                self.channel_buffers[ch] = np.array([], dtype=AUDIO_DTYPE)
                frames.append(np.column_stack((data, data)))

        if self.is_recording and self.wav_file:
            for frame in frames:
                self.wav_file.writeframes(frame.astype(AUDIO_DTYPE).tobytes())

        if not self.mute_check.isChecked() and self.output_stream:
            for frame in frames:
                try:
                    self.output_stream.write((frame * self.volume).astype(AUDIO_DTYPE))
                except Exception:
                    pass

        if hasattr(self, 'scope_curve'):
            self.scope_curve.setData(audio_samples)

        audio_samples_float = audio_samples.astype(np.float32) / 32768.0

        if hasattr(self, 'rms_label'):
            self.rms_label.setText(f"RMS: {np.sqrt(np.mean(audio_samples_float**2)):.4f}")

        if len(audio_samples_float) < CHUNK_SAMPLES:
            audio_samples_float = np.pad(audio_samples_float, (0, CHUNK_SAMPLES - len(audio_samples_float)))

        with np.errstate(divide='ignore', invalid='ignore'):
            magnitude = np.abs(np.fft.fft(audio_samples_float)[:CHUNK_SAMPLES // 2])
            log_magnitude = 20 * np.log10(magnitude + 1e-12)
        log_magnitude = np.nan_to_num(log_magnitude, nan=MIN_DB, posinf=MAX_DB, neginf=MIN_DB)

        if hasattr(self, 'peak_freq_label'):
            self.peak_freq_label.setText(f"Peak: {np.argmax(log_magnitude) * (AUDIO_RATE / CHUNK_SAMPLES):.0f} Hz")

        if hasattr(self, 'spec_data') and hasattr(self, 'imv'):
            self.spec_data = np.roll(self.spec_data, -1, axis=0)
            self.spec_data[-1, :] = log_magnitude
            self.imv.setImage(np.rot90(self.spec_data), autoLevels=False, levels=(MIN_DB, MAX_DB))

    def search_in_log(self):
        if self.terminal_output_conf.find(self.search_input.text()): return
        cursor = self.terminal_output_conf.textCursor(); cursor.movePosition(QTextCursor.Start); self.terminal_output_conf.setTextCursor(cursor)
        if not self.terminal_output_conf.find(self.search_input.text()): QMessageBox.information(self, "Search", f"Phrase '{self.search_input.text()}' not found.")

    def filter_logbook(self):
        search_text = self.logbook_search_input.text().lower()
        start_date = self.logbook_start_date.date()
        end_date = self.logbook_end_date.date()

        for row in range(self.logbook_table.rowCount()):
            is_hidden = False

            date_item = self.logbook_table.item(row, 0)
            if date_item:
                try:
                    row_date = datetime.strptime(date_item.text(), "%Y-%m-%d %H:%M:%S").date()
                    if not (start_date.toPyDate() <= row_date <= end_date.toPyDate()):
                        is_hidden = True
                except ValueError:
                    is_hidden = True
            else:
                is_hidden = True

            if not is_hidden and search_text:
                text_match = False
                for col in range(self.logbook_table.columnCount()):
                    item = self.logbook_table.item(row, col)
                    if item and search_text in item.text().lower():
                        text_match = True
                        break
                if not text_match:
                    is_hidden = True

            self.logbook_table.setRowHidden(row, is_hidden)


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
        start_date = self.stats_start_date.date().toPyDate()
        end_date = self.stats_end_date.date().toPyDate()

        tg_counts = Counter()
        id_counts = Counter()
        time_data = []
        total_duration = timedelta()
        filtered_rows = 0

        for row in range(self.logbook_table.rowCount()):
            date_item = self.logbook_table.item(row, 0)
            if not date_item: continue

            try:
                row_date = datetime.strptime(date_item.text(), "%Y-%m-%d %H:%M:%S").date()
                if not (start_date <= row_date <= end_date):
                    continue
            except (ValueError, TypeError):
                continue

            filtered_rows += 1

            tg_item = self.logbook_table.item(row, 3)
            id_item = self.logbook_table.item(row, 4)
            if tg_item and tg_item.data(Qt.UserRole):
                tg_counts[tg_item.data(Qt.UserRole)] += 1
            if id_item and id_item.data(Qt.UserRole):
                id_counts[id_item.data(Qt.UserRole)] += 1

            try:
                dt_obj = datetime.strptime(date_item.text(), "%Y-%m-%d %H:%M:%S")
                time_data.append(dt_obj.timestamp())
            except (ValueError, TypeError):
                pass

            duration_item = self.logbook_table.item(row, 2)
            if duration_item and duration_item.text():
                try:
                    h, m, s = map(int, duration_item.text().split(':'))
                    total_duration += timedelta(hours=h, minutes=m, seconds=s)
                except ValueError:
                    pass

        stats_data = {
            "summary": {
                "total_calls": filtered_rows,
                "total_duration": str(total_duration),
                "most_active_tg": tg_counts.most_common(1)[0] if tg_counts else ("N/A", 0),
                "most_active_id": id_counts.most_common(1)[0] if id_counts else ("N/A", 0),
            },
            "tg_chart": tg_counts.most_common(10),
            "id_chart": id_counts.most_common(10),
            "time_chart": sorted(time_data)
        }

        self.display_statistics(stats_data)

    def display_statistics(self, data):
        summary = data.get("summary", {})
        self.total_calls_label.setText(f"<b>{summary.get('total_calls', '---')}</b>")
        self.total_duration_label.setText(f"<b>{summary.get('total_duration', '---')}</b>")

        tg_info = summary.get('most_active_tg')
        if tg_info and tg_info[1] > 0:
            tg_alias = self.aliases['tg'].get(tg_info[0], tg_info[0])
            self.most_active_tg_label.setText(f"<b>{tg_alias}</b> ({tg_info[1]} calls)")
        else:
            self.most_active_tg_label.setText("---")

        id_info = summary.get('most_active_id')
        if id_info and id_info[1] > 0:
            id_alias = self.aliases['id'].get(id_info[0], id_info[0])
            self.most_active_id_label.setText(f"<b>{id_alias}</b> ({id_info[1]} calls)")
        else:
            self.most_active_id_label.setText("---")

        for chart, chart_data, alias_type in [(self.tg_chart, data.get("tg_chart", []), 'tg'), (self.id_chart, data.get("id_chart", []), 'id')]:
            chart.clear()
            if chart_data:
                labels = [self.aliases[alias_type].get(item[0], item[0]) for item in chart_data]
                counts = [item[1] for item in chart_data]

                bar = pg.BarGraphItem(x=range(len(counts)), height=counts, width=0.6, brush=self.palette().highlight().color())
                chart.addItem(bar)

                ax = chart.getAxis('bottom')
                ax.setTicks([list(enumerate(labels))])
                chart.getAxis('left').setGrid(128)

        self.time_chart.clear()
        time_data_points = data.get("time_chart", [])
        if time_data_points:
            y, x = np.histogram(time_data_points, bins=100)
            self.time_chart.plot(x, y, stepMode=True, fillLevel=0, brush=(0,0,255,150), pen=pg.mkPen(color=self.palette().highlight().color(), width=2))
        self.time_chart.getAxis('left').setGrid(128)
        self.time_chart.getAxis('bottom').setGrid(128)

    def export_statistics(self):
        path, _ = QFileDialog.getSaveFileName(self, "Export Statistics", "", "JSON Files (*.json)")
        if not path:
            return

        try:
            tg_data = []
            if self.tg_chart.items:
                bar_item = self.tg_chart.items[0]
                ticks = self.tg_chart.getAxis('bottom').ticks[0]
                for i, height in enumerate(bar_item.opts['height']):
                    alias = ticks[i][1]
                    original_id = next((k for k, v in self.aliases['tg'].items() if v == alias), alias)
                    tg_data.append((original_id, height))

            id_data = []
            if self.id_chart.items:
                bar_item = self.id_chart.items[0]
                ticks = self.id_chart.getAxis('bottom').ticks[0]
                for i, height in enumerate(bar_item.opts['height']):
                    alias = ticks[i][1]
                    original_id = next((k for k, v in self.aliases['id'].items() if v == alias), alias)
                    id_data.append((original_id, height))

            time_data = []
            if self.time_chart.items:
                plot_item = self.time_chart.items[0]
                x_data = plot_item.xData
                time_data = list(x_data) if x_data is not None else []

            stats_to_save = {
                "summary": {
                    "total_calls": int(self.total_calls_label.text().strip("<b></b>")),
                    "total_duration": self.total_duration_label.text().strip("<b></b>"),
                    "most_active_tg": self.most_active_tg_label.text().strip("<b></b>"),
                    "most_active_id": self.most_active_id_label.text().strip("<b></b>"),
                },
                "tg_chart": tg_data,
                "id_chart": id_data,
                "time_chart": time_data,
                "exported_at": datetime.now().isoformat()
            }

            with open(path, 'w') as f:
                json.dump(stats_to_save, f, indent=4)
            QMessageBox.information(self, "Success", "Statistics have been exported.")
        except Exception as e:
            QMessageBox.critical(self, "Error", f"Could not export statistics: {e}")

    def import_statistics(self):
        path, _ = QFileDialog.getOpenFileName(self, "Import Statistics", "", "JSON Files (*.json)")
        if not path:
            return

        try:
            with open(path, 'r') as f:
                stats_data = json.load(f)

            summary = stats_data.get("summary", {})
            most_tg_str = summary.get("most_active_tg", "N/A (0 calls)")
            most_id_str = summary.get("most_active_id", "N/A (0 calls)")

            summary['most_active_tg'] = (most_tg_str.split(' (')[0], int(most_tg_str.split('(')[-1].replace(' calls)', ''))) if '(' in most_tg_str else (most_tg_str, 0)
            summary['most_active_id'] = (most_id_str.split(' (')[0], int(most_id_str.split('(')[-1].replace(' calls)', ''))) if '(' in most_id_str else (most_id_str, 0)

            stats_data['summary'] = summary

            self.display_statistics(stats_data)
            QMessageBox.information(self, "Success", "Statistics have been imported.")
        except Exception as e:
            QMessageBox.critical(self, "Error", f"Could not import statistics file: {e}\nThe file may be corrupted or in a wrong format.")

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
            try:
                with open(path, 'r', newline='', encoding='utf-8') as f:
                    reader = csv.reader(f)
                    self.logbook_table.setRowCount(0)
                    header = next(reader, None)
                    self.logbook_table.setSortingEnabled(False)
                    for row_data in reader:
                        row = self.logbook_table.rowCount()
                        self.logbook_table.insertRow(row)
                        for i, data in enumerate(row_data):
                            item = QTableWidgetItem(data)
                            if i < 6:
                                item.setFlags(item.flags() & ~Qt.ItemIsEditable)
                            self.logbook_table.setItem(row, i, item)
                    self.logbook_table.setSortingEnabled(True)
                QMessageBox.information(self, "Success", "Logbook has been imported.")
            except Exception as e:
                QMessageBox.critical(self, "Import Error", f"Could not import CSV file:\n{e}")

    def save_history_to_csv(self):
        path, _ = QFileDialog.getSaveFileName(self, "Save CSV", "", "CSV Files (*.csv)");
        if path:
            try:
                with open(path, 'w', newline='', encoding='utf-8') as f:
                    writer = csv.writer(f)
                    header_labels = [self.logbook_table.horizontalHeaderItem(i).text() for i in range(self.logbook_table.columnCount())]
                    writer.writerow(header_labels)
                    for row in range(self.logbook_table.rowCount()):
                        row_data = []
                        for col in range(self.logbook_table.columnCount()):
                            item = self.logbook_table.item(row, col)
                            row_data.append(item.text() if item else "")
                        writer.writerow(row_data)
                QMessageBox.information(self, "Success", f"Logbook successfully saved to {os.path.basename(path)}")
            except Exception as e:
                QMessageBox.critical(self, "Save Error", f"Could not save CSV file:\n{e}")

    def export_stt_history(self):
        path, _ = QFileDialog.getSaveFileName(self, "Export Transcription History", "", "CSV Files (*.csv)");
        if path:
            try:
                with open(path, 'w', newline='', encoding='utf-8') as f:
                    writer = csv.writer(f)
                    writer.writerow(["Time", "Radio ID", "Transcription Text"])
                    for row in range(self.stt_table.rowCount()):
                        row_data = [self.stt_table.item(row, col).text() if self.stt_table.item(row, col) else "" for col in range(self.stt_table.columnCount())]
                        writer.writerow(row_data)
                QMessageBox.information(self, "Success", f"Transcription history has been saved.")
            except Exception as e:
                QMessageBox.critical(self, "Save Error", f"Could not save CSV file:\n{e}")

    def import_stt_history(self):
        path, _ = QFileDialog.getOpenFileName(self, "Import Transcription History", "", "CSV Files (*.csv)");
        if path:
            try:
                with open(path, 'r', newline='', encoding='utf-8') as f:
                    reader = csv.reader(f)
                    self.stt_table.setRowCount(0)
                    header = next(reader, None)
                    for row_data in reader:
                        row = self.stt_table.rowCount()
                        self.stt_table.insertRow(row)
                        for i, data in enumerate(row_data):
                            self.stt_table.setItem(row, i, QTableWidgetItem(data))
                QMessageBox.information(self, "Success", "Transcription history has been imported.")
            except Exception as e:
                QMessageBox.critical(self, "Import Error", f"Could not import CSV file:\n{e}")

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
        if self.output_stream:
            self.output_stream.stop()
            self.output_stream.close()
        self.filter_states.clear()
        self.channel_buffers = {1: np.array([], dtype=AUDIO_DTYPE), 2: np.array([], dtype=AUDIO_DTYPE)}
        try:
            self.output_stream = sd.OutputStream(samplerate=AUDIO_RATE, device=self.device_combo.currentData(), channels=2, dtype=AUDIO_DTYPE, blocksize=CHUNK_SAMPLES)
            self.output_stream.start()
        except Exception as e:
            print(f"Error opening audio stream: {e}")

    def set_volume(self, value): self.volume = value / 100.0

    def start_transcription(self, audio_data, radio_id):
        if self.transcription_thread and self.transcription_thread.isRunning():
            print("Transcription already in progress, skipping...")
            return

        stt_settings = {
            'engine': self.stt_engine_combo.currentText(),
            'language': self.stt_lang_combo.currentText(),
            'whisper_model': self.stt_whisper_model_combo.currentText(),
            'vosk_model_path': self.stt_vosk_path_edit.text()
        }

        self.transcription_thread = QThread()
        self.transcription_worker = TranscriptionWorker(audio_data, radio_id, stt_settings)
        self.transcription_worker.moveToThread(self.transcription_thread)

        self.transcription_thread.started.connect(self.transcription_worker.run)
        self.transcription_worker.finished.connect(self.update_stt_table)
        self.transcription_worker.finished.connect(self.transcription_thread.quit)
        self.transcription_worker.finished.connect(self.transcription_worker.deleteLater)
        self.transcription_thread.finished.connect(self.transcription_thread.deleteLater)

        if hasattr(self, 'stt_status_bar'):
             self.transcription_worker.progress.connect(self.stt_status_bar.showMessage)

        self.transcription_thread.start()

    @pyqtSlot(str, str)
    def update_stt_table(self, radio_id, text):
        if radio_id in self.stt_active_id_row:
            row = self.stt_active_id_row[radio_id]
            current_item = self.stt_table.item(row, 2)
            if current_item: # Check if item exists
                current_text = current_item.text()
                if current_text == "...":
                    current_item.setText(text)
                else:
                    current_item.setText(f"{current_text} {text}")
        if hasattr(self, 'stt_status_bar'):
            self.stt_status_bar.clearMessage()


    def apply_filters(self, samples):
        samples_float = samples.astype(np.float32)

        if self.widgets['agc_check'].isChecked():
            samples_float_normalized = samples_float / 32768.0

            strength = self.widgets['agc_strength_slider'].value() / 100.0
            target_rms = 0.1

            current_rms = np.sqrt(np.mean(samples_float_normalized**2))
            if current_rms > 1e-6:
                gain = target_rms / current_rms
                gain = np.clip(gain, 0.1, 10.0)

                if 'agc_gain' not in self.filter_states: self.filter_states['agc_gain'] = 1.0
                self.filter_states['agc_gain'] = (1.0 - strength) * self.filter_states['agc_gain'] + strength * gain

                samples_float *= self.filter_states['agc_gain']

        if self.widgets["hp_filter_check"].isChecked():
            cutoff = self.widgets["hp_cutoff_spin"].value()
            b, a = signal.butter(4, cutoff, 'highpass', fs=AUDIO_RATE)
            if 'hp_filter' not in self.filter_states: self.filter_states['hp_filter'] = signal.lfilter_zi(b,a)
            samples_float, self.filter_states['hp_filter'] = signal.lfilter(b, a, samples_float, zi=self.filter_states['hp_filter'])


        if self.widgets["lp_filter_check"].isChecked():
            cutoff = self.widgets["lp_cutoff_spin"].value()
            b, a = signal.butter(4, cutoff, 'lowpass', fs=AUDIO_RATE)
            if 'lp_filter' not in self.filter_states: self.filter_states['lp_filter'] = signal.lfilter_zi(b,a)
            samples_float, self.filter_states['lp_filter'] = signal.lfilter(b, a, samples_float, zi=self.filter_states['lp_filter'])

        if self.widgets["bp_filter_check"].isChecked():
            low = self.widgets["bp_center_spin"].value() - self.widgets["bp_width_spin"].value() / 2
            high = self.widgets["bp_center_spin"].value() + self.widgets["bp_width_spin"].value() / 2
            b, a = signal.butter(4, [low, high], 'bandpass', fs=AUDIO_RATE)
            if 'bp_filter' not in self.filter_states: self.filter_states['bp_filter'] = signal.lfilter_zi(b,a)
            samples_float, self.filter_states['bp_filter'] = signal.lfilter(b, a, samples_float, zi=self.filter_states['bp_filter'])

        if self.widgets["notch_filter_check"].isChecked():
            freq = self.widgets["notch_freq_spin"].value()
            q = self.widgets["notch_q_spin"].value()
            b, a = signal.iirnotch(freq, q, fs=AUDIO_RATE)
            if 'notch_filter' not in self.filter_states: self.filter_states['notch_filter'] = signal.lfilter_zi(b,a)
            samples_float, self.filter_states['notch_filter'] = signal.lfilter(b, a, samples_float, zi=self.filter_states['notch_filter'])

        if hasattr(self, 'eq_sliders'):
            eq_bands = [100, 300, 600, 1000, 3000, 6000]
            for i, slider in enumerate(self.eq_sliders):
                gain_db = slider.value()
                if abs(gain_db) > 0.1: # Apply only if there is a change
                    center_freq = eq_bands[i]
                    q_factor = 3.0
                    b, a = signal.iirpeak(center_freq, q_factor, fs=AUDIO_RATE, gain=gain_db)
                    
                    filter_name = f'eq_filter_{i}'
                    if filter_name not in self.filter_states: self.filter_states[filter_name] = signal.lfilter_zi(b, a)
                    samples_float, self.filter_states[filter_name] = signal.lfilter(b, a, samples_float, zi=self.filter_states[filter_name])


        if self.widgets['nr_check'].isChecked():
            strength = self.widgets['nr_strength_slider'].value() / 100.0

            spec = np.fft.fft(samples_float)
            mag = np.abs(spec)
            phase = np.angle(spec)

            if 'noise_profile' not in self.filter_states:
                self.filter_states['noise_profile'] = np.mean(mag)

            self.filter_states['noise_profile'] = (1 - 0.01) * self.filter_states['noise_profile'] + 0.01 * np.mean(mag)

            mag_denoised = np.maximum(0, mag - self.filter_states['noise_profile'] * strength)
            spec_denoised = mag_denoised * np.exp(1j * phase)
            samples_float = np.fft.ifft(spec_denoised).real

        np.clip(samples_float, -32767, 32767, out=samples_float)
        return samples_float.astype(AUDIO_DTYPE)
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
