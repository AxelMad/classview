"""Видеоплеер: libmpv (низкая задержка, работает в X11 и Wayland) с запасным Qt Multimedia."""
import ctypes
import logging

from PySide6.QtCore import QByteArray, Qt, QUrl, Signal
from PySide6.QtGui import QOpenGLContext
from PySide6.QtWidgets import QVBoxLayout, QWidget

log = logging.getLogger(__name__)

try:
    import mpv  # python-mpv; бросает OSError, если нет libmpv
    from PySide6.QtOpenGLWidgets import QOpenGLWidget
    HAVE_MPV = True
except Exception as e:  # noqa: BLE001
    HAVE_MPV = False
    log.info("libmpv недоступна (%s), используется Qt Multimedia", e)


def _gl_proc_address(name: bytes) -> int:
    ctx = QOpenGLContext.currentContext()
    if ctx is not None:
        try:
            addr = ctx.getProcAddress(QByteArray(name))
            if addr:
                return int(addr)
        except Exception:  # noqa: BLE001
            pass
    for lib, fn in (("libEGL.so.1", "eglGetProcAddress"), ("libGL.so.1", "glXGetProcAddressARB")):
        try:
            f = getattr(ctypes.CDLL(lib), fn)
            f.restype = ctypes.c_void_p
            f.argtypes = [ctypes.c_char_p]
            addr = f(name)
            if addr:
                return addr
        except OSError:
            continue
    return 0


if HAVE_MPV:
    class MpvPlayer(QOpenGLWidget):
        started = Signal()
        failed = Signal(str)
        _repaint = Signal()
        _state = Signal(str, object)

        def __init__(self, parent=None):
            super().__init__(parent)
            self._url = None
            self._ctx = None
            self._playing = False
            self._active = False
            self._mpv = mpv.MPV(
                vo="libmpv", profile="low-latency", cache="no", rtsp_transport="tcp",
                ao="pulse", audio_buffer=0.2, mute=False, volume=100,
                network_timeout=10, keep_open="no", idle="yes", osc="no",
                input_default_bindings="no", input_vo_keyboard="no", loglevel="warn")
            self._repaint.connect(self.update, Qt.QueuedConnection)
            self._state.connect(self._on_state, Qt.QueuedConnection)
            self._mpv.observe_property("video-params", lambda n, v: self._state.emit(n, v))
            self._mpv.observe_property("idle-active", lambda n, v: self._state.emit(n, v))

        def initializeGL(self):
            self._gpa = mpv.MpvGlGetProcAddressFn(lambda _c, name: _gl_proc_address(name))
            self._ctx = mpv.MpvRenderContext(
                self._mpv, "opengl", opengl_init_params={"get_proc_address": self._gpa})
            self._ctx.update_cb = self._repaint.emit
            if self._url:
                self._mpv.play(self._url)

        def paintGL(self):
            if self._ctx:
                r = self.devicePixelRatioF()
                self._ctx.render(flip_y=True, opengl_fbo={
                    "w": int(self.width() * r), "h": int(self.height() * r),
                    "fbo": self.defaultFramebufferObject()})

        def _on_state(self, name, value):
            if name == "video-params" and value and not self._playing:
                self._playing = True
                self.started.emit()
            elif name == "idle-active":
                if not value:
                    self._active = True
                elif self._active and self._url:
                    self._active = False
                    was, self._playing = self._playing, False
                    self.failed.emit("Поток прервался" if was else "Панель не отвечает")

        def play(self, url):
            self._url = url
            self._playing = False
            self._active = False
            if self._ctx:
                self._mpv.play(url)

        def stop(self):
            self._url = None
            self._mpv.command("stop")

        def set_volume(self, v):
            self._mpv.volume = v

        def set_muted(self, m):
            self._mpv.mute = bool(m)

        def shutdown(self):
            self._url = None
            if self._ctx:
                self.makeCurrent()
                self._ctx.free()
                self._ctx = None
                self.doneCurrent()
            self._mpv.terminate()


class QtPlayer(QWidget):
    started = Signal()
    failed = Signal(str)

    def __init__(self, parent=None):
        super().__init__(parent)
        from PySide6.QtMultimedia import QAudioOutput, QMediaPlayer
        from PySide6.QtMultimediaWidgets import QVideoWidget
        self._QMP = QMediaPlayer
        self.video = QVideoWidget(self)
        lay = QVBoxLayout(self)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.addWidget(self.video)
        self._audio = QAudioOutput(self)
        self._player = QMediaPlayer(self)
        self._player.setAudioOutput(self._audio)
        self._player.setVideoOutput(self.video)
        self._player.mediaStatusChanged.connect(self._on_status)
        self._player.errorOccurred.connect(lambda _e, s: self.failed.emit(s or "Ошибка потока"))
        self._ok = False

    def _on_status(self, st):
        if st in (self._QMP.MediaStatus.BufferedMedia, self._QMP.MediaStatus.LoadedMedia) and not self._ok:
            self._ok = True
            self.started.emit()
        elif st in (self._QMP.MediaStatus.EndOfMedia, self._QMP.MediaStatus.InvalidMedia):
            self.failed.emit("Поток прервался" if self._ok else "Панель не отвечает")
            self._ok = False

    def play(self, url):
        self._ok = False
        self._player.setSource(QUrl(url))
        self._player.play()

    def stop(self):
        if self._player:
            self._player.stop()

    def set_volume(self, v):
        self._audio.setVolume(v / 100)

    def set_muted(self, m):
        self._audio.setMuted(bool(m))

    def shutdown(self):
        if self._player is None:
            return
        self._player.stop()
        self._player.setSource(QUrl())
        self._player.setVideoOutput(None)
        self._player.setAudioOutput(None)
        self._player.deleteLater()
        self._player = None


def make_player(parent=None):
    if HAVE_MPV:
        try:
            return MpvPlayer(parent)
        except Exception as e:  # noqa: BLE001
            log.warning("mpv не запустился (%s), переключаюсь на Qt Multimedia", e)
    return QtPlayer(parent)
