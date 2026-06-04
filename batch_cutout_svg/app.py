from __future__ import annotations

import sys

from PySide6.QtGui import QIcon
from PySide6.QtWidgets import QApplication

from batch_cutout_svg.ui.main_window import APP_ICON_PATH, MainWindow, log_unhandled_exception, resource_path


def main() -> None:
    app = QApplication.instance() or QApplication(sys.argv)
    app.setWindowIcon(QIcon(str(resource_path(APP_ICON_PATH))))
    sys.excepthook = log_unhandled_exception
    window = MainWindow()
    window.show()
    raise SystemExit(app.exec())


if __name__ == "__main__":
    main()
