"""Suite de contrato ``CameraDriver``: todo driver debe pasarla.

Qué cubre:

1. **Forma y reglas** de cada driver registrado por *entry points* (automático:
   un driver nuevo declarado en pyproject.toml entra aquí sin tocar este archivo):
   miembros del contrato, ``probe`` rechaza dispositivos ajenos, ``discover``
   devuelve ``DeviceInfo`` que el propio driver acepta, y su módulo no importa
   PySide6 ni red ni escribe archivos.
2. **Comportamiento** con instancias sin hardware (``CASES``): ``open``/``close``,
   ``read_frame`` con *timeout*, capacidades coherentes, metadatos sin datos
   privados y errores de dominio (ocupada, inexistente, desconexión, formato).
3. **Hardware real** (opcional): con ``COLPO_CONTRACT_HARDWARE=1`` se ejecuta el
   punto 2 contra cada dispositivo que detecten los drivers registrados.

Para un driver nuevo sin simulación posible, conecta el equipo y ejecuta::

    COLPO_CONTRACT_HARDWARE=1 pytest tests/test_driver_contract.py -k <nombre>
"""

from __future__ import annotations

import ast
import inspect
import json
import os
import threading
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path

import numpy as np
import pytest

from colpo import CaptureCamera
from colpo.devices import DeviceInfo
from colpo.drivers.base import (
    FORBIDDEN_METADATA_KEYS,
    METADATA_KEYS,
    CameraDriver,
    Capabilities,
)
from colpo.drivers.errors import (
    CameraBusy,
    CameraDisconnected,
    CameraNotFound,
    FormatNotSupported,
)
from colpo.drivers.mock import MockDriver
from colpo.drivers.registry import default_registry, validate_driver_class
from colpo.drivers.uvc import UVCCamera
from colpo.errors import CameraNotOpenError
from conftest import FakeCapture, factory_for

READ_TIMEOUT_S = 5.0
HARDWARE = os.environ.get("COLPO_CONTRACT_HARDWARE") == "1"
REGISTERED = default_registry().list_drivers()

Maker = Callable[[Path], CameraDriver]


@dataclass(frozen=True)
class DriverCase:
    """Cómo obtener instancias de un driver para la suite (sin abrirlas)."""

    id: str
    device: DeviceInfo
    make: Maker
    make_busy: Maker | None = None
    make_not_found: Maker | None = None
    make_disconnecting: Maker | None = None  # se desconecta tras pocos frames
    make_bad_format: Maker | None = None


def _uvc(capture: FakeCapture, **kwargs) -> UVCCamera:
    return UVCCamera(
        index=kwargs.pop("index", 0),
        capture_factory=factory_for(capture),
        warmup_frames=0,
        max_read_failures=2,
        **kwargs,
    )


_UVC_DEVICE = DeviceInfo(index=0, name="UVC simulada", backend="auto", driver="uvc")
_FILE_DEVICE = DeviceInfo(index=0, name="synthetic.avi", backend="file", path="x", driver="uvc")
_MOCK_DEVICE = DeviceInfo(index=0, name="Cámara simulada 1", backend="mock", driver="mock")

CASES: list[DriverCase] = [
    DriverCase(
        id="uvc-simulada",
        device=_UVC_DEVICE,
        make=lambda _v: _uvc(FakeCapture()),
        make_busy=lambda _v: _uvc(FakeCapture(fail_after=0)),  # abre pero no entrega frames
        make_not_found=lambda _v: _uvc(FakeCapture(opened=False), index=57),
        make_disconnecting=lambda _v: _uvc(FakeCapture(fail_after=3)),
        make_bad_format=lambda _v: _uvc(FakeCapture(), width=1920, height=1080, strict_format=True),
    ),
    DriverCase(
        id="uvc-archivo",
        device=_FILE_DEVICE,
        make=lambda video: UVCCamera(source=video),
        make_not_found=lambda video: UVCCamera(source=video.with_name("no-existe.avi")),
    ),
    DriverCase(
        id="mock",
        device=_MOCK_DEVICE,
        make=lambda _v: MockDriver(_MOCK_DEVICE, realtime=False),
        make_busy=lambda _v: MockDriver(_MOCK_DEVICE, busy=True),
        make_not_found=lambda _v: MockDriver(_MOCK_DEVICE, not_found=True),
        make_disconnecting=lambda _v: MockDriver(_MOCK_DEVICE, disconnect_after=3),
        make_bad_format=lambda _v: MockDriver(_MOCK_DEVICE, resolution=(1920, 1080)),
    ),
]


