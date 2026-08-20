"""
skins.py – Skin definitions, QSS stylesheet builder, BackgroundWidget,
           and Windows taskbar progress (ITaskbarList3).
"""
import os, sys

from PySide6.QtCore import Qt
from PySide6.QtGui  import QPixmap, QPainter, QColor
from PySide6.QtWidgets import QWidget

try:
    import comtypes
    USE_COMTYPES = (sys.platform == "win32")
except ImportError:
    USE_COMTYPES = False

# ══════════════════════════════════════════════════════════════════════════════
# Skin palette definitions
# ══════════════════════════════════════════════════════════════════════════════
SKINS = {
    "Sakura Mist": {
        "bg": "#faf7f5", "sidebar": "#f0ebe8", "surface": "#ffffff",
        "border": "#e2dbd8", "accent": "#c45c78", "accent2": "#8a67c2",
        "success": "#2e7d32", "warning": "#d99a3e",
        "danger": "#d94f4f", "text": "#3d3330", "subtext": "#9b918d",
        "log_bg": "#f5f0ee", "log_fg": "#6b605c",
    },
    "Arctic Clarity": {
        "bg": "#f4f7fb", "sidebar": "#e4ecf5", "surface": "#ffffff",
        "border": "#d4dde9", "accent": "#2d7dd2", "accent2": "#6e55c4",
        "success": "#2e7d32", "warning": "#d9a52e",
        "danger": "#cf4444", "text": "#1e2d42", "subtext": "#8899b0",
        "log_bg": "#eef2f8", "log_fg": "#4a5e78",
    },
    "Matcha Calm": {
        "bg": "#f4f6f2", "sidebar": "#e4e8e0", "surface": "#ffffff",
        "border": "#d5dbd0", "accent": "#4a7c59", "accent2": "#7a6abf",
        "success": "#1b5e20", "warning": "#c9972e",
        "danger": "#c44e4e", "text": "#2a3228", "subtext": "#8a9886",
        "log_bg": "#eef0eb", "log_fg": "#5a6e58",
    },
    "Twilight Plum": {
        "bg": "#f6f4fa", "sidebar": "#e8e4f4", "surface": "#ffffff",
        "border": "#dcd8ea", "accent": "#7c5cbf", "accent2": "#4a7bc4",
        "success": "#2e7d32", "warning": "#cc9a3e",
        "danger": "#c44a5a", "text": "#28203c", "subtext": "#9288b0",
        "log_bg": "#f0eef8", "log_fg": "#5e5480",
    },
    "Fluent Glass": {
        "bg": "#e8e0f5", "sidebar": "#ece4f7", "surface": "#f5eefc",
        "border": "#d8c8ee", "accent": "#7c3cbf", "accent2": "#3c64c8",
        "success": "#2e7d32", "warning": "#d4922e",
        "danger": "#c83c46", "text": "#3d2a50", "subtext": "#8a78a0",
        "log_bg": "#f0e8fa", "log_fg": "#5e3a80", "glass": True,
    },
}
SKIN_NAMES = list(SKINS.keys())


def darken(hex_color, amount=25):
    h = hex_color.lstrip("#")
    r, g, b = int(h[0:2], 16), int(h[2:4], 16), int(h[4:6], 16)
    r, g, b = max(0, r-amount), max(0, g-amount), max(0, b-amount)
    return f"#{r:02x}{g:02x}{b:02x}"


_CHECKMARK_PATH = None

def get_checkmark_icon_path():
    """Return the path to a small checkmark PNG, generating it if needed."""
    global _CHECKMARK_PATH
    if _CHECKMARK_PATH and os.path.exists(_CHECKMARK_PATH):
        return _CHECKMARK_PATH
    import tempfile
    from PySide6.QtGui import QPen
    from PySide6.QtCore import QPoint
    size = 20
    pm = QPixmap(size, size)
    pm.fill(Qt.transparent)
    painter = QPainter(pm)
    painter.setRenderHint(QPainter.Antialiasing)
    pen = QPen(QColor("#ffffff"))
    pen.setWidth(3)
    pen.setCapStyle(Qt.RoundCap)
    pen.setJoinStyle(Qt.RoundJoin)
    painter.setPen(pen)
    painter.drawPolyline([
        QPoint(int(size*0.22), int(size*0.52)),
        QPoint(int(size*0.42), int(size*0.72)),
        QPoint(int(size*0.80), int(size*0.28)),
    ])
    painter.end()
    path = os.path.join(tempfile.gettempdir(), "fw_transcriber_checkmark.png")
    pm.save(path, "PNG")
    _CHECKMARK_PATH = path
    return path


