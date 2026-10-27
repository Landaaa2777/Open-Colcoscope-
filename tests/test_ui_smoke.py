"""Prueba de humo de la interfaz multi-dispositivo (offscreen, drivers simulados)."""

from __future__ import annotations

import ast
import json
import os
import re
import string
import time
from collections.abc import Callable, Iterator
from pathlib import Path
from typing import ClassVar

import cv2
import numpy as np
import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
QtWidgets = pytest.importorskip("PySide6.QtWidgets", reason="PySide6 no disponible")

from PySide6.QtCore import QEvent, QSettings, Qt  # noqa: E402

from colpo import DeviceDisconnectedError, DiskFullError, RecordingError  # noqa: E402
from colpo import capture as capture_module  # noqa: E402
from colpo.drivers.mock import MockDriver  # noqa: E402
from colpo.drivers.registry import DriverRegistry  # noqa: E402
from colpo.metadata import METADATA_FIELDS, sha256_file  # noqa: E402
from colpo.session import CaptureSession  # noqa: E402
from colpo.synthetic import decode_index, make_frame  # noqa: E402
from colpo.ui.app import MainWindow, error_message_key  # noqa: E402
from colpo.ui.device_tab import DeviceTab  # noqa: E402
from colpo.ui.i18n import LANGUAGES, Translator, load_catalog  # noqa: E402

UI_DIR = Path(__file__).resolve().parents[1] / "src" / "colpo" / "ui"
TIMESTAMP_RE = re.compile(r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}[+-]\d{2}:\d{2}$")
BANNER_ES = "Prototipo educativo — no validado para diagnóstico clínico"
BANNER_EN = "Educational prototype — not validated for clinical diagnosis"


class DemoMock(MockDriver):
    """Dos cámaras simuladas de 320x240."""

    device_count = 2

    @classmethod
    def for_device(cls, device_info, **options):
        return cls(device_info, resolution=(320, 240))


class BusyMock(DemoMock):
    simulate_busy = True


class MissingMock(DemoMock):
    simulate_not_found = True


class DisconnectingMock(DemoMock):
    disconnect_after = 20


class BadFormatMock(DemoMock):
    # No admite los 320x240 que pide for_device.
    MODES: ClassVar[dict[tuple[int, int], tuple[float, ...]]] = {(640, 480): (30.0,)}


def _registry(driver: type[MockDriver] = DemoMock) -> DriverRegistry:
    registry = DriverRegistry()
    registry.register(driver)
    return registry


@pytest.fixture(scope="module")
def qapp():
    return QtWidgets.QApplication.instance() or QtWidgets.QApplication([])


def wait_until(app, predicate: Callable[[], bool], timeout: float = 6.0) -> None:
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

    def factory(driver: type[MockDriver] = DemoMock, **kwargs) -> MainWindow:
        kwargs.setdefault("session", CaptureSession(tmp_path / "datos"))
        window = MainWindow(
            registry=_registry(driver),
            settings=QSettings(str(tmp_path / "ui.ini"), QSettings.Format.IniFormat),
            **kwargs,
        )
        window.show()
        windows.append(window)
        return window

    yield factory
    for window in windows:
        window.close()
        window.deleteLater()
    # Destruir las ventanas ahora (y no al salir del intérprete, cuando Qt ya se
    # está desmontando) evita cierres abruptos de PySide en el teardown.
    qapp.sendPostedEvents(None, QEvent.Type.DeferredDelete.value)
    qapp.processEvents()


def _open(qapp, window: MainWindow, choice: int, *, new_tab: bool = False) -> DeviceTab:
    window.select_device(choice)
    tab = window.open_selected(new_tab=new_tab)
    assert tab is not None
    wait_until(qapp, lambda: tab.streaming and tab.last_sequence >= 2)
    return tab


def _json_files(window: MainWindow) -> list[Path]:
    return sorted(window.session.study_dir.glob("*.json"))


# ------------------------------------------------------------------- arranque
def test_start_state_and_grouped_selector(qapp, make_window) -> None:
    window = make_window()
    assert window.banner_label.text() == BANNER_ES and window.banner_label.isVisible()
    combo = window.device_combo
    items = [combo.itemText(i) for i in range(combo.count())]
    assert items[0] == "Simulado (demostración)"  # cabecera del grupo (driver)
    assert combo.model().item(0).flags() == Qt.ItemFlag.NoItemFlags  # no seleccionable
    assert items[1].strip().startswith("0 — Cámara simulada 1")
    assert "????:????" in items[1]  # VID:PID visible
    assert "No UVC" in window.capabilities_label.text()
    assert "640\u00d7480" in window.capabilities_label.text()
    assert window.tabs() == []
    assert not window.photo_button.isEnabled()
    assert not window.watermark_status.isVisible()


def test_no_devices(qapp, make_window) -> None:
    class NoDevices(MockDriver):
        device_count = 0

    window = make_window(NoDevices)
    assert window.device_combo.itemText(0) == "No se detectaron dispositivos"
    assert not window.open_button.isEnabled()


