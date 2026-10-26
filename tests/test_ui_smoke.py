"""Prueba de humo de la interfaz con MockDriver, en modo offscreen (sin ventanas visibles)."""

from __future__ import annotations

import ast
import json
import os
import re
import string
import time
from collections.abc import Callable, Iterator
from pathlib import Path

import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
QtWidgets = pytest.importorskip("PySide6.QtWidgets", reason="PySide6 no disponible")

from PySide6.QtCore import QSettings  # noqa: E402

from colpo import DeviceDisconnectedError, DiskFullError, RecordingError  # noqa: E402
from colpo.metadata import METADATA_FIELDS, sha256_file  # noqa: E402
from colpo.session import CaptureSession  # noqa: E402
from colpo.ui.app import MainWindow, error_message_key  # noqa: E402
from colpo.ui.i18n import LANGUAGES, Translator, load_catalog  # noqa: E402
from mock_driver import MockDriver  # noqa: E402

UI_DIR = Path(__file__).resolve().parents[1] / "src" / "colpo" / "ui"
TIMESTAMP_RE = re.compile(r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}[+-]\d{2}:\d{2}$")
BANNER_ES = "Prototipo educativo — no validado para diagnóstico clínico"
BANNER_EN = "Educational prototype — not validated for clinical diagnosis"


@pytest.fixture(scope="module")
def qapp():
    return QtWidgets.QApplication.instance() or QtWidgets.QApplication([])


def wait_until(app, predicate: Callable[[], bool], timeout: float = 5.0) -> None:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        app.processEvents()
        if predicate():
            return
        time.sleep(0.01)
    raise AssertionError("Tiempo agotado esperando a la UI")


@pytest.fixture
def make_window(qapp, tmp_path: Path) -> Iterator[Callable[..., MainWindow]]:
    windows: list[MainWindow] = []

    def factory(driver: MockDriver | None = None, **kwargs) -> MainWindow:
        driver = driver or MockDriver()
        kwargs.setdefault("session", CaptureSession(tmp_path / "datos"))
        window = MainWindow(
            list_devices_fn=driver.list_devices,
            camera_factory=driver.camera_factory,
            settings=QSettings(str(tmp_path / "ui.ini"), QSettings.Format.IniFormat),
            **kwargs,
        )
        window.show()
        windows.append(window)
        return window

    yield factory
    for window in windows:
        window.close()


def _connect(qapp, window: MainWindow) -> None:
    window.connect_camera()
    wait_until(qapp, lambda: window._state == "streaming" and window._last_sequence >= 3)


def _json_files(window: MainWindow) -> list[Path]:
    return sorted(window.session.study_dir.glob("*.json"))


# ------------------------------------------------------------------- arranque
def test_window_starts_in_spanish_with_permanent_banner(qapp, make_window) -> None:
    window = make_window()
    assert window.banner_label.text() == BANNER_ES
    assert window.banner_label.isVisible()
    assert window.translator.language == "es"
    items = [window.camera_combo.itemText(i) for i in range(window.camera_combo.count())]
    assert items == ["0 — GOLDCARE GC 3000E (simulada)", "1 — Webcam integrada (simulada)"]
    assert not window.photo_button.isEnabled()
    assert not window.record_button.isEnabled()
    stages = [window.stage_combo.itemText(i) for i in range(window.stage_combo.count())]
    assert stages == ["Basal", "Solución salina", "Ácido acético", "Lugol", "Filtro verde"]


def test_no_cameras(qapp, make_window) -> None:
    window = make_window(MockDriver(names=()))
    assert window.camera_combo.itemText(0) == "No se detectaron cámaras"
    assert not window.connect_button.isEnabled()