def build_qss(sk):
    """Generate the full application stylesheet for the given skin palette."""
    accent_dark   = darken(sk["accent"])
    accent2_dark  = darken(sk["accent2"])
    success_dark  = darken(sk["success"])
    danger_dark   = darken(sk["danger"])
    warning_dark  = darken(sk["warning"])
    checkmark_path = get_checkmark_icon_path().replace("\\", "/")
    return f"""
    QMainWindow {{ background: {sk['bg']}; }}
    QWidget {{ color: {sk['text']}; font-family: "Segoe UI"; font-size: 10pt; }}

    /* "page" containers sit on top of BackgroundWidget, which already
       paints the flat colour / gradient / image for the content area -
       so pages must stay transparent instead of re-painting sk['bg']
       opaquely on top of it (that would hide the Fluent Glass gradient
       and any custom background image). */
    QWidget#page {{ background: transparent; }}
    QStackedWidget {{ background: transparent; }}

    QWidget#sidebar {{ background: {sk['sidebar']}; }}
    QLabel#appTitle {{ color: {sk['accent']}; font-size: 12pt; font-weight: 700; }}
    QPushButton#navItem {{
        background: transparent; color: {sk['text']}; text-align: left;
        padding: 10px 14px; border: none; border-radius: 8px; font-size: 10pt;
    }}
    QPushButton#navItem:hover {{ background: {sk['border']}; }}
    QPushButton#navItem:checked {{ background: {sk['accent']}; color: white; font-weight: 600; }}

    QLabel#sectionLabel {{
        color: {sk['subtext']}; font-size: 9pt; font-weight: 700;
        letter-spacing: 1px; padding-top: 8px;
    }}
    QLabel#hintLabel {{ color: {sk['subtext']}; font-size: 9pt; }}
    QLabel#warnLabel {{ color: #c07820; font-size: 9pt; }}

    QLineEdit, QComboBox {{
        background: {sk['surface']}; border: 1px solid {sk['border']};
        border-radius: 8px; padding: 6px 10px; color: {sk['text']};
        selection-background-color: {sk['accent']};
    }}
    QLineEdit:disabled, QComboBox:disabled {{ color: {sk['subtext']}; }}
    QComboBox::drop-down {{ border: none; width: 24px; }}
    QComboBox QAbstractItemView {{
        background: {sk['surface']}; border: 1px solid {sk['border']};
        selection-background-color: {sk['accent']}; selection-color: white;
        outline: none;
    }}

    QCheckBox {{ spacing: 8px; color: {sk['text']}; }}
    QCheckBox::indicator {{
        width: 16px; height: 16px; border-radius: 4px;
        border: 1px solid {sk['border']}; background: {sk['surface']};
    }}
    QCheckBox::indicator:checked {{
        background: {sk['accent']}; border-color: {sk['accent']};
        image: url({checkmark_path});
    }}

    /* ── Start button: green when enabled, grey when disabled ── */
    QPushButton#startBtn {{
        background: {sk['success']}; color: white; border: none;
        border-radius: 8px; padding: 10px 24px; font-weight: 700; font-size: 10pt;
    }}
    QPushButton#startBtn:hover {{ background: {success_dark}; }}
    QPushButton#startBtn:disabled {{
        background: {sk['border']}; color: {sk['subtext']}; border: none;
    }}

    /* ── Stop button: red when enabled, grey when disabled ── */
    QPushButton#stopBtn {{
        background: {sk['danger']}; color: white; border: none;
        border-radius: 8px; padding: 10px 24px; font-weight: 700; font-size: 10pt;
    }}
    QPushButton#stopBtn:hover {{ background: {danger_dark}; }}
    QPushButton#stopBtn:disabled {{
        background: {sk['border']}; color: {sk['subtext']}; border: none;
    }}

    /* ── Pause button: amber/yellow when enabled, grey when disabled ── */
    QPushButton#pauseBtn {{
        background: {sk['warning']}; color: white; border: none;
        border-radius: 8px; padding: 10px 24px; font-weight: 700; font-size: 10pt;
    }}
    QPushButton#pauseBtn:hover {{ background: {warning_dark}; }}
    QPushButton#pauseBtn:disabled {{
        background: {sk['border']}; color: {sk['subtext']}; border: none;
    }}

    /* ── Stop All: outlined red, deliberately smaller/quieter than Stop
       so the "abort everything" action isn't mistaken for the routine
       "stop this step" action ── */
    QPushButton#stopAllBtn {{
        background: transparent; color: {sk['danger']};
        border: 1px solid {sk['danger']}; border-radius: 8px;
        padding: 9px 14px; font-weight: 600; font-size: 9pt;
    }}
    QPushButton#stopAllBtn:hover {{ background: {sk['danger']}; color: white; }}
    QPushButton#stopAllBtn:disabled {{
        background: transparent; color: {sk['subtext']}; border: 1px solid {sk['border']};
    }}

    QPushButton#primaryBtn {{
        background: {sk['accent']}; color: white; border: none;
        border-radius: 8px; padding: 8px 16px; font-weight: 600;
    }}
    QPushButton#primaryBtn:hover {{ background: {accent_dark}; }}
    QPushButton#primaryBtn:disabled {{ background: {sk['border']}; color: {sk['subtext']}; }}

    QPushButton#secondaryBtn {{
        background: {sk['surface']}; color: {sk['text']}; border: 1px solid {sk['border']};
        border-radius: 8px; padding: 8px 14px;
    }}
    QPushButton#secondaryBtn:hover {{ background: {sk['border']}; }}

    QPushButton#dangerBtn {{
        background: {sk['danger']}; color: white; border: none;
        border-radius: 8px; padding: 8px 14px; font-weight: 600;
    }}
    QPushButton#dangerBtn:hover {{ background: {danger_dark}; }}
    QPushButton#dangerBtn:disabled {{ background: {sk['border']}; color: {sk['subtext']}; }}

    QPushButton#purpleBtn {{
        background: {sk['accent2']}; color: white; border: none;
        border-radius: 8px; padding: 8px 14px; font-weight: 600;
    }}
    QPushButton#purpleBtn:hover {{ background: {accent2_dark}; }}
    QPushButton#purpleBtn:disabled {{ background: {sk['border']}; color: {sk['subtext']}; }}

    QProgressBar {{
        background: {sk['border']}; border: none; border-radius: 3px;
        height: 6px; text-align: center; color: transparent;
    }}
    QProgressBar::chunk {{ background: {sk['accent']}; border-radius: 3px; }}

    QTextEdit#logView {{
        background: {sk['log_bg']}; color: {sk['log_fg']};
        border: none; font-family: "Cascadia Code", "Consolas", monospace;
        font-size: 9pt; padding: 8px;
    }}
    QLabel#logHeader {{
        background: {sk['sidebar']}; color: {sk['subtext']};
        font-size: 9pt; font-weight: 700; padding: 6px 10px;
    }}

    QScrollArea {{ background: transparent; border: none; }}
    QScrollArea > QWidget > QWidget {{ background: transparent; }}
    QScrollBar:vertical {{
        background: {sk['bg']}; width: 12px; margin: 0;
    }}
    QScrollBar::handle:vertical {{
        background: {sk['border']}; border-radius: 5px; min-height: 30px;
    }}
    QScrollBar::handle:vertical:hover {{ background: {sk['accent']}; }}
    QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical {{ height: 0; }}

    QSplitter::handle {{ background: {sk['border']}; }}
    QSplitter::handle:horizontal {{ width: 4px; }}
    QSplitter::handle:vertical {{ height: 4px; }}

    QSlider::groove:horizontal {{
        background: {sk['border']}; height: 4px; border-radius: 2px;
    }}
    QSlider::handle:horizontal {{
        background: {sk['accent']}; width: 14px; height: 14px;
        margin: -5px 0; border-radius: 7px;
    }}

    QToolTip {{
        background: #1e1e2e; color: #cdd6f4; border: 1px solid #2a2a3e;
        padding: 6px 10px; border-radius: 4px; font-size: 9pt;
    }}
    """


