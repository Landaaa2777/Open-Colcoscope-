"""Pruebas de apertura, lectura y foto fija con video sintético y cámara simulada."""

from __future__ import annotations

from pathlib import Path

import cv2
import numpy as np
import pytest

from colpo import (
    BackendUnavailableError,
    CameraNotOpenError,
    DeviceDisconnectedError,
    DeviceOpenError,
    EndOfStreamError,
    SnapshotError,
    UnsupportedFormatError,
    UVCCamera,
)
from colpo.capture import decode_fourcc, nominal_fps
from conftest import SYNTH_FPS, SYNTH_FRAMES, SYNTH_SIZE, FakeCapture, FakeClock, factory_for
from synthetic_video import decode_index


# ----------------------------------------------------------- fuente de archivo
def test_open_file_reports_real_stream_info(synthetic_video: Path) -> None:
    with UVCCamera(source=synthetic_video) as cam:
        info = cam.stream_info
        assert (info.width, info.height) == SYNTH_SIZE
        assert info.fps_reported == pytest.approx(SYNTH_FPS)
        assert info.backend == "file"
        assert cam.measure_fps() == pytest.approx(SYNTH_FPS)


def test_reads_every_frame_in_order_then_end_of_stream(synthetic_video: Path) -> None:
    with UVCCamera(source=synthetic_video) as cam:
        for expected in range(SYNTH_FRAMES):
            frame = cam.read_frame()
            assert frame.sequence == expected
            assert decode_index(frame.image) == expected
            assert frame.timestamp == pytest.approx(expected / SYNTH_FPS)
        with pytest.raises(EndOfStreamError):
            cam.read_frame()


def test_frames_are_read_only(synthetic_video: Path) -> None:
    with UVCCamera(source=synthetic_video) as cam:
        frame = cam.read_frame()
        with pytest.raises(ValueError):
            frame.image[0, 0, 0] = 1


def test_missing_file_raises_device_open_error(tmp_path: Path) -> None:
    with pytest.raises(DeviceOpenError, match="No existe"):
        UVCCamera(source=tmp_path / "no-existe.avi").open()


@pytest.mark.parametrize(
    "kwargs",
    [
        {},
        {"index": 0, "source": "x.avi"},
        {"index": -1},
        {"index": 0, "fourcc": "MJ"},
        {"index": 0, "width": 640},
    ],
)
def test_invalid_arguments(kwargs: dict) -> None:
    with pytest.raises(ValueError):
        UVCCamera(**kwargs)


def test_operations_require_open_camera(tmp_path: Path) -> None:
    cam = UVCCamera(source=tmp_path / "x.avi")
    with pytest.raises(CameraNotOpenError):
        cam.read_frame()
    with pytest.raises(CameraNotOpenError):
        cam.start_recording(tmp_path / "x.mp4")
    with pytest.raises(CameraNotOpenError):
        _ = cam.stream_info


def test_close_is_idempotent(synthetic_video: Path) -> None:
    cam = UVCCamera(source=synthetic_video)
    cam.open()
    assert cam.close() is None
    assert cam.close() is None
    assert not cam.is_open


# -------------------------------------------------------------- foto fija PNG
def test_snapshot_is_lossless_png_without_exif(synthetic_video: Path, tmp_path: Path) -> None:
    out = tmp_path / "fotos" / "captura.png"  # la carpeta se crea
    with UVCCamera(source=synthetic_video) as cam:
        cam.read_frame()
        frame = cam.read_frame()
        saved = cam.snapshot(out, frame=frame)
    assert saved == out
    data = out.read_bytes()
    assert data.startswith(b"\x89PNG")
    assert b"eXIf" not in data
    restored = cv2.imdecode(np.frombuffer(data, np.uint8), cv2.IMREAD_COLOR)
    assert np.array_equal(restored, frame.image)
    assert [p.name for p in out.parent.iterdir()] == ["captura.png"]  # sin temporales


def test_snapshot_reads_new_frame_when_none_given(synthetic_video: Path, tmp_path: Path) -> None:
    with UVCCamera(source=synthetic_video) as cam:
        cam.snapshot(tmp_path / "a.png")
        assert cam.last_frame is not None
        assert cam.last_frame.sequence == 0


