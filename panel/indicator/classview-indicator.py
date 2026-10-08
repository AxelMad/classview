#!/usr/bin/env python3
"""Индикатор ClassView в системном трее панели.
Точка: скрыта — никто не подключён; зелёная — идёт просмотр; красная — идёт запись.
Никакого текста на экране. Состояние опрашивается у локального MediaMTX API.
"""
import json
import sys
import urllib.request

from PySide6.QtCore import Qt, QTimer
from PySide6.QtGui import QIcon, QPainter, QPixmap
from PySide6.QtWidgets import QApplication, QSystemTrayIcon

API = "http://127.0.0.1:9997/v3/paths/list"
POLL_MS = 1500
GREEN = "#2e9d4a"
RED = "#d33127"


def dot(color: str) -> QIcon:
    px = QPixmap(64, 64)
    px.fill(Qt.transparent)
    p = QPainter(px)
    p.setRenderHint(QPainter.Antialiasing)
    p.setPen(Qt.NoPen)
    p.setBrush(Qt.white)
    p.drawEllipse(6, 6, 52, 52)          # белая окантовка для видимости на любом фоне
    p.setBrush(color)
    p.drawEllipse(10, 10, 44, 44)
    p.end()
    return QIcon(px)


def poll_state():
    """Возвращает 'rec' | 'view' | 'idle' по числу читателей путей cam/rec."""
    try:
        with urllib.request.urlopen(API, timeout=1.0) as r:
            items = json.load(r).get("items", [])
    except Exception:
        return "idle"
    readers = {}
    for it in items:
        readers[it.get("name")] = len(it.get("readers", []))
    # Запись и просмотр идут по одному пути cam. Сервер при записи открывает ВТОРОЕ
    # подключение к cam, поэтому: 0 читателей — покой, 1 — просмотр, 2+ — идёт запись.
    cam = readers.get("cam", 0)
    if cam >= 2:
        return "rec"
    return "view" if cam == 1 else "idle"


def main():
    app = QApplication(sys.argv)
    app.setQuitOnLastWindowClosed(False)
    if not QSystemTrayIcon.isSystemTrayAvailable():
        # трея нет — тихо выходим, не мешая пользователю
        return 0
    tray = QSystemTrayIcon()
    icons = {"view": dot(GREEN), "rec": dot(RED)}
    state = {"cur": None}

    def refresh():
        s = poll_state()
        if s == state["cur"]:
            return
        state["cur"] = s
        if s == "idle":
            tray.hide()
        else:
            tray.setIcon(icons[s])
            tray.setVisible(True)

    timer = QTimer()
    timer.timeout.connect(refresh)
    timer.start(POLL_MS)
    refresh()
    sys.exit(app.exec())


if __name__ == "__main__":
    main()