# ------------------------------------------------------------ flujo completo
def test_single_device_capture_flow(qapp, make_window) -> None:
    window = make_window()
    tab = _open(qapp, window, 0)
    assert re.match(r"320\u00d7240 · \d+\.\d FPS", tab.stream_label.text())
    assert not tab.preview_label.pixmap().isNull()

    window.stage_combo.setCurrentIndex(window.stage_combo.findData("acido_acetico"))
    window.notes_edit.setPlainText("Maniquí de práctica, ZT tipo 1")
    window.photo_button.click()
    wait_until(qapp, lambda: len(_json_files(window)) == 1)

    window.stage_combo.setCurrentIndex(window.stage_combo.findData("lugol"))
    window.record_button.click()
    wait_until(qapp, lambda: tab.recording)
    assert window.record_button.text() == "Detener grabación (F9)"
    assert window.tab_widget.tabText(0).startswith("● ")
    time.sleep(0.8)
    window.record_button.click()
    wait_until(qapp, lambda: not tab.recording and len(_json_files(window)) == 2)

    photo_json, video_json = (json.loads(p.read_text("utf-8")) for p in _json_files(window))
    for data in (photo_json, video_json):
        assert list(data) == list(METADATA_FIELDS)
        assert TIMESTAMP_RE.match(data["timestamp"])
        assert data["resolucion"] == {"ancho": 320, "alto": 240}
    assert (photo_json["tipo"], photo_json["etapa_ifcpc"]) == ("foto", "acido_acetico")
    assert (video_json["tipo"], video_json["etapa_ifcpc"]) == ("video", "lugol")
    for json_path in _json_files(window):
        assert json_path.stem.endswith("_mock0")  # el dispositivo va en el nombre
        media = next(p for p in json_path.parent.glob(json_path.stem + ".*") if p != json_path)
        assert json.loads(json_path.read_text("utf-8"))["sha256"] == sha256_file(media)
    assert window._error is None


# -------------------------------------------------------------- multi-dispositivo
def test_two_devices_simultaneously(qapp, make_window) -> None:
    window = make_window()
    first = _open(qapp, window, 0)
    second = _open(qapp, window, 1, new_tab=True)
    assert len(window.tabs()) == 2 and window.current_tab() is second

    # La pestaña de fondo sigue capturando mientras la otra está visible.
    seq = first._live.status().sequence
    wait_until(qapp, lambda: first._live.status().sequence > seq + 5)

    window.photo_button.click()  # actúa sobre la pestaña activa (cámara 2)
    wait_until(qapp, lambda: any(p.stem.endswith("_mock1") for p in _json_files(window)))

    window.tab_widget.setCurrentWidget(first)
    window.record_button.click()  # graba la cámara 1...
    wait_until(qapp, lambda: first.recording)
    window.tab_widget.setCurrentWidget(second)
    window.photo_button.click()  # ...mientras la cámara 2 hace otra foto
    wait_until(qapp, lambda: len([p for p in _json_files(window) if "_mock1" in p.stem]) == 2)
    assert second.streaming and first.recording
    window.tab_widget.setCurrentWidget(first)
    window.record_button.click()
    wait_until(qapp, lambda: any(p.stem.startswith("video") for p in _json_files(window)))

    window.close_tab(window.tab_widget.indexOf(second))
    assert window.tabs() == [first] and first.streaming


def test_hot_switch_in_same_tab(qapp, make_window) -> None:
    window = make_window()
    tab = _open(qapp, window, 0)
    window.select_device(1)
    assert window.open_selected() is tab  # misma pestaña, otro dispositivo
    wait_until(qapp, lambda: tab.streaming and tab.choice.device.index == 1)
    assert len(window.tabs()) == 1
    assert "Cámara simulada 2" in window.tab_widget.tabText(0)


def test_same_device_cannot_open_twice(qapp, make_window) -> None:
    window = make_window()
    _open(qapp, window, 0)
    window.select_device(0)
    assert window.open_selected(new_tab=True) is None
    assert "ya está abierto" in window.error_label.text()
    assert len(window.tabs()) == 1


def test_language_switch_with_tabs(qapp, make_window) -> None:
    window = make_window()
    _open(qapp, window, 0)
    window.stage_combo.setCurrentIndex(window.stage_combo.findData("lugol"))
    window.set_language("en")
    assert window.banner_label.text() == BANNER_EN
    assert window.photo_button.text() == "Photo (F8)"
    assert window.open_new_tab_button.text() == "Open in new tab"
    assert window.device_combo.itemText(0) == "Simulated (demo)"
    assert window.stage_combo.currentText() == "Lugol's iodine"
    assert window.current_tab().streaming
    window.set_language("es")
    assert window.banner_label.text() == BANNER_ES


