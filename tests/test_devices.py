"""Pruebas de enumeración de dispositivos (sin hardware)."""

from __future__ import annotations

import platform

import pytest

from colpo import BackendUnavailableError, DeviceInfo, devices
from colpo.devices import available_backends, default_backend, find_device, resolve_backend
from conftest import FakeCapture


def test_default_backend_per_platform() -> None:
    assert default_backend("Windows") == "dshow"
    assert default_backend("Linux") == "v4l2"
    assert default_backend("Darwin") == "avfoundation"
    assert "msmf" in available_backends("Windows")


def test_resolve_backend() -> None:
    name, _api = resolve_backend("auto")
    assert name == default_backend(platform.system())
    with pytest.raises(BackendUnavailableError, match="Opciones válidas"):
        resolve_backend("no-existe")


def test_vid_pid_formatting() -> None:
    dev = DeviceInfo(index=0, name="X", backend="dshow", vendor_id=0x1234, product_id=0xABC)
    assert dev.vid_pid == "1234:0ABC"
    assert DeviceInfo(index=1, name="Y", backend="dshow").vid_pid == "????:????"


def test_native_enumeration_is_used(monkeypatch: pytest.MonkeyPatch) -> None:
    fake = [DeviceInfo(index=0, name="Cámara UVC", backend="v4l2", vendor_id=1, product_id=2)]
    monkeypatch.setattr(devices, "_enumerate_native", lambda api, backend: fake)
    assert devices.list_devices() == fake


def test_falls_back_to_probing_when_native_fails(monkeypatch: pytest.MonkeyPatch) -> None:
    def broken(api: int, backend: str) -> list[DeviceInfo]:
        raise RuntimeError("API nativa no disponible")

    monkeypatch.setattr(devices, "_enumerate_native", broken)
    opened = {0, 2}
    created: list[FakeCapture] = []

    def factory(index: int, _api: int) -> FakeCapture:
        cap = FakeCapture(opened=index in opened)
        created.append(cap)
        return cap

    found = devices.list_devices(probe_limit=4, capture_factory=factory)
    assert [d.index for d in found] == [0, 2]
    assert all(d.vid_pid == "????:????" for d in found)
    assert all(cap.released for cap in created)


def test_find_device() -> None:
    devs = [DeviceInfo(index=i, name=str(i), backend="v4l2") for i in (0, 3)]
    found = find_device(devs, 3)
    assert found is not None and found.name == "3"
    assert find_device(devs, 1) is None