def test_snapshot_supports_non_ascii_paths(synthetic_video: Path, tmp_path: Path) -> None:
    out = tmp_path / "capturas_señal_ácido" / "foto_niña.png"
    with UVCCamera(source=synthetic_video) as cam:
        cam.snapshot(out)
    assert out.exists()


def test_snapshot_refuses_to_overwrite(synthetic_video: Path, tmp_path: Path) -> None:
    out = tmp_path / "a.png"
    with UVCCamera(source=synthetic_video) as cam:
        cam.snapshot(out)
        with pytest.raises(SnapshotError, match="ya existe"):
            cam.snapshot(out)
        cam.snapshot(out, overwrite=True)


def test_snapshot_rejects_lossy_formats(synthetic_video: Path, tmp_path: Path) -> None:
    with UVCCamera(source=synthetic_video) as cam, pytest.raises(UnsupportedFormatError):
        cam.snapshot(tmp_path / "a.jpg")


# ---------------------------------------------------------- cámara simulada
def test_camera_open_failure_has_actionable_message() -> None:
    cam = UVCCamera(index=3, capture_factory=factory_for(FakeCapture(opened=False)))
    with pytest.raises(DeviceOpenError, match="índice 3"):
        cam.open()


def test_camera_that_opens_but_never_delivers_frames() -> None:
    fake = FakeCapture(fail_after=0)
    cam = UVCCamera(index=0, warmup_frames=2, capture_factory=factory_for(fake))
    with pytest.raises(DeviceOpenError, match="no entrega imágenes"):
        cam.open()
    assert fake.released


def test_warmup_frames_are_discarded() -> None:
    fake = FakeCapture()
    with UVCCamera(index=0, warmup_frames=4, capture_factory=factory_for(fake)) as cam:
        frame = cam.read_frame()
        assert decode_index(frame.image) == 4
        assert frame.sequence == 0


def test_requested_format_is_applied_fourcc_first() -> None:
    fake = FakeCapture()
    with UVCCamera(
        index=0,
        width=1920,
        height=1080,
        fps=30,
        fourcc="MJPG",
        capture_factory=factory_for(fake),
    ) as cam:
        props = [prop for prop, _ in fake.set_calls]
        assert props[0] == cv2.CAP_PROP_FOURCC
        assert props.index(cv2.CAP_PROP_FOURCC) < props.index(cv2.CAP_PROP_FRAME_WIDTH)
        # El simulador ignora la petición: se informa el tamaño real, no el pedido.
        assert (cam.stream_info.width, cam.stream_info.height) == SYNTH_SIZE
        assert cam.stream_info.fourcc == "MJPG"


def test_measure_fps_uses_real_frame_timing() -> None:
    clock = FakeClock(step=1 / 25)
    fake = FakeCapture(fps=30.0, clock=clock)  # el driver dice 30, la cámara da 25
    with UVCCamera(index=0, capture_factory=factory_for(fake), clock=clock) as cam:
        assert cam.stream_info.fps_reported == 30.0
        assert cam.measure_fps(20) == pytest.approx(25.0)


def test_disconnection_raises_after_consecutive_failures() -> None:
    fake = FakeCapture(fail_after=10)
    with UVCCamera(
        index=0, warmup_frames=0, max_read_failures=3, capture_factory=factory_for(fake)
    ) as cam:
        for _ in range(10):
            cam.read_frame()
        with pytest.raises(DeviceDisconnectedError, match="desconect"):
            cam.read_frame()


def test_unknown_backend_for_platform() -> None:
    with pytest.raises(BackendUnavailableError):
        UVCCamera(index=0, backend="no-existe").open()


def test_decode_fourcc_and_nominal_fps() -> None:
    assert decode_fourcc(cv2.VideoWriter_fourcc(*"YUY2")) == "YUY2"
    assert decode_fourcc(0) == ""
    assert nominal_fps(29.7) == 30.0
    assert nominal_fps(14.6) == 15.0
    assert nominal_fps(42.0) == 42.0
