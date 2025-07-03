import sys
import os
import subprocess
import json
import shlex
import threading
import csv

try:
    import winsound
    WINSOUND_AVAILABLE = True
except ImportError:
    WINSOUND_AVAILABLE = False

from PyQt5.QtWidgets import *
from PyQt5.QtGui import QFont, QPalette, QColor, QTextCursor
from PyQt5.QtCore import (Qt, QThread, pyqtSignal, QObject, pyqtSlot, QTimer, 
                           QDir, QFileSystemWatcher, QTime)
from PyQt5.QtMultimedia import QSound


CONFIG_FILE = 'dsd-fme-gui-config.json'

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
        self.finished.emit()

class DSDApp(QMainWindow):
    def __init__(self):
        super().__init__()
        self.process = None
        self.reader_thread = None
        self.reader_worker = None
        
       
        self.is_in_transmission = False 
        self.alerts = []
        self.recording_dir = ""
        self.fs_watcher = QFileSystemWatcher()
        self.fs_watcher.directoryChanged.connect(self.update_recording_list)

        self.setWindowTitle("DSD-FME GUI by Kameleon v1.4")
        self.setGeometry(100, 100, 1100, 850)
        
        self.widgets = {}
        self.inverse_widgets = {}
        self.dsd_fme_path = self._load_config_or_prompt()
        
        if self.dsd_fme_path:
            self._init_ui()
            self._load_app_config()
        else:
            QTimer.singleShot(100, self.close)

    def _load_config_or_prompt(self):
        config = {}
        if os.path.exists(CONFIG_FILE):
            try:
                with open(CONFIG_FILE, 'r') as f: config = json.load(f)
            except json.JSONDecodeError: pass
        
        path = config.get('dsd_fme_path')
        if path and os.path.exists(path):
            return path
        
        return self._prompt_for_dsd_fme_path()

    def _prompt_for_dsd_fme_path(self):
        QMessageBox.information(self, "Setup", "Please locate your 'dsd-fme.exe' file.")
        path, _ = QFileDialog.getOpenFileName(self, "Select dsd-fme.exe", "", "Executable Files (dsd-fme.exe dsd-fme)")
        
        if path and ("dsd-fme" in os.path.basename(path).lower()):
            with open(CONFIG_FILE, 'w') as f: json.dump({'dsd_fme_path': path}, f, indent=4)
            return path
        else:
            QMessageBox.critical(self, "Error", "DSD-FME not selected. The application cannot function without it.")
            return None

    def _load_app_config(self):
        config = {}
        if os.path.exists(CONFIG_FILE):
            try:
                with open(CONFIG_FILE, 'r') as f:
                    config = json.load(f)
            except json.JSONDecodeError:
                return
        
        self.alerts = config.get('alerts', [])
        self.update_alerts_list()
        
        self.recording_dir = config.get('recording_dir', "")
        self.recorder_dir_edit.setText(self.recording_dir)
        if self.recording_dir and os.path.exists(self.recording_dir):
            if self.recording_dir not in self.fs_watcher.directories():
                 self.fs_watcher.addPath(self.recording_dir)
            self.update_recording_list()
        
        self.recorder_enabled_check.setChecked(config.get('recorder_enabled', False))

    def _save_app_config(self):
        config = {'dsd_fme_path': self.dsd_fme_path}
        config['alerts'] = self.alerts
        config['recording_dir'] = self.recorder_dir_edit.text()
        config['recorder_enabled'] = self.recorder_enabled_check.isChecked()
        
        with open(CONFIG_FILE, 'w') as f:
            json.dump(config, f, indent=4)

    def _init_ui(self):
        central_widget = QWidget(); self.setCentralWidget(central_widget)
        main_layout = QVBoxLayout(central_widget)
        
        root_tabs = QTabWidget()
        main_layout.addWidget(root_tabs)

        config_widget = QWidget()
        config_layout = QVBoxLayout(config_widget)
        main_splitter = QSplitter(Qt.Vertical)
        config_layout.addWidget(main_splitter)
        
        options_container_widget = QWidget()
        scroll_area = QScrollArea(); scroll_area.setWidgetResizable(True); scroll_area.setWidget(options_container_widget)
        container_layout = QVBoxLayout(options_container_widget)
        
        options_tabs = QTabWidget(); container_layout.addWidget(options_tabs)
        options_tabs.addTab(self._create_io_tab(), "Input / Output"); options_tabs.addTab(self._create_decoder_tab(), "Decoder Modes")
        options_tabs.addTab(self._create_advanced_tab(), "Advanced & Crypto"); options_tabs.addTab(self._create_trunking_tab(), "Trunking")
        
        cmd_group = QGroupBox("Execution"); cmd_layout = QGridLayout(cmd_group)
        self.cmd_preview = QLineEdit(); self.cmd_preview.setReadOnly(False); self.cmd_preview.setFont(QFont("Consolas", 9))
        self.btn_build_cmd = QPushButton("Generate Command from Options"); self.btn_build_cmd.clicked.connect(self.build_command)
        self.btn_start = QPushButton("START"); self.btn_stop = QPushButton("STOP"); self.btn_stop.setEnabled(False)
        self.btn_start.clicked.connect(self.start_process); self.btn_stop.clicked.connect(self.stop_process)
        cmd_layout.addWidget(self.btn_start, 0, 0); cmd_layout.addWidget(self.btn_stop, 0, 1)
        cmd_layout.addWidget(self.btn_build_cmd, 1, 0, 1, 2)
        cmd_layout.addWidget(QLabel("Command to Execute:"), 2, 0, 1, 2); cmd_layout.addWidget(self.cmd_preview, 3, 0, 1, 2)
        container_layout.addWidget(cmd_group)

        terminal_container = QWidget(); terminal_main_layout = QVBoxLayout(terminal_container)
        live_data_group = self._create_live_analysis_group()
        terminal_main_layout.addWidget(live_data_group)
        terminal_group = self._create_terminal_group()
        terminal_main_layout.addWidget(terminal_group)
        
        main_splitter.addWidget(scroll_area); main_splitter.addWidget(terminal_container)
        main_splitter.setSizes([350, 450])

        root_tabs.addTab(config_widget, "Configuration & Live Log")
        root_tabs.addTab(self._create_call_history_tab(), "Voice Events")
        root_tabs.addTab(self._create_recorder_tab(), "Recorder")
        root_tabs.addTab(self._create_alerts_tab(), "Alerts")

        if not self.dsd_fme_path:
            self.btn_start.setEnabled(False); self.statusBar().showMessage("DSD-FME path not set!")

    def _create_io_tab(self):
        tab = QWidget(); layout = QGridLayout(tab)
        g1 = QGroupBox("Input (-i)"); l1 = QGridLayout(g1)
        self._add_widget("-i_type", QComboBox()).addItems(["tcp", "wav", "rtl", "pulse"])
        self._add_widget("-i_tcp", QLineEdit("127.0.0.1:7355")); self._add_widget("-i_wav", QLineEdit())
        l1.addWidget(QLabel("Type:"), 0, 0); l1.addWidget(self.widgets["-i_type"], 0, 1); l1.addWidget(QLabel("TCP Addr:Port:"), 1, 0); l1.addWidget(self.widgets["-i_tcp"], 1, 1)
        l1.addWidget(QLabel("WAV File:"), 2, 0); l1.addWidget(self.widgets["-i_wav"], 2, 1); l1.addWidget(self._create_browse_button(self.widgets["-i_wav"]), 2, 2)
        g2 = QGroupBox("Output (-o)"); l2 = QGridLayout(g2)
        self._add_widget("-o_type", QComboBox()).addItems(["Windows Default", "null", "pulse", "udp"]); self._add_widget("-o_udp", QLineEdit("127.0.0.1:23456"))
        l2.addWidget(QLabel("Type:"), 0, 0); l2.addWidget(self.widgets["-o_type"], 0, 1); l2.addWidget(QLabel("UDP Addr:Port:"), 1, 0); l2.addWidget(self.widgets["-o_udp"], 1, 1)
        g3 = QGroupBox("File Outputs"); l3 = QGridLayout(g3)
        self._add_widget("-w", QLineEdit()); self._add_widget("-6", QLineEdit()); self._add_widget("-7", QLineEdit()); self._add_widget("-d", QLineEdit()); self._add_widget("-c", QLineEdit())
        l3.addWidget(QLabel("Synth Speech [-w]:"), 0, 0); l3.addWidget(self.widgets["-w"], 0, 1); l3.addWidget(self._create_browse_button(self.widgets["-w"]), 0, 2)
        l3.addWidget(QLabel("Raw Audio [-6]:"), 1, 0); l3.addWidget(self.widgets["-6"], 1, 1); l3.addWidget(self._create_browse_button(self.widgets["-6"]), 1, 2)
        l3.addWidget(QLabel("Per Call Dir [-7]:"), 2, 0); l3.addWidget(self.widgets["-7"], 2, 1); l3.addWidget(self._create_browse_button(self.widgets["-7"], is_dir=True), 2, 2)
        l3.addWidget(QLabel("MBE Data Dir [-d]:"), 3, 0); l3.addWidget(self.widgets["-d"], 3, 1); l3.addWidget(self._create_browse_button(self.widgets["-d"], is_dir=True), 3, 2)
        l3.addWidget(QLabel("Symbol Capture [-c]:"), 4, 0); l3.addWidget(self.widgets["-c"], 4, 1); l3.addWidget(self._create_browse_button(self.widgets["-c"]), 4, 2)
        g4 = QGroupBox("Other"); l4 = QGridLayout(g4)
        self._add_widget("-P", QCheckBox("Enable Per Call WAV Saving")); self._add_widget("-s", QLineEdit("48000")); self._add_widget("-g", QLineEdit("0")); self._add_widget("-V", QLineEdit("3"))
        l4.addWidget(self.widgets["-P"], 0, 0, 1, 2); l4.addWidget(QLabel("WAV Sample Rate [-s]:"), 1, 0); l4.addWidget(self.widgets["-s"], 1, 1); l4.addWidget(QLabel("Digital Gain [-g]:"), 2, 0); l4.addWidget(self.widgets["-g"], 2, 1); l4.addWidget(QLabel("TDMA Slot Synth [-V]:"), 3, 0); l4.addWidget(self.widgets["-V"], 3, 1)
        layout.addWidget(g1, 0, 0); layout.addWidget(g2, 0, 1); layout.addWidget(g3, 1, 0); layout.addWidget(g4, 1, 1)
        return tab

    def _create_decoder_tab(self):
        tab = QWidget(); scroll = QScrollArea(); scroll.setWidgetResizable(True); layout = QVBoxLayout(tab); layout.addWidget(scroll); container = QWidget(); scroll.setWidget(container); grid = QGridLayout(container)
        g1 = QGroupBox("Decoder Mode (-f...)"); l1 = QVBoxLayout(g1); self.decoder_mode_group = QButtonGroup()
        modes = {"-fa":"Auto", "-fA":"Analog", "-ft":"Trunk P25/DMR", "-fs":"DMR Simplex", "-f1":"P25 P1", "-f2":"P25 P2", "-fd":"D-STAR", "-fx":"X2-TDMA", "-fy":"YSF", "-fz":"M17", "-fi":"NXDN48", "-fn":"NXDN96", "-fp":"ProVoice", "-fe":"EDACS EA"}
        for flag, name in modes.items(): rb = QRadioButton(name); self._add_widget(flag, rb); self.decoder_mode_group.addButton(rb); l1.addWidget(rb)
        self.widgets["-fa"].setChecked(True)
        g2 = QGroupBox("Decoder Options"); l2 = QVBoxLayout(g2); l2.addWidget(self._add_widget("-l", QCheckBox("Disable Input Filtering"))); l2.addWidget(self._add_widget("-xx", QCheckBox("Invert X2-TDMA"))); l2.addWidget(self._add_widget("-xr", QCheckBox("Invert DMR")))
        l2.addWidget(self._add_widget("-xd", QCheckBox("Invert dPMR"))); l2.addWidget(self._add_widget("-xz", QCheckBox("Invert M17"))); l2.addStretch()
        grid.addWidget(g1, 0, 0); grid.addWidget(g2, 0, 1)
        return tab

    def _create_advanced_tab(self):
        tab = QWidget(); layout = QGridLayout(tab); g1 = QGroupBox("Modulation (-m...) & Display"); l1 = QVBoxLayout(g1); self.mod_group = QButtonGroup()
        mods = {"-ma":"Auto", "-mc":"C4FM (default)", "-mg":"GFSK", "-mq":"QPSK", "-m2":"P25p2 QPSK"}
        for flag, name in mods.items(): rb = QRadioButton(name); self._add_widget(flag, rb); self.mod_group.addButton(rb); l1.addWidget(rb)
        self.widgets["-mc"].setChecked(True); l1.addSpacing(20); l1.addWidget(self._add_widget("-N", QCheckBox("Use NCurses Emulation [-N]"))); l1.addWidget(self._add_widget("-Z", QCheckBox("Log Payloads to Console [-Z]")))
        g2 = QGroupBox("Encryption Keys"); l2 = QGridLayout(g2)
        l2.addWidget(QLabel("Basic Privacy Key [-b]:"), 0, 0); l2.addWidget(self._add_widget("-b", QLineEdit()), 0, 1); l2.addWidget(QLabel("RC4 Key [-1]:"), 1, 0); l2.addWidget(self._add_widget("-1", QLineEdit()), 1, 1)
        l2.addWidget(QLabel("Hytera BP Key [-H]:"), 2, 0); l2.addWidget(self._add_widget("-H", QLineEdit()), 2, 1); l2.addWidget(QLabel("Keys from .csv [-K]:"), 3, 0); self._add_widget("-K", QLineEdit()); l2.addWidget(self.widgets["-K"], 3, 1); l2.addWidget(self._create_browse_button(self.widgets["-K"]), 3, 2)
        g3 = QGroupBox("Force Options"); l3 = QVBoxLayout(g3); l3.addWidget(self._add_widget("-4", QCheckBox("Force BP Key"))); l3.addWidget(self._add_widget("-0", QCheckBox("Force RC4 Key"))); l3.addWidget(self._add_widget("-3", QCheckBox("Disable DMR Late Entry Enc."))); l3.addWidget(self._add_widget("-F", QCheckBox("Relax CRC Checksum")))
        layout.addWidget(g1, 0, 0); layout.addWidget(g2, 0, 1); layout.addWidget(g3, 1, 0, 1, 2)
        return tab

    def _create_trunking_tab(self):
        tab = QWidget(); layout = QVBoxLayout(tab); g1 = QGroupBox("Trunking Options"); l1 = QGridLayout(g1)
        l1.addWidget(self._add_widget("-T", QCheckBox("Enable Trunking")), 0, 0); l1.addWidget(self._add_widget("-Y", QCheckBox("Enable Scanning")), 0, 1)
        l1.addWidget(QLabel("Channel Map [-C]:"), 1, 0); self._add_widget("-C", QLineEdit()); l1.addWidget(self.widgets["-C"], 1, 1); l1.addWidget(self._create_browse_button(self.widgets["-C"]), 1, 2)
        l1.addWidget(QLabel("Group List [-G]:"), 2, 0); self._add_widget("-G", QLineEdit()); l1.addWidget(self.widgets["-G"], 2, 1); l1.addWidget(self._create_browse_button(self.widgets["-G"]), 2, 2)
        l1.addWidget(QLabel("RigCtl Port [-U]:"), 3, 0); l1.addWidget(self._add_widget("-U", QLineEdit("")), 3, 1)
        g2 = QGroupBox("Tuning Control"); l2 = QVBoxLayout(g2); l2.addWidget(self._add_widget("-p", QCheckBox("Disable Tune to Private Calls"))); l2.addWidget(self._add_widget("-E", QCheckBox("Disable Tune to Group Calls"))); l2.addWidget(self._add_widget("-e", QCheckBox("Enable Tune to Data Calls")))
        layout.addWidget(g1); layout.addWidget(g2); layout.addStretch()
        return tab
    
    def _create_live_analysis_group(self):
        group = QGroupBox("Live Analysis")
        layout = QGridLayout(group)
        font = QFont(); font.setBold(True)
        
        layout.addWidget(QLabel("Status:"), 0, 0); self.lbl_status = QLabel("---"); self.lbl_status.setFont(font); layout.addWidget(self.lbl_status, 0, 1)
        layout.addWidget(QLabel("Talkgroup (TG):"), 1, 0); self.lbl_tg = QLabel("---"); self.lbl_tg.setFont(font); layout.addWidget(self.lbl_tg, 1, 1)
        layout.addWidget(QLabel("Radio ID (ID):"), 2, 0); self.lbl_id = QLabel("---"); self.lbl_id.setFont(font); layout.addWidget(self.lbl_id, 2, 1)
        layout.addWidget(QLabel("Color Code (CC):"), 0, 2); self.lbl_cc = QLabel("---"); self.lbl_cc.setFont(font); layout.addWidget(self.lbl_cc, 0, 3)
        layout.addWidget(QLabel("Last Voice:"), 1, 2); self.lbl_last_voice = QLabel("---"); self.lbl_last_voice.setFont(font); layout.addWidget(self.lbl_last_voice, 1, 3)
        
        layout.setColumnStretch(1, 1); layout.setColumnStretch(3, 1)
        return group

    def _create_terminal_group(self):
        group = QGroupBox("Terminal Log")
        layout = QGridLayout(group)
        self.terminal_output = QPlainTextEdit(); self.terminal_output.setReadOnly(True); self.terminal_output.setFont(QFont("Consolas", 10))
        self.terminal_output.setStyleSheet("background-color: black; color: lightgreen;")
        
        self.search_input = QLineEdit(); self.search_input.setPlaceholderText("Search in log...")
        self.search_button = QPushButton("Find Next"); self.search_button.clicked.connect(self.search_in_log)
        self.search_input.returnPressed.connect(self.search_in_log)

        layout.addWidget(self.terminal_output, 0, 0, 1, 2)
        layout.addWidget(self.search_input, 1, 0)
        layout.addWidget(self.search_button, 1, 1)
        return group

    def _create_call_history_tab(self):
        widget = QWidget()
        layout = QVBoxLayout(widget)
        self.voice_event_table = QTableWidget()
        self.voice_event_table.setColumnCount(4)
        self.voice_event_table.setHorizontalHeaderLabels(["Time", "Talkgroup", "Radio ID", "Color Code"])
        self.voice_event_table.setEditTriggers(QAbstractItemView.NoEditTriggers)
        self.voice_event_table.setSelectionBehavior(QAbstractItemView.SelectRows)
        self.voice_event_table.horizontalHeader().setSectionResizeMode(QHeaderView.Stretch)
        self.voice_event_table.verticalHeader().setVisible(False)
        
        self.save_csv_button = QPushButton("Save to CSV")
        self.save_csv_button.clicked.connect(self.save_history_to_csv)
        
        layout.addWidget(self.voice_event_table)
        layout.addWidget(self.save_csv_button)
        return widget

    def _create_recorder_tab(self):
        widget = QWidget()
        layout = QGridLayout(widget)
        
        self.recorder_enabled_check = QCheckBox("Enable Voice-Activated Recording to Directory")
        self.recorder_dir_edit = QLineEdit()
        self.recorder_dir_edit.setPlaceholderText("Select directory for WAV files...")
        self.recorder_browse_btn = QPushButton("Browse...")
        self.recorder_browse_btn.clicked.connect(self.browse_for_recording_dir)
        
        self.recording_list = QListWidget()
        self.recording_list.itemDoubleClicked.connect(self.play_recording)
        
        play_btn = QPushButton("Play Selected Recording")
        play_btn.clicked.connect(self.play_recording)

        layout.addWidget(self.recorder_enabled_check, 0, 0, 1, 2)
        layout.addWidget(QLabel("Recording Directory:"), 1, 0)
        layout.addWidget(self.recorder_dir_edit, 1, 1)
        layout.addWidget(self.recorder_browse_btn, 1, 2)
        layout.addWidget(self.recording_list, 2, 0, 1, 3)
        layout.addWidget(play_btn, 3, 0, 1, 3)
        return widget

    def _create_alerts_tab(self):
        widget = QWidget()
        layout = QGridLayout(widget)
        
        form_group = QGroupBox("Add New Alert (plays 2-tone system beep)")
        form_layout = QGridLayout(form_group)
        
        self.alert_type_combo = QComboBox(); self.alert_type_combo.addItems(["Talkgroup (TG)", "Radio ID"])
        self.alert_value_edit = QLineEdit(); self.alert_value_edit.setPlaceholderText("Enter TG or ID value...")
        self.alert_add_btn = QPushButton("Add Alert"); self.alert_add_btn.clicked.connect(self.add_alert)

        form_layout.addWidget(QLabel("Alert Type:"), 0, 0); form_layout.addWidget(self.alert_type_combo, 0, 1)
        form_layout.addWidget(QLabel("Value:"), 1, 0); form_layout.addWidget(self.alert_value_edit, 1, 1)
        form_layout.addWidget(self.alert_add_btn, 2, 1)
        
        self.alerts_list_widget = QListWidget()
        self.alert_remove_btn = QPushButton("Remove Selected Alert")
        self.alert_remove_btn.clicked.connect(self.remove_alert)

        layout.addWidget(form_group, 0, 0)
        layout.addWidget(self.alerts_list_widget, 1, 0)
        layout.addWidget(self.alert_remove_btn, 2, 0)
        layout.setRowStretch(1, 1)
        return widget

    def _add_widget(self, key, widget):
        self.widgets[key] = widget
        if isinstance(widget, QRadioButton): self.inverse_widgets[widget] = key
        return widget
        
    def _create_browse_button(self, line_edit_widget, is_dir=False):
        button = QPushButton("Browse..."); button.clicked.connect(lambda: self._browse_for_path(line_edit_widget, is_dir)); return button

    def _browse_for_path(self, line_edit_widget, is_dir):
        if is_dir: path = QFileDialog.getExistingDirectory(self, "Select Directory")
        else: path, _ = QFileDialog.getOpenFileName(self, "Select File")
        if path: line_edit_widget.setText(path)

    @pyqtSlot()
    def search_in_log(self):
        query = self.search_input.text()
        if not query: return
        if not self.terminal_output.find(query):
            cursor = self.terminal_output.textCursor()
            cursor.movePosition(QTextCursor.Start)
            self.terminal_output.setTextCursor(cursor)
            if not self.terminal_output.find(query):
                 QMessageBox.information(self, "Search", f"Phrase '{query}' not found.")

    @pyqtSlot()
    def build_command(self):
        if not self.dsd_fme_path: self.cmd_preview.setText("ERROR: DSD-FME path not set!"); return []
        command = [self.dsd_fme_path]
        
        self.widgets['-P'].setChecked(self.recorder_enabled_check.isChecked())
        if self.recorder_enabled_check.isChecked():
            rec_dir = self.recorder_dir_edit.text()
            if rec_dir and os.path.isdir(rec_dir):
                self.widgets["-7"].setText(rec_dir)
        
        in_type = self.widgets["-i_type"].currentText()
        if in_type == "tcp": val = self.widgets["-i_tcp"].text(); command.extend(["-i", f"tcp:{val}" if val else "tcp"])
        elif in_type == "wav": val = self.widgets["-i_wav"].text(); command.extend(["-i", val]) if val else None
        else: command.extend(["-i", in_type])
        out_type = self.widgets["-o_type"].currentText()
        if out_type != "Windows Default": command.extend(["-o", out_type.lower()])
        for flag in ["-s","-g","-V","-w","-6","-7","-d","-c","-b","-1","-H","-K","-C","-G","-U"]:
            if self.widgets[flag].text(): command.extend([flag, self.widgets[flag].text()])
        
        for flag in ["-P", "-l","-xx","-xr","-xd","-xz","-N","-Z","-4","-0","-3","-F","-T","-Y","-p","-E","-e"]:
            if flag in self.widgets and self.widgets[flag].isChecked():
                command.append(flag)
        
        for btn, flag in self.inverse_widgets.items():
            if btn.isChecked(): command.append(flag)
        
        final_command = list(dict.fromkeys(item for item in command if item is not None and item != ""))
        self.cmd_preview.setText(subprocess.list2cmdline(final_command))
        return final_command

    @pyqtSlot()
    def start_process(self):
        if self.process: return
        self.voice_event_table.setRowCount(0)
        self.is_in_transmission = False
        
        command = self.build_command()
        if not command: return
        
        self.terminal_output.clear(); self.terminal_output.appendPlainText(f"$ {subprocess.list2cmdline(command)}\n\n")
        try:
            self.process = subprocess.Popen(
                command, stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                stdin=subprocess.DEVNULL, universal_newlines=True, encoding='utf-8', errors='ignore',
                creationflags=subprocess.CREATE_NO_WINDOW if os.name == 'nt' else 0)
            
            self.reader_thread = QThread(); self.reader_worker = ProcessReader(self.process)
            self.reader_worker.moveToThread(self.reader_thread)
            self.reader_worker.line_read.connect(self.update_terminal)
            self.reader_worker.finished.connect(self.on_process_finished)
            self.reader_thread.started.connect(self.reader_worker.run)
            self.reader_thread.start(); self.btn_start.setEnabled(False); self.btn_stop.setEnabled(True)
        except Exception as e:
            self.terminal_output.appendPlainText(f"\nERROR: Failed to start process: {e}")
            self.reset_ui_state()

    @pyqtSlot()
    def stop_process(self):
        if self.process and self.process.poll() is None:
            self.btn_stop.setEnabled(False) 
            self.terminal_output.appendPlainText("\n--- SENDING STOP SIGNAL ---\n")
            self.process.terminate()
            try:
                self.process.wait(timeout=2)
            except subprocess.TimeoutExpired:
                self.process.kill()

    @pyqtSlot()
    def on_process_finished(self):
        if self.reader_thread:
            self.reader_thread.quit()
            self.reader_thread.wait()
        self.reset_ui_state()
    
    def reset_ui_state(self):
        self.process = None; self.reader_thread = None; self.reader_worker = None
        self.btn_start.setEnabled(True); self.btn_stop.setEnabled(False)
        self.terminal_output.appendPlainText("\n--- READY ---\n");
    
    @pyqtSlot(str)
    def update_terminal(self, text):
        self.parse_and_display_log(text)
        self.terminal_output.moveCursor(QTextCursor.End); self.terminal_output.insertPlainText(text)
    
    def closeEvent(self, event):
        self._save_app_config()
        if self.process: self.stop_process()
        event.accept()

    def parse_and_display_log(self, text):
        try:
            if "Color Code=" in text: self.lbl_cc.setText(text.split("Color Code=")[1].split()[0].strip())
            if "TGT=" in text: self.lbl_tg.setText(text.split("TGT=")[1].split()[0].strip())
            if "SRC=" in text: self.lbl_id.setText(text.split("SRC=")[1].split()[0].strip())
            
            if "Sync: no sync" in text:
                self.is_in_transmission = False
                self.lbl_status.setText("No Sync")
                return

            is_voice = "VC" in text and ("Sync:" in text or "VOICE" in text)
            
            if is_voice and not self.is_in_transmission:
                self.is_in_transmission = True
                self.lbl_status.setText("VOICE CALL")
                
                timestamp = text[:8] if (len(text) > 8 and text[2] == ':') else None
                if timestamp:
                    self.lbl_last_voice.setText(timestamp)
                    
                    tg_from_label = self.lbl_tg.text()
                    id_from_label = self.lbl_id.text()
                    cc_from_label = self.lbl_cc.text()
                    
                    if tg_from_label != "---" and id_from_label != "---":
                        row_pos = self.voice_event_table.rowCount()
                        self.voice_event_table.insertRow(row_pos)
                        self.voice_event_table.setItem(row_pos, 0, QTableWidgetItem(timestamp))
                        self.voice_event_table.setItem(row_pos, 1, QTableWidgetItem(tg_from_label))
                        self.voice_event_table.setItem(row_pos, 2, QTableWidgetItem(id_from_label))
                        self.voice_event_table.setItem(row_pos, 3, QTableWidgetItem(cc_from_label))
                        self.voice_event_table.scrollToBottom()
                        
                        self.check_for_alerts(tg_from_label, id_from_label)

            elif "Sync:" in text and not self.is_in_transmission:
                self.lbl_status.setText(text.strip().replace("Sync: ", ""))
            
        except Exception: pass

    def browse_for_recording_dir(self):
        path = QFileDialog.getExistingDirectory(self, "Select Recording Directory")
        if path:
            self.recorder_dir_edit.setText(path)
            if self.recording_dir and self.recording_dir in self.fs_watcher.directories():
                self.fs_watcher.removePath(self.recording_dir)
            self.recording_dir = path
            self.fs_watcher.addPath(path)
            self.update_recording_list()
    
    def update_recording_list(self):
        self.recording_list.clear()
        if not self.recording_dir or not os.path.exists(self.recording_dir): return
        
        d = QDir(self.recording_dir)
        files = d.entryList(["*.wav"], QDir.Files, QDir.Time)
        self.recording_list.addItems(files)

    def play_recording(self):
        selected_items = self.recording_list.selectedItems()
        if not selected_items: return
        
        file_path = os.path.join(self.recording_dir, selected_items[0].text())
        if os.path.exists(file_path):
            QSound.play(file_path)

    def save_history_to_csv(self):
        path, _ = QFileDialog.getSaveFileName(self, "Save CSV", "", "CSV Files (*.csv)")
        if not path:
            return
        
        try:
            with open(path, 'w', newline='', encoding='utf-8') as f:
                writer = csv.writer(f)
                
                # Write headers
                headers = [self.voice_event_table.horizontalHeaderItem(i).text() for i in range(self.voice_event_table.columnCount())]
                writer.writerow(headers)
                
                # Write data
                for row in range(self.voice_event_table.rowCount()):
                    row_data = [self.voice_event_table.item(row, col).text() for col in range(self.voice_event_table.columnCount())]
                    writer.writerow(row_data)
            
            QMessageBox.information(self, "Success", f"Event log successfully saved to {os.path.basename(path)}")
        except Exception as e:
            QMessageBox.critical(self, "Error", f"Failed to save file: {e}")

    def add_alert(self):
        alert_type = "TG" if self.alert_type_combo.currentText() == "Talkgroup (TG)" else "ID"
        value = self.alert_value_edit.text().strip()
        
        if not value:
            QMessageBox.warning(self, "Input Error", "Value cannot be empty.")
            return
            
        self.alerts.append({"type": alert_type, "value": value})
        self.update_alerts_list()
        self.alert_value_edit.clear()

    def remove_alert(self):
        current_row = self.alerts_list_widget.currentRow()
        if current_row >= 0:
            self.alerts.pop(current_row)
            self.update_alerts_list()
    
    def update_alerts_list(self):
        self.alerts_list_widget.clear()
        for alert in self.alerts:
            self.alerts_list_widget.addItem(f"[{alert['type']}] {alert['value']}")

    def play_alert_beep(self):
        def beep_thread_func():
            if WINSOUND_AVAILABLE:
                winsound.Beep(1200, 150)
                winsound.Beep(1000, 150)
            else:
                print('\a', flush=True)

        beep_thread = threading.Thread(target=beep_thread_func)
        beep_thread.start()

    def check_for_alerts(self, tg, id):
        if tg == "---" and id == "---": return
        
        for alert in self.alerts:
            if (alert['type'] == 'TG' and alert['value'] == tg) or \
               (alert['type'] == 'ID' and alert['value'] == id):
                self.play_alert_beep()
                break

