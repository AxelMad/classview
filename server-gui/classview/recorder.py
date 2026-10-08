"""Запись потока через ffmpeg без перекодирования (fragmented MP4 — файл цел даже при сбое)."""
import os
import shutil
import time
from pathlib import Path

from PySide6.QtCore import QObject, QProcess, QTimer, Signal


class Recorder(QObject):
    started = Signal(str)          # путь файла
    stopped = Signal(str)          # путь файла
    failed = Signal(str, str)      # путь, сообщение
    tick = Signal(int, int)        # секунды, байты

    def __init__(self, parent=None):
        super().__init__(parent)
        self._proc = None
        self._path = ""
        self._stopping = False
        self._stderr = b""
        self._t0 = 0.0
        self._timer = QTimer(self)
        self._timer.setInterval(1000)
        self._timer.timeout.connect(self._on_tick)

    @property
    def active(self) -> bool:
        return self._proc is not None

    def start(self, url: str, path: str) -> bool:
        if self._proc:
            return False
        ffmpeg = shutil.which("ffmpeg")
        if not ffmpeg:
            self.failed.emit(path, "Не найден ffmpeg (dnf install ffmpeg)")
            return False
        Path(path).parent.mkdir(parents=True, exist_ok=True)
        args = ["-hide_banner", "-loglevel", "error"]
        if url.startswith("rtsp://"):
            args += ["-rtsp_transport", "tcp"]
        args += ["-i", url, "-map", "0", "-c", "copy", "-strict", "experimental",
                 "-movflags", "+frag_keyframe+empty_moov+default_base_moof", "-flush_packets", "1",
                 "-f", "mp4", "-y", path]
        p = QProcess(self)
        p.setProgram(ffmpeg)
        p.setArguments(args)
        p.readyReadStandardError.connect(self._read_err)
        p.finished.connect(self._on_finished)
        self._proc, self._path, self._stopping, self._stderr = p, path, False, b""
        p.start()
        if not p.waitForStarted(3000):
            self._proc = None
            self.failed.emit(path, "Не удалось запустить ffmpeg")
            return False
        self._t0 = time.monotonic()
        self._timer.start()
        self.started.emit(path)
        return True

    def stop(self):
        p = self._proc
        if not p:
            return
        self._stopping = True
        p.write(b"q")
        p.closeWriteChannel()
        if not p.waitForFinished(5000):
            p.terminate()
            if not p.waitForFinished(2000):
                p.kill()
                p.waitForFinished(1000)

    def _read_err(self):
        if self._proc:
            self._stderr = (self._stderr + bytes(self._proc.readAllStandardError()))[-4000:]

    def _on_tick(self):
        try:
            size = os.path.getsize(self._path)
        except OSError:
            size = 0
        self.tick.emit(int(time.monotonic() - self._t0), size)

    def _on_finished(self, code, _status):
        self._timer.stop()
        path, stopping = self._path, self._stopping
        self._proc = None
        if stopping or code == 0:
            self.stopped.emit(path)
        else:
            msg = self._stderr.decode("utf-8", "replace").strip().splitlines()
            self.failed.emit(path, msg[-1] if msg else f"ffmpeg завершился с кодом {code}")
