"""De Qt-interface: speler, tijdlijn, metadata-formulier en bijwerken."""

from __future__ import annotations

import os
import sys
import tempfile
import webbrowser
from pathlib import Path
from typing import Optional

from PyQt5.QtCore import QPointF, QRectF, QSize, Qt, QThread, QTimer, QUrl, pyqtSignal
from PyQt5.QtGui import (
    QColor, QFont, QIcon, QKeySequence, QPainter, QPen, QPixmap, QPolygonF,
)
from PyQt5.QtMultimedia import QMediaContent, QMediaPlayer
from PyQt5.QtMultimediaWidgets import QVideoWidget
from PyQt5.QtWidgets import (
    QApplication, QFileDialog, QFrame, QGridLayout, QHBoxLayout, QLabel,
    QLineEdit, QMessageBox, QProgressBar, QPushButton, QSizePolicy, QSlider,
    QStackedLayout, QVBoxLayout, QWidget,
)

from . import core, updater
from .version import APP_NAME, VERSION

def _asset(*parts: str) -> Optional[str]:
    """Pad naar een meegeleverd bestand (bron, PyInstaller _MEIPASS of onedir)."""
    candidates: list[Path] = []
    meipass = getattr(sys, "_MEIPASS", None)
    if meipass:
        candidates.append(Path(meipass).joinpath(*parts))
    here = Path(__file__).resolve().parent
    candidates.append(here.parent.joinpath(*parts))
    candidates.append(here.joinpath(*parts))
    for candidate in candidates:
        if candidate.exists():
            return str(candidate)
    return None


INK = "#0f172a"
MUTED = "#64748b"
LINE = "#e2e8f0"
ACCENT = "#1d4ed8"
PLAYER_BG = "#0b1220"

# In CI (of een andere omgeving zonder scherm) mogen er geen modale vensters
# verschijnen: die wachten op een klik die nooit komt. Meldingen gaan dan naar
# de statusregel.
HEADLESS = os.environ.get("MEDIA_META_HEADLESS") == "1"

STYLESHEET = f"""
QWidget {{
    font-family: "Segoe UI", "Noto Sans", "DejaVu Sans", sans-serif;
    font-size: 12px;
    color: {INK};
}}
QWidget#Root {{ background: #ffffff; }}
QLabel#AppName {{ font-size: 16px; font-weight: 600; color: {INK}; }}
QLabel#AppSub {{ font-size: 11px; color: {MUTED}; }}
QLabel#Chip {{
    background: #f1f5f9; color: #475569; border-radius: 9px;
    padding: 3px 9px; font-size: 10px;
}}
QLabel#SectionTitle {{
    font-size: 10px; font-weight: 600; color: #94a3b8;
    letter-spacing: 1px;
}}
QLabel#FieldLabel {{ font-size: 11px; color: #475569; }}
QLabel#Status {{ font-size: 11px; color: {MUTED}; }}
QLabel#Info {{ font-size: 11px; color: #94a3b8; }}
QLabel#Hint {{
    color: #94a3b8; font-size: 13px; border: 1px dashed #334155;
    border-radius: 10px; background: transparent;
}}
QWidget#HintBox {{ background: {PLAYER_BG}; }}
QLabel#Poster {{ background: {PLAYER_BG}; color: #94a3b8; font-size: 13px; }}
QLineEdit {{
    background: #ffffff; border: 1px solid {LINE}; border-radius: 6px;
    padding: 6px 9px; color: {INK};
    selection-background-color: {ACCENT}; selection-color: #ffffff;
}}
QLineEdit:focus {{ border: 1px solid {ACCENT}; }}
QPushButton {{
    background: #ffffff; border: 1px solid {LINE}; border-radius: 6px;
    padding: 7px 14px; color: {INK};
}}
QPushButton:hover {{ background: #f8fafc; border-color: #cbd5e1; }}
QPushButton:disabled {{ color: #cbd5e1; border-color: #f1f5f9; }}
QPushButton#Primary {{
    background: {INK}; color: #ffffff; border: 1px solid {INK}; font-weight: 600;
    padding: 8px 18px;
}}
QPushButton#Primary:hover {{ background: #1e293b; }}
QPushButton#Primary:disabled {{ background: #cbd5e1; border-color: #cbd5e1; }}
QPushButton#Round {{ background: {INK}; border: 1px solid {INK}; border-radius: 20px; }}
QPushButton#Round:hover {{ background: #1e293b; }}
QPushButton#IconButton {{ border: 1px solid transparent; background: transparent; padding: 4px; }}
QPushButton#IconButton:hover {{ background: #f1f5f9; }}
QPushButton#Update {{
    background: #eff6ff; color: {ACCENT}; border: 1px solid #bfdbfe;
    font-weight: 600; padding: 6px 12px;
}}
QPushButton#Update:hover {{ background: #dbeafe; }}
QFrame#Card {{ background: #f8fafc; border: 1px solid #eef2f7; border-radius: 10px; }}
QFrame#PlayerFrame {{ background: {PLAYER_BG}; border-radius: 10px; }}
QSlider::groove:horizontal {{ height: 4px; background: {LINE}; border-radius: 2px; }}
QSlider::sub-page:horizontal {{ background: {ACCENT}; border-radius: 2px; }}
QSlider::handle:horizontal {{
    background: #ffffff; border: 2px solid {ACCENT}; width: 14px; height: 14px;
    margin: -5px 0; border-radius: 7px;
}}
QSlider#Volume::sub-page:horizontal {{ background: #94a3b8; }}
QSlider#Volume::handle:horizontal {{ border: 2px solid #94a3b8; }}
QProgressBar {{
    border: none; background: #eef2f7; border-radius: 3px;
    max-height: 6px; min-height: 6px; color: transparent;
}}
QProgressBar::chunk {{ background: {ACCENT}; border-radius: 3px; }}
"""


