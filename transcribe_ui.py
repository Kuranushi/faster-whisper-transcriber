"""
Faster-Whisper Transcriber – desktop GUI for local speech transcription
(faster-whisper) and translation (Ollama), built on PySide6.

Entry point.  All logic is split across:
  config.py   – persistent settings
  models.py   – model discovery / download / validation
  data.py     – language lists, subtitle I/O, Ollama helpers, validation
  skins.py    – QSS theming, BackgroundWidget, TaskbarProgress
  workers.py  – QThread workers (TranscribeWorker, TranslateWorker)
"""
import sys, os, time

_HERE = os.path.dirname(os.path.abspath(__file__))
if _HERE not in sys.path:
    sys.path.insert(0, _HERE)

import logging
logging.getLogger("huggingface_hub").setLevel(logging.ERROR)

from PySide6.QtCore    import Qt, QTimer
from PySide6.QtGui     import QIcon, QDragEnterEvent, QDropEvent, QCloseEvent
from PySide6.QtWidgets import (
    QApplication, QMainWindow, QWidget, QVBoxLayout, QHBoxLayout,
    QGridLayout, QLabel, QLineEdit, QPushButton, QComboBox, QCheckBox,
    QScrollArea, QSplitter, QTextEdit, QProgressBar, QSlider, QFileDialog,
    QMessageBox, QFrame, QStackedWidget,
)

from config  import SCRIPT_DIR, DEFAULT_CONFIG, load_config, save_config
from models  import (
    scan_local_models, build_model_choices, is_dl_choice, dl_model_name,
    resolve_model, validate_model, HF_REPOS,
)
from data    import (
    LANGUAGES, LANG_DISPLAY, LANG_CODE,
    TRANSLATE_TARGETS, TRANSLATE_TARGETS_DEF, ENGLISH_TARGET_DISPLAY,
    AUTO_DETECT_DISPLAY, sorted_by_freq,
    tgt_code, tgt_prompt,
    FORMATS, MEDIA_EXTS, SUBTITLE_EXTS,
    ollama_models, sanitize_filename,
    validate_media, validate_subtitle, validate_output_dir, validate_ollama,
)
from skins   import SKINS, SKIN_NAMES, build_qss, BackgroundWidget, TaskbarProgress
from workers import TranscribeWorker, TranslateWorker

MODELS_DIR = os.path.join(SCRIPT_DIR, "Faster-Whisper-Models")
os.makedirs(MODELS_DIR, exist_ok=True)

# ══════════════════════════════════════════════════════════════════════════════
# Small UI helpers
# ══════════════════════════════════════════════════════════════════════════════
def make_row():
    w = QWidget()
    lay = QHBoxLayout(w)
    lay.setContentsMargins(0, 2, 0, 2)
    lay.setSpacing(8)
    return w, lay

def section_label(text, tooltip=None):
    lbl = QLabel(text)
    lbl.setObjectName("sectionLabel")
    if tooltip:
        lbl.setToolTip(tooltip)
    return lbl

def hint_label(text, object_name="hintLabel"):
    lbl = QLabel(text)
    lbl.setObjectName(object_name)
    lbl.setWordWrap(True)
    return lbl

