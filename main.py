"""
Application entry point — constructs QApplication, loads QSS theme, and launches MainWindow.
"""
import os
import sys

from PySide6.QtWidgets import QApplication

if __name__ == "__main__":
    # When frozen by PyInstaller, set CWD to the exe directory so that all
    # relative paths (gui/themes, saves/, settings.json, core/data) resolve correctly.
    if getattr(sys, "frozen", False):
        os.chdir(os.path.dirname(sys.executable))

    app = QApplication(sys.argv)

    # app_config must be imported AFTER QApplication is constructed —
    # it reads the primary screen DPI at module level.
    import gui.app_config as app_config
    from gui.main_window import MainWindow

    app_config.load_qss()
    if app_config.raw_qss():
        app.setStyleSheet(app_config.raw_qss())
    else:
        print(f"WARNING: stylesheet not found at '{app_config.THEME_PATH}' — running unstyled.")
    app.setFont(app_config.app_font())

    window = MainWindow()
    window.show()
    sys.exit(app.exec())
