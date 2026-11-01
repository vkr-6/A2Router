"""Complete palette-derived themes, including popups, disabled controls and tables."""

import sys

from PySide6.QtCore import Qt
from PySide6.QtGui import QColor, QFont, QPalette
from PySide6.QtWidgets import QApplication

THEMES = {
    "Orange": ("#000000", "#000000", "#000000", "#f5f5f5", "#000000", "#333333", "#ff9600"),
    "White": ("#ffffff", "#ffffff", "#f4f6f8", "#161b22", "#f0f2f5", "#d1d7de", "#3157c8"),
    "Dark": ("#141618", "#1b1e21", "#22262a", "#edf0f2", "#262a2f", "#383e45", "#a9db4e"),
    "Lime": ("#111811", "#19221a", "#202d21", "#eff8e9", "#253527", "#3e5140", "#c2ef62"),
    "Blue": ("#111824", "#192335", "#202e43", "#eff5ff", "#263a55", "#405574", "#83b9ff"),
    "Violet": ("#191522", "#241d32", "#30263f", "#f6f0ff", "#392d4c", "#544469", "#c4a0ff"),
}


def apply_theme(window, name, density):
    app = QApplication.instance()
    if name == "Light":
        name = "White"  # Migrate the previous preference without touching profiles.
    if name == "System":
        name = "Dark" if app.styleHints().colorScheme() == Qt.ColorScheme.Dark else "White"
    bg, base, alternate, text, button, border, accent = THEMES.get(name, THEMES["Orange"])
    selected_text = "#000000" if name == "Orange" else "#101510" if name != "White" else "#ffffff"
    muted = "#90989f" if name != "White" else "#68717c"
    palette = QPalette()
    for role, color in [
        (QPalette.Window, bg),
        (QPalette.Base, base),
        (QPalette.AlternateBase, alternate),
        (QPalette.WindowText, text),
        (QPalette.Text, text),
        (QPalette.Button, button),
        (QPalette.ButtonText, text),
        (QPalette.Highlight, accent),
        (QPalette.HighlightedText, selected_text),
        (QPalette.ToolTipBase, base),
        (QPalette.ToolTipText, text),
        (QPalette.Mid, border),
        (QPalette.PlaceholderText, muted),
    ]:
        palette.setColor(role, QColor(color))
    for role in (QPalette.Text, QPalette.WindowText, QPalette.ButtonText):
        palette.setColor(QPalette.Disabled, role, QColor(muted))
    if app.style().objectName().lower() != "fusion":
        app.setStyle("Fusion")
    app.setPalette(palette)
    window.setPalette(palette)
    window.setFont(QFont("Segoe UI" if sys.platform == "win32" else "DejaVu Sans", 9))
    padding = 2 if density == "Extra compact" else 4
    window.setStyleSheet(f"""
        QWidget {{ background: {bg}; color: {text}; }}
        QMenuBar, QMenu, QToolBar, QStatusBar {{ background: {bg}; color: {text}; }}
        QMenu::item {{ padding: 5px 24px; }}
        QMenu::item:selected, QMenuBar::item:selected {{ background: {accent}; color: {selected_text}; }}
        QAbstractItemView, QPlainTextEdit, QLineEdit, QComboBox, QSpinBox, QDoubleSpinBox {{
            background: {base}; color: {text}; border: 1px solid {border}; border-radius: 3px;
            selection-background-color: {accent}; selection-color: {selected_text}; }}
        QAbstractItemView {{ alternate-background-color: {alternate}; }}
        QLineEdit, QComboBox, QSpinBox, QDoubleSpinBox {{ min-height: 22px; padding: 1px 4px; }}
        QPushButton, QToolButton {{ background: {button}; color: {text}; border: 1px solid {border};
            border-radius: 3px; padding: 4px 10px; min-height: 18px; }}
        QPushButton:hover, QToolButton:hover {{ border-color: {accent}; }}
        QPushButton:checked, QToolButton:checked {{ background: {accent}; color: {selected_text}; }}
        QPushButton:pressed, QToolButton:pressed {{ background: {accent}; color: {selected_text}; }}
        QToolButton {{ padding: 2px 10px; }}
        QWidget:disabled {{ color: {muted}; }}
        QHeaderView::section {{ background: {button}; color: {text}; border: 0; padding: 5px; }}
        QTreeView::item {{ padding: {padding}px 3px; }}
        QGroupBox {{ border: 1px solid {border}; border-radius: 4px; margin-top: 10px; padding-top: 10px; }}
        QGroupBox::title {{ subcontrol-origin: margin; left: 8px; padding: 0 4px; }}
        QTabWidget::pane {{ border: 1px solid {border}; }}
        QTabBar::tab {{ background: {button}; color: {text}; padding: 6px 12px; border-bottom: 2px solid transparent; }}
        QTabBar::tab:selected {{ background: {bg}; border-bottom-color: {accent}; }}
        QFrame#DeviceCard {{ border: 1px solid {border}; border-radius: 4px; }}
        QLabel#MutedText {{ color: {muted}; }}
        QLabel#CardTitle, QLabel#SectionTitle {{ font-weight: 600; }}
        QSlider::groove:horizontal {{ background: {border}; height: 4px; }}
        QSlider::sub-page:horizontal {{ background: {accent}; }}
        QSlider::handle:horizontal {{ background: {text}; width: 10px; margin: -4px 0; border-radius: 3px; }}
        QProgressBar {{ border: 1px solid {border}; background: {base}; text-align: center; }}
        QProgressBar::chunk {{ background: {accent}; }}
        QToolTip {{ background: {base}; color: {text}; border: 1px solid {border}; padding: 5px; }}
    """)