# ══════════════════════════════════════════════════════════════════════════════
# Main window
# ══════════════════════════════════════════════════════════════════════════════
class MainWindow(QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("Faster-Whisper Transcriber")
        self.resize(1180, 860)
        self.setMinimumSize(760, 560)
        self.setAcceptDrops(True)

        icon_path = os.path.join(SCRIPT_DIR, "icon.ico")
        if os.path.exists(icon_path):
            self.setWindowIcon(QIcon(icon_path))

        self.cfg = load_config()
        self.models_dir_override = None
        self.input_paths = []
        self.t_input_paths = []
        self.tr_worker   = None
        self.tl_worker   = None
        self._paused     = False   # Transcribe page pause/resume toggle state
        self._t_paused   = False   # Translate page pause/resume toggle state
        self.current_skin_name = self.cfg.get("skin", "Sakura Mist")

        self._build_ui()
        self._apply_qss()
        self._apply_config()
        self._scan_models()
        self._refresh_ollama()

        self.taskbar = None
        QTimer.singleShot(0, self._init_taskbar)
        QTimer.singleShot(0, self._init_splitters)

    # ── Layout shell ─────────────────────────────────────────────────────────
    _SIDEBAR_ICON_THRESHOLD = 100
    _NAV_DEFS = [("🎙", "Transcribe"), ("🌐", "Translate"), ("⚙️", "Settings")]

    def _build_ui(self):
        central = QWidget()
        self.setCentralWidget(central)
        outer = QHBoxLayout(central)
        outer.setContentsMargins(0, 0, 0, 0)
        outer.setSpacing(0)

        # ── Sidebar ──────────────────────────────────────────────────────────
        self.sidebar = QWidget()
        self.sidebar.setObjectName("sidebar")
        self.sidebar.setMinimumWidth(52)
        self.sidebar.setMaximumWidth(320)
        sb_layout = QVBoxLayout(self.sidebar)
        sb_layout.setContentsMargins(8, 16, 8, 16)
        sb_layout.setSpacing(4)

        self.app_title = QLabel("FW\nTranscriber")
        self.app_title.setObjectName("appTitle")
        sb_layout.addWidget(self.app_title)
        sb_layout.addSpacing(10)

        self.nav_buttons = []
        for icon, label in self._NAV_DEFS[:-1]:
            btn = QPushButton(f"  {icon}  {label}")
            btn.setObjectName("navItem")
            btn.setCheckable(True)
            btn.setCursor(Qt.PointingHandCursor)
            sb_layout.addWidget(btn)
            self.nav_buttons.append(btn)

        sb_layout.addStretch(1)

        icon, label = self._NAV_DEFS[-1]
        settings_btn = QPushButton(f"  {icon}  {label}")
        settings_btn.setObjectName("navItem")
        settings_btn.setCheckable(True)
        settings_btn.setCursor(Qt.PointingHandCursor)
        sb_layout.addWidget(settings_btn)
        self.nav_buttons.append(settings_btn)

        for i, btn in enumerate(self.nav_buttons):
            btn.clicked.connect(lambda checked, idx=i: self._switch_page(idx))

        # ── Horizontal splitter: sidebar | content ────────────────────────
        self.h_splitter = QSplitter(Qt.Horizontal)
        self.h_splitter.setHandleWidth(5)
        self.h_splitter.addWidget(self.sidebar)

        self.bg_widget = BackgroundWidget()
        bg_layout = QVBoxLayout(self.bg_widget)
        bg_layout.setContentsMargins(0, 0, 0, 0)
        self.stack = QStackedWidget()
        # Transparency for this and the page/scroll-area chain beneath it
        # is handled centrally in skins.build_qss() (QWidget#page,
        # QStackedWidget, QScrollArea rules) so it stays part of the
        # normal stylesheet cascade - see skins.py for why that matters.
        bg_layout.addWidget(self.stack)
        self.h_splitter.addWidget(self.bg_widget)

        self.h_splitter.setCollapsible(0, False)
        self.h_splitter.setCollapsible(1, False)
        self.h_splitter.setStretchFactor(0, 0)
        self.h_splitter.setStretchFactor(1, 1)

        outer.addWidget(self.h_splitter)

        self.transcribe_page = self._build_transcribe_page()
        self.translate_page  = self._build_translate_page()
        self.settings_page   = self._build_settings_page()
        self.stack.addWidget(self.transcribe_page)
        self.stack.addWidget(self.translate_page)
        self.stack.addWidget(self.settings_page)

        self.h_splitter.splitterMoved.connect(self._on_sidebar_resize)
        self._switch_page(0)

    def _on_sidebar_resize(self, pos, index):
        if index != 1:
            return
        self._apply_sidebar_mode(self.sidebar.width())

    def _apply_sidebar_mode(self, width):
        compact = width < self._SIDEBAR_ICON_THRESHOLD
        self.app_title.setText("FW" if compact else "FW\nTranscriber")
        for btn, (icon, label) in zip(self.nav_buttons, self._NAV_DEFS):
            if compact:
                btn.setText(f" {icon} ")
                btn.setToolTip(label)
            else:
                btn.setText(f"  {icon}  {label}")
                btn.setToolTip("")

    def _switch_page(self, idx):
        for i, btn in enumerate(self.nav_buttons):
            btn.setChecked(i == idx)
        self.stack.setCurrentIndex(idx)

    # ── Drag & drop ──────────────────────────────────────────────────────────
    def dragEnterEvent(self, event: QDragEnterEvent):
        if event.mimeData().hasUrls():
            event.acceptProposedAction()

    def dropEvent(self, event: QDropEvent):
        urls = event.mimeData().urls()
        if not urls:
            return
        idx = self.stack.currentIndex()
        if idx == 0:
            self._set_inputs([u.toLocalFile() for u in urls])
        elif idx == 1:
            self._set_t_inputs([u.toLocalFile() for u in urls])

    # ── Taskbar ──────────────────────────────────────────────────────────────
    def _init_taskbar(self):
        try:
            hwnd = int(self.winId())
            self.taskbar = TaskbarProgress(hwnd)
            if sys.platform == "win32" and not self.taskbar._tb:
                if self.taskbar._init_error:
                    self._log(f"[WARN] Taskbar progress unavailable: {self.taskbar._init_error}\n")
        except Exception:
            self.taskbar = TaskbarProgress(0)

    def _init_splitters(self):
        saved_sb = self.cfg.get("sidebar_width", 200)
        total_w  = self.h_splitter.width()
        if total_w > 0:
            sb_w = max(52, min(saved_sb, 320))
            self.h_splitter.setSizes([sb_w, max(total_w - sb_w, 400)])
            self._apply_sidebar_mode(sb_w)

        for splitter, cfg_key, ratio in (
                (self.tr_splitter, "splitter_tr", 0.78),
                (self.tl_splitter, "splitter_tl", 0.65)):
            saved = self.cfg.get(cfg_key)
            total = splitter.height()
            if saved and isinstance(saved, list) and len(saved) == 2 and sum(saved) > 0:
                try:
                    splitter.setSizes(saved)
                    continue
                except Exception:
                    pass
            top    = max(int(total * ratio), 200)
            bottom = max(total - top, 80)
            splitter.setSizes([top, bottom])

    # ── Transcribe page ──────────────────────────────────────────────────────
    def _build_transcribe_page(self):
        page = QWidget(); page.setObjectName("page")
        outer = QVBoxLayout(page); outer.setContentsMargins(0, 0, 0, 0)

        splitter = QSplitter(Qt.Vertical)
        self.tr_splitter = splitter
        outer.addWidget(splitter)

        form = QWidget(); form.setObjectName("page")
        form_layout = QVBoxLayout(form)
        form_layout.setContentsMargins(20, 16, 20, 16)
        form_layout.setSpacing(6)

        scroll = QScrollArea(); scroll.setWidgetResizable(True); scroll.setWidget(form)
        splitter.addWidget(scroll)

        # Input file
        form_layout.addWidget(section_label(
            "INPUT FILE",
            "Audio or video file to transcribe.\n"
            "Supported: mp3, mp4, wav, m4a, aac, flac, ogg, mkv, mov, avi, "
            "webm, wma, opus, oga, ts\nDrag & drop anywhere in the window."))
        row, lay = make_row()
        self.input_edit = QLineEdit()
        self.input_edit.setPlaceholderText(
            "Drag & drop or Browse...  ( mp3 / mp4 / wav / m4a / aac / flac / "
            "ogg / mkv / mov / avi / webm / wma / opus / ts )")
        lay.addWidget(self.input_edit, stretch=1)
        browse_input_btn = QPushButton("Browse...")
        browse_input_btn.setObjectName("secondaryBtn")
        browse_input_btn.clicked.connect(self._browse_input)
        lay.addWidget(browse_input_btn)
        form_layout.addWidget(row)

        # Model
        form_layout.addWidget(section_label(
            "FASTER-WHISPER MODEL",
            "Only faster-whisper (CTranslate2) format is supported.\n"
            "[local] installed locally   [↓] will download from HuggingFace"))
        row, lay = make_row()
        self.model_combo = QComboBox()
        self.model_combo.currentTextChanged.connect(self._on_model_pick)
        lay.addWidget(self.model_combo, stretch=1)
        for label, slot in (("Refresh", self._scan_models),
                             ("Open Folder", self._open_models_folder),
                             ("Change...", self._change_models_dir)):
            btn = QPushButton(label)
            btn.setObjectName("secondaryBtn")
            if label == "Refresh": btn.setMinimumWidth(80)
            btn.clicked.connect(slot)
            lay.addWidget(btn)
        form_layout.addWidget(row)

        self.models_dir_label      = hint_label(f"  {self._models_dir()}")
        self.download_notice_label = hint_label("", "warnLabel")
        form_layout.addWidget(self.models_dir_label)
        form_layout.addWidget(self.download_notice_label)

        # Source language
        form_layout.addWidget(section_label(
            "SOURCE LANGUAGE",
            "Spoken language in the audio.\n'Auto Detect' is slightly slower."))
        row, lay = make_row()
        self.lang_combo = QComboBox()
        self.lang_combo.addItems(LANG_DISPLAY)
        lay.addWidget(self.lang_combo)
        lay.addStretch(1)
        form_layout.addWidget(row)

        # Output
        form_layout.addWidget(section_label("OUTPUT", "Where to save subtitle files."))
        row, lay = make_row()
        self.outdir_edit = QLineEdit(); self.outdir_edit.setPlaceholderText("Output directory")
        lay.addWidget(self.outdir_edit, stretch=1)
        browse_outdir_btn = QPushButton("Browse...")
        browse_outdir_btn.setObjectName("secondaryBtn")
        browse_outdir_btn.clicked.connect(self._browse_outdir)
        lay.addWidget(browse_outdir_btn)
        form_layout.addWidget(row)

        self.samedir_check = QCheckBox("Save to same folder as input file")
        self.samedir_check.setChecked(True)
        self.samedir_check.toggled.connect(self._toggle_samedir)
        form_layout.addWidget(self.samedir_check)

        row, lay = make_row()
        lay.addWidget(QLabel("Filename:"))
        self.filename_edit = QLineEdit()
        self.filename_edit.setPlaceholderText("output filename")
        self.filename_edit.setToolTip(
            "Base filename (without extension).\nFiles saved:\n"
            "  <name>.srt\n  <name>.chs.srt\n  <name>.chs.bilingual.srt")
        lay.addWidget(self.filename_edit, stretch=1)
        lay.addWidget(QLabel("Format:"))
        self.fmt_combo = QComboBox(); self.fmt_combo.addItems(FORMATS)
        lay.addWidget(self.fmt_combo)
        form_layout.addWidget(row)

        # Transcription options
        form_layout.addWidget(section_label("TRANSCRIPTION OPTIONS"))
        row, lay = make_row()
        self.vad_check = QCheckBox("VAD filter")
        self.vad_check.setChecked(True)
        self.vad_check.setToolTip(
            "Remove silent segments before transcription.\n"
            "Reduces hallucinated text. Recommended.")
        lay.addWidget(self.vad_check)
        self.halluc_check = QCheckBox("Reduce hallucinations")
        self.halluc_check.setChecked(True)
        self.halluc_check.setToolTip(
            "Disables condition_on_previous_text.\n"
            "Reduces repeated text in long recordings.")
        lay.addWidget(self.halluc_check)
        lay.addStretch(1)
        form_layout.addWidget(row)

        divider = QFrame(); divider.setFrameShape(QFrame.HLine)
        divider.setStyleSheet("background: transparent; border-top: 1px solid palette(mid);")
        form_layout.addWidget(divider)

        # Translation
        form_layout.addWidget(section_label(
            "TRANSLATION  (via Ollama)",
            "Translate subtitles using a local Ollama LLM.\n"
            "Original file is always saved first."))
        row, lay = make_row()
        self.translate_check = QCheckBox("Enable translation after transcription")
        self.translate_check.toggled.connect(self._toggle_translate)
        lay.addWidget(self.translate_check)
        self.bilingual_check = QCheckBox("Also save bilingual file")
        self.bilingual_check.setEnabled(False)
        lay.addWidget(self.bilingual_check)
        lay.addStretch(1)
        form_layout.addWidget(row)

        row, lay = make_row()
        lay.addWidget(QLabel("Translate to:"))
        self.tgt_combo = QComboBox()
        self.tgt_combo.addItems(TRANSLATE_TARGETS)
        self.tgt_combo.setEnabled(False)
        self.tgt_combo.currentTextChanged.connect(self._on_tgt_change)
        lay.addWidget(self.tgt_combo)
        lay.addSpacing(16)
        lay.addWidget(QLabel("Ollama model:"))
        self.ollama_combo = QComboBox()
        self.ollama_combo.addItem("detecting...")
        self.ollama_combo.setEnabled(False)
        lay.addWidget(self.ollama_combo, stretch=1)
        refresh_ollama_btn = QPushButton("Refresh")
        refresh_ollama_btn.setObjectName("secondaryBtn")
        refresh_ollama_btn.setMinimumWidth(80)
        refresh_ollama_btn.clicked.connect(self._refresh_ollama)
        lay.addWidget(refresh_ollama_btn)
        form_layout.addWidget(row)

        row, lay = make_row()
        self.whisper_tr_check = QCheckBox(
            "Use Faster-Whisper built-in translation  (English only)")
        self.whisper_tr_check.setEnabled(False)
        self.whisper_tr_check.setToolTip(
            "Only available when target language is English.\n"
            "Transcribes + translates in one pass - no Ollama needed.")
        self.whisper_tr_check.toggled.connect(self._on_whisper_tr_toggle)
        lay.addWidget(self.whisper_tr_check)
        lay.addStretch(1)
        form_layout.addWidget(row)

        divider2 = QFrame(); divider2.setFrameShape(QFrame.HLine)
        divider2.setStyleSheet("background: transparent; border-top: 1px solid palette(mid);")
        form_layout.addWidget(divider2)

        # Controls
        row, lay = make_row()
        self.start_btn = QPushButton("▶  Start")
        self.start_btn.setObjectName("startBtn")
        self.start_btn.clicked.connect(self._start_transcribe)
        lay.addWidget(self.start_btn)
        self.pause_btn = QPushButton("⏸  Pause")
        self.pause_btn.setObjectName("pauseBtn")
        self.pause_btn.setEnabled(False)
        self.pause_btn.setToolTip(
            "Freeze the current step in place - nothing already produced is lost.")
        self.pause_btn.clicked.connect(self._toggle_pause)
        lay.addWidget(self.pause_btn)
        self.stop_btn = QPushButton("■  Stop")
        self.stop_btn.setObjectName("stopBtn")
        self.stop_btn.setEnabled(False)
        self.stop_btn.setToolTip(
            "Stop only the current step (this file's transcription or translation).\n"
            "Whatever was already produced is kept, and the queue continues normally.")
        self.stop_btn.clicked.connect(self._stop_current)
        lay.addWidget(self.stop_btn)
        self.stop_all_btn = QPushButton("⛔  Stop All")
        self.stop_all_btn.setObjectName("stopAllBtn")
        self.stop_all_btn.setEnabled(False)
        self.stop_all_btn.setToolTip(
            "Abort the entire queue immediately - no further files or steps will run.")
        self.stop_all_btn.clicked.connect(self._stop_all)
        lay.addWidget(self.stop_all_btn)
        self.status_label = QLabel("")
        self.status_label.setObjectName("hintLabel")
        lay.addWidget(self.status_label)
        lay.addStretch(1)
        form_layout.addWidget(row)

        self.progress_bar = QProgressBar(); self.progress_bar.setRange(0, 1000)
        form_layout.addWidget(self.progress_bar)
        row, lay = make_row()
        self.pct_label     = hint_label("0%")
        self.elapsed_label = hint_label("Elapsed: -")
        self.eta_label     = hint_label("ETA: -")
        for w in (self.pct_label, self.elapsed_label, self.eta_label):
            lay.addWidget(w)
        lay.addStretch(1)
        form_layout.addWidget(row)
        form_layout.addStretch(1)

        # Log pane
        log_container = QWidget()
        log_lay = QVBoxLayout(log_container)
        log_lay.setContentsMargins(0, 0, 0, 0); log_lay.setSpacing(0)
        log_header = QLabel("  LOG   (drag to resize)")
        log_header.setObjectName("logHeader")
        log_lay.addWidget(log_header)
        self.log_view = QTextEdit()
        self.log_view.setObjectName("logView"); self.log_view.setReadOnly(True)
        log_lay.addWidget(self.log_view)
        splitter.addWidget(log_container)
        splitter.setStretchFactor(0, 3); splitter.setStretchFactor(1, 1)

        self._elapsed_timer = QTimer(self)
        self._elapsed_timer.timeout.connect(self._tick_elapsed)
        self._start_time = None
        # Track which phase is running: "transcribe" or "translate"
        self._tr_phase = "transcribe"
        return page

    # ── Translate page ───────────────────────────────────────────────────────
    def _build_translate_page(self):
        page = QWidget(); page.setObjectName("page")
        outer = QVBoxLayout(page); outer.setContentsMargins(0, 0, 0, 0)

        splitter = QSplitter(Qt.Vertical)
        self.tl_splitter = splitter
        outer.addWidget(splitter)

        form = QWidget(); form.setObjectName("page")
        form_layout = QVBoxLayout(form)
        form_layout.setContentsMargins(20, 16, 20, 16)
        form_layout.setSpacing(6)

        scroll = QScrollArea(); scroll.setWidgetResizable(True); scroll.setWidget(form)
        splitter.addWidget(scroll)

        form_layout.addWidget(hint_label(
            "Translate an existing subtitle file with a local Ollama model."))

        form_layout.addWidget(section_label(
            "SUBTITLE FILE(S)",
            "Supported: .srt .vtt .txt\n"
            "Note: video/audio files are NOT accepted here.\n"
            "Generate subtitles in the Transcribe tab first.\n"
            "Select or drop multiple files to translate them as a batch."))
        row, lay = make_row()
        self.t_input_edit = QLineEdit()
        self.t_input_edit.setPlaceholderText(
            "Drag & drop or Browse...  ( .srt / .vtt / .txt, multiple allowed )")
        lay.addWidget(self.t_input_edit, stretch=1)
        t_browse_btn = QPushButton("Browse...")
        t_browse_btn.setObjectName("secondaryBtn")
        t_browse_btn.clicked.connect(self._t_browse_input)
        lay.addWidget(t_browse_btn)
        form_layout.addWidget(row)

        form_layout.addWidget(section_label("TRANSLATION SETTINGS"))
        row, lay = make_row()
        lay.addWidget(QLabel("Translate to:"))
        self.t_tgt_combo = QComboBox(); self.t_tgt_combo.addItems(TRANSLATE_TARGETS)
        lay.addWidget(self.t_tgt_combo)
        lay.addSpacing(16)
        lay.addWidget(QLabel("Ollama model:"))
        self.t_ollama_combo = QComboBox(); self.t_ollama_combo.addItem("detecting...")
        lay.addWidget(self.t_ollama_combo, stretch=1)
        t_refresh_ollama_btn = QPushButton("Refresh")
        t_refresh_ollama_btn.setObjectName("secondaryBtn")
        t_refresh_ollama_btn.setMinimumWidth(80)
        t_refresh_ollama_btn.clicked.connect(self._refresh_ollama)
        lay.addWidget(t_refresh_ollama_btn)
        form_layout.addWidget(row)

        self.t_bilingual_check = QCheckBox(
            "Output bilingual subtitles  (original + translation on each line)")
        form_layout.addWidget(self.t_bilingual_check)

        form_layout.addWidget(section_label("OUTPUT"))
        row, lay = make_row()
        self.t_outdir_edit = QLineEdit()
        self.t_outdir_edit.setPlaceholderText("Output directory")
        lay.addWidget(self.t_outdir_edit, stretch=1)
        t_out_browse_btn = QPushButton("Browse...")
        t_out_browse_btn.setObjectName("secondaryBtn")
        t_out_browse_btn.clicked.connect(self._t_browse_outdir)
        lay.addWidget(t_out_browse_btn)
        form_layout.addWidget(row)

        self.t_samedir_check = QCheckBox("Save to same folder as input file")
        self.t_samedir_check.setChecked(True)
        self.t_samedir_check.toggled.connect(self._t_toggle_samedir)
        form_layout.addWidget(self.t_samedir_check)

        row, lay = make_row()
        lay.addWidget(QLabel("Filename:"))
        self.t_filename_edit = QLineEdit()
        self.t_filename_edit.setPlaceholderText("output filename")
        lay.addWidget(self.t_filename_edit, stretch=1)
        lay.addWidget(QLabel("Format:"))
        self.t_fmt_combo = QComboBox(); self.t_fmt_combo.addItems(FORMATS)
        lay.addWidget(self.t_fmt_combo)
        form_layout.addWidget(row)

        divider = QFrame(); divider.setFrameShape(QFrame.HLine)
        divider.setStyleSheet("background: transparent; border-top: 1px solid palette(mid);")
        form_layout.addWidget(divider)

        row, lay = make_row()
        self.t_start_btn = QPushButton("▶  Translate")
        self.t_start_btn.setObjectName("startBtn")
        self.t_start_btn.clicked.connect(self._start_translate)
        lay.addWidget(self.t_start_btn)
        self.t_pause_btn = QPushButton("⏸  Pause")
        self.t_pause_btn.setObjectName("pauseBtn")
        self.t_pause_btn.setEnabled(False)
        self.t_pause_btn.setToolTip(
            "Freeze translation in place - nothing already produced is lost.")
        self.t_pause_btn.clicked.connect(self._t_toggle_pause)
        lay.addWidget(self.t_pause_btn)
        self.t_stop_btn = QPushButton("■  Stop")
        self.t_stop_btn.setObjectName("stopBtn")
        self.t_stop_btn.setEnabled(False)
        self.t_stop_btn.setToolTip(
            "Stop only the current file's translation.\n"
            "Whatever was already produced is kept, and the queue continues normally.")
        self.t_stop_btn.clicked.connect(self._t_stop)
        lay.addWidget(self.t_stop_btn)
        self.t_stop_all_btn = QPushButton("⛔  Stop All")
        self.t_stop_all_btn.setObjectName("stopAllBtn")
        self.t_stop_all_btn.setEnabled(False)
        self.t_stop_all_btn.setToolTip(
            "Abort the entire queue immediately - no further files will run.")
        self.t_stop_all_btn.clicked.connect(self._t_stop_all)
        lay.addWidget(self.t_stop_all_btn)
        self.t_status_label = hint_label("")
        lay.addWidget(self.t_status_label)
        lay.addStretch(1)
        form_layout.addWidget(row)

        self.t_progress_bar = QProgressBar(); self.t_progress_bar.setRange(0, 1000)
        form_layout.addWidget(self.t_progress_bar)
        row, lay = make_row()
        self.t_pct_label     = hint_label("0%")
        self.t_elapsed_label = hint_label("Elapsed: -")
        self.t_eta_label     = hint_label("ETA: -")
        for w in (self.t_pct_label, self.t_elapsed_label, self.t_eta_label):
            lay.addWidget(w)
        lay.addStretch(1)
        form_layout.addWidget(row)
        form_layout.addStretch(1)

        log_container = QWidget()
        log_lay = QVBoxLayout(log_container)
        log_lay.setContentsMargins(0, 0, 0, 0); log_lay.setSpacing(0)
        log_header = QLabel("  LOG   (drag to resize)")
        log_header.setObjectName("logHeader")
        log_lay.addWidget(log_header)
        self.t_log_view = QTextEdit()
        self.t_log_view.setObjectName("logView"); self.t_log_view.setReadOnly(True)
        log_lay.addWidget(self.t_log_view)
        splitter.addWidget(log_container)
        splitter.setStretchFactor(0, 3); splitter.setStretchFactor(1, 1)

        self._t_elapsed_timer = QTimer(self)
        self._t_elapsed_timer.timeout.connect(self._t_tick_elapsed)
        self._t_start_time = None
        return page

    # ── Settings page ────────────────────────────────────────────────────────
    def _build_settings_page(self):
        page = QWidget(); page.setObjectName("page")
        outer = QVBoxLayout(page); outer.setContentsMargins(0, 0, 0, 0)

        form = QWidget(); form.setObjectName("page")
        form_layout = QVBoxLayout(form)
        form_layout.setContentsMargins(20, 16, 20, 16)
        form_layout.setSpacing(8)

        scroll = QScrollArea(); scroll.setWidgetResizable(True); scroll.setWidget(form)
        outer.addWidget(scroll)

        form_layout.addWidget(section_label(
            "THEME  /  SKIN",
            "Changes take effect immediately.\n"
            "Fluent Glass shows a built-in pastel gradient by default - "
            "pick your own background image below for a fully custom look."))

        grid_widget = QWidget()
        grid = QGridLayout(grid_widget); grid.setSpacing(12)
        self.skin_swatches = {}
        for i, name in enumerate(SKIN_NAMES):
            sk = SKINS[name]
            card = QFrame()
            card.setCursor(Qt.PointingHandCursor)
            card.setFixedHeight(70)
            card.setStyleSheet(
                f"QFrame {{ background: {sk['bg']}; border: 2px solid {sk['border']}; "
                f"border-radius: 10px; }}")
            card_layout = QVBoxLayout(card)
            card_layout.setContentsMargins(10, 8, 10, 8)
            preview_row = QHBoxLayout()
            for key in ("accent", "accent2", "danger"):
                dot = QFrame(); dot.setFixedSize(16, 16)
                dot.setStyleSheet(
                    f"background: {sk[key]}; border-radius: 8px; border: none;")
                preview_row.addWidget(dot)
            preview_row.addStretch(1)
            card_layout.addLayout(preview_row)
            name_lbl = QLabel(name)
            name_lbl.setStyleSheet(
                f"color: {sk['text']}; font-weight: 600; border: none; background: transparent;")
            card_layout.addWidget(name_lbl)
            card.mousePressEvent = (lambda e, n=name: self._pick_skin(n))
            self.skin_swatches[name] = card
            grid.addWidget(card, i // 3, i % 3)
        form_layout.addWidget(grid_widget)

        divider = QFrame(); divider.setFrameShape(QFrame.HLine)
        divider.setStyleSheet("background: transparent; border-top: 1px solid palette(mid);")
        form_layout.addWidget(divider)

        form_layout.addWidget(section_label(
            "BACKGROUND IMAGE",
            "Set a custom background image for the main area.\n"
            "Works best with the Fluent Glass skin."))
        row, lay = make_row()
        self.bg_path_edit = QLineEdit()
        self.bg_path_edit.setPlaceholderText("No image selected")
        self.bg_path_edit.setReadOnly(True)
        lay.addWidget(self.bg_path_edit, stretch=1)
        choose_bg_btn = QPushButton("Choose image...")
        choose_bg_btn.setObjectName("secondaryBtn")
        choose_bg_btn.clicked.connect(self._browse_bg)
        lay.addWidget(choose_bg_btn)
        remove_bg_btn = QPushButton("Remove")
        remove_bg_btn.setObjectName("dangerBtn")
        remove_bg_btn.clicked.connect(self._remove_bg)
        lay.addWidget(remove_bg_btn)
        form_layout.addWidget(row)

        row, lay = make_row()
        lay.addWidget(QLabel("Overlay opacity:"))
        self.opacity_slider = QSlider(Qt.Horizontal)
        self.opacity_slider.setRange(0, 100)
        self.opacity_slider.setValue(72)
        self.opacity_slider.setFixedWidth(220)
        self.opacity_slider.valueChanged.connect(self._on_opacity_change)
        lay.addWidget(self.opacity_slider)
        self.opacity_value_label = hint_label("72%")
        lay.addWidget(self.opacity_value_label)
        lay.addStretch(1)
        form_layout.addWidget(row)

        form_layout.addStretch(1)
        return page

    # ── Model management ─────────────────────────────────────────────────────
    def _models_dir(self):
        return self.models_dir_override or MODELS_DIR

    def _scan_models(self):
        d = self._models_dir()
        local   = scan_local_models(d)
        choices = build_model_choices(local)
        self.model_combo.blockSignals(True)
        self.model_combo.clear()
        for choice in choices:
            self.model_combo.addItem(choice)
            idx = self.model_combo.count() - 1
            if is_dl_choice(choice):
                from PySide6.QtGui import QColor
                self.model_combo.setItemData(idx, QColor("#aaaaaa"), Qt.ForegroundRole)
        self.model_combo.blockSignals(False)
        first = next((c for c in choices if not is_dl_choice(c)), choices[0] if choices else "")
        if first:
            self.model_combo.setCurrentText(first)
        self._on_model_pick(self.model_combo.currentText())
        self.models_dir_label.setText(f"  {d}")
        dl_count    = sum(1 for c in choices if is_dl_choice(c))
        ready_count = len(choices) - dl_count
        self._log(f"Models: {ready_count} ready, {dl_count} not downloaded.\n")

    def _on_model_pick(self, choice):
        if is_dl_choice(choice):
            name = dl_model_name(choice)
            repo = HF_REPOS.get(name, f"Systran/faster-whisper-{name}")
            self.download_notice_label.setText(
                f"  ↓ Will download from HuggingFace: {repo}  →  {self._models_dir()}")
        else:
            self.download_notice_label.setText("")

    def _open_models_folder(self):
        d = self._models_dir()
        if sys.platform == "win32":
            os.startfile(d)
        else:
            os.system(f'xdg-open "{d}"')

    def _change_models_dir(self):
        d = QFileDialog.getExistingDirectory(self, "Select Whisper models folder")
        if d:
            self.models_dir_override = d
            self._scan_models()

    def _refresh_ollama(self):
        models = ollama_models()
        for combo in (self.ollama_combo, self.t_ollama_combo):
            combo.blockSignals(True); combo.clear()
        if models:
            for combo in (self.ollama_combo, self.t_ollama_combo):
                combo.addItems(models); combo.setCurrentIndex(0)
            self._log(f"Ollama models: {', '.join(models)}\n")
        else:
            for combo in (self.ollama_combo, self.t_ollama_combo):
                combo.addItem("(not found)")
            self._log("[WARN] Ollama not detected at localhost:11434\n")
        for combo in (self.ollama_combo, self.t_ollama_combo):
            combo.blockSignals(False)

    # ── Language list helpers ─────────────────────────────────────────────────
    def _rebuild_lang_combo(self):
        """Repopulate lang_combo sorted by usage frequency."""
        freq = self.cfg.get("lang_freq", {})
        ordered = sorted_by_freq(LANG_DISPLAY, freq, pinned_top=AUTO_DETECT_DISPLAY)
        current = self.lang_combo.currentText()
        self.lang_combo.blockSignals(True)
        self.lang_combo.clear()
        self.lang_combo.addItems(ordered)
        if current in ordered:
            self.lang_combo.setCurrentText(current)
        self.lang_combo.blockSignals(False)

    def _rebuild_tgt_combos(self):
        """Repopulate both target language combos sorted by usage frequency."""
        freq = self.cfg.get("tgt_lang_freq", {})
        ordered = sorted_by_freq(TRANSLATE_TARGETS, freq)
        for combo, attr in ((self.tgt_combo, "_tgt_current"),
                            (self.t_tgt_combo, "_t_tgt_current")):
            current = combo.currentText()
            combo.blockSignals(True)
            combo.clear()
            combo.addItems(ordered)
            if current in ordered:
                combo.setCurrentText(current)
            combo.blockSignals(False)

    def _record_lang_use(self, lang_display):
        """Increment usage count for a source language."""
        freq = self.cfg.setdefault("lang_freq", {})
        freq[lang_display] = freq.get(lang_display, 0) + 1

    def _record_tgt_use(self, tgt_display):
        """Increment usage count for a target language."""
        freq = self.cfg.setdefault("tgt_lang_freq", {})
        freq[tgt_display] = freq.get(tgt_display, 0) + 1

    # ── Browse handlers ──────────────────────────────────────────────────────
    def _set_inputs(self, paths):
        valid, errors = [], []
        for path in paths:
            ok, err = validate_media(path)
            if ok:
                valid.append(path)
            else:
                errors.append(f"{os.path.basename(path)}: {err}")
        if errors:
            QMessageBox.critical(self, "Invalid File(s)", "\n\n".join(errors))
        if not valid:
            return
        self.input_paths = valid
        if len(valid) == 1:
            self.input_edit.setText(valid[0])
            self.filename_edit.setEnabled(True)
            self.filename_edit.setText(os.path.splitext(os.path.basename(valid[0]))[0])
        else:
            self.input_edit.setText(f"{len(valid)} files selected")
            self.filename_edit.setEnabled(False)
            self.filename_edit.setText("")
            self.filename_edit.setPlaceholderText("each file keeps its own name - batch mode")
        if self.samedir_check.isChecked():
            self.outdir_edit.setText(os.path.dirname(valid[0]))

    def _set_t_inputs(self, paths):
        valid, errors = [], []
        for path in paths:
            ok, err = validate_subtitle(path)
            if ok:
                valid.append(path)
            else:
                errors.append(f"{os.path.basename(path)}: {err}")
        if errors:
            QMessageBox.critical(self, "Invalid File(s)", "\n\n".join(errors))
        if not valid:
            return
        self.t_input_paths = valid
        if len(valid) == 1:
            self.t_input_edit.setText(valid[0])
            self.t_filename_edit.setEnabled(True)
            self.t_filename_edit.setText(os.path.splitext(os.path.basename(valid[0]))[0])
        else:
            self.t_input_edit.setText(f"{len(valid)} files selected")
            self.t_filename_edit.setEnabled(False)
            self.t_filename_edit.setText("")
            self.t_filename_edit.setPlaceholderText("each file keeps its own name - batch mode")
        if self.t_samedir_check.isChecked():
            self.t_outdir_edit.setText(os.path.dirname(valid[0]))

    def _browse_input(self):
        exts = " ".join(f"*{e}" for e in sorted(MEDIA_EXTS))
        paths, _ = QFileDialog.getOpenFileNames(
            self, "Select audio/video file(s)", "", f"Media files ({exts});;All files (*)")
        if paths:
            self._set_inputs(paths)

    def _browse_outdir(self):
        d = QFileDialog.getExistingDirectory(self, "Select output folder")
        if d: self.outdir_edit.setText(d)

    def _toggle_samedir(self, checked):
        self.outdir_edit.setEnabled(not checked)
        if checked and self.input_paths:
            self.outdir_edit.setText(os.path.dirname(self.input_paths[0]))

    def _t_browse_input(self):
        paths, _ = QFileDialog.getOpenFileNames(
            self, "Select subtitle file(s)", "",
            "Subtitle files (*.srt *.vtt *.txt);;All files (*)")
        if paths: self._set_t_inputs(paths)

    def _t_browse_outdir(self):
        d = QFileDialog.getExistingDirectory(self, "Select output folder")
        if d: self.t_outdir_edit.setText(d)

    def _t_toggle_samedir(self, checked):
        self.t_outdir_edit.setEnabled(not checked)
        if checked and self.t_input_paths:
            self.t_outdir_edit.setText(os.path.dirname(self.t_input_paths[0]))

    # ── Translation toggles ──────────────────────────────────────────────────
    def _toggle_translate(self, checked):
        self.bilingual_check.setEnabled(checked)
        self.tgt_combo.setEnabled(checked)
        self.ollama_combo.setEnabled(checked and not self.whisper_tr_check.isChecked())
        self._on_tgt_change(self.tgt_combo.currentText())

    def _on_tgt_change(self, value):
        is_en = (value == ENGLISH_TARGET_DISPLAY)
        on    = self.translate_check.isChecked()
        self.whisper_tr_check.setEnabled(is_en and on)
        if not is_en:
            self.whisper_tr_check.setChecked(False)
        self.ollama_combo.setEnabled(on and not self.whisper_tr_check.isChecked())

    def _on_whisper_tr_toggle(self, checked):
        on = self.translate_check.isChecked()
        self.ollama_combo.setEnabled(on and not checked)

    # ── Transcribe start/stop ────────────────────────────────────────────────
    def _start_transcribe(self):
        if not self.input_paths:
            self._log("[WARN] No file selected.\n")
            QMessageBox.critical(self, "Invalid Input", "No file selected."); return
        for path in self.input_paths:
            ok, err = validate_media(path)
            if not ok:
                self._log(f"[WARN] {err}\n")
                QMessageBox.critical(self, "Invalid Input", err); return

        out_dir = (os.path.dirname(self.input_paths[0]) if self.samedir_check.isChecked()
                   else self.outdir_edit.text().strip())
        ok, err = validate_output_dir(out_dir)
        if not ok:
            self._log(f"[WARN] {err}\n")
            QMessageBox.critical(self, "Output Error", err); return

        choice = self.model_combo.currentText()
        ok, err = validate_model(choice, self._models_dir())
        if not ok:
            self._log(f"[WARN] {err}\n")
            QMessageBox.critical(self, "Model Error", err); return

        use_wtr = (self.translate_check.isChecked()
                   and self.whisper_tr_check.isChecked()
                   and self.tgt_combo.currentText() == ENGLISH_TARGET_DISPLAY)
        if self.translate_check.isChecked() and not use_wtr:
            ok, err = validate_ollama(self.ollama_combo.currentText())
            if not ok:
                self._log(f"[WARN] {err}\n")
                QMessageBox.critical(self, "Ollama Error", err); return

        if self.tr_worker is not None and self.tr_worker.isRunning():
            self._log("[WARN] Already running.\n"); return

        if len(self.input_paths) == 1:
            out_name = sanitize_filename(
                self.filename_edit.text().strip()
                or os.path.splitext(os.path.basename(self.input_paths[0]))[0])
            files = [(self.input_paths[0], out_name)]
        else:
            files = [(path, sanitize_filename(os.path.splitext(os.path.basename(path))[0]))
                     for path in self.input_paths]

        model_path, needs_dl, online_name = resolve_model(choice, self._models_dir())

        # Record language usage for frequency sorting
        self._record_lang_use(self.lang_combo.currentText())
        if self.translate_check.isChecked():
            self._record_tgt_use(self.tgt_combo.currentText())

        self.start_btn.setEnabled(False)
        self.pause_btn.setEnabled(True)
        self.pause_btn.setText("⏸  Pause")
        self._paused = False
        self.stop_btn.setEnabled(True)
        self.stop_btn.setText("■  Stop")
        self.stop_all_btn.setEnabled(True)
        self._tr_phase = "transcribe"
        self.progress_bar.setValue(0)
        self.pct_label.setText("0%")
        self.elapsed_label.setText("Elapsed: 00:00")
        self.eta_label.setText("ETA: -")
        self.log_view.clear()
        self.status_label.setText("Running...")
        self._start_time = time.time()
        self._elapsed_timer.start(500)

        params = dict(
            files=files, out_dir=out_dir,
            model_path=model_path, needs_dl=needs_dl,
            online_name=online_name, models_dir=self._models_dir(),
            lang_code=LANG_CODE[self.lang_combo.currentText()],
            fmt=self.fmt_combo.currentText(),
            use_vad=self.vad_check.isChecked(),
            no_halluc=self.halluc_check.isChecked(),
            do_translate=self.translate_check.isChecked(),
            use_wtr=use_wtr, tgt=self.tgt_combo.currentText(),
            ollama=self.ollama_combo.currentText(),
            bilingual=self.bilingual_check.isChecked(),
        )
        self.tr_worker = TranscribeWorker(params)
        self.tr_worker.log.connect(self._log)
        self.tr_worker.progress.connect(self._update_progress)
        self.tr_worker.status.connect(self._on_tr_status)
        self.tr_worker.done.connect(self._on_transcribe_done)
        self.tr_worker.failed.connect(self._on_transcribe_failed)
        self.tr_worker.start()

    def _on_tr_status(self, text):
        self.status_label.setText(text)
        # Track which phase is running (used by _stop_current), but the Stop
        # button's label always stays "Stop" - it means the same thing in
        # both phases: stop the current step, keep what it already produced.
        if "Translat" in text:
            self._tr_phase = "translate"
        elif text not in ("Done", "Error", "Stopped", ""):
            self._tr_phase = "transcribe"

    def _stop_current(self):
        """Stop only the current file's current stage. The queue continues
        normally afterwards - to the translation of this file, or to the
        next file - with whatever this stage already produced kept."""
        if self.tr_worker:
            self.tr_worker.request_stop_stage()
            self.status_label.setText("Stopping current step...")
        # Deliberately NOT disabling Start/Stop/Pause here - more stages or
        # files may still follow, and the user should still be able to
        # stop/pause them too.

    def _toggle_pause(self):
        if not self.tr_worker:
            return
        self._paused = not self._paused
        if self._paused:
            self.tr_worker.request_pause()
            self.pause_btn.setText("▶  Resume")
            self.status_label.setText("Paused")
        else:
            self.tr_worker.request_resume()
            self.pause_btn.setText("⏸  Pause")
            self.status_label.setText("Resuming...")

    def _stop_all(self):
        """Abort the entire queue immediately - no further files or stages."""
        if self.tr_worker:
            self.tr_worker.request_stop_all()
            self.status_label.setText("Stopping all...")
        self.stop_btn.setEnabled(False)
        self.stop_all_btn.setEnabled(False)
        self.pause_btn.setEnabled(False)
        if self._paused:
            self._paused = False
            self.pause_btn.setText("⏸  Pause")

    def _on_transcribe_done(self):
        self._reset_transcribe_buttons()
        if self.taskbar: self.taskbar.clear()

    def _on_transcribe_failed(self, msg):
        self._reset_transcribe_buttons()
        if self.taskbar: self.taskbar.error()

    def _reset_transcribe_buttons(self):
        self.start_btn.setEnabled(True)
        self.pause_btn.setEnabled(False)
        self.pause_btn.setText("⏸  Pause")
        self._paused = False
        self.stop_btn.setEnabled(False)
        self.stop_all_btn.setEnabled(False)
        self._elapsed_timer.stop()

    # ── Translate start/stop ─────────────────────────────────────────────────
    def _start_translate(self):
        if not self.t_input_paths:
            self._t_log("[WARN] No file selected.\n")
            QMessageBox.critical(self, "Invalid Input", "No file selected."); return
        for path in self.t_input_paths:
            ok, err = validate_subtitle(path)
            if not ok:
                self._t_log(f"[WARN] {err}\n")
                QMessageBox.critical(self, "Invalid File", err); return

        out_dir = (os.path.dirname(self.t_input_paths[0]) if self.t_samedir_check.isChecked()
                   else self.t_outdir_edit.text().strip())
        ok, err = validate_output_dir(out_dir)
        if not ok:
            self._t_log(f"[WARN] {err}\n")
            QMessageBox.critical(self, "Output Error", err); return

        ok, err = validate_ollama(self.t_ollama_combo.currentText())
        if not ok:
            self._t_log(f"[WARN] {err}\n")
            QMessageBox.critical(self, "Ollama Error", err); return

        if self.tl_worker is not None and self.tl_worker.isRunning():
            self._t_log("[WARN] Already running.\n"); return

        if len(self.t_input_paths) == 1:
            out_name = sanitize_filename(
                self.t_filename_edit.text().strip()
                or os.path.splitext(os.path.basename(self.t_input_paths[0]))[0])
            files = [(self.t_input_paths[0], out_name)]
        else:
            files = [(path, sanitize_filename(os.path.splitext(os.path.basename(path))[0]))
                     for path in self.t_input_paths]

        # Record target language usage for frequency sorting
        self._record_tgt_use(self.t_tgt_combo.currentText())

        self.t_start_btn.setEnabled(False)
        self.t_pause_btn.setEnabled(True)
        self.t_pause_btn.setText("⏸  Pause")
        self._t_paused = False
        self.t_stop_btn.setEnabled(True)
        self.t_stop_all_btn.setEnabled(True)
        self.t_progress_bar.setValue(0)
        self.t_pct_label.setText("0%")
        self.t_elapsed_label.setText("Elapsed: 00:00")
        self.t_eta_label.setText("ETA: -")
        self.t_log_view.clear()
        self.t_status_label.setText("Running...")
        self._t_start_time = time.time()
        self._t_elapsed_timer.start(500)

        params = dict(
            files=files, out_dir=out_dir,
            tgt=self.t_tgt_combo.currentText(),
            ollama=self.t_ollama_combo.currentText(),
            bilingual=self.t_bilingual_check.isChecked(),
            fmt=self.t_fmt_combo.currentText(),
        )
        self.tl_worker = TranslateWorker(params)
        self.tl_worker.log.connect(self._t_log)
        self.tl_worker.progress.connect(self._t_update_progress)
        self.tl_worker.status.connect(self.t_status_label.setText)
        self.tl_worker.done.connect(self._on_translate_done)
        self.tl_worker.failed.connect(self._on_translate_failed)
        self.tl_worker.start()

    def _t_stop(self):
        """Stop only the current file's translation. The queue continues
        normally to the next file, with whatever this file already
        produced kept."""
        if self.tl_worker:
            self.tl_worker.request_stop_stage()
            self.t_status_label.setText("Stopping current file...")
        # Deliberately NOT disabling Start/Stop/Pause here - more files may
        # still follow, and the user should still be able to stop/pause them.

    def _t_stop_all(self):
        """Abort the entire translation queue immediately - no further
        files will run."""
        if self.tl_worker:
            self.tl_worker.request_stop_all()
            self.t_status_label.setText("Stopping all...")
        self.t_stop_btn.setEnabled(False)
        self.t_stop_all_btn.setEnabled(False)
        self.t_pause_btn.setEnabled(False)
        if self._t_paused:
            self._t_paused = False
            self.t_pause_btn.setText("⏸  Pause")

    def _t_toggle_pause(self):
        if not self.tl_worker:
            return
        self._t_paused = not self._t_paused
        if self._t_paused:
            self.tl_worker.request_pause()
            self.t_pause_btn.setText("▶  Resume")
            self.t_status_label.setText("Paused")
        else:
            self.tl_worker.request_resume()
            self.t_pause_btn.setText("⏸  Pause")
            self.t_status_label.setText("Resuming...")

    def _on_translate_done(self):
        self._reset_translate_buttons()
        if self.taskbar: self.taskbar.clear()

    def _on_translate_failed(self, msg):
        self._reset_translate_buttons()
        if self.taskbar: self.taskbar.error()

    def _reset_translate_buttons(self):
        self.t_start_btn.setEnabled(True)
        self.t_pause_btn.setEnabled(False)
        self.t_pause_btn.setText("⏸  Pause")
        self._t_paused = False
        self.t_stop_btn.setEnabled(False)
        self.t_stop_all_btn.setEnabled(False)
        self._t_elapsed_timer.stop()

    # ── Progress / elapsed ───────────────────────────────────────────────────
    def _fmt_dur(self, s):
        m, sec = divmod(int(s), 60)
        h, m   = divmod(m, 60)
        return f"{h:02d}:{m:02d}:{sec:02d}" if h else f"{m:02d}:{sec:02d}"

    def _update_progress(self, pct):
        self.progress_bar.setValue(int(pct * 1000))
        self.pct_label.setText(f"{pct*100:.0f}%")
        if self.taskbar:
            self.taskbar.set_value(pct, TaskbarProgress.TBPF_NORMAL)
        if self._start_time:
            el = time.time() - self._start_time
            self.elapsed_label.setText(f"Elapsed: {self._fmt_dur(el)}")
            if pct > 0.01:
                self.eta_label.setText(f"ETA: {self._fmt_dur(el/pct - el)}")

    def _t_update_progress(self, pct):
        self.t_progress_bar.setValue(int(pct * 1000))
        self.t_pct_label.setText(f"{pct*100:.0f}%")
        if self.taskbar:
            self.taskbar.set_value(pct, TaskbarProgress.TBPF_NORMAL)
        if self._t_start_time:
            el = time.time() - self._t_start_time
            self.t_elapsed_label.setText(f"Elapsed: {self._fmt_dur(el)}")
            if pct > 0.01:
                self.t_eta_label.setText(f"ETA: {self._fmt_dur(el/pct - el)}")

    def _tick_elapsed(self):
        if self._start_time and self.tr_worker and self.tr_worker.isRunning():
            self.elapsed_label.setText(
                f"Elapsed: {self._fmt_dur(time.time() - self._start_time)}")

    def _t_tick_elapsed(self):
        if self._t_start_time and self.tl_worker and self.tl_worker.isRunning():
            self.t_elapsed_label.setText(
                f"Elapsed: {self._fmt_dur(time.time() - self._t_start_time)}")

    # ── Logging ──────────────────────────────────────────────────────────────
    def _append_log(self, view: QTextEdit, text: str):
        from PySide6.QtGui import QTextCursor
        cursor = view.textCursor()
        cursor.movePosition(QTextCursor.MoveOperation.End)
        view.setTextCursor(cursor)
        view.insertPlainText(text)
        view.ensureCursorVisible()

    def _log(self, text):
        self._append_log(self.log_view, text)
        self._append_log(self.t_log_view, text)

    def _t_log(self, text):
        self._append_log(self.t_log_view, text)
        self._append_log(self.log_view, text)

    # ── Skins & background ───────────────────────────────────────────────────
    def _apply_qss(self):
        sk = SKINS[self.current_skin_name]
        QApplication.instance().setStyleSheet(build_qss(sk))
        self.bg_widget.set_skin(sk)
        self._refresh_skin_selection()

    def _pick_skin(self, name):
        self.current_skin_name = name
        self._apply_qss()

    def _refresh_skin_selection(self):
        for name, card in self.skin_swatches.items():
            sk = SKINS[name]
            if name == self.current_skin_name:
                card.setStyleSheet(
                    f"QFrame {{ background: {sk['bg']}; border: 3px solid {sk['accent']}; "
                    f"border-radius: 10px; }}")
            else:
                card.setStyleSheet(
                    f"QFrame {{ background: {sk['bg']}; border: 2px solid {sk['border']}; "
                    f"border-radius: 10px; }}")

    def _browse_bg(self):
        path, _ = QFileDialog.getOpenFileName(
            self, "Select background image", "",
            "Image files (*.jpg *.jpeg *.png *.webp *.bmp);;All files (*)")
        if path:
            self.bg_path_edit.setText(path)
            self.bg_widget.set_background(path)

    def _remove_bg(self):
        self.bg_path_edit.setText("")
        self.bg_widget.set_background("")

    def _on_opacity_change(self, value):
        self.bg_widget.set_opacity(value / 100.0)
        self.opacity_value_label.setText(f"{value}%")

    # ── Config ───────────────────────────────────────────────────────────────
    def _apply_config(self):
        cfg = self.cfg
        if cfg.get("window_geometry"):
            try:
                from base64 import b64decode
                self.restoreGeometry(b64decode(cfg["window_geometry"]))
            except Exception:
                pass

        # Populate language combos with frequency-sorted order
        lang_freq = cfg.get("lang_freq", {})
        tgt_freq  = cfg.get("tgt_lang_freq", {})
        ordered_lang = sorted_by_freq(LANG_DISPLAY, lang_freq, pinned_top=AUTO_DETECT_DISPLAY)
        ordered_tgt  = sorted_by_freq(TRANSLATE_TARGETS, tgt_freq)

        self.lang_combo.blockSignals(True)
        self.lang_combo.clear()
        self.lang_combo.addItems(ordered_lang)
        self.lang_combo.blockSignals(False)

        self.tgt_combo.blockSignals(True)
        self.tgt_combo.clear()
        self.tgt_combo.addItems(ordered_tgt)
        self.tgt_combo.blockSignals(False)

        self.t_tgt_combo.blockSignals(True)
        self.t_tgt_combo.clear()
        self.t_tgt_combo.addItems(ordered_tgt)
        self.t_tgt_combo.blockSignals(False)

        if cfg.get("lang") in ordered_lang:
            self.lang_combo.setCurrentText(cfg["lang"])
        if cfg.get("fmt") in FORMATS:
            self.fmt_combo.setCurrentText(cfg["fmt"])
        self.vad_check.setChecked(bool(cfg.get("vad", True)))
        self.halluc_check.setChecked(bool(cfg.get("halluc", True)))
        self.translate_check.setChecked(bool(cfg.get("translate", False)))
        self.bilingual_check.setChecked(bool(cfg.get("bilingual", False)))
        if cfg.get("tgt_lang") in ordered_tgt:
            self.tgt_combo.setCurrentText(cfg["tgt_lang"])
        self.whisper_tr_check.setChecked(bool(cfg.get("whisper_tr", False)))
        self.samedir_check.setChecked(bool(cfg.get("samedir", True)))
        self.t_bilingual_check.setChecked(bool(cfg.get("t_bilingual", False)))
        self.t_samedir_check.setChecked(bool(cfg.get("t_samedir", True)))
        if cfg.get("t_fmt") in FORMATS:
            self.t_fmt_combo.setCurrentText(cfg["t_fmt"])

        self._toggle_translate(self.translate_check.isChecked())
        self._toggle_samedir(self.samedir_check.isChecked())
        self._t_toggle_samedir(self.t_samedir_check.isChecked())

        bg_image = cfg.get("bg_image", "")
        if bg_image and os.path.exists(bg_image):
            self.bg_path_edit.setText(bg_image)
            self.bg_widget.set_background(bg_image)
        opacity = cfg.get("bg_opacity", 0.72)
        self.opacity_slider.setValue(int(opacity * 100))
        self.bg_widget.set_opacity(opacity)

    def closeEvent(self, event: QCloseEvent):
        cfg = self.cfg.copy()
        try:
            from base64 import b64encode
            cfg["window_geometry"] = b64encode(bytes(self.saveGeometry())).decode("ascii")
        except Exception:
            pass
        try: cfg["splitter_tr"] = self.tr_splitter.sizes()
        except Exception: pass
        try: cfg["splitter_tl"] = self.tl_splitter.sizes()
        except Exception: pass
        try: cfg["sidebar_width"] = self.h_splitter.sizes()[0]
        except Exception: pass

        cfg["skin"]        = self.current_skin_name
        cfg["bg_image"]    = self.bg_path_edit.text()
        cfg["bg_opacity"]  = self.opacity_slider.value() / 100.0
        cfg["lang"]        = self.lang_combo.currentText()
        cfg["fmt"]         = self.fmt_combo.currentText()
        cfg["vad"]         = self.vad_check.isChecked()
        cfg["halluc"]      = self.halluc_check.isChecked()
        cfg["translate"]   = self.translate_check.isChecked()
        cfg["bilingual"]   = self.bilingual_check.isChecked()
        cfg["tgt_lang"]    = self.tgt_combo.currentText()
        cfg["whisper_tr"]  = self.whisper_tr_check.isChecked()
        cfg["samedir"]     = self.samedir_check.isChecked()
        cfg["t_bilingual"] = self.t_bilingual_check.isChecked()
        cfg["t_samedir"]   = self.t_samedir_check.isChecked()
        cfg["t_fmt"]       = self.t_fmt_combo.currentText()
        cfg["lang_freq"]   = self.cfg.get("lang_freq", {})
        cfg["tgt_lang_freq"] = self.cfg.get("tgt_lang_freq", {})
        save_config(cfg)

        if self.tr_worker and self.tr_worker.isRunning():
            self.tr_worker.request_stop_all()   # also wakes it if paused
            self.tr_worker.wait(2000)
        if self.tl_worker and self.tl_worker.isRunning():
            self.tl_worker.request_stop_all()   # also wakes it if paused
            self.tl_worker.wait(2000)

        event.accept()


# ══════════════════════════════════════════════════════════════════════════════
def main():
    QApplication.setHighDpiScaleFactorRoundingPolicy(
        Qt.HighDpiScaleFactorRoundingPolicy.PassThrough)
    app = QApplication(sys.argv)
    app.setStyle("Fusion")

    icon_path = os.path.join(SCRIPT_DIR, "icon.ico")

    window = MainWindow()
    window.show()

    if os.path.exists(icon_path) and sys.platform == "win32":
        def _reapply_icon():
            # Send WM_SETICON directly to the native window handle.
            # This nudges Windows into re-binding the taskbar icon for
            # pythonw.exe (GUI-subsystem) processes, without which the
            # taskbar can show a generic icon until Explorer refreshes.
            try:
                import ctypes
                LR_LOADFROMFILE = 0x00000010
                LR_DEFAULTSIZE  = 0x00000040
                IMAGE_ICON      = 1
                WM_SETICON      = 0x0080
                ICON_BIG, ICON_SMALL = 1, 0
                hwnd = int(window.winId())
                hicon = ctypes.windll.user32.LoadImageW(
                    0, icon_path, IMAGE_ICON, 0, 0,
                    LR_LOADFROMFILE | LR_DEFAULTSIZE)
                if hicon:
                    ctypes.windll.user32.SendMessageW(
                        hwnd, WM_SETICON, ICON_BIG, hicon)
                    ctypes.windll.user32.SendMessageW(
                        hwnd, WM_SETICON, ICON_SMALL, hicon)
            except Exception:
                pass
        QTimer.singleShot(200, _reapply_icon)

    sys.exit(app.exec())

if __name__ == "__main__":
    main()