# --------------------------------------------------------------------------- #
# Icoontjes tekenen (geen glyph-afhankelijkheid per platform)
# --------------------------------------------------------------------------- #

def _icon(kind: str, size: int = 18, color: str = INK) -> QIcon:
    ratio = 2
    pixmap = QPixmap(size * ratio, size * ratio)
    pixmap.setDevicePixelRatio(ratio)
    pixmap.fill(Qt.transparent)
    painter = QPainter(pixmap)
    painter.setRenderHint(QPainter.Antialiasing, True)
    painter.setPen(Qt.NoPen)
    painter.setBrush(QColor(color))
    s = size
    if kind == "play":
        painter.drawPolygon(QPolygonF([QPointF(s * 0.34, s * 0.24),
                                       QPointF(s * 0.34, s * 0.76),
                                       QPointF(s * 0.76, s * 0.50)]))
    elif kind == "pause":
        painter.drawRoundedRect(QRectF(s * 0.32, s * 0.26, s * 0.12, s * 0.48), 1, 1)
        painter.drawRoundedRect(QRectF(s * 0.56, s * 0.26, s * 0.12, s * 0.48), 1, 1)
    elif kind in ("back", "forward"):
        sign = -1 if kind == "back" else 1
        cx = s * 0.5
        for offset in (-0.16, 0.16):
            base = cx + sign * offset * s
            tip = base + sign * s * 0.20
            painter.drawPolygon(QPolygonF([
                QPointF(base - sign * s * 0.09, s * 0.30),
                QPointF(base - sign * s * 0.09, s * 0.70),
                QPointF(tip, s * 0.50),
            ]))
    elif kind in ("volume", "muted"):
        body = QPolygonF([
            QPointF(s * 0.14, s * 0.40),
            QPointF(s * 0.28, s * 0.40),
            QPointF(s * 0.44, s * 0.24),
            QPointF(s * 0.44, s * 0.76),
            QPointF(s * 0.28, s * 0.60),
            QPointF(s * 0.14, s * 0.60),
        ])
        painter.setBrush(QColor(color))
        painter.setPen(Qt.NoPen)
        painter.drawPolygon(body)
        pen = QPen(QColor(color))
        pen.setWidthF(s * 0.07)
        pen.setCapStyle(Qt.RoundCap)
        painter.setPen(pen)
        painter.setBrush(Qt.NoBrush)
        if kind == "volume":
            painter.drawArc(QRectF(s * 0.46, s * 0.38, s * 0.18, s * 0.24), -60 * 16, 120 * 16)
            painter.drawArc(QRectF(s * 0.43, s * 0.30, s * 0.34, s * 0.40), -60 * 16, 120 * 16)
        else:
            painter.drawLine(QPointF(s * 0.60, s * 0.38), QPointF(s * 0.84, s * 0.62))
            painter.drawLine(QPointF(s * 0.84, s * 0.38), QPointF(s * 0.60, s * 0.62))
    elif kind == "fullscreen":
        painter.setBrush(Qt.NoBrush)
        pen = painter.pen()
        pen.setColor(QColor(color))
        pen.setWidthF(s * 0.09)
        pen.setCapStyle(Qt.FlatCap)
        painter.setPen(pen)
        for (x, y, dx, dy) in ((0.18, 0.18, 1, 1), (0.82, 0.18, -1, 1),
                               (0.18, 0.82, 1, -1), (0.82, 0.82, -1, -1)):
            painter.drawLine(QPointF(s * x, s * y), QPointF(s * (x + dx * 0.18), s * y))
            painter.drawLine(QPointF(s * x, s * y), QPointF(s * x, s * (y + dy * 0.18)))
    painter.end()
    return QIcon(pixmap)


# --------------------------------------------------------------------------- #
# Achtergrondtaken
# --------------------------------------------------------------------------- #

