"""Aplicación de escritorio Open Colposcope (F3: multi-dispositivo).

Esta capa solo presenta y recoge acciones. Los dispositivos llegan del
**registro de drivers** (:mod:`colpo.drivers.registry`) y se abren con
:func:`colpo.live.open_capture`; la UI nunca importa OpenCV ni drivers
concretos (una prueba lo verifica). La captura, el guardado y los metadatos
viven en el núcleo (:mod:`colpo.live`, :mod:`colpo.session`).

Ejecutar: ``colpo-ui`` o ``python -m colpo.ui.app``.
"""

from __future__ import annotations

import argparse
import os
import sys
from pathlib import Path

from PySide6.QtCore import QEvent, QSettings, Qt, QTimer, QUrl
from PySide6.QtGui import QCloseEvent, QDesktopServices, QFont, QKeySequence, QShortcut
from PySide6.QtWidgets import (
    QApplication,
    QComboBox,
    QFrame,
    QGroupBox,
    QHBoxLayout,
    QLabel,
    QMainWindow,
    QPlainTextEdit,
    QPushButton,
    QSizePolicy,
    QStackedWidget,
    QTabWidget,
    QToolButton,
    QVBoxLayout,
    QWidget,
)

from colpo import __version__, storage
from colpo.capture import CaptureCamera
from colpo.devices import DeviceInfo, available_backends
from colpo.drivers.base import Capabilities
from colpo.drivers.errors import CameraNotFound, FormatNotSupported
from colpo.drivers.registry import DriverRegistry, default_registry
from colpo.errors import (
    BackendUnavailableError,
    ColpoError,
    DeviceDisconnectedError,
    DeviceOpenError,
    DiskFullError,
    MetadataError,
    NotesRejectedError,
    RecordingError,
    SnapshotError,
)
from colpo.live import FILE_BACKEND, Captured, Failed, LiveEvent, open_capture
from colpo.metadata import IFCPC_STAGES
from colpo.session import CaptureSession
from colpo.ui.device_tab import DeviceChoice, DeviceTab
from colpo.ui.i18n import DEFAULT_LANGUAGE, LANGUAGES, Translator
from colpo.ui.preferences import PreferencesDialog
from colpo.watermark import WatermarkOptions

PREVIEW_INTERVAL_MS = 15  # sondeo del último frame (> 60 Hz: no se pierde ninguno a 30 FPS)
DEMO_ENV = "COLPO_MOCK_DEVICES"  # lo lee el driver simulado (sin importarlo desde la UI)

_BANNER_STYLE = (
    "#disclaimerBanner { background: #FFF3CD; color: #5C4400; border: 1px solid #E0A800;"
    " padding: 6px; font-weight: bold; }"
)
_ERROR_STYLE = "#errorPanel { background: #FDECEA; border: 1px solid #E57373; }"
_ERROR_TEXT_STYLE = "color: #611A15;"
_NOTES_WARNING_STYLE = "color: #B71C1C;"
_CAPS_STYLE = "color: #444;"


def error_message_key(error: ColpoError, action: str) -> str:
    """Clave de traducción del mensaje principal para un error del núcleo o de un driver."""
    if isinstance(error, DiskFullError) or storage.is_disk_full_error(error):
        return "error.disk_full"
    if isinstance(error, DeviceDisconnectedError):
        return "error.camera_disconnected"
    if isinstance(error, FormatNotSupported):
        return "error.format"
    if isinstance(error, CameraNotFound):
        return "error.camera_not_found"
    if isinstance(error, DeviceOpenError) or action == "open":
        return "error.camera_busy"
    if isinstance(error, BackendUnavailableError):
        return "error.backend"
    if isinstance(error, MetadataError):
        return "error.metadata"
    if isinstance(error, RecordingError) or action.startswith("video"):
        return "error.recording_failed"
    if isinstance(error, SnapshotError) or action == "photo":
        return "error.photo_failed"
    return "error.generic"


