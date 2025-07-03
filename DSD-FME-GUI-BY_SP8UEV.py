
import sys
import os
import subprocess
import json
import shlex
from PyQt5.QtWidgets import *
from PyQt5.QtGui import QFont, QPalette, QColor, QTextCursor
from PyQt5.QtCore import Qt, QThread, pyqtSignal, QObject, pyqtSlot


CONFIG_FILE = 'dsd-fme-gui-config.json'

class ProcessReader(QObject):
    """
    Worker QObject that reads output from a subprocess in a separate thread.
    """
    line_read = pyqtSignal(str)
    finished = pyqtSignal()

    def __init__(self, process):
        super().__init__()
        self.process = process

    @pyqtSlot()
    def run(self):
        """ Reads stdout of the process line by line until it terminates. """
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
        self.setWindowTitle("DSD-FME GUI by SP8UEV v8.3")
        self.setGeometry(100, 100, 1000, 800)
        
        self.widgets = {}
        self.inverse_widgets = {} # For radio buttons
        self.dsd_fme_path = self._load_config_or_prompt()
        
        if self.dsd_fme_path:
            self._init_ui()
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

    def _init_ui(self):
        central_widget = QWidget(); self.setCentralWidget(central_widget)
        main_layout = QVBoxLayout(central_widget)
        main_splitter = QSplitter(Qt.Vertical); main_layout.addWidget(main_splitter)
        
        options_container_widget = QWidget()
        scroll_area = QScrollArea(); scroll_area.setWidgetResizable(True); scroll_area.setWidget(options_container_widget)
        container_layout = QVBoxLayout(options_container_widget)

        tabs = QTabWidget(); container_layout.addWidget(tabs)
        tabs.addTab(self._create_io_tab(), "Input / Output"); tabs.addTab(self._create_decoder_tab(), "Decoder Modes")
        tabs.addTab(self._create_advanced_tab(), "Advanced & Crypto"); tabs.addTab(self._create_trunking_tab(), "Trunking")
        
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
        terminal_group = QGroupBox("Terminal Log"); terminal_layout = QVBoxLayout(terminal_group)
        self.terminal_output = QPlainTextEdit(); self.terminal_output.setReadOnly(True); self.terminal_output.setFont(QFont("Consolas", 10))
        self.terminal_output.setStyleSheet("background-color: black; color: lightgreen;"); terminal_layout.addWidget(self.terminal_output)
        terminal_main_layout.addWidget(terminal_group)
        
        main_splitter.addWidget(scroll_area); main_splitter.addWidget(terminal_container)
        main_splitter.setSizes([350, 450])

        if not self.dsd_fme_path:
            self.btn_start.setEnabled(False); self.statusBar().showMessage("DSD-FME path not set!")

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

    @pyqtSlot()
    def build_command(self):
        if not self.dsd_fme_path: self.cmd_preview.setText("ERROR: DSD-FME path not set!"); return []
        command = [self.dsd_fme_path]
        in_type = self.widgets["-i_type"].currentText()
        if in_type == "tcp": val = self.widgets["-i_tcp"].text(); command.extend(["-i", f"tcp:{val}" if val else "tcp"])
        elif in_type == "wav": val = self.widgets["-i_wav"].text(); command.extend(["-i", val]) if val else None
        else: command.extend(["-i", in_type])
        out_type = self.widgets["-o_type"].currentText()
        if out_type != "Windows Default": command.extend(["-o", out_type.lower()])
        for flag in ["-s","-g","-V","-w","-6","-7","-d","-c","-b","-1","-H","-K","-C","-G","-U"]:
            if self.widgets[flag].text(): command.extend([flag, self.widgets[flag].text()])
        for flag in ["-P","-l","-xx","-xr","-xd","-xz","-N","-Z","-4","-0","-3","-F","-T","-Y","-p","-E","-e"]:
            if flag in self.widgets and self.widgets[flag].isChecked(): command.append(flag)
        for btn, flag in self.inverse_widgets.items():
            if btn.isChecked(): command.append(flag)
        
      
        final_command = [item for item in command if item is not None]
        self.cmd_preview.setText(subprocess.list2cmdline(final_command))
        return final_command

    @pyqtSlot()
    def start_process(self):
        if self.process: return
        command = self.build_command()
        if not command: QMessageBox.critical(self, "Error", "Cannot start: DSD-FME path is not set or command is empty."); return
        self.terminal_output.clear(); self.terminal_output.appendPlainText(f"$ {subprocess.list2cmdline(command)}\n\n")
        try:
            self.process = subprocess.Popen(
                command, stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                stdin=subprocess.DEVNULL, # This is a key fix for stability
                universal_newlines=True, encoding='utf-8', errors='ignore',
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
            self.btn_stop.setEnabled(False) # Prevent double clicks
            self.terminal_output.appendPlainText("\n--- SENDING STOP SIGNAL ---\n")
        
            self.process.terminate()
         
            try:
                self.process.wait(timeout=2)
            except subprocess.TimeoutExpired:
                self.process.kill()

    @pyqtSlot()
    def on_process_finished(self):
        """ This slot is the single, reliable point of cleanup. """
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
        self.terminal_output.moveCursor(QTextCursor.End); self.terminal_output.insertPlainText(text)
    
    def closeEvent(self, event):
        if self.process: self.stop_process()
        event.accept()

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