def _hardware_cases() -> list[DriverCase]:
    if not HARDWARE:
        return []
    cases = []
    for name, cls in REGISTERED.items():
        for device in cls.discover():
            if cls.probe(device):
                cases.append(
                    DriverCase(
                        id=f"hw-{name}-{device.index}",
                        device=device,
                        make=lambda _v, c=cls, d=device: c.for_device(d),
                    )
                )
    return cases


ALL_CASES = CASES + _hardware_cases()


def _read_with_timeout(driver: CameraDriver) -> np.ndarray:
    result: dict[str, object] = {}

    def run() -> None:
        try:
            result["frame"] = driver.read_frame()
        except BaseException as exc:
            result["error"] = exc

    thread = threading.Thread(target=run, daemon=True)
    thread.start()
    thread.join(READ_TIMEOUT_S)
    if thread.is_alive():
        pytest.fail(f"read_frame() no respondió en {READ_TIMEOUT_S} s")
    if "error" in result:
        raise result["error"]  # type: ignore[misc]
    return result["frame"]  # type: ignore[return-value]


def _check_frame(frame: object) -> np.ndarray:
    assert isinstance(frame, np.ndarray), "read_frame() debe devolver numpy.ndarray"
    assert frame.dtype == np.uint8
    assert frame.ndim == 3 and frame.shape[2] == 3, f"se espera (alto, ancho, 3): {frame.shape}"
    assert frame.shape[0] > 0 and frame.shape[1] > 0
    return frame


# =================================================== 1. forma de los registrados
@pytest.mark.parametrize("name", sorted(REGISTERED))
def test_registered_driver_shape(name: str) -> None:
    cls = REGISTERED[name]
    assert validate_driver_class(cls) == name
    foreign = DeviceInfo(index=0, name="ajeno", backend="__ninguno__", driver="__otro__")
    assert cls.probe(foreign) is False


@pytest.mark.parametrize("name", sorted(REGISTERED))
def test_discover_returns_devices_the_driver_accepts(name: str) -> None:
    cls = REGISTERED[name]
    devices = cls.discover(backend="auto")
    assert isinstance(devices, list)
    for device in devices:
        assert isinstance(device, DeviceInfo)
        assert cls.probe(device) is True


_FORBIDDEN_IMPORTS = ("PySide6", "PyQt5", "PyQt6", "socket", "ssl", "http", "urllib",
                      "requests", "httpx", "shutil", "tempfile")  # fmt: skip
# Llamadas que escriben o borran archivos (atributos de cv2/Path y funciones de os).
_FORBIDDEN_CALLS = {"imwrite", "VideoWriter", "write_text", "write_bytes", "mkdir", "unlink",
                    "touch", "rmtree"}  # fmt: skip
_FORBIDDEN_OS_CALLS = {"replace", "remove", "rename", "makedirs", "unlink", "rmdir", "open"}


@pytest.mark.parametrize("name", sorted(REGISTERED))
def test_driver_module_rules(name: str) -> None:
    """Ningún driver importa UI ni red, ni escribe archivos."""
    source_file = inspect.getsourcefile(REGISTERED[name])
    if source_file is None:
        pytest.skip("código fuente no disponible")
    tree = ast.parse(Path(source_file).read_text(encoding="utf-8"))
    for node in ast.walk(tree):
        if isinstance(node, ast.Import | ast.ImportFrom):
            modules = (
                [a.name for a in node.names]
                if isinstance(node, ast.Import)
                else [node.module or ""]
            )
            for module in modules:
                assert not module.startswith(_FORBIDDEN_IMPORTS), f"{name} importa {module}"
        elif isinstance(node, ast.Call):
            func = node.func
            called = func.attr if isinstance(func, ast.Attribute) else getattr(func, "id", "")
            assert called not in _FORBIDDEN_CALLS, f"{name} llama a {called}() (escribe archivos)"
            if isinstance(func, ast.Attribute) and getattr(func.value, "id", "") == "os":
                assert called not in _FORBIDDEN_OS_CALLS, f"{name} llama a os.{called}()"
            if called == "open" and isinstance(func, ast.Name):
                pytest.fail(f"{name} usa open(): los drivers no tocan archivos")


def test_builtin_drivers_satisfy_runtime_protocol() -> None:
    assert isinstance(UVCCamera(index=0), CameraDriver)
    assert isinstance(MockDriver(), CameraDriver)
    assert {"uvc", "mock"} <= set(REGISTERED)


# ========================================================= 2. comportamiento
@pytest.mark.parametrize("case", ALL_CASES, ids=lambda c: c.id)
def test_probe_accepts_own_device(case: DriverCase, synthetic_video: Path) -> None:
    driver = case.make(synthetic_video)
    assert type(driver).probe(case.device) is True


