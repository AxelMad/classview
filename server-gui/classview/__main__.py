import locale
import logging
import sys

from PySide6.QtWidgets import QApplication

from .config import Config
from .db import DB
from .mainwindow import MainWindow


def main():
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(name)s: %(message)s")
    app = QApplication(sys.argv)
    app.setApplicationName("classview")
    app.setDesktopFileName("classview")
    locale.setlocale(locale.LC_NUMERIC, "C")  # требование libmpv
    win = MainWindow(Config.load(), DB())
    win.show()
    sys.exit(app.exec())


if __name__ == "__main__":
    main()
