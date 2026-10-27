"""Registro de drivers (entry points y manual) y perfiles de dispositivo."""

from __future__ import annotations

import json
from importlib import resources

import pytest

from colpo.devices import DeviceInfo
from colpo.drivers import registry as registry_module
from colpo.drivers import uvc as uvc_module
from colpo.drivers.errors import DriverContractError
from colpo.drivers.mock import MockDriver
from colpo.drivers.profiles import (
    DeviceProfile,
    PreferredMode,
    ProfileError,
    load_profiles,
    parse_profile,
)
from colpo.drivers.registry import DriverRegistry, validate_driver_class
from colpo.drivers.uvc import UVCCamera


class TwoMocks(MockDriver):
    device_count = 2


class OtherMock(MockDriver):
    name = "otro"
    device_count = 1


class BrokenDiscover(MockDriver):
    name = "roto"

    @classmethod
    def discover(cls, **options):
        raise RuntimeError("fallo del SDK simulado")


class NotADriver:
    name = "incompleto"

    def open(self) -> None: ...


# ------------------------------------------------------------- registro manual
def test_manual_registration_and_listing() -> None:
    reg = DriverRegistry()
    assert reg.register(TwoMocks) == "mock"
    assert reg.register(OtherMock) == "otro"
    assert reg.list_drivers() == {"mock": TwoMocks, "otro": OtherMock}
    with pytest.raises(DriverContractError, match="Ya hay"):
        reg.register(MockDriver)
    reg.register(MockDriver, replace=True)
    assert reg.get("mock") is MockDriver
    reg.unregister("otro")
    assert set(reg.list_drivers()) == {"mock"}
    with pytest.raises(DriverContractError):
        reg.get("otro")


@pytest.mark.parametrize(
    "bad", [NotADriver, object(), type("SinNombre", (MockDriver,), {"name": "Mal Nombre"})]
)
def test_invalid_classes_are_rejected(bad: object) -> None:
    with pytest.raises(DriverContractError):
        validate_driver_class(bad)


def test_probe_all_groups_devices_and_survives_broken_drivers() -> None:
    reg = DriverRegistry()
    for cls in (TwoMocks, OtherMock, BrokenDiscover):
        reg.register(cls)
    found = reg.probe_all(backend="auto")
    assert [(cls.name, d.index) for cls, d in found] == [("mock", 0), ("mock", 1), ("otro", 0)]
    assert "roto" in reg.load_errors


def test_create_and_describe() -> None:
    reg = DriverRegistry()
    reg.register(TwoMocks)
    device = TwoMocks.discover()[0]
    driver = reg.create("mock", device)
    assert isinstance(driver, TwoMocks) and not driver.is_connected()
    assert reg.describe("mock", device).resoluciones_soportadas
    with pytest.raises(DriverContractError, match="no maneja"):
        reg.create("mock", DeviceInfo(index=0, name="x", backend="auto", driver="uvc"))


# ------------------------------------------------------------------ entry points
class _FakeEntryPoint:
    def __init__(self, name: str, target: object) -> None:
        self.name = name
        self._target = target

    def load(self) -> object:
        if isinstance(self._target, Exception):
            raise self._target
        return self._target


def test_entry_points_are_loaded_and_failures_isolated(monkeypatch: pytest.MonkeyPatch) -> None:
    eps = [
        _FakeEntryPoint("otro", OtherMock),
        _FakeEntryPoint("roto", ImportError("dependencia ausente")),
        _FakeEntryPoint("nombre-distinto", TwoMocks),  # el entry point no coincide con name
    ]
    monkeypatch.setattr(registry_module, "entry_points", lambda group: eps)
    reg = DriverRegistry()
    assert reg.load_entry_points() == ["otro"]
    assert set(reg.load_errors) == {"roto", "nombre-distinto"}


def test_installed_package_declares_builtin_drivers() -> None:
    reg = DriverRegistry()
    reg.load_entry_points()
    assert reg.list_drivers()["uvc"] is UVCCamera
    assert reg.list_drivers()["mock"] is MockDriver