@pytest.mark.parametrize("case", ALL_CASES, ids=lambda c: c.id)
def test_open_read_close(case: DriverCase, synthetic_video: Path) -> None:
    driver = case.make(synthetic_video)
    assert driver.is_connected() is False
    with pytest.raises(CameraNotOpenError):
        driver.read_frame()

    driver.open()
    try:
        assert driver.is_connected() is True
        first = _check_frame(_read_with_timeout(driver))
        second = _check_frame(_read_with_timeout(driver))
        assert not np.shares_memory(first, second), "cada frame debe ser un array nuevo"
    finally:
        driver.close()
    assert driver.is_connected() is False
    driver.close()  # idempotente
    with pytest.raises(CameraNotOpenError):
        driver.read_frame()

    driver.open()  # se puede volver a abrir
    try:
        _check_frame(_read_with_timeout(driver))
    finally:
        driver.close()


@pytest.mark.parametrize("case", ALL_CASES, ids=lambda c: c.id)
def test_capabilities_are_coherent(case: DriverCase, synthetic_video: Path) -> None:
    driver = case.make(synthetic_video)
    before = driver.capabilities()
    assert isinstance(before, Capabilities)
    assert before.problems() == []
    driver.open()
    try:
        height, width = _read_with_timeout(driver).shape[:2]
        after = driver.capabilities()
    finally:
        driver.close()
    assert after.problems() == []
    assert (width, height) in after.resoluciones_soportadas, "la resolución activa debe figurar"
    for flag in (
        after.tiene_control_zoom,
        after.tiene_control_brillo,
        after.tiene_control_balance_blancos,
    ):
        assert flag in (True, False, None)
    assert isinstance(after.es_uvc, bool)
    assert isinstance(after.notas, str)
    json.dumps(after.to_dict())


@pytest.mark.parametrize("case", ALL_CASES, ids=lambda c: c.id)
def test_metadata_is_serializable_and_private(case: DriverCase, synthetic_video: Path) -> None:
    driver = case.make(synthetic_video)
    for opened in (False, True):
        if opened:
            driver.open()
            height, width = _read_with_timeout(driver).shape[:2]
        try:
            meta = driver.metadata()
            json.dumps(meta)
            assert set(METADATA_KEYS) <= set(meta), f"faltan {set(METADATA_KEYS) - set(meta)}"
            assert not FORBIDDEN_METADATA_KEYS & set(meta)
            assert meta["driver"] == type(driver).name
            assert meta["es_uvc"] is driver.capabilities().es_uvc
            assert meta["fuente"] in ("camara", "archivo", "simulada")
            if opened:
                assert meta["resolucion"] == [width, height]
            text = json.dumps(meta)
            assert "\\\\?\\" not in text and "/dev/" not in text, "sin rutas del sistema"
        finally:
            if opened:
                driver.close()


@pytest.mark.parametrize("case", ALL_CASES, ids=lambda c: c.id)
def test_any_driver_gets_photos_from_the_core(
    case: DriverCase, synthetic_video: Path, tmp_path: Path
) -> None:
    with CaptureCamera(case.make(synthetic_video)) as camera:
        path = camera.snapshot(tmp_path / "foto.png")
    assert path.read_bytes().startswith(b"\x89PNG")


def _require(maker: Maker | None) -> Maker:
    if maker is None:
        pytest.skip("este caso no puede simular la situación")
    return maker


@pytest.mark.parametrize("case", CASES, ids=lambda c: c.id)
def test_busy_device_raises_camera_busy(case: DriverCase, synthetic_video: Path) -> None:
    driver = _require(case.make_busy)(synthetic_video)
    with pytest.raises(CameraBusy):
        driver.open()
    assert driver.is_connected() is False


@pytest.mark.parametrize("case", CASES, ids=lambda c: c.id)
def test_missing_device_raises_camera_not_found(case: DriverCase, synthetic_video: Path) -> None:
    driver = _require(case.make_not_found)(synthetic_video)
    with pytest.raises(CameraNotFound):
        driver.open()
    assert driver.is_connected() is False


@pytest.mark.parametrize("case", CASES, ids=lambda c: c.id)
def test_disconnection_raises_camera_disconnected(case: DriverCase, synthetic_video: Path) -> None:
    driver = _require(case.make_disconnecting)(synthetic_video)
    driver.open()
    try:
        with pytest.raises(CameraDisconnected):
            for _ in range(50):
                _read_with_timeout(driver)
        assert driver.is_connected() is False
    finally:
        driver.close()


@pytest.mark.parametrize("case", CASES, ids=lambda c: c.id)
def test_unsupported_format_raises(case: DriverCase, synthetic_video: Path) -> None:
    driver = _require(case.make_bad_format)(synthetic_video)
    with pytest.raises(FormatNotSupported):
        driver.open()
    assert driver.is_connected() is False