class Worker(QThread):
    progress = pyqtSignal(float)
    done = pyqtSignal(object)
    failed = pyqtSignal(str)

    def __init__(self, fn, *args, wants_progress: bool = True, **kwargs):
        super().__init__()
        self._fn = fn
        self._args = args
        self._kwargs = kwargs
        self._wants_progress = wants_progress
        self._cancelled = False

    def cancel(self) -> None:
        self._cancelled = True

    def run(self) -> None:
        try:
            kwargs = dict(self._kwargs)
            if self._wants_progress:
                kwargs.setdefault("on_progress", self._emit_progress)
            result = self._fn(*self._args, **kwargs)
        except Exception as exc:  # noqa: BLE001 - alles naar de UI
            if not self._cancelled:
                self.failed.emit(str(exc))
            return
        if not self._cancelled:
            self.done.emit(result)

    def _emit_progress(self, value: float) -> None:
        if not self._cancelled:
            self.progress.emit(float(value))


# --------------------------------------------------------------------------- #
# Speler-oppervlak
# --------------------------------------------------------------------------- #

class VideoSurface(QVideoWidget):
    """Klik = afspelen/pauzeren, dubbelklik = volledig scherm."""

    clicked = pyqtSignal()
    double_clicked = pyqtSignal()
    dropped = pyqtSignal(str)

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setAcceptDrops(True)
        self.setMinimumHeight(240)
        self.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Expanding)

    def mousePressEvent(self, event):
        if event.button() == Qt.LeftButton:
            self.clicked.emit()
        super().mousePressEvent(event)

    def mouseDoubleClickEvent(self, event):
        if event.button() == Qt.LeftButton:
            self.double_clicked.emit()
        super().mouseDoubleClickEvent(event)

    def dragEnterEvent(self, event):
        mime = event.mimeData()
        if mime.hasUrls():
            urls = mime.urls()
            if urls and core.is_supported(urls[0].toLocalFile() or urls[0].toString()):
                event.acceptProposedAction()

    def dropEvent(self, event):
        urls = event.mimeData().urls()
        if urls:
            path = urls[0].toLocalFile() or urls[0].toString()
            self.dropped.emit(path)
            event.acceptProposedAction()


# --------------------------------------------------------------------------- #
# Hoofdvenster
# --------------------------------------------------------------------------- #

