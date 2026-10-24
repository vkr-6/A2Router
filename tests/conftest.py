"""Keep UI preference tests away from the desktop user's real settings."""

import sys

import pytest


@pytest.fixture(autouse=True)
def isolated_qt_preferences(tmp_path):
    qt = sys.modules.get("PySide6.QtCore")
    if qt is not None:
        qt.QSettings.setDefaultFormat(qt.QSettings.IniFormat)
        qt.QSettings.setPath(qt.QSettings.IniFormat, qt.QSettings.UserScope, str(tmp_path / "qt-preferences"))
