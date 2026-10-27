"""Diálogo de preferencias del usuario (no del estudio)."""

from __future__ import annotations

from PySide6.QtWidgets import (
    QCheckBox,
    QDialog,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QVBoxLayout,
    QWidget,
)

from colpo.ui.i18n import Translator


class PreferencesDialog(QDialog):
    """Preferencias: por ahora, la marca de agua "Uso educativo" (desactivada por defecto)."""

    def __init__(
        self, translator: Translator, *, watermark_enabled: bool, parent: QWidget | None = None
    ) -> None:
        super().__init__(parent)
        t = translator.tr
        self.setWindowTitle(t("prefs.title"))
        layout = QVBoxLayout(self)
        self.watermark_checkbox = QCheckBox(t("prefs.watermark"))
        self.watermark_checkbox.setChecked(watermark_enabled)
        help_label = QLabel(t("prefs.watermark_help"), wordWrap=True)
        help_label.setStyleSheet("color: #555;")
        layout.addWidget(self.watermark_checkbox)
        layout.addWidget(help_label)
        buttons = QHBoxLayout()
        buttons.addStretch(1)
        self.ok_button = QPushButton(t("prefs.ok"))
        self.cancel_button = QPushButton(t("prefs.cancel"))
        self.ok_button.setDefault(True)
        self.ok_button.clicked.connect(self.accept)
        self.cancel_button.clicked.connect(self.reject)
        buttons.addWidget(self.ok_button)
        buttons.addWidget(self.cancel_button)
        layout.addLayout(buttons)

    @property
    def watermark_enabled(self) -> bool:
        return self.watermark_checkbox.isChecked()