# ══════════════════════════════════════════════════════════════════════════════
# Background widget
# ══════════════════════════════════════════════════════════════════════════════
def _hex_to_rgb(h):
    h = h.lstrip("#")
    return (int(h[0:2], 16), int(h[2:4], 16), int(h[4:6], 16))


class BackgroundWidget(QWidget):
    """Content-area background widget.

    Paints an optional user-chosen image (or, for the Fluent Glass skin with
    no image set, a built-in soft gradient) behind all child widgets, with an
    adjustable-opacity overlay so text stays readable.
    """
    def __init__(self):
        super().__init__()
        self._pixmap  = None
        self._opacity = 0.72
        self._skin    = SKINS["Sakura Mist"]

    def set_background(self, path):
        if path and os.path.exists(path):
            pm = QPixmap(path)
            self._pixmap = pm if not pm.isNull() else None
        else:
            self._pixmap = None
        self.update()

    def set_opacity(self, value):
        self._opacity = max(0.0, min(1.0, value))
        self.update()

    def set_skin(self, sk):
        self._skin = sk
        self.update()

    def paintEvent(self, event):
        painter = QPainter(self)
        sk = self._skin
        if self._pixmap is not None:
            scaled = self._pixmap.scaled(
                self.size(), Qt.KeepAspectRatioByExpanding,
                Qt.SmoothTransformation)
            x = (self.width()  - scaled.width())  // 2
            y = (self.height() - scaled.height()) // 2
            painter.drawPixmap(x, y, scaled)
            overlay_rgb = (255, 255, 255) if sk.get("glass") else _hex_to_rgb(sk["bg"])
            overlay = QColor(*overlay_rgb)
            overlay.setAlphaF(self._opacity)
            painter.fillRect(self.rect(), overlay)
        elif sk.get("glass"):
            from PySide6.QtGui import QLinearGradient
            grad = QLinearGradient(0, 0, self.width(), self.height())
            grad.setColorAt(0.0,  QColor(255, 214, 231))
            grad.setColorAt(0.35, QColor(224, 192, 248))
            grad.setColorAt(0.7,  QColor(184, 212, 248))
            grad.setColorAt(1.0,  QColor(192, 240, 232))
            painter.fillRect(self.rect(), grad)
            overlay = QColor(255, 255, 255)
            overlay.setAlphaF(self._opacity)
            painter.fillRect(self.rect(), overlay)
        else:
            painter.fillRect(self.rect(), QColor(sk["bg"]))
        painter.end()


