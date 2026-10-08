"""Главное окно: панели, архив записей, журнал."""
import csv
import getpass
import os
import time
from datetime import datetime
from pathlib import Path

from PySide6.QtCore import QObject, QRunnable, Qt, QThreadPool, QTimer, QUrl, Signal
from PySide6.QtGui import QAction, QColor, QDesktopServices, QGuiApplication, QIcon
from PySide6.QtWidgets import (QAbstractItemView, QComboBox, QFileDialog, QHBoxLayout, QHeaderView,
                               QLabel, QLineEdit, QMainWindow, QMessageBox, QPushButton,
                               QTableWidget, QTableWidgetItem, QTabWidget, QToolBar, QVBoxLayout,
                               QWidget)

from . import __version__
from .dialogs import PanelDialog, SettingsDialog
from .naming import parse_hostname
from .resolver import port_open, resolve, stream_url
from .viewer import ViewerWindow, fmt_dur, fmt_size

EVENTS = {"connect": "Подключение", "disconnect": "Отключение", "error": "Ошибка связи",
          "rec_start": "Запись: старт", "rec_stop": "Запись: стоп", "rec_error": "Запись: сбой"}
GREEN, GREY, BLUE = QColor("#2e9d4a"), QColor("#9a9a9a"), QColor("#2f6fd0")


class _Signals(QObject):
    result = Signal(str, str, bool)   # hostname, ip, online


class _CheckJob(QRunnable):
    def __init__(self, sig, host, ip, cfg):
        super().__init__()
        self.sig, self.host, self.ip, self.cfg = sig, host, ip, cfg

    def run(self):
        ip = self.ip
        if self.cfg.directory_url:
            ip = resolve(self.host, self.cfg.directory_url, self.cfg.directory_token) or ip
        self.sig.result.emit(self.host, ip or "", port_open(ip, self.cfg.rtsp_port))


def _table(headers):
    t = QTableWidget(0, len(headers))
    t.setHorizontalHeaderLabels(headers)
    t.setSelectionBehavior(QAbstractItemView.SelectRows)
    t.setSelectionMode(QAbstractItemView.SingleSelection)
    t.setEditTriggers(QAbstractItemView.NoEditTriggers)
    t.verticalHeader().hide()
    t.setAlternatingRowColors(True)
    t.horizontalHeader().setStretchLastSection(True)
    return t


def _item(text, data=None):
    it = QTableWidgetItem(str(text))
    if data is not None:
        it.setData(Qt.UserRole, data)
    return it