class MainWindow(QWidget):
    def __init__(self, autoupdate: bool = True):
        super().__init__()
        self.setObjectName("Root")
        self.setWindowTitle(APP_NAME)
        self.resize(1120, 840)
        self.setMinimumSize(880, 660)
        self.setStyleSheet(STYLESHEET)
        self.setAcceptDrops(True)

        self.media_path: Optional[str] = None
        self.info: Optional[core.MediaInfo] = None
        self._worker: Optional[Worker] = None
        self._update_worker: Optional[Worker] = None
        self._update_info: Optional[updater.UpdateInfo] = None
        self._poster_pixmap: Optional[QPixmap] = None
        self._poster_source: Optional[str] = None
        self._seeking = False
        self._playback_started = False
        self._tempdir = tempfile.mkdtemp(prefix="mediameta-")
        self._unverified_style = "border: 1px solid #fca5a5; background: #fef2f2;"

        self._build_ui()
        self._wire_player()

        logo_path = _asset("branding", "logo.png")
        if logo_path:
            self.setWindowIcon(QIcon(logo_path))

        if autoupdate:
            QTimer.singleShot(1200, self._check_updates_silently)
        self._sync_enabled()

    # ------------------------------------------------------------------ UI --

    def _build_ui(self) -> None:
        root = QVBoxLayout(self)
        root.setContentsMargins(22, 18, 22, 16)
        root.setSpacing(12)

        root.addLayout(self._build_header())
        root.addWidget(self._build_player(), 1)
        root.addLayout(self._build_timeline())
        root.addLayout(self._build_transport())
        root.addWidget(self._build_metadata_card())
        root.addLayout(self._build_footer())

        self.status_label = QLabel("Klaar om een mediabestand te openen.")
        self.status_label.setObjectName("Status")
        self.info_label = QLabel("")
        self.info_label.setObjectName("Info")
        self.info_label.setAlignment(Qt.AlignRight | Qt.AlignVCenter)

        footer = QHBoxLayout()
        footer.addWidget(self.status_label, 1)
        footer.addWidget(self.info_label, 0)

        self.progress = QProgressBar()
        self.progress.setTextVisible(False)
        self.progress.setRange(0, 1000)
        self.progress.setValue(0)
        self.progress.hide()

        root.addLayout(footer)
        root.addWidget(self.progress)

    def _build_header(self) -> QHBoxLayout:
        header = QHBoxLayout()
        header.setSpacing(12)

        self.logo_label = QLabel()
        self.logo_label.setFixedSize(42, 42)
        logo_path = _asset("branding", "logo.png")
        if logo_path:
            self.logo_label.setPixmap(
                QPixmap(logo_path).scaled(42, 42, Qt.KeepAspectRatio, Qt.SmoothTransformation)
            )
        header.addWidget(self.logo_label)

        titles = QVBoxLayout()
        titles.setSpacing(1)
        name = QLabel("Media Metadata Editor")
        name.setObjectName("AppName")
        subtitle = QLabel("Bekijk en bewerk titel, artiest, album, genre en jaar")
        subtitle.setObjectName("AppSub")
        titles.addWidget(name)
        titles.addWidget(subtitle)
        header.addLayout(titles)
        header.addStretch(1)

        self.update_btn = QPushButton("Update beschikbaar")
        self.update_btn.setObjectName("Update")
        self.update_btn.setCursor(Qt.PointingHandCursor)
        self.update_btn.clicked.connect(self._on_update_clicked)
        self.update_btn.hide()
        header.addWidget(self.update_btn)

        self.version_label = QLabel(f"v{VERSION}")
        self.version_label.setObjectName("Chip")
        header.addWidget(self.version_label, 0, Qt.AlignVCenter)
        return header

    def _build_player(self) -> QWidget:
        frame = QFrame()
        frame.setObjectName("PlayerFrame")
        self.player_frame = frame
        layout = QStackedLayout(frame)
        layout.setContentsMargins(0, 0, 0, 0)

        self.video = VideoSurface(frame)
        self.video.clicked.connect(self.toggle_play)
        self.video.double_clicked.connect(self.toggle_fullscreen)
        self.video.dropped.connect(self.open_path)

        self.poster_label = QLabel()
        self.poster_label.setObjectName("Poster")
        self.poster_label.setAlignment(Qt.AlignCenter)
        self.poster_label.setMinimumHeight(240)

        self.hint_label = QLabel(
            "Sleep een video of audiobestand hierheen\nof klik op ‘Open media’"
        )
        self.hint_label.setObjectName("Hint")
        self.hint_label.setAlignment(Qt.AlignCenter)
        self.hint_box = QWidget()
        self.hint_box.setObjectName("HintBox")
        self.hint_box.setAttribute(Qt.WA_StyledBackground, True)
        hint_layout = QVBoxLayout(self.hint_box)
        hint_layout.setContentsMargins(26, 26, 26, 26)
        hint_layout.addWidget(self.hint_label)

        layout.addWidget(self.video)
        layout.addWidget(self.poster_label)
        layout.addWidget(self.hint_box)
        layout.setCurrentWidget(self.hint_box)
        self.player_layout = layout
        return frame

    def _build_timeline(self) -> QHBoxLayout:
        row = QHBoxLayout()
        row.setSpacing(10)
        self.position_label = QLabel("00:00")
        self.position_label.setObjectName("Info")
        self.position_label.setFixedWidth(48)
        self.duration_label = QLabel("00:00")
        self.duration_label.setObjectName("Info")
        self.duration_label.setFixedWidth(48)
        self.duration_label.setAlignment(Qt.AlignRight | Qt.AlignVCenter)

        self.timeline = QSlider(Qt.Horizontal)
        self.timeline.setRange(0, 0)
        self.timeline.sliderPressed.connect(self._on_slider_pressed)
        self.timeline.sliderReleased.connect(self._on_slider_released)
        self.timeline.sliderMoved.connect(self._on_slider_moved)

        row.addWidget(self.position_label)
        row.addWidget(self.timeline, 1)
        row.addWidget(self.duration_label)
        return row

    def _build_transport(self) -> QHBoxLayout:
        row = QHBoxLayout()
        row.setSpacing(6)

        self.open_btn = QPushButton("Open media")
        self.open_btn.setCursor(Qt.PointingHandCursor)
        self.open_btn.clicked.connect(self.open_file_dialog)

        self.back_btn = QPushButton()
        self.back_btn.setIcon(_icon("back", 16))
        self.back_btn.setToolTip("5 seconden terug (←)")
        self.back_btn.setObjectName("IconButton")
        self.back_btn.clicked.connect(lambda: self.seek_relative(-5000))

        self.play_btn = QPushButton()
        self.play_btn.setObjectName("Round")
        self.play_btn.setFixedSize(40, 40)
        self.play_btn.setIcon(_icon("play", 18, "#ffffff"))
        self.play_btn.setIconSize(QSize(18, 18))
        self.play_btn.setCursor(Qt.PointingHandCursor)
        self.play_btn.setToolTip("Afspelen / pauzeren (spatiebalk)")
        self.play_btn.clicked.connect(self.toggle_play)

        self.forward_btn = QPushButton()
        self.forward_btn.setIcon(_icon("forward", 16))
        self.forward_btn.setToolTip("5 seconden vooruit (→)")
        self.forward_btn.setObjectName("IconButton")
        self.forward_btn.clicked.connect(lambda: self.seek_relative(5000))

        self.mute_btn = QPushButton()
        self.mute_btn.setIcon(_icon("volume", 16))
        self.mute_btn.setObjectName("IconButton")
        self.mute_btn.setToolTip("Geluid aan/uit")
        self.mute_btn.clicked.connect(self.toggle_mute)

        self.volume = QSlider(Qt.Horizontal)
        self.volume.setObjectName("Volume")
        self.volume.setRange(0, 100)
        self.volume.setValue(80)
        self.volume.setFixedWidth(90)
        self.volume.setToolTip("Volume")
        self.volume.valueChanged.connect(self._on_volume_changed)

        self.fullscreen_btn = QPushButton()
        self.fullscreen_btn.setIcon(_icon("fullscreen", 16))
        self.fullscreen_btn.setObjectName("IconButton")
        self.fullscreen_btn.setToolTip("Volledig scherm (F11)")
        self.fullscreen_btn.clicked.connect(self.toggle_fullscreen)

        self.read_btn = QPushButton("Lees metadata")
        self.read_btn.setCursor(Qt.PointingHandCursor)
        self.read_btn.clicked.connect(self.read_metadata)

        self.save_as_btn = QPushButton("Opslaan als…")
        self.save_as_btn.setCursor(Qt.PointingHandCursor)
        self.save_as_btn.clicked.connect(lambda: self.save_metadata(save_as=True))

        self.save_btn = QPushButton("Opslaan")
        self.save_btn.setObjectName("Primary")
        self.save_btn.setCursor(Qt.PointingHandCursor)
        self.save_btn.setToolTip("Metadata in dit bestand opslaan (Ctrl+S)")
        self.save_btn.clicked.connect(lambda: self.save_metadata(save_as=False))

        for widget in (self.open_btn, self.back_btn, self.play_btn, self.forward_btn,
                       self.mute_btn, self.fullscreen_btn, self.read_btn,
                       self.save_as_btn, self.save_btn):
            widget.setFocusPolicy(Qt.NoFocus)

        row.addWidget(self.open_btn)
        row.addSpacing(6)
        row.addWidget(self.back_btn)
        row.addWidget(self.play_btn)
        row.addWidget(self.forward_btn)
        row.addSpacing(6)
        row.addWidget(self.mute_btn)
        row.addWidget(self.volume)
        row.addWidget(self.fullscreen_btn)
        row.addStretch(1)
        row.addWidget(self.read_btn)
        row.addWidget(self.save_as_btn)
        row.addWidget(self.save_btn)
        return row

    def _build_metadata_card(self) -> QWidget:
        card = QFrame()
        card.setObjectName("Card")
        outer = QVBoxLayout(card)
        outer.setContentsMargins(16, 12, 16, 14)
        outer.setSpacing(8)

        title = QLabel("METADATA")
        title.setObjectName("SectionTitle")
        outer.addWidget(title)

        grid = QGridLayout()
        grid.setHorizontalSpacing(14)
        grid.setVerticalSpacing(4)
        self.edits: dict[str, QLineEdit] = {}
        labels = {
            "title": "Titel",
            "artist": "Artiest",
            "album": "Album",
            "genre": "Genre",
            "year": "Jaar",
            "comment": "Commentaar / labels (komma-gescheiden)",
        }
        placeholders = {
            "title": "Naam van het fragment",
            "artist": "Maker of artiest",
            "album": "Album of serie",
            "genre": "Bijv. Documentaire",
            "year": "Bijv. 2026",
            "comment": "Bijv. klant, locatie, versie",
        }
        positions = {"title": (0, 0), "artist": (0, 1), "album": (0, 2),
                     "genre": (1, 0), "year": (1, 1), "comment": (2, 0)}
        for key, (row, col) in positions.items():
            label = QLabel(labels[key])
            label.setObjectName("FieldLabel")
            edit = QLineEdit()
            edit.setPlaceholderText(placeholders[key])
            edit.setClearButtonEnabled(True)
            edit.returnPressed.connect(lambda: self.save_metadata(save_as=False))
            self.edits[key] = edit
            grid.addWidget(label, row * 2, col)
            grid.addWidget(edit, row * 2 + 1, col)
        grid.setColumnStretch(0, 1)
        grid.setColumnStretch(1, 1)
        grid.setColumnStretch(2, 1)
        grid.setRowMinimumHeight(1, 32)
        grid.setRowMinimumHeight(3, 32)
        grid.setRowMinimumHeight(5, 32)
        # Commentaar over de volle breedte.
        grid.addWidget(self.edits["comment"], 5, 0, 1, 3)
        outer.addLayout(grid)
        return card

    def _build_footer(self) -> QHBoxLayout:
        return QHBoxLayout()

    # ------------------------------------------------------------- speler --

    def _wire_player(self) -> None:
        self.player = QMediaPlayer(None, QMediaPlayer.VideoSurface)
        self.player.setVideoOutput(self.video)
        self.player.setVolume(self.volume.value())
        self.player.positionChanged.connect(self._on_position)
        self.player.durationChanged.connect(self._on_duration)
        self.player.stateChanged.connect(self._on_state)
        self.player.error.connect(self._on_player_error)

    def _on_position(self, position: int) -> None:
        if not self._seeking:
            self.timeline.setValue(position)
        self.position_label.setText(core.format_duration(position))

    def _on_duration(self, duration: int) -> None:
        self.timeline.setRange(0, max(0, duration))
        self.duration_label.setText(core.format_duration(duration))
        if duration and not self.info:
            self.info_label.setText(core.format_duration(duration))

    def _on_state(self, state) -> None:
        playing = state == QMediaPlayer.PlayingState
        self.play_btn.setIcon(_icon("pause", 18, "#ffffff") if playing else _icon("play", 18, "#ffffff"))
        if playing and not self._playback_started:
            self._playback_started = True
            self.player_layout.setCurrentWidget(self.video)

    def _on_player_error(self, *_args) -> None:
        if self.player.error() == QMediaPlayer.NoError:
            return
        message = self.player.errorString() or "Onbekende fout"
        self.set_status(f"Kan dit bestand niet afspelen: {message}")
        if self.media_path:
            self.player_layout.setCurrentWidget(self.poster_label)

    def _on_slider_pressed(self) -> None:
        self._seeking = True

    def _on_slider_moved(self, value: int) -> None:
        self.position_label.setText(core.format_duration(value))

    def _on_slider_released(self) -> None:
        self.player.setPosition(self.timeline.value())
        self._seeking = False

    def _on_volume_changed(self, value: int) -> None:
        self.player.setVolume(value)
        self.mute_btn.setIcon(_icon("muted" if value == 0 else "volume", 16))

    def toggle_play(self) -> None:
        if not self.media_path:
            self.open_file_dialog()
            return
        if self.player.state() == QMediaPlayer.PlayingState:
            self.player.pause()
        else:
            self.player.play()

    def toggle_mute(self) -> None:
        self.volume.setValue(0 if self.volume.value() > 0 else 80)

    def seek_relative(self, delta_ms: int) -> None:
        if not self.media_path:
            return
        duration = max(0, self.player.duration())
        target = min(max(0, self.player.position() + delta_ms), duration or 0)
        self.player.setPosition(target)
        self.timeline.setValue(target)

    def toggle_fullscreen(self) -> None:
        if self.isFullScreen():
            self.showNormal()
            self.fullscreen_btn.setIcon(_icon("fullscreen", 16))
        else:
            self.showFullScreen()
            self.fullscreen_btn.setIcon(_icon("fullscreen", 16, "#ffffff"))

    # ------------------------------------------------------------- bestand --

    def open_file_dialog(self) -> None:
        patterns = " ".join(f"*{ext}" for ext in core.SUPPORTED_EXTS)
        path, _ = QFileDialog.getOpenFileName(
            self, "Selecteer video of audio", "",
            f"Media-bestanden ({patterns});;Alle bestanden (*)",
        )
        if path:
            self.open_path(path)

    def open_path(self, path: str) -> None:
        if not path or not Path(path).is_file():
            return
        if not core.is_supported(path):
            self.notify(
                "warning", "Bestandstype niet ondersteund",
                "Dit bestandstype wordt niet ondersteund.\n"
                f"Wel: {', '.join(core.SUPPORTED_EXTS)}",
            )
            return
        self.media_path = path
        self._playback_started = False
        self.info = None
        self.player.setMedia(QMediaContent(QUrl.fromLocalFile(path)))
        self._load_poster(path)
        self.read_metadata()
        self.setFocus(Qt.OtherFocusReason)
        self.set_status(f"Geopend: {Path(path).name}")
        self._sync_enabled()

    def _load_poster(self, path: str) -> None:
        self.player_layout.setCurrentWidget(self.poster_label)
        # Qt cachet QPixmap op bestandsnaam; elke bron krijgt daarom een eigen
        # bestandsnaam, anders blijft de poster van het vorige bestand staan.
        try:
            stamp = Path(path).stat().st_mtime_ns
        except OSError:
            stamp = 0
        poster_file = Path(self._tempdir) / f"poster-{abs(hash((path, stamp)))}.png"
        old_file = getattr(self, "_poster_file", None)
        if old_file and old_file != poster_file:
            Path(old_file).unlink(missing_ok=True)

        poster = core.poster_image(path, poster_file)
        if poster:
            self._poster_file = poster
            self._poster_pixmap = QPixmap(poster)
            self._apply_poster()
        else:
            self._poster_file = None
            self._poster_pixmap = None
            self.poster_label.setPixmap(QPixmap())
            self.poster_label.setText(Path(path).name)

    def _apply_poster(self) -> None:
        if not self._poster_pixmap or self._poster_pixmap.isNull():
            return
        area = self.poster_label.size()
        if area.width() < 20 or area.height() < 20:
            return
        self.poster_label.setPixmap(
            self._poster_pixmap.scaled(area, Qt.KeepAspectRatio, Qt.SmoothTransformation)
        )

    def resizeEvent(self, event):
        super().resizeEvent(event)
        self._apply_poster()

    # ------------------------------------------------------------ metadata --

    def current_values(self) -> dict:
        return {key: edit.text().strip() for key, edit in self.edits.items()}

    def set_values(self, values: dict) -> None:
        for key, edit in self.edits.items():
            edit.setStyleSheet("")
            edit.setText(values.get(key, "") or "")

    def read_metadata(self) -> None:
        if not self.media_path:
            return
        try:
            self.info = core.probe(self.media_path)
        except (core.FFmpegMissing, core.MediaError) as exc:
            self.set_status(str(exc), error=True)
            self.notify("critical", "Kan metadata niet lezen", str(exc))
            return
        self.set_values(self.info.fields())
        self.info_label.setText(self.info.summary())
        duration = self.info.duration_ms
        if duration:
            self.timeline.setRange(0, duration)
            self.duration_label.setText(core.format_duration(duration))
        self._sync_enabled()

    def save_metadata(self, save_as: bool = False) -> None:
        if not self.media_path or self._worker:
            return
        values = self.current_values()
        target = self.media_path
        if save_as:
            source = Path(self.media_path)
            suggested = str(source.with_name(f"{source.stem}-met-tags{source.suffix}"))
            chosen, _ = QFileDialog.getSaveFileName(
                self, "Sla media op als", suggested,
                f"Media-bestanden (*{source.suffix});;Alle bestanden (*)",
            )
            if not chosen:
                return
            if Path(chosen).suffix.lower() != source.suffix.lower():
                chosen += source.suffix
            target = chosen

        self._set_busy(True)
        self.set_status("Metadata opslaan…")
        worker = Worker(core.write_tags, self.media_path, target, values)
        worker.progress.connect(self._on_progress)
        worker.done.connect(lambda result: self._on_saved(result, values, target))
        worker.failed.connect(self._on_save_failed)
        worker.finished.connect(lambda: self._set_busy(False))
        self._worker = worker
        worker.start()

    def _on_progress(self, value: float) -> None:
        self.progress.show()
        self.progress.setValue(int(value * 1000))

    def _on_saved(self, result: core.MediaInfo, values: dict, target: str) -> None:
        self._worker = None
        self.progress.hide()
        self.progress.setValue(0)
        matches = core.tags_match(values, result)
        missing = [name for name, ok in matches.items() if not ok]
        for key, edit in self.edits.items():
            edit.setStyleSheet(self._unverified_style if key in missing else "")
        elapsed = result.tags.pop("_elapsed_s", "")
        if elapsed:
            elapsed = elapsed.replace(".", ",")
        self.media_path = target
        self.info = result
        self.info_label.setText(result.summary())
        suffix = f" in {elapsed} s" if elapsed else ""
        if missing:
            self.set_status(
                f"Opgeslagen{suffix}, maar {len(missing)} veld(en) niet door de container "
                f"overgenomen: {', '.join(missing)}.", error=True,
            )
            self._show_save_dialog(missing)
        else:
            self.set_status(
                f"Opgeslagen{suffix} · {len(matches)} van {len(matches)} velden gecontroleerd "
                f"in {Path(target).name}"
            )
        self.player.setMedia(QMediaContent(QUrl.fromLocalFile(target)))
        self._sync_enabled()

    def _show_save_dialog(self, missing: list[str]) -> None:
        self.notify(
            "info", "Metadata opgeslagen",
            "Het bestand is opgeslagen, maar deze velden kon de container niet opslaan:\n\n"
            + "\n".join(f"• {name}" for name in missing)
            + "\n\nDit ligt aan het bestandsformaat, niet aan de app.",
        )

    def _on_save_failed(self, message: str) -> None:
        self._worker = None
        self.progress.hide()
        self.set_status("Opslaan mislukt.", error=True)
        self.notify("critical", "Opslaan mislukt", message)

    def _set_busy(self, busy: bool) -> None:
        for widget in (self.save_btn, self.save_as_btn, self.read_btn, self.open_btn):
            widget.setEnabled(not busy)
        self.progress.setVisible(busy)
        QApplication.setOverrideCursor(Qt.BusyCursor) if busy else QApplication.restoreOverrideCursor()

    def _sync_enabled(self) -> None:
        has_media = bool(self.media_path) and self._worker is None
        for widget in (self.save_btn, self.save_as_btn, self.read_btn,
                       self.play_btn, self.back_btn, self.forward_btn):
            widget.setEnabled(has_media)
        self.timeline.setEnabled(has_media)

    def set_status(self, text: str, error: bool = False) -> None:
        self.status_label.setText(text)
        self.status_label.setStyleSheet(f"color: {'#b91c1c' if error else MUTED}; font-size: 11px;")

    def notify(self, kind: str, title: str, text: str) -> bool:
        """Melding tonen — of alleen loggen als er geen scherm is (CI).

        Zonder deze omweg blijft een modaal venster in een headless run eindeloos
        op een klik wachten. Bij 'question' betekent de returnwaarde "ja".
        """
        if HEADLESS:
            self.set_status(f"{title} — {' '.join(text.split())}", error=kind != "info")
            return False
        if kind == "question":
            answer = QMessageBox.question(
                self, title, text, QMessageBox.Yes | QMessageBox.No, QMessageBox.Yes
            )
            return answer == QMessageBox.Yes
        if kind == "critical":
            QMessageBox.critical(self, title, text)
        elif kind == "warning":
            QMessageBox.warning(self, title, text)
        else:
            QMessageBox.information(self, title, text)
        return True

    # ---------------------------------------------------------------- drop --

    def dragEnterEvent(self, event):
        if event.mimeData().hasUrls():
            urls = event.mimeData().urls()
            if urls and core.is_supported(urls[0].toLocalFile() or urls[0].toString()):
                event.acceptProposedAction()

    def dropEvent(self, event):
        urls = event.mimeData().urls()
        if urls:
            self.open_path(urls[0].toLocalFile() or urls[0].toString())
            event.acceptProposedAction()

    # ------------------------------------------------------------- toetsen --

    def keyPressEvent(self, event):
        key = event.key()
        modifiers = event.modifiers()
        if key == Qt.Key_Escape and self.isFullScreen():
            self.toggle_fullscreen()
            return
        if key == Qt.Key_Space:
            self.toggle_play()
            return
        if key == Qt.Key_Left:
            self.seek_relative(-5000)
            return
        if key == Qt.Key_Right:
            self.seek_relative(5000)
            return
        if key == Qt.Key_Up:
            self.volume.setValue(min(100, self.volume.value() + 5))
            return
        if key == Qt.Key_Down:
            self.volume.setValue(max(0, self.volume.value() - 5))
            return
        if key == Qt.Key_F11 or (key == Qt.Key_F and modifiers == Qt.ControlModifier):
            self.toggle_fullscreen()
            return
        if event.matches(QKeySequence.Open) or (modifiers == Qt.ControlModifier and key == Qt.Key_O):
            self.open_file_dialog()
            return
        if modifiers == Qt.ControlModifier and key == Qt.Key_S:
            self.save_metadata(save_as=False)
            return
        if modifiers == (Qt.ControlModifier | Qt.ShiftModifier) and key == Qt.Key_S:
            self.save_metadata(save_as=True)
            return
        super().keyPressEvent(event)

    def closeEvent(self, event):
        if self._worker and self._worker.isRunning():
            self._worker.cancel()
            self._worker.wait(3000)
        self.player.stop()
        super().closeEvent(event)

    # -------------------------------------------------------------- update --

    def _check_updates_silently(self) -> None:
        worker = Worker(updater.check_for_update, VERSION, wants_progress=False)
        worker.done.connect(self._on_update_checked)
        worker.failed.connect(lambda message: self.set_status(f"Updatecontrole: {message}", error=True))
        self._update_worker = worker
        worker.start()

    def _on_update_checked(self, info) -> None:
        self._update_worker = None
        if info.available:
            self._update_info = info
            self.update_btn.setText(f"Update naar v{info.latest}")
            self.update_btn.show()
            self.set_status(f"Er is een nieuwe versie beschikbaar: {info.latest}")

    def _on_update_clicked(self) -> None:
        info = self._update_info
        if not info:
            return
        notes = f"\n\n{info.notes}" if info.notes else ""
        proceed = self.notify(
            "question", "Bijwerken",
            f"Versie {info.latest} is beschikbaar (je hebt {VERSION}).{notes}\n\n"
            "Nu downloaden en installeren? De app sluit daarna af en start opnieuw.",
        )
        if not proceed:
            return
        if not updater.is_frozen():
            self.notify(
                "info", "Bijwerken",
                "Deze versie draait vanuit de broncode, niet als installatie. "
                f"Download de nieuwe versie op github.com/{updater.REPO}/releases",
            )
            return
        self._set_busy(True)
        self.set_status(f"Update {info.latest} downloaden…")
        zip_path = Path(tempfile.gettempdir()) / f"mediameta-{info.latest}.zip"
        worker = Worker(updater.download, info, zip_path)
        worker.progress.connect(self._on_progress)
        worker.done.connect(lambda path: self._install_update(path))
        worker.failed.connect(lambda message: (
            self._set_busy(False), self.set_status(message, error=True),
            self.notify("critical", "Bijwerken mislukt", message),
        ))
        self._worker = worker
        worker.start()

    def _install_update(self, zip_path: Path) -> None:
        install_dir, exe_path = updater.install_dirs()
        try:
            if sys.platform == "win32":
                updater.apply_update_windows(Path(zip_path), install_dir, exe_path)
            else:
                updater.apply_update_posix(Path(zip_path), install_dir)
        except Exception as exc:  # noqa: BLE001
            self._set_busy(False)
            self.notify("critical", "Bijwerken mislukt", str(exc))
            return
        self.set_status("Bijwerken gestart. De app sluit nu en start opnieuw.")
        QTimer.singleShot(400, QApplication.quit)


def run(argv: Optional[list[str]] = None) -> int:
    argv = list(sys.argv if argv is None else argv)
    QApplication.setAttribute(Qt.AA_EnableHighDpiScaling, True)
    QApplication.setAttribute(Qt.AA_UseHighDpiPixmaps, True)
    app = QApplication(argv)
    app.setApplicationName(APP_NAME)
    app.setApplicationVersion(VERSION)
    window = MainWindow()
    window.show()
    if len(argv) > 1 and Path(argv[1]).is_file():
        window.open_path(argv[1])
    return app.exec_()
