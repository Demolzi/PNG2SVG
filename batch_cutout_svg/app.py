from __future__ import annotations

import sys

from PySide6.QtWidgets import QApplication

from batch_cutout_svg.ui.main_window import MainWindow, log_unhandled_exception


def main() -> None:
    app = QApplication.instance() or QApplication(sys.argv)
    sys.excepthook = log_unhandled_exception
    window = MainWindow()
    window.show()
    raise SystemExit(app.exec())


if __name__ == "__main__":
    main()