# ══════════════════════════════════════════════════════════════════════════════
# Windows taskbar progress  (ITaskbarList3 via comtypes)
# ══════════════════════════════════════════════════════════════════════════════
class TaskbarProgress:
    """Windows taskbar button progress indicator via ITaskbarList3 (comtypes).
    Requires a raw HWND, e.g. int(main_window.winId()).
    """
    TBPF_NOPROGRESS    = 0
    TBPF_INDETERMINATE = 1
    TBPF_NORMAL        = 2
    TBPF_ERROR         = 4

    _CLSID = "{56FDF344-FD6D-11D0-958A-006097C9A090}"
    _IID   = "{EA1AFB91-9E28-4B86-90E9-9E9F8A5EEFAF}"

    def __init__(self, hwnd):
        self._hwnd = hwnd
        self._tb   = None
        self._init_error = None
        if not USE_COMTYPES:
            return
        try:
            from comtypes import GUID, COMMETHOD, IUnknown
            from ctypes import HRESULT, c_int, c_ulonglong
            from ctypes.wintypes import HWND, BOOL

            class ITaskbarList3(IUnknown):
                _case_insensitive_ = True
                _iid_ = GUID(self._IID)
                _methods_ = [
                    COMMETHOD([], HRESULT, "HrInit"),
                    COMMETHOD([], HRESULT, "AddTab",         (["in"], HWND, "hwnd")),
                    COMMETHOD([], HRESULT, "DeleteTab",      (["in"], HWND, "hwnd")),
                    COMMETHOD([], HRESULT, "ActivateTab",    (["in"], HWND, "hwnd")),
                    COMMETHOD([], HRESULT, "SetActiveAlt",   (["in"], HWND, "hwnd")),
                    COMMETHOD([], HRESULT, "MarkFullscreenWindow",
                              (["in"], HWND, "hwnd"), (["in"], BOOL, "f")),
                    COMMETHOD([], HRESULT, "SetProgressValue",
                              (["in"], HWND, "hwnd"),
                              (["in"], c_ulonglong, "completed"),
                              (["in"], c_ulonglong, "total")),
                    COMMETHOD([], HRESULT, "SetProgressState",
                              (["in"], HWND, "hwnd"), (["in"], c_int, "flags")),
                ]

            obj = comtypes.CoCreateInstance(
                GUID(self._CLSID), interface=ITaskbarList3,
                clsctx=comtypes.CLSCTX_INPROC_SERVER)
            obj.HrInit()
            self._tb = obj
        except Exception as ex:
            self._tb = None
            self._init_error = str(ex)

    def set_value(self, value, state=None):
        if not self._tb: return
        try:
            total = 1000
            self._tb.SetProgressValue(
                self._hwnd, int(max(0.0, min(1.0, value)) * total), total)
            if state is not None:
                self._tb.SetProgressState(self._hwnd, state)
        except Exception:
            pass

    def set_state(self, state):
        if not self._tb: return
        try:
            self._tb.SetProgressState(self._hwnd, state)
        except Exception:
            pass

    def clear(self):         self.set_state(self.TBPF_NOPROGRESS)
    def indeterminate(self): self.set_state(self.TBPF_INDETERMINATE)
    def error(self):         self.set_state(self.TBPF_ERROR)