def test_default_registry_falls_back_to_builtins(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(registry_module, "entry_points", lambda group: [])
    monkeypatch.setattr(registry_module, "_default", None)
    assert set(registry_module.default_registry().list_drivers()) == {"uvc", "mock"}


def test_mock_demo_devices_from_environment(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("COLPO_MOCK_DEVICES", raising=False)
    assert MockDriver.discover() == []
    monkeypatch.setenv("COLPO_MOCK_DEVICES", "3")
    assert len(MockDriver.discover()) == 3


# ---------------------------------------------------------------------- perfiles
def test_goldcare_profile_is_shipped_and_valid() -> None:
    profiles = {p.id: p for p in load_profiles()}
    gc = profiles["goldcare-gc3000e"]
    assert gc.nombre == "GOLDCARE GC 3000E"
    assert gc.estado == "confirmado_uvc"
    assert gc.driver_recomendado == "uvc"
    # VID:PID pendiente: el perfil no se aplica a ningún dispositivo todavía.
    assert gc.vid_pid is None
    assert not gc.matches(DeviceInfo(index=0, name="x", backend="auto", vendor_id=1, product_id=2))
    assert gc.verified_modes == ()  # resolución objetivo sin verificar: no se solicita


def test_every_shipped_profile_file_parses() -> None:
    folder = resources.files("colpo.drivers.profiles")
    files = [f for f in folder.iterdir() if f.name.endswith(".json")]
    assert files
    for f in files:
        parse_profile(json.loads(f.read_text(encoding="utf-8")), f.name)


def _profile_dict(**overrides) -> dict:
    data = json.loads(
        resources.files("colpo.drivers.profiles")
        .joinpath("goldcare_gc3000e.json")
        .read_text("utf-8")
    )
    data.update(overrides)
    return data


@pytest.mark.parametrize(
    "overrides",
    [
        {"esquema": "otro/1"},
        {"id": "Con Espacios"},
        {"estado": "quizas"},
        {"vendor_id": "0x12G4", "product_id": "0x0001"},
        {"vendor_id": "0x1234", "product_id": None},
        {"api_recomendada": "gstreamer"},
        {"controles": {"zoom": "si", "brillo": None, "balance_blancos": None}},
        {
            "resoluciones_preferidas": [
                {"ancho": 0, "alto": 720, "fps": 30, "formato": "MJPG", "verificada": True}
            ]
        },
        {"numero_serie": "123"},
    ],
)
def test_invalid_profiles_are_rejected(overrides: dict) -> None:
    with pytest.raises(ProfileError):
        parse_profile(_profile_dict(**overrides))


def test_vid_pid_parsing_and_matching() -> None:
    profile = parse_profile(_profile_dict(vendor_id="0x1A2B", product_id="00ff"))
    assert profile.vid_pid == "1A2B:00FF"
    assert profile.matches(
        DeviceInfo(index=0, name="x", backend="auto", vendor_id=0x1A2B, product_id=0x00FF)
    )


def test_uvc_applies_only_verified_profile_modes(monkeypatch: pytest.MonkeyPatch) -> None:
    device = DeviceInfo(index=1, name="Colposcopio", backend="auto", vendor_id=1, product_id=2)
    verified = DeviceProfile(
        id="prueba", nombre="Prueba", fabricante="X", modelo="Y", vendor_id=1, product_id=2,
        estado="confirmado_uvc", driver_recomendado="uvc", api_recomendada="auto",
        resoluciones_preferidas=(
            PreferredMode(1920, 1080, 30, "MJPG", verificada=False),
            PreferredMode(1280, 720, 30, "MJPG", verificada=True),
        ),
        controles={"zoom": None, "brillo": True, "balance_blancos": None},
        notas=(),
    )  # fmt: skip
    monkeypatch.setattr(uvc_module, "find_profile", lambda d: verified)
    driver = UVCCamera.for_device(device)
    assert driver._requested == (1280, 720, 30, "MJPG")
    caps = driver.capabilities()
    assert caps.resoluciones_soportadas == ((1280, 720),)
    assert caps.tiene_control_brillo is True and caps.tiene_control_zoom is None
    assert driver.metadata()["perfil"] == "prueba"

    monkeypatch.setattr(uvc_module, "find_profile", lambda d: None)
    assert UVCCamera.for_device(device)._requested == (None, None, None, None)
