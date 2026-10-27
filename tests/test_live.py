"""Hilo de captura en vivo (sin Qt): eventos, comandos y errores."""

from __future__ import annotations

import threading
import time
from collections.abc import Callable
from pathlib import Path

import pytest

from colpo import CaptureCamera, DeviceDisconnectedError, DeviceOpenError, DiskFullError
from colpo.devices import DeviceInfo
from colpo.drivers.errors import CameraBusy, CameraDisconnected
from colpo.drivers.mock import MockDriver
from colpo.drivers.uvc import UVCCamera
from colpo.live import (
    Captured,
    Failed,
    LiveCapture,
    Opened,
    RecordingChanged,
    Stopped,
    camera_for_device,
)
from colpo.metadata import read_sidecar
from colpo.session import CaptureSession

PLENTY = 10 * 1024**3


class Recorder:
    def __init__(self) -> None:
        self.events: list[object] = []
        self.lock = threading.Lock()

    def __call__(self, event: object) -> None:
        with self.lock:
            self.events.append(event)

    def of(self, kind: type) -> list:
        with self.lock:
            return [e for e in self.events if isinstance(e, kind)]

    def wait_for(self, predicate: Callable[[], bool], timeout: float = 5.0) -> None:
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            if predicate():
                return
            time.sleep(0.01)
        raise AssertionError(f"Tiempo agotado. Eventos: {self.events}")


def _live(session: CaptureSession, recorder: Recorder, **mock_options) -> LiveCapture:
    def factory() -> CaptureCamera:
        return CaptureCamera(MockDriver(resolution=(320, 240), **mock_options))

    return LiveCapture(factory, session, on_event=recorder, tag="mock0")


def _session(tmp_path: Path, free: int = PLENTY) -> CaptureSession:
    return CaptureSession(tmp_path, free_bytes=lambda _p: free)


def test_photo_and_video_from_live_thread(tmp_path: Path) -> None:
    rec = Recorder()
    session = _session(tmp_path)
    live = _live(session, rec)
    live.start()
    try:
        rec.wait_for(lambda: live.status() is not None and live.status().sequence >= 5)
        assert isinstance(rec.events[0], Opened)
        assert (live.status().width, live.status().height) == (320, 240)
        assert live.status().fps > 10

        live.request_photo()
        rec.wait_for(lambda: len(rec.of(Captured)) == 1)
        live.request_start_video()
        rec.wait_for(lambda: rec.of(RecordingChanged) == [RecordingChanged(True)])
        time.sleep(0.5)
        live.request_stop_video()
        rec.wait_for(lambda: len(rec.of(Captured)) == 2)
    finally:
        live.stop()
    photo, video = (e.result for e in rec.of(Captured))
    assert photo.metadata.tipo == "foto" and video.metadata.tipo == "video"
    assert photo.media_path.stem.endswith("_mock0")
    assert read_sidecar(video.metadata_path).sha256 == video.metadata.sha256
    assert isinstance(rec.events[-1], Stopped)
    assert not rec.of(Failed)


def test_stopping_while_recording_saves_the_video(tmp_path: Path) -> None:
    rec = Recorder()
    live = _live(_session(tmp_path), rec)
    live.start()
    rec.wait_for(lambda: rec.of(Opened))
    live.request_start_video()
    rec.wait_for(lambda: rec.of(RecordingChanged))
    time.sleep(0.3)
    live.stop()
    assert [e.result.metadata.tipo for e in rec.of(Captured)] == ["video"]
    assert rec.of(RecordingChanged)[-1] == RecordingChanged(False)


def test_busy_camera_reports_open_error(tmp_path: Path) -> None:
    rec = Recorder()
    live = _live(_session(tmp_path), rec, busy=True)
    live.start()
    rec.wait_for(lambda: rec.of(Stopped))
    (failure,) = rec.of(Failed)
    assert isinstance(failure.error, CameraBusy) and failure.action == "open"
    assert isinstance(failure.error, DeviceOpenError)
    assert not live.is_running


def test_disconnection_during_recording_keeps_file(tmp_path: Path) -> None:
    rec = Recorder()
    live = _live(_session(tmp_path), rec, disconnect_after=25)
    live.start()
    rec.wait_for(lambda: rec.of(Opened))
    live.request_start_video()
    rec.wait_for(lambda: rec.of(Stopped))
    errors = [f.error for f in rec.of(Failed)]
    assert any(isinstance(e, CameraDisconnected) for e in errors)
    assert all(isinstance(e, DeviceDisconnectedError) for e in errors)
    (video,) = (e.result for e in rec.of(Captured))
    assert video.media_path.exists() and video.metadata_path.exists()


def test_low_disk_space_stops_recording_and_saves(tmp_path: Path) -> None:
    rec = Recorder()
    free = {"bytes": PLENTY}
    session = CaptureSession(tmp_path, free_bytes=lambda _p: free["bytes"])
    live = LiveCapture(
        lambda: CaptureCamera(MockDriver(resolution=(320, 240))),
        session,
        on_event=rec,
        space_check_interval=0.05,
    )
    live.start()
    try:
        rec.wait_for(lambda: rec.of(Opened))
        live.request_start_video()
        rec.wait_for(lambda: rec.of(RecordingChanged))
        time.sleep(0.2)
        free["bytes"] = 50 * 1024 * 1024  # el disco se llena durante la grabación
        rec.wait_for(lambda: rec.of(Captured))
        rec.wait_for(lambda: rec.of(Failed))
    finally:
        live.stop()
    assert isinstance(rec.of(Failed)[0].error, DiskFullError)
    assert rec.of(Captured)[0].result.media_path.exists()
    assert not session.is_recording


def test_camera_for_device() -> None:
    camera = camera_for_device(DeviceInfo(index=2, name="x", backend="auto"))
    assert isinstance(camera.driver, UVCCamera) and not camera.driver.is_file_source
    demo = camera_for_device(DeviceInfo(index=0, name="d", backend="file", path="demo.avi"))
    assert isinstance(demo.driver, UVCCamera) and demo.driver.is_file_source
    with pytest.raises(ValueError):
        camera_for_device(DeviceInfo(index=0, name="d", backend="file"))