# ------------------------------------------------------------ flujo completo
def test_full_capture_flow(qapp, make_window) -> None:
    window = make_window()
    _connect(qapp, window)
    assert re.match(r"320\u00d7240 · \d+\.\d FPS", window.stream_label.text())
    assert window.preview_label.pixmap() is not None and not window.preview_label.pixmap().isNull()

    # Foto en etapa "ácido acético", con notas válidas.
    window.stage_combo.setCurrentIndex(window.stage_combo.findData("acido_acetico"))
    window.notes_edit.setPlainText("Maniquí de práctica, ZT tipo 1")
    window.photo_button.click()
    wait_until(qapp, lambda: len(_json_files(window)) == 1)

    # Grabación ~1 s en etapa "lugol".
    window.stage_combo.setCurrentIndex(window.stage_combo.findData("lugol"))
    window.record_button.click()
    wait_until(qapp, lambda: window._recording)
    assert window.record_button.text() == "Detener grabación (F9)"
    wait_until(qapp, lambda: window.recording_label.text().startswith("● GRABANDO"))
    time.sleep(1.0)
    window.record_button.click()
    wait_until(qapp, lambda: not window._recording and len(_json_files(window)) == 2)
    wait_until(qapp, lambda: "Video guardado" in window.last_capture_label.text())

    photo_json, video_json = (json.loads(p.read_text("utf-8")) for p in _json_files(window))
    for data in (photo_json, video_json):
        assert list(data) == list(METADATA_FIELDS)
        assert data["id_estudio"] == window.session.study_id
        assert TIMESTAMP_RE.match(data["timestamp"])
        assert data["resolucion"] == {"ancho": 320, "alto": 240}
        assert data["fps"] > 0
    assert (photo_json["tipo"], photo_json["etapa_ifcpc"]) == ("foto", "acido_acetico")
    assert photo_json["notas"] == "Maniquí de práctica, ZT tipo 1"
    assert (video_json["tipo"], video_json["etapa_ifcpc"]) == ("video", "lugol")

    for json_path in _json_files(window):
        media = next(
            p for p in json_path.parent.iterdir() if p.stem == json_path.stem and p != json_path
        )
        assert json.loads(json_path.read_text("utf-8"))["sha256"] == sha256_file(media)
    assert window._error is None


def test_language_switch_is_hot_and_keeps_state(qapp, make_window) -> None:
    window = make_window()
    _connect(qapp, window)
    window.stage_combo.setCurrentIndex(window.stage_combo.findData("lugol"))
    window.set_language("en")
    assert window.banner_label.text() == BANNER_EN
    assert window.photo_button.text() == "Photo (F8)"
    assert window.record_button.text() == "Start recording (F9)"
    assert window.connect_button.text() == "Disconnect"
    assert window.stage_combo.currentText() == "Lugol's iodine"
    assert window.session.stage == "lugol"
    assert window._state == "streaming"  # sigue la vista previa
    window.set_language("es")
    assert window.banner_label.text() == BANNER_ES
    assert window.stage_combo.currentText() == "Lugol"


def test_language_choice_is_remembered(qapp, make_window) -> None:
    make_window().set_language("en")
    assert make_window().translator.language == "en"


def test_identifying_notes_are_warned_and_not_saved(qapp, make_window) -> None:
    window = make_window()
    _connect(qapp, window)
    window.notes_edit.setPlainText("DNI 45871236")
    assert window.notes_warning.isVisible()
    assert "NO se guardarán" in window.notes_warning.text()
    window.photo_button.click()
    wait_until(qapp, lambda: len(_json_files(window)) == 1)
    assert json.loads(_json_files(window)[0].read_text("utf-8"))["notas"] is None
    window.notes_edit.setPlainText("Maniquí 2")
    assert not window.notes_warning.isVisible()


def test_new_study_changes_folder(qapp, make_window) -> None:
    window = make_window()
    first = window.session.study_id
    window.new_study_button.click()
    assert window.session.study_id != first
    assert window.session.study_id in window.study_label.text()