# ---------------------------------------------------------------- marca de agua
def _saved_photo(window: MainWindow, qapp) -> tuple[np.ndarray, np.ndarray]:
    before = set(window.session.study_dir.glob("*.png"))
    window.photo_button.click()
    wait_until(qapp, lambda: len(set(window.session.study_dir.glob("*.png")) - before) == 1)
    (path,) = set(window.session.study_dir.glob("*.png")) - before
    saved = cv2.imdecode(np.frombuffer(path.read_bytes(), np.uint8), cv2.IMREAD_COLOR)
    return saved, make_frame(decode_index(saved), 320, 240)


def test_watermark_off_by_default_and_user_preference(qapp, make_window, tmp_path) -> None:
    window = make_window()
    assert window.watermark_enabled is False
    assert window.session.watermark.enabled is False
    _open(qapp, window, 0)

    saved, original = _saved_photo(window, qapp)
    assert np.array_equal(saved, original)  # sin marca: la foto es idéntica al frame

    dialog = window.preferences_dialog()
    assert dialog.watermark_checkbox.isChecked() is False
    dialog.watermark_checkbox.setChecked(True)
    dialog.accept()
    assert window.watermark_enabled and window.session.watermark.enabled
    assert window.watermark_status.isVisible()
    assert window.session.watermark.text == "Uso educativo - no diagnostico"

    saved, original = _saved_photo(window, qapp)
    assert not np.array_equal(saved, original)
    assert np.array_equal(saved[:200], original[:200])  # solo cambia la franja inferior

    # Es preferencia del usuario (QSettings), no del estudio: se recuerda.
    assert make_window().watermark_enabled is True
    window.set_language("en")
    assert window.session.watermark.text == "Educational use - not for diagnosis"
    window.set_watermark_enabled(False)
    assert not window.session.watermark.enabled and not window.watermark_status.isVisible()


# ------------------------------------------------------------------ errores
@pytest.mark.parametrize(
    ("driver", "expected"),
    [
        (BusyMock, "ocupado por otra aplicación"),
        (MissingMock, "No se encontró el dispositivo"),
        (BadFormatMock, "no admite el formato"),
    ],
)
def test_open_errors_are_shown(qapp, make_window, driver, expected) -> None:
    window = make_window(driver)
    window.select_device(0)
    tab = window.open_selected()
    wait_until(qapp, lambda: window._error is not None and tab.state == "idle")
    assert expected in window.error_label.text()
    assert "Cámara simulada 1" in window.error_label.text()


def test_disconnection_is_shown(qapp, make_window) -> None:
    window = make_window(DisconnectingMock)
    window.select_device(0)
    tab = window.open_selected()
    wait_until(qapp, lambda: window._error is not None and tab.state == "idle")
    assert "Se perdió la conexión" in window.error_label.text()
    window.set_language("en")
    assert "Connection to the device was lost" in window.error_label.text()


def test_disk_full_is_shown(qapp, make_window, tmp_path: Path) -> None:
    window = make_window(session=CaptureSession(tmp_path / "datos", free_bytes=lambda _p: 1024))
    _open(qapp, window, 0)
    window.photo_button.click()
    wait_until(qapp, lambda: window._error is not None)
    assert "Disco lleno" in window.error_label.text()
    assert _json_files(window) == []


def test_recording_failure_is_shown(qapp, make_window, monkeypatch) -> None:
    monkeypatch.setattr(capture_module, "video_codec_candidates", lambda _s: ("XXXX",))
    window = make_window()
    tab = _open(qapp, window, 0)
    window.record_button.click()
    wait_until(qapp, lambda: window._error is not None)
    assert "La grabación falló" in window.error_label.text()
    assert not tab.recording and tab.streaming


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
        # La marca de agua se dibuja con fuentes de OpenCV: solo ASCII.
        assert catalog["watermark.text"].isascii()


def test_translator_fallback() -> None:
    translator = Translator("en")
    assert translator.tr("clave.inexistente") == "clave.inexistente"
    assert not translator.has("clave.inexistente")
    with pytest.raises(ValueError):
        translator.set_language("fr")


_UI_FORBIDDEN = {"cv2", "numpy", "colpo.drivers.uvc", "colpo.drivers.mock"}


@pytest.mark.parametrize("path", sorted(UI_DIR.rglob("*.py")), ids=lambda p: p.name)
def test_ui_does_not_import_opencv_or_concrete_drivers(path: Path) -> None:
    tree = ast.parse(path.read_text(encoding="utf-8"))
    imported: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            imported.update(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module:
            imported.add(node.module)
    bad = {m for m in imported if m.split(".")[0] in _UI_FORBIDDEN or m in _UI_FORBIDDEN}
    assert not bad, f"{path.name} importa {bad}"


def test_main_parser() -> None:
    from colpo.ui.app import build_parser

    args = build_parser().parse_args(["--lang", "en", "--data-dir", "x", "--demo"])
    assert args.lang == "en" and args.data_dir == Path("x") and args.demo == 2
