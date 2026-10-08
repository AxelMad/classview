"""Окно просмотра одной панели: видео, звук, запись."""
from datetime import datetime
from pathlib import Path

from PySide6.QtCore import QEvent, Qt, Signal
from PySide6.QtGui import QKeySequence, QShortcut
from PySide6.QtWidgets import (QHBoxLayout, QLabel, QMessageBox, QPushButton, QSlider,
                               QVBoxLayout, QWidget)

from .player import make_player
from .recorder import Recorder


def fmt_size(n: int) -> str:
    for unit in ("Б", "КБ", "МБ", "ГБ"):
        if n < 1024 or unit == "ГБ":
            return f"{n:.0f} {unit}" if unit == "Б" else f"{n:.1f} {unit}"
        n /= 1024


def fmt_dur(s: int) -> str:
    return f"{s // 3600:02d}:{s % 3600 // 60:02d}:{s % 60:02d}"


class ViewerWindow(QWidget):
    closed = Signal(str)            # hostname
    recording_changed = Signal()

    def __init__(self, panel, view_url, rec_url, cfg, db, operator):
        super().__init__(None, Qt.Window)
        self.setAttribute(Qt.WA_DeleteOnClose)
        self.panel, self.view_url, self.rec_url = panel, view_url, rec_url
        self.cfg, self.db, self.operator = cfg, db, operator
        self.host = panel["hostname"]
        self._rec_id = None
        title = f"Кабинет {panel['room'] or '?'}"
        if panel["corpus"]:
            title += f" · корпус {panel['corpus']}"
        self.setWindowTitle(f"{title} — {self.host}")

        self.player = make_player(self)
        self.player.setMinimumSize(320, 180)
        self.player.installEventFilter(self)
        if hasattr(self.player, "video"):
            self.player.video.installEventFilter(self)

        self.state = QLabel("Подключение…")
        self.btn_retry = QPushButton("Переподключить")
        self.btn_retry.hide()
        self.btn_mute = QPushButton("Звук вкл")
        self.btn_mute.setCheckable(True)
        self.vol = QSlider(Qt.Horizontal)
        self.vol.setRange(0, 100)
        self.vol.setValue(80)
        self.vol.setFixedWidth(120)
        self.btn_full = QPushButton("Во весь экран")
        self.btn_rec = QPushButton("● Запись")
        self.btn_rec.setCheckable(True)
        self.btn_rec.setEnabled(False)
        self.rec_info = QLabel("")

        bar = QHBoxLayout()
        bar.addWidget(self.state)
        bar.addWidget(self.btn_retry)
        bar.addStretch(1)
        bar.addWidget(self.rec_info)
        bar.addWidget(self.btn_rec)
        bar.addSpacing(12)
        bar.addWidget(self.btn_mute)
        bar.addWidget(self.vol)
        bar.addWidget(self.btn_full)
        self.bar = QWidget()
        self.bar.setLayout(bar)

        lay = QVBoxLayout(self)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.setSpacing(0)
        lay.addWidget(self.player, 1)
        lay.addWidget(self.bar)

        self.recorder = Recorder(self)
        self.player.started.connect(self._on_started)
        self.player.failed.connect(self._on_failed)
        self.btn_retry.clicked.connect(self._connect)
        self.btn_mute.toggled.connect(self._on_mute)
        self.vol.valueChanged.connect(self.player.set_volume)
        self.btn_full.clicked.connect(self.toggle_fullscreen)
        self.btn_rec.toggled.connect(self._on_rec_toggled)
        self.recorder.started.connect(self._rec_started)
        self.recorder.stopped.connect(self._rec_stopped)
        self.recorder.failed.connect(self._rec_failed)
        self.recorder.tick.connect(lambda s, b: self.rec_info.setText(f"{fmt_dur(s)}  {fmt_size(b)}"))
        QShortcut(QKeySequence("F"), self, self.toggle_fullscreen)
        QShortcut(QKeySequence("Esc"), self, lambda: self.isFullScreen() and self.toggle_fullscreen())
        QShortcut(QKeySequence("R"), self, lambda: self.btn_rec.isEnabled() and self.btn_rec.toggle())

        self.resize(1024, 640)
        self.player.set_volume(self.vol.value())
        self.db.log_event(operator, self.host, "connect")
        self._connect()

    # --- подключение ---
    def _connect(self):
        self.btn_retry.hide()
        self.state.setText("Подключение…")
        self.player.play(self.view_url)

    def _on_started(self):
        self.state.setText("● В эфире")
        self.state.setStyleSheet("color:#2e9d4a; font-weight:bold")
        self.btn_rec.setEnabled(True)

    def _on_failed(self, msg):
        self.state.setText(msg)
        self.state.setStyleSheet("color:#c0392b")
        self.btn_retry.show()
        if self.recorder.active:
            self.recorder.stop()
        self.btn_rec.setEnabled(False)
        self.db.log_event(self.operator, self.host, "error", msg)

    def _on_mute(self, muted):
        self.player.set_muted(muted)
        self.btn_mute.setText("Звук выкл" if muted else "Звук вкл")

    # --- запись ---
    def _on_rec_toggled(self, on):
        if on and not self.recorder.active:
            folder = Path(self.cfg.recordings_dir) / f"{self.panel['corpus'] or 'x'}-{self.panel['room'] or self.host}"
            name = f"{self.host}_{datetime.now():%Y-%m-%d_%H-%M-%S}.mp4"
            if not self.recorder.start(self.rec_url, str(folder / name)):
                self.btn_rec.setChecked(False)
        elif not on and self.recorder.active:
            self.recorder.stop()

    def _rec_started(self, path):
        self._rec_id = self.db.add_recording(self.host, path, self.operator)
        self.db.log_event(self.operator, self.host, "rec_start", path)
        self.btn_rec.setText("■ Стоп")
        self.btn_rec.setStyleSheet("color:#c0392b; font-weight:bold")
        self.rec_info.setText("00:00:00")
        self.recording_changed.emit()

    def _finish_rec(self):
        if self._rec_id is not None:
            self.db.finish_recording(self._rec_id)
            self._rec_id = None
        self.btn_rec.blockSignals(True)
        self.btn_rec.setChecked(False)
        self.btn_rec.blockSignals(False)
        self.btn_rec.setText("● Запись")
        self.btn_rec.setStyleSheet("")
        self.recording_changed.emit()

    def _rec_stopped(self, path):
        self.db.log_event(self.operator, self.host, "rec_stop", path)
        self._finish_rec()
        self.rec_info.setText("Сохранено")

    def _rec_failed(self, path, msg):
        self.db.log_event(self.operator, self.host, "rec_error", msg)
        self._finish_rec()
        self.rec_info.setText("")
        QMessageBox.warning(self, "Запись", f"Запись прервана:\n{msg}")

    # --- окно ---
    def toggle_fullscreen(self):
        if self.isFullScreen():
            self.showNormal()
            self.bar.show()
        else:
            self.bar.hide()
            self.showFullScreen()

    def eventFilter(self, obj, ev):
        if ev.type() == QEvent.MouseButtonDblClick:
            self.toggle_fullscreen()
            return True
        return super().eventFilter(obj, ev)

    def closeEvent(self, ev):
        if self.recorder.active:
            if QMessageBox.question(self, "Идёт запись",
                                    "Остановить запись и закрыть окно?") != QMessageBox.Yes:
                ev.ignore()
                return
            self.recorder.stop()
        self.player.shutdown()
        self.db.log_event(self.operator, self.host, "disconnect")
        self.closed.emit(self.host)
        super().closeEvent(ev)


