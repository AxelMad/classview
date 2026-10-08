"""Диалоги: панель, настройки."""
from PySide6.QtWidgets import (QDialog, QDialogButtonBox, QFileDialog, QFormLayout, QHBoxLayout,
                               QLineEdit, QMessageBox, QPushButton, QSpinBox, QWidget)

from .naming import parse_hostname


class PanelDialog(QDialog):
    def __init__(self, parent=None, panel=None):
        super().__init__(parent)
        self.setWindowTitle("Панель" if panel else "Новая панель")
        self.hostname = QLineEdit()
        self.hostname.setPlaceholderText("p<школа>-<корпус>-<кабинет>-0")
        self.corpus = QLineEdit()
        self.room = QLineEdit()
        self.ip = QLineEdit()
        self.ip.setPlaceholderText("пусто — брать из справочника")
        self.note = QLineEdit()
        form = QFormLayout(self)
        form.addRow("Имя хоста", self.hostname)
        form.addRow("Корпус", self.corpus)
        form.addRow("Кабинет", self.room)
        form.addRow("IP-адрес", self.ip)
        form.addRow("Заметка", self.note)
        bb = QDialogButtonBox(QDialogButtonBox.Save | QDialogButtonBox.Cancel)
        bb.accepted.connect(self._accept)
        bb.rejected.connect(self.reject)
        form.addRow(bb)
        self.hostname.textEdited.connect(self._autofill)
        if panel:
            for k in ("hostname", "corpus", "room", "ip", "note"):
                getattr(self, k).setText(panel[k])

    def _autofill(self, text):
        p = parse_hostname(text)
        if p:
            self.corpus.setText(p[1])
            self.room.setText(p[2])

    def _accept(self):
        if not self.hostname.text().strip():
            QMessageBox.warning(self, "Панель", "Укажите имя хоста")
            return
        self.accept()

    def values(self):
        return {k: getattr(self, k).text().strip() for k in ("hostname", "corpus", "room", "ip", "note")}


class SettingsDialog(QDialog):
    def __init__(self, cfg, parent=None):
        super().__init__(parent)
        self.cfg = cfg
        self.setWindowTitle("Настройки")
        self.setMinimumWidth(480)
        self.school = QLineEdit(cfg.school_id)
        self.school.setPlaceholderText("напр. 1747 (пусто — любая школа)")
        self.port = QSpinBox()
        self.port.setRange(1, 65535)
        self.port.setValue(cfg.rtsp_port)
        self.user = QLineEdit(cfg.rtsp_user)
        self.password = QLineEdit(cfg.rtsp_password)
        self.password.setEchoMode(QLineEdit.Password)
        self.view_path = QLineEdit(cfg.view_path)
        self.record_path = QLineEdit(cfg.record_path)
        self.rec_dir = QLineEdit(cfg.recordings_dir)
        browse = QPushButton("…")
        browse.clicked.connect(self._browse)
        row = QHBoxLayout()
        row.setContentsMargins(0, 0, 0, 0)
        row.addWidget(self.rec_dir)
        row.addWidget(browse)
        rec_w = QWidget()
        rec_w.setLayout(row)
        self.retention = QSpinBox()
        self.retention.setRange(0, 3650)
        self.retention.setSuffix(" дн. (0 — не удалять)")
        self.retention.setValue(cfg.retention_days)
        self.dir_url = QLineEdit(cfg.directory_url)
        self.dir_url.setPlaceholderText("http://адрес-справочника:порт")
        self.dir_token = QLineEdit(cfg.directory_token)
        self.dir_token.setEchoMode(QLineEdit.Password)
        self.interval = QSpinBox()
        self.interval.setRange(5, 3600)
        self.interval.setSuffix(" с")
        self.interval.setValue(cfg.status_interval_sec)

        form = QFormLayout(self)
        form.addRow("Номер школы", self.school)
        form.addRow("RTSP-порт панелей", self.port)
        form.addRow("Логин потоков", self.user)
        form.addRow("Пароль потоков", self.password)
        form.addRow("Путь просмотра", self.view_path)
        form.addRow("Путь записи", self.record_path)
        form.addRow("Папка записей", rec_w)
        form.addRow("Хранить записи", self.retention)
        form.addRow("Справочник filedrop", self.dir_url)
        form.addRow("Токен справочника", self.dir_token)
        form.addRow("Проверка статуса", self.interval)
        bb = QDialogButtonBox(QDialogButtonBox.Save | QDialogButtonBox.Cancel)
        bb.accepted.connect(self._save)
        bb.rejected.connect(self.reject)
        form.addRow(bb)

    def _browse(self):
        d = QFileDialog.getExistingDirectory(self, "Папка записей", self.rec_dir.text())
        if d:
            self.rec_dir.setText(d)

    def _save(self):
        c = self.cfg
        c.school_id = self.school.text().strip()
        c.rtsp_port = self.port.value()
        c.rtsp_user = self.user.text().strip()
        c.rtsp_password = self.password.text()
        c.view_path = self.view_path.text().strip().strip("/") or "cam"
        c.record_path = self.record_path.text().strip().strip("/") or "rec"
        c.recordings_dir = self.rec_dir.text().strip()
        c.retention_days = self.retention.value()
        c.directory_url = self.dir_url.text().strip()
        c.directory_token = self.dir_token.text().strip()
        c.status_interval_sec = self.interval.value()
        c.save()
        self.accept()