class MainWindow(QMainWindow):
    def __init__(self, cfg, db):
        super().__init__()
        self.cfg, self.db = cfg, db
        self.operator = getpass.getuser()
        self.viewers = {}      # hostname -> ViewerWindow
        self.status = {}       # hostname -> True/False
        self.pool = QThreadPool(self)
        self.pool.setMaxThreadCount(16)
        self.sig = _Signals()
        self.sig.result.connect(self._on_status)
        self.setWindowTitle(f"ClassView {__version__} — камеры панелей")
        self.setWindowIcon(QIcon.fromTheme("camera-web"))
        self.resize(1000, 640)

        self.tabs = QTabWidget()
        self.tabs.addTab(self._build_panels_tab(), "Панели")
        self.tabs.addTab(self._build_archive_tab(), "Архив записей")
        self.tabs.addTab(self._build_log_tab(), "Журнал")
        self.tabs.currentChanged.connect(self._on_tab)
        self.setCentralWidget(self.tabs)
        self._build_toolbar()
        self.statusBar().showMessage(f"Оператор: {self.operator}")

        self.timer = QTimer(self)
        self.timer.timeout.connect(self.check_status)
        self._restart_timer()
        self.cleanup_old_recordings()
        self.refresh_panels()
        QTimer.singleShot(300, self.check_status)

    # ---------- UI ----------
    def _build_toolbar(self):
        tb = QToolBar("Действия")
        tb.setMovable(False)
        tb.setToolButtonStyle(Qt.ToolButtonTextBesideIcon)
        self.addToolBar(tb)

        def act(text, icon, slot, shortcut=None):
            a = QAction(QIcon.fromTheme(icon), text, self)
            a.triggered.connect(slot)
            if shortcut:
                a.setShortcut(shortcut)
            tb.addAction(a)
            return a

        act("Подключиться", "media-playback-start", self.connect_selected, "Return")
        tb.addSeparator()
        act("Добавить", "list-add", self.add_panel, "Ctrl+N")
        act("Изменить", "document-edit", self.edit_panel, "F2")
        act("Удалить", "list-remove", self.delete_panel, "Del")
        act("Импорт CSV", "document-import", self.import_csv)
        tb.addSeparator()
        act("Обновить статус", "view-refresh", self.check_status, "F5")
        act("Настройки", "configure", self.open_settings)

    def _build_panels_tab(self):
        w = QWidget()
        self.corpus_filter = QComboBox()
        self.corpus_filter.currentIndexChanged.connect(self._apply_filter)
        self.search = QLineEdit()
        self.search.setPlaceholderText("Поиск: кабинет, имя, заметка")
        self.search.textChanged.connect(self._apply_filter)
        top = QHBoxLayout()
        top.addWidget(QLabel("Корпус:"))
        top.addWidget(self.corpus_filter)
        top.addWidget(self.search, 1)
        self.panels_table = _table(["", "Корпус", "Кабинет", "Имя хоста", "IP-адрес", "Заметка"])
        h = self.panels_table.horizontalHeader()
        h.setSectionResizeMode(0, QHeaderView.ResizeToContents)
        for c in (1, 2, 3, 4):
            h.setSectionResizeMode(c, QHeaderView.ResizeToContents)
        self.panels_table.doubleClicked.connect(lambda *_: self.connect_selected())
        lay = QVBoxLayout(w)
        lay.addLayout(top)
        lay.addWidget(self.panels_table)
        return w

    def _build_archive_tab(self):
        w = QWidget()
        self.archive_table = _table(["Кабинет", "Начало", "Длительность", "Размер", "Оператор", "Файл"])
        self.archive_table.doubleClicked.connect(lambda *_: self.open_recording())
        btns = QHBoxLayout()
        for text, slot in (("Открыть", self.open_recording), ("Показать в папке", self.show_in_folder),
                           ("Удалить", self.delete_recording), ("Обновить", self.refresh_archive)):
            b = QPushButton(text)
            b.clicked.connect(slot)
            btns.addWidget(b)
        btns.addStretch(1)
        lay = QVBoxLayout(w)
        lay.addLayout(btns)
        lay.addWidget(self.archive_table)
        return w

    def _build_log_tab(self):
        w = QWidget()
        self.log_table = _table(["Время", "Оператор", "Панель", "Событие", "Подробности"])
        lay = QVBoxLayout(w)
        lay.addWidget(self.log_table)
        return w

    def _on_tab(self, idx):
        if idx == 1:
            self.refresh_archive()
        elif idx == 2:
            self.refresh_log()

    # ---------- панели ----------
    def refresh_panels(self):
        panels = self.db.panels()
        cur = self.corpus_filter.currentData()
        self.corpus_filter.blockSignals(True)
        self.corpus_filter.clear()
        self.corpus_filter.addItem("Все", None)
        for c in sorted({p["corpus"] for p in panels if p["corpus"]}, key=lambda x: (len(x), x)):
            self.corpus_filter.addItem(c, c)
        i = self.corpus_filter.findData(cur)
        self.corpus_filter.setCurrentIndex(max(i, 0))
        self.corpus_filter.blockSignals(False)

        t = self.panels_table
        sel = self.selected_host()
        t.setRowCount(len(panels))
        for r, p in enumerate(panels):
            t.setItem(r, 0, _item("●", p["hostname"]))
            t.setItem(r, 1, _item(p["corpus"]))
            t.setItem(r, 2, _item(p["room"]))
            t.setItem(r, 3, _item(p["hostname"]))
            t.setItem(r, 4, _item(p["ip"]))
            t.setItem(r, 5, _item(p["note"]))
            self._paint_status(r)
            if p["hostname"] == sel:
                t.selectRow(r)
        self._apply_filter()

    def _row_of(self, host):
        t = self.panels_table
        for r in range(t.rowCount()):
            if t.item(r, 0).data(Qt.UserRole) == host:
                return r
        return -1

    def _paint_status(self, row):
        host = self.panels_table.item(row, 0).data(Qt.UserRole)
        it = self.panels_table.item(row, 0)
        if host in self.viewers:
            it.setForeground(BLUE)
            it.setToolTip("Открыт просмотр")
        elif self.status.get(host):
            it.setForeground(GREEN)
            it.setToolTip("В сети")
        else:
            it.setForeground(GREY)
            it.setToolTip("Недоступна" if host in self.status else "Статус неизвестен")

    def _apply_filter(self):
        corpus = self.corpus_filter.currentData()
        q = self.search.text().strip().lower()
        t = self.panels_table
        for r in range(t.rowCount()):
            ok = corpus is None or t.item(r, 1).text() == corpus
            if ok and q:
                ok = any(q in t.item(r, c).text().lower() for c in (2, 3, 4, 5))
            t.setRowHidden(r, not ok)

    def selected_host(self):
        rows = self.panels_table.selectionModel().selectedRows() if self.panels_table.selectionModel() else []
        return self.panels_table.item(rows[0].row(), 0).data(Qt.UserRole) if rows else None

    def add_panel(self):
        d = PanelDialog(self)
        if d.exec():
            v = d.values()
            if self.db.panel(v["hostname"]) and QMessageBox.question(
                    self, "Панель", "Такая панель уже есть. Перезаписать?") != QMessageBox.Yes:
                return
            self.db.save_panel(**v)
            self.refresh_panels()
            self.check_status()

    def edit_panel(self):
        host = self.selected_host()
        if not host:
            return
        d = PanelDialog(self, self.db.panel(host))
        if d.exec():
            self.db.save_panel(**d.values(), old_hostname=host)
            self.refresh_panels()

    def delete_panel(self):
        host = self.selected_host()
        if host and QMessageBox.question(self, "Удаление", f"Удалить панель {host} из списка?") == QMessageBox.Yes:
            self.db.delete_panel(host)
            self.status.pop(host, None)
            self.refresh_panels()

    def import_csv(self):
        path, _ = QFileDialog.getOpenFileName(self, "Импорт панелей", str(Path.home()),
                                              "CSV (*.csv *.txt);;Все файлы (*)")
        if not path:
            return
        added = skipped = 0
        with open(path, newline="", encoding="utf-8-sig") as f:
            for row in csv.reader(f):
                if not row or not row[0].strip() or row[0].strip().startswith("#"):
                    continue
                host = row[0].strip()
                parsed = parse_hostname(host, self.cfg.school_id)
                if not parsed or not parsed or parsed[0] != "p":
                    skipped += 1
                    continue
                ip = row[1].strip() if len(row) > 1 else ""
                self.db.import_panel(host, parsed[1], parsed[2], ip)
                added += 1
        self.refresh_panels()
        self.check_status()
        QMessageBox.information(self, "Импорт", f"Панелей загружено: {added}\nПропущено строк: {skipped}\n"
                                "(берутся только панели — имена вида p<школа>-…)")

    # ---------- статус ----------
    def _restart_timer(self):
        self.timer.start(max(5, int(self.cfg.status_interval_sec)) * 1000)

    def check_status(self):
        for p in self.db.panels():
            self.pool.start(_CheckJob(self.sig, p["hostname"], p["ip"], self.cfg))

    def _on_status(self, host, ip, online):
        self.status[host] = online
        row = self._row_of(host)
        if row < 0:
            return
        if ip and ip != self.panels_table.item(row, 4).text():
            self.db.set_ip(host, ip)
            self.panels_table.item(row, 4).setText(ip)
        self._paint_status(row)

    # ---------- просмотр ----------
    def connect_selected(self):
        host = self.selected_host()
        if not host:
            return
        if host in self.viewers:
            w = self.viewers[host]
            w.showNormal()
            w.raise_()
            w.activateWindow()
            return
        p = self.db.panel(host)
        ip = p["ip"]
        if self.cfg.directory_url:
            QGuiApplication.setOverrideCursor(Qt.WaitCursor)
            try:
                fresh = resolve(host, self.cfg.directory_url, self.cfg.directory_token)
            finally:
                QGuiApplication.restoreOverrideCursor()
            if fresh and fresh != ip:
                self.db.set_ip(host, fresh)
                p["ip"] = ip = fresh
                self.refresh_panels()
        if not ip:
            QMessageBox.warning(self, "Подключение", "IP-адрес панели неизвестен: укажите его вручную "
                                "или настройте справочник.")
            return
        if not self.cfg.rtsp_password:
            QMessageBox.warning(self, "Подключение", "Не задан пароль потоков (Настройки).")
            return
        w = ViewerWindow(p, stream_url(self.cfg, ip, self.cfg.view_path),
                         stream_url(self.cfg, ip, self.cfg.view_path),  # запись по тому же пути, что просмотр
                         self.cfg, self.db, self.operator)
        w.closed.connect(self._viewer_closed)
        w.recording_changed.connect(self.refresh_archive)
        self.viewers[host] = w
        self._paint_status(self._row_of(host))
        w.show()

    def _viewer_closed(self, host):
        self.viewers.pop(host, None)
        r = self._row_of(host)
        if r >= 0:
            self._paint_status(r)
        self.refresh_log()

    # ---------- архив ----------
    def refresh_archive(self):
        rooms = {p["hostname"]: (p["corpus"], p["room"]) for p in self.db.panels()}
        recs = self.db.recordings()
        t = self.archive_table
        t.setRowCount(len(recs))
        for r, rec in enumerate(recs):
            corpus, room = rooms.get(rec["hostname"], ("", ""))
            label = f"{room} (корп. {corpus})" if room else rec["hostname"]
            dur = "идёт запись" if rec["stopped"] is None else fmt_dur(int(rec["stopped"] - rec["started"]))
            try:
                size = fmt_size(os.path.getsize(rec["path"]))
            except OSError:
                size = "нет файла"
            t.setItem(r, 0, _item(label, rec["id"]))
            t.setItem(r, 1, _item(datetime.fromtimestamp(rec["started"]).strftime("%d.%m.%Y %H:%M:%S")))
            t.setItem(r, 2, _item(dur))
            t.setItem(r, 3, _item(size))
            t.setItem(r, 4, _item(rec["operator"]))
            t.setItem(r, 5, _item(rec["path"], rec["path"]))
        t.resizeColumnsToContents()

    def _selected_rec(self):
        rows = self.archive_table.selectionModel().selectedRows()
        if not rows:
            return None, None
        r = rows[0].row()
        return self.archive_table.item(r, 0).data(Qt.UserRole), self.archive_table.item(r, 5).data(Qt.UserRole)

    def open_recording(self):
        _, path = self._selected_rec()
        if path and os.path.exists(path):
            QDesktopServices.openUrl(QUrl.fromLocalFile(path))

    def show_in_folder(self):
        _, path = self._selected_rec()
        if path:
            QDesktopServices.openUrl(QUrl.fromLocalFile(str(Path(path).parent)))

    def delete_recording(self):
        rec_id, path = self._selected_rec()
        if rec_id is None:
            return
        if any(v.recorder.active and v._rec_id == rec_id for v in self.viewers.values()):
            QMessageBox.warning(self, "Архив", "Эта запись ещё идёт.")
            return
        if QMessageBox.question(self, "Удаление", f"Удалить запись?\n{path}") != QMessageBox.Yes:
            return
        try:
            os.remove(path)
        except FileNotFoundError:
            pass
        except OSError as e:
            QMessageBox.warning(self, "Удаление", str(e))
            return
        self.db.delete_recording(rec_id)
        self.refresh_archive()

    def cleanup_old_recordings(self):
        days = int(self.cfg.retention_days)
        if days <= 0:
            return
        for rec in self.db.recordings_before(time.time() - days * 86400):
            try:
                os.remove(rec["path"])
            except OSError:
                pass
            self.db.delete_recording(rec["id"])

    # ---------- журнал ----------
    def refresh_log(self):
        rows = self.db.log_entries()
        t = self.log_table
        t.setRowCount(len(rows))
        for r, e in enumerate(rows):
            t.setItem(r, 0, _item(datetime.fromtimestamp(e["ts"]).strftime("%d.%m.%Y %H:%M:%S")))
            t.setItem(r, 1, _item(e["operator"]))
            t.setItem(r, 2, _item(e["hostname"]))
            t.setItem(r, 3, _item(EVENTS.get(e["event"], e["event"])))
            t.setItem(r, 4, _item(e["detail"]))
        t.resizeColumnsToContents()

    # ---------- прочее ----------
    def open_settings(self):
        if SettingsDialog(self.cfg, self).exec():
            self._restart_timer()
            self.check_status()

    def closeEvent(self, ev):
        for w in list(self.viewers.values()):
            if not w.close():
                ev.ignore()
                return
        self.pool.clear()
        super().closeEvent(ev)