def set_dark_theme(app):
    app.setStyle("Fusion"); p = QPalette(); p.setColor(QPalette.Window, QColor(53,53,53)); p.setColor(QPalette.WindowText, Qt.white); p.setColor(QPalette.Base, QColor(25,25,25)); p.setColor(QPalette.AlternateBase, QColor(53,53,53)); p.setColor(QPalette.ToolTipBase, Qt.white); p.setColor(QPalette.ToolTipText, Qt.white); p.setColor(QPalette.Text, Qt.white); p.setColor(QPalette.Button, QColor(53,53,53)); p.setColor(QPalette.ButtonText, Qt.white); p.setColor(QPalette.BrightText, Qt.red); p.setColor(QPalette.Link, QColor(42,130,218)); p.setColor(QPalette.Highlight, QColor(42,130,218)); p.setColor(QPalette.HighlightedText, Qt.black); p.setColor(QPalette.Disabled, QPalette.Text, Qt.darkGray); p.setColor(QPalette.Disabled, QPalette.ButtonText, Qt.darkGray); app.setPalette(p)

if __name__ == '__main__':
    app = QApplication(sys.argv)
    set_dark_theme(app) 
    main_window = DSDApp()
    if main_window.dsd_fme_path:
        main_window.show()
        sys.exit(app.exec_())
    else:
        sys.exit(0)