def capabilities_summary(caps: Capabilities, translator: Translator) -> str:
    """Resumen de una línea de las capacidades de un dispositivo."""
    t = translator.tr

    def flag(value: bool | None) -> str:
        return t("caps.unknown") if value is None else t("caps.yes" if value else "caps.no")

    modes = []
    for w, h in caps.resoluciones_soportadas:
        fps = caps.fps_por_resolucion.get((w, h))
        rates = f" @{'/'.join(f'{f:g}' for f in fps)}" if fps else ""
        modes.append(f"{w}\u00d7{h}{rates}")
    return t(
        "caps.summary",
        uvc=t("caps.uvc_yes" if caps.es_uvc else "caps.uvc_no"),
        resolutions=", ".join(modes) or t("caps.unknown_modes"),
        formats=", ".join(caps.formatos_pixel) or t("caps.unknown"),
        zoom=flag(caps.tiene_control_zoom),
        brightness=flag(caps.tiene_control_brillo),
        wb=flag(caps.tiene_control_balance_blancos),
    )


class MainWindow(QMainWindow):
    """Ventana principal con pestañas, una por dispositivo abierto.

    Args:
        data_dir: carpeta de datos (por defecto ``~/OpenColposcope``).
        registry: registro de drivers (por defecto, el de los *entry points*).
        settings: preferencias del usuario (idioma, API, última cámara, marca de agua).
        language: idioma inicial; si no, el guardado; si no, español.
        demo_source: video que se ofrece como "cámara" de demostración.
        session: sesión de captura (por defecto, una nueva en ``data_dir``).
    """

    def __init__(
        self,
        *,
        data_dir: Path | None = None,
        registry: DriverRegistry | None = None,
        settings: QSettings | None = None,
        language: str | None = None,
        demo_source: Path | None = None,
        session: CaptureSession | None = None,
    ) -> None:
        super().__init__()
        self._settings = settings or QSettings("OpenColposcope", "OpenColposcope")
        initial = language or str(self._settings.value("language", DEFAULT_LANGUAGE))
        self.translator = Translator(initial if initial in LANGUAGES else DEFAULT_LANGUAGE)
        self.registry = registry or default_registry()
        self._demo_source = demo_source
        self.session = session or CaptureSession(data_dir or storage.default_data_dir())

        self.choices: list[DeviceChoice] = []
        self._error: tuple[str, str] | None = None
        self._last_capture: tuple[str, dict[str, object]] | None = None
        self._notes_reasons: tuple[str, ...] = ()

        self._build_ui()
        self._apply_watermark_setting(self.watermark_enabled)
        self.refresh_devices()
        self._retranslate()

        self._timer = QTimer(self)
        self._timer.timeout.connect(self._refresh_tabs)
        self._timer.start(PREVIEW_INTERVAL_MS)

    # ------------------------------------------------------------- interfaz
    def _build_ui(self) -> None:
        central = QWidget()
        root = QVBoxLayout(central)

        self.banner_label = QLabel(objectName="disclaimerBanner")
        self.banner_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.banner_label.setWordWrap(True)
        self.banner_label.setStyleSheet(_BANNER_STYLE)
        root.addWidget(self.banner_label)

        self.error_panel = QFrame(objectName="errorPanel")
        self.error_panel.setStyleSheet(_ERROR_STYLE)
        error_layout = QHBoxLayout(self.error_panel)
        self.error_label = QLabel(wordWrap=True)
        self.error_label.setStyleSheet(_ERROR_TEXT_STYLE)
        self.error_label.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
        self.error_close_button = QToolButton(text="✕")  # ✕
        self.error_close_button.clicked.connect(self.dismiss_error)
        error_layout.addWidget(self.error_label, 1)
        error_layout.addWidget(self.error_close_button, 0, Qt.AlignmentFlag.AlignTop)
        self.error_panel.hide()
        root.addWidget(self.error_panel)

        top = QHBoxLayout()
        self.device_label = QLabel()
        self.device_combo = QComboBox()
        self.device_combo.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
        self.api_label = QLabel()
        self.backend_combo = QComboBox()
        for backend in ("auto", *available_backends()):
            self.backend_combo.addItem(backend, backend)
        saved_backend = self.backend_combo.findData(str(self._settings.value("backend", "auto")))
        self.backend_combo.setCurrentIndex(max(0, saved_backend))
        self.refresh_button = QPushButton()
        self.open_button = QPushButton()
        self.open_new_tab_button = QPushButton()
        self.language_label = QLabel()
        self.language_combo = QComboBox()
        for code, name in LANGUAGES.items():
            self.language_combo.addItem(name, code)
        self.language_combo.setCurrentIndex(self.language_combo.findData(self.translator.language))
        self.preferences_button = QPushButton()
        for widget in (
            self.device_label,
            self.device_combo,
            self.api_label,
            self.backend_combo,
            self.refresh_button,
            self.open_button,
            self.open_new_tab_button,
        ):
            top.addWidget(widget)
        top.addSpacing(16)
        top.addWidget(self.language_label)
        top.addWidget(self.language_combo)
        top.addWidget(self.preferences_button)
        root.addLayout(top)

        self.capabilities_label = QLabel(wordWrap=True)
        self.capabilities_label.setStyleSheet(_CAPS_STYLE)
        root.addWidget(self.capabilities_label)

        body = QHBoxLayout()
        self.tab_widget = QTabWidget()
        self.tab_widget.setTabsClosable(True)
        self.tab_widget.setMovable(True)
        self.placeholder_label = QLabel(alignment=Qt.AlignmentFlag.AlignCenter, wordWrap=True)
        self.placeholder_label.setStyleSheet("background: #111; color: #BBB;")
        self.placeholder_label.setMinimumSize(480, 270)
        self.view_stack = QStackedWidget()
        self.view_stack.addWidget(self.placeholder_label)
        self.view_stack.addWidget(self.tab_widget)
        body.addWidget(self.view_stack, 1)

        panel = QWidget()
        panel.setFixedWidth(320)
        side = QVBoxLayout(panel)
        side.setContentsMargins(0, 0, 0, 0)
        self.study_group = QGroupBox()
        study_layout = QVBoxLayout(self.study_group)
        self.study_label = QLabel()
        self.study_label.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
        self.new_study_button = QPushButton()
        study_layout.addWidget(self.study_label)
        study_layout.addWidget(self.new_study_button)
        side.addWidget(self.study_group)

        self.stage_label = QLabel()
        self.stage_combo = QComboBox()
        for code in IFCPC_STAGES:
            self.stage_combo.addItem(code, code)
        self.stage_combo.setCurrentIndex(self.stage_combo.findData(self.session.stage))
        side.addWidget(self.stage_label)
        side.addWidget(self.stage_combo)

        self.notes_label = QLabel()
        self.notes_edit = QPlainTextEdit()
        self.notes_edit.setMaximumHeight(110)
        self.notes_warning = QLabel(wordWrap=True)
        self.notes_warning.setStyleSheet(_NOTES_WARNING_STYLE)
        self.notes_warning.hide()
        side.addWidget(self.notes_label)
        side.addWidget(self.notes_edit)
        side.addWidget(self.notes_warning)

        self.active_device_label = QLabel(wordWrap=True)
        side.addWidget(self.active_device_label)
        self.photo_button = QPushButton()
        self.record_button = QPushButton()
        for button in (self.photo_button, self.record_button):
            button.setMinimumHeight(44)
            side.addWidget(button)

        self.last_capture_title = QLabel()
        self.last_capture_label = QLabel(wordWrap=True)
        self.open_folder_button = QPushButton()
        side.addSpacing(8)
        side.addWidget(self.last_capture_title)
        side.addWidget(self.last_capture_label)
        side.addWidget(self.open_folder_button)
        side.addStretch(1)
        body.addWidget(panel)
        root.addLayout(body, 1)
        self.setCentralWidget(central)

        self.watermark_status = QLabel()
        self.statusBar().addPermanentWidget(self.watermark_status)

        self.refresh_button.clicked.connect(self.refresh_devices)
        self.backend_combo.currentIndexChanged.connect(self._on_backend_changed)
        self.device_combo.currentIndexChanged.connect(self._render_capabilities)
        self.open_button.clicked.connect(lambda: self.open_selected(new_tab=False))
        self.open_new_tab_button.clicked.connect(lambda: self.open_selected(new_tab=True))
        self.tab_widget.tabCloseRequested.connect(self.close_tab)
        self.tab_widget.currentChanged.connect(lambda _i: self._update_controls())
        self.language_combo.currentIndexChanged.connect(self._on_language_changed)
        self.preferences_button.clicked.connect(self.show_preferences)
        self.new_study_button.clicked.connect(self.new_study)
        self.stage_combo.currentIndexChanged.connect(self._on_stage_changed)
        self.notes_edit.textChanged.connect(self._on_notes_changed)
        self.photo_button.clicked.connect(self.take_photo)
        self.record_button.clicked.connect(self.toggle_recording)
        self.open_folder_button.clicked.connect(self._open_study_folder)
        # Atajos globales: funcionan aunque el foco esté en las notas (y con pedales
        # USB que emulan teclas). Actúan sobre la pestaña activa.
        for key, slot in (("F8", self.take_photo), ("F9", self.toggle_recording)):
            shortcut = QShortcut(QKeySequence(key), self)
            shortcut.setContext(Qt.ShortcutContext.ApplicationShortcut)
            shortcut.activated.connect(slot)

    def _retranslate(self) -> None:
        t = self.translator.tr
        self.setWindowTitle(t("app.title"))
        self.banner_label.setText(t("banner.disclaimer"))
        self.device_label.setText(t("device.label"))
        self.api_label.setText(t("device.api"))
        self.refresh_button.setText(t("device.refresh"))
        self.refresh_button.setToolTip(t("device.refresh_tip"))
        self.open_button.setText(t("device.open"))
        self.open_button.setToolTip(t("device.open_tip"))
        self.open_new_tab_button.setText(t("device.open_new_tab"))
        self.language_label.setText(t("language.label"))
        self.preferences_button.setText(t("prefs.button"))
        self.placeholder_label.setText(t("tabs.placeholder"))
        self.study_group.setTitle(t("study.group"))
        self.new_study_button.setText(t("study.new"))
        self.stage_label.setText(t("stage.label"))
        for row, code in enumerate(IFCPC_STAGES):
            self.stage_combo.setItemText(row, t(f"stage.{code}"))
        self.notes_label.setText(t("notes.label"))
        self.notes_edit.setPlaceholderText(t("notes.placeholder"))
        self.photo_button.setText(t("capture.photo"))
        self.last_capture_title.setText(t("capture.last"))
        self.open_folder_button.setText(t("capture.open_folder"))
        self.error_close_button.setToolTip(t("error.close"))
        self.watermark_status.setText(t("watermark.status"))
        self.session.watermark = WatermarkOptions(
            enabled=self.session.watermark.enabled, text=t("watermark.text")
        )
        self._fill_device_combo()
        for tab in self.tabs():
            tab.retranslate()
        self._render_study()
        self._render_notes_warning()
        self._render_error()
        self._render_last_capture()
        self._update_controls()

    def _update_controls(self) -> None:
        t = self.translator.tr
        tab = self.current_tab()
        streaming = tab is not None and tab.streaming
        recording = tab is not None and tab.recording
        has_device = self._selected_choice() is not None
        self.open_button.setEnabled(has_device)
        self.open_new_tab_button.setEnabled(has_device)
        self.photo_button.setEnabled(streaming)
        self.record_button.setEnabled(streaming)
        self.record_button.setText(
            t("capture.record_stop" if recording else "capture.record_start")
        )
        self.new_study_button.setEnabled(not any(tb.recording for tb in self.tabs()))
        self.active_device_label.setText(
            t("capture.target", device=tab.choice.label(self.translator))
            if tab is not None and tab.choice is not None
            else t("capture.no_target")
        )
        self.view_stack.setCurrentWidget(self.tab_widget if self.tabs() else self.placeholder_label)
        for index, tb in enumerate(self.tabs()):
            self.tab_widget.setTabText(index, tb.title())

    # ---------------------------------------------------------- dispositivos
    def refresh_devices(self) -> None:
        """Vuelve a preguntar a todos los drivers qué dispositivos hay."""
        backend = self.backend_combo.currentData() or "auto"
        try:
            found = self.registry.probe_all(backend=backend)
        except ColpoError as exc:
            found = []
            self.show_error(exc, "enumerate")
        choices = [DeviceChoice(cls.name, device) for cls, device in found]
        if self._demo_source is not None:
            demo = DeviceInfo(
                index=0,
                name=self._demo_source.name,
                backend=FILE_BACKEND,
                path=str(self._demo_source),
                driver="uvc",
            )
            choices.append(DeviceChoice("uvc", demo))
        self.choices = choices
        self._fill_device_combo()
        self._update_controls()

    def _driver_title(self, name: str) -> str:
        key = f"driver.{name}"
        if self.translator.has(key):
            return self.translator.tr(key)
        cls = self.registry.list_drivers().get(name)
        return str(getattr(cls, "display_name", name))

    def _fill_device_combo(self) -> None:
        """Rellena el selector agrupado por driver (cabeceras no seleccionables)."""
        t = self.translator.tr
        previous = self._selected_choice()
        wanted = previous.device.name if previous else str(self._settings.value("last_device", ""))
        combo = self.device_combo
        combo.blockSignals(True)
        combo.clear()
        header_font = QFont()
        header_font.setBold(True)
        first_row = wanted_row = -1
        for driver in dict.fromkeys(c.driver for c in self.choices):
            combo.addItem(self._driver_title(driver), None)
            header = combo.model().item(combo.count() - 1)
            header.setFlags(Qt.ItemFlag.NoItemFlags)
            header.setFont(header_font)
            for position, choice in enumerate(self.choices):
                if choice.driver != driver:
                    continue
                text = f"    {choice.label(self.translator)}  ·  {choice.device.vid_pid}"
                combo.addItem(text, position)
                row = combo.count() - 1
                first_row = row if first_row < 0 else first_row
                if wanted_row < 0 and choice.device.name == wanted:
                    wanted_row = row
        if not self.choices:
            combo.addItem(t("device.none_found"), None)
        combo.setCurrentIndex(max(0, wanted_row if wanted_row >= 0 else first_row))
        combo.blockSignals(False)
        self._render_capabilities()

    def _selected_choice(self) -> DeviceChoice | None:
        if not hasattr(self, "device_combo"):
            return None
        position = self.device_combo.currentData()
        if position is None or not 0 <= position < len(self.choices):
            return None
        return self.choices[position]

    def select_device(self, choice_index: int) -> None:
        """Selecciona ``self.choices[choice_index]`` en el selector."""
        self.device_combo.setCurrentIndex(self.device_combo.findData(choice_index))

    def _render_capabilities(self) -> None:
        choice = self._selected_choice()
        if choice is None:
            self.capabilities_label.setText("")
            return
        try:
            caps = self.registry.describe(choice.driver, choice.device)
        except ColpoError as exc:
            self.capabilities_label.setText(str(exc))
            return
        summary = capabilities_summary(caps, self.translator)
        self.capabilities_label.setText(
            f"[{self._driver_title(choice.driver)}] VID:PID {choice.device.vid_pid} · {summary}"
        )
        self.capabilities_label.setToolTip(caps.notas)
        self._update_controls()

    def _open_camera(self, choice: DeviceChoice) -> CaptureCamera:
        backend = self.backend_combo.currentData() or "auto"
        options = {} if backend == "auto" else {"backend": backend}
        return open_capture(choice.driver, choice.device, registry=self.registry, **options)

    # ---------------------------------------------------------------- pestañas
    def tabs(self) -> list[DeviceTab]:
        return [self.tab_widget.widget(i) for i in range(self.tab_widget.count())]

    def current_tab(self) -> DeviceTab | None:
        widget = self.tab_widget.currentWidget()
        return widget if isinstance(widget, DeviceTab) else None

    def open_selected(self, *, new_tab: bool = False) -> DeviceTab | None:
        """Abre el dispositivo seleccionado en la pestaña actual o en una nueva.

        En la pestaña actual equivale a **cambiar de dispositivo en caliente**:
        se cierra el anterior (guardando un video en curso) y se abre el nuevo.
        """
        choice = self._selected_choice()
        if choice is None:
            return None
        target = None if new_tab else self.current_tab()
        for tab in self.tabs():
            if tab is not target and tab.choice is not None and tab.choice.key == choice.key:
                self._show_message("device.already_open", choice.label(self.translator))
                self.tab_widget.setCurrentWidget(tab)
                return None
        self.dismiss_error()
        if target is None:
            target = DeviceTab(self.translator, self.session, self._open_camera, self._on_tab_event)
            self.tab_widget.addTab(target, "")
        self.tab_widget.setCurrentWidget(target)
        self._settings.setValue("last_device", choice.device.name)
        target.start(choice)
        self._update_controls()
        return target

    def close_tab(self, index: int) -> None:
        tab = self.tab_widget.widget(index)
        if isinstance(tab, DeviceTab):
            tab.stop()
        self.tab_widget.removeTab(index)
        if tab is not None:
            tab.deleteLater()
        self._update_controls()

    def _on_tab_event(self, tab: DeviceTab, event: LiveEvent) -> None:
        if isinstance(event, Captured):
            result = event.result
            name = result.media_path.name
            if result.metadata.tipo == "foto":
                self._last_capture = ("capture.photo_saved", {"name": name})
            else:
                self._last_capture = (
                    "capture.video_saved",
                    {"name": name, "codec": result.codec or "?"},
                )
                if result.frames_dropped:
                    self.statusBar().showMessage(
                        self.translator.tr("capture.frames_dropped", count=result.frames_dropped),
                        10000,
                    )
            self._render_last_capture()
        elif isinstance(event, Failed):
            label = tab.choice.label(self.translator) if tab.choice else ""
            self.show_error(event.error, event.action, device=label)
        self._update_controls()

    def _refresh_tabs(self) -> None:
        current = self.current_tab()
        for tab in self.tabs():
            tab.refresh(paint=tab is current)

    # ------------------------------------------------------------- acciones
    def take_photo(self) -> None:
        tab = self.current_tab()
        if tab is None or not tab.streaming:
            return
        if self._notes_reasons:
            self.statusBar().showMessage(self.translator.tr("capture.notes_skipped"), 8000)
        tab.take_photo()

    def toggle_recording(self) -> None:
        tab = self.current_tab()
        if tab is None or not tab.streaming:
            return
        if not tab.recording and self._notes_reasons:
            self.statusBar().showMessage(self.translator.tr("capture.notes_skipped"), 8000)
        tab.toggle_recording()

    def new_study(self) -> None:
        try:
            study_id = self.session.new_study()
        except ColpoError as exc:
            self.show_error(exc, "study")
            return
        self._last_capture = None
        self._render_study()
        self._render_last_capture()
        self.statusBar().showMessage(self.translator.tr("study.new_done", id=study_id), 5000)

    def _open_study_folder(self) -> None:
        folder = self.session.study_dir
        folder.mkdir(parents=True, exist_ok=True)
        QDesktopServices.openUrl(QUrl.fromLocalFile(str(folder)))

    def _on_backend_changed(self) -> None:
        self._settings.setValue("backend", self.backend_combo.currentData())
        self.refresh_devices()

    def _on_stage_changed(self) -> None:
        code = self.stage_combo.currentData()
        if code:
            self.session.stage = code

    def _on_notes_changed(self) -> None:
        try:
            self.session.set_notes(self.notes_edit.toPlainText())
            self._notes_reasons = ()
        except NotesRejectedError as exc:
            self._notes_reasons = exc.reasons
        self._render_notes_warning()

    def _on_language_changed(self) -> None:
        code = self.language_combo.currentData()
        if code and code != self.translator.language:
            self.translator.set_language(code)
            self._settings.setValue("language", code)
            self._retranslate()

    def set_language(self, code: str) -> None:
        """Cambia el idioma en caliente (equivale a usar el selector)."""
        self.language_combo.setCurrentIndex(self.language_combo.findData(code))

    # ------------------------------------------------------- marca de agua
    @property
    def watermark_enabled(self) -> bool:
        """Preferencia del usuario (no del estudio). Desactivada por defecto."""
        return bool(self._settings.value("watermark_enabled", False, type=bool))

    def set_watermark_enabled(self, enabled: bool) -> None:
        self._settings.setValue("watermark_enabled", bool(enabled))
        self._apply_watermark_setting(bool(enabled))

    def _apply_watermark_setting(self, enabled: bool) -> None:
        self.session.watermark = WatermarkOptions(
            enabled=enabled, text=self.translator.tr("watermark.text")
        )
        self.watermark_status.setText(self.translator.tr("watermark.status"))
        self.watermark_status.setVisible(enabled)

    def preferences_dialog(self) -> PreferencesDialog:
        dialog = PreferencesDialog(
            self.translator, watermark_enabled=self.watermark_enabled, parent=self
        )
        dialog.accepted.connect(lambda: self.set_watermark_enabled(dialog.watermark_enabled))
        return dialog

    def show_preferences(self) -> None:
        self.preferences_dialog().exec()

    # -------------------------------------------------------------- errores
    def show_error(self, error: ColpoError, action: str, *, device: str = "") -> None:
        detail = f"{device}: {error}" if device else str(error)
        self._error = (error_message_key(error, action), detail)
        self._render_error()

    def _show_message(self, key: str, detail: str) -> None:
        self._error = (key, detail)
        self._render_error()

    def dismiss_error(self) -> None:
        self._error = None
        self._render_error()

    def _render_error(self) -> None:
        if self._error is None:
            self.error_panel.hide()
            return
        key, detail = self._error
        t = self.translator.tr
        self.error_label.setText(f"{t(key)}\n{t('error.detail', detail=detail)}")
        self.error_panel.show()

    def _render_study(self) -> None:
        t = self.translator.tr
        self.study_label.setText(t("study.id", id=self.session.study_id))
        self.open_folder_button.setToolTip(t("capture.folder_tip", path=self.session.study_dir))

    def _render_notes_warning(self) -> None:
        if not self._notes_reasons:
            self.notes_warning.hide()
            return
        t = self.translator.tr
        reasons = ", ".join(t(f"notes.reason.{code}") for code in self._notes_reasons)
        self.notes_warning.setText(t("notes.rejected", reasons=reasons))
        self.notes_warning.show()

    def _render_last_capture(self) -> None:
        t = self.translator.tr
        if self._last_capture is None:
            self.last_capture_label.setText(t("capture.none"))
        else:
            key, params = self._last_capture
            self.last_capture_label.setText(t(key, **params))
        self._render_study()

    def closeEvent(self, event: QCloseEvent) -> None:  # noqa: N802 (API de Qt)
        self._timer.stop()
        for tab in self.tabs():
            tab.stop()
        self._settings.sync()
        super().closeEvent(event)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="colpo-ui",
        description="Open Colposcope: interfaz de captura (prototipo educativo, no diagnóstico).",
    )
    parser.add_argument("--version", action="version", version=f"%(prog)s {__version__}")
    parser.add_argument("--lang", choices=tuple(LANGUAGES), help="idioma inicial (es o en)")
    parser.add_argument(
        "--data-dir", type=Path, help="carpeta de datos (por defecto ~/OpenColposcope)"
    )
    parser.add_argument(
        "--source", type=Path, help="video de demostración que se ofrece como cámara"
    )
    parser.add_argument(
        "--demo",
        type=int,
        nargs="?",
        const=2,
        metavar="N",
        help="añade N cámaras simuladas (por defecto 2) para practicar sin hardware",
    )
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    if args.demo:
        os.environ[DEMO_ENV] = str(args.demo)
    app = QApplication.instance() or QApplication([sys.argv[0]])
    app.setApplicationName("Open Colposcope")
    app.setApplicationVersion(__version__)
    window = MainWindow(data_dir=args.data_dir, language=args.lang, demo_source=args.source)
    window.resize(1280, 800)
    window.show()
    code = int(app.exec())
    # Destruir la ventana antes de que PySide desmonte Qt al salir del intérprete:
    # si no, Qt puede destruir widgets con la plataforma ya cerrada (cierre abrupto).
    window.deleteLater()
    app.sendPostedEvents(None, QEvent.Type.DeferredDelete.value)
    return code


if __name__ == "__main__":
    sys.exit(main())