# ------------------------------------------------------------------ errores
def test_busy_camera_shows_error(qapp, make_window) -> None:
    window = make_window(MockDriver(busy=True))
    window.connect_camera()
    wait_until(qapp, lambda: window._error is not None and window._state == "disconnected")
    assert window.error_panel.isVisible()
    assert "ocupada por otra aplicación" in window.error_label.text()
    window.set_language("en")
    assert "in use by another application" in window.error_label.text()
    window.dismiss_error()
    assert not window.error_panel.isVisible()


def test_disconnected_camera_shows_error(qapp, make_window) -> None:
    window = make_window(MockDriver(fail_after=20))
    window.connect_camera()
    wait_until(qapp, lambda: window._error is not None and window._state == "disconnected")
    assert "Se perdió la conexión con la cámara" in window.error_label.text()
    assert window.connect_button.text() == "Conectar"


def test_disk_full_shows_error(qapp, make_window, tmp_path: Path) -> None:
    session = CaptureSession(tmp_path / "datos", free_bytes=lambda _p: 1024)
    window = make_window(session=session)
    _connect(qapp, window)
    window.photo_button.click()
    wait_until(qapp, lambda: window._error is not None)
    assert "Disco lleno" in window.error_label.text()
    window.record_button.click()
    wait_until(qapp, lambda: "Espacio insuficiente" in window.error_label.text())
    assert not window._recording
    assert _json_files(window) == []


class _BrokenWriter:
    def __init__(self, *_args: object) -> None:
        pass

    def isOpened(self) -> bool:  # noqa: N802 (API de OpenCV)
        return True

    def write(self, _image: object) -> None:
        raise OSError("fallo de escritura simulado")

    def release(self) -> None:
        pass


def test_recording_failure_shows_error(qapp, make_window) -> None:
    window = make_window(MockDriver(writer_factory=_BrokenWriter))
    _connect(qapp, window)
    window.record_button.click()
    wait_until(qapp, lambda: window._error is not None, timeout=8)
    assert "La grabación falló" in window.error_label.text()
    wait_until(qapp, lambda: not window._recording)
    assert window._state == "streaming"  # la vista previa sigue funcionando


def test_error_message_keys() -> None:
    assert error_message_key(DiskFullError("x"), "photo") == "error.disk_full"
    assert error_message_key(DeviceDisconnectedError("x"), "read") == "error.camera_disconnected"
    assert error_message_key(RecordingError("x"), "video_stop") == "error.recording_failed"


# ----------------------------------------------------- i18n y separación de capas
def test_catalogs_have_same_keys_and_placeholders() -> None:
    catalogs = {lang: load_catalog(lang) for lang in LANGUAGES}
    reference = catalogs["es"]
    formatter = string.Formatter()
    for lang, catalog in catalogs.items():
        assert set(catalog) == set(reference), lang
        for key, text in catalog.items():
            fields = {f for _, f, _, _ in formatter.parse(text) if f}
            expected = {f for _, f, _, _ in formatter.parse(reference[key]) if f}
            assert fields == expected, (lang, key)


def test_translator_falls_back_to_spanish_and_rejects_unknown_language() -> None:
    translator = Translator("en")
    assert translator.tr("clave.inexistente") == "clave.inexistente"
    with pytest.raises(ValueError):
        translator.set_language("fr")


@pytest.mark.parametrize("path", sorted(UI_DIR.rglob("*.py")), ids=lambda p: p.name)
def test_ui_does_not_import_opencv_or_numpy(path: Path) -> None:
    tree = ast.parse(path.read_text(encoding="utf-8"))
    imported: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            imported.update(alias.name.split(".")[0] for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module:
            imported.add(node.module.split(".")[0])
    assert not imported & {"cv2", "numpy"}, f"{path.name} importa {imported & {'cv2', 'numpy'}}"


def test_main_parser() -> None:
    from colpo.ui.app import build_parser

    args = build_parser().parse_args(["--lang", "en", "--data-dir", "x"])
    assert args.lang == "en" and args.data_dir == Path("x")
