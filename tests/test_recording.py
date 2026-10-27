"""Pruebas de grabación de video con video sintético y cámara simulada."""

from __future__ import annotations

import time
from pathlib import Path

import cv2
import pytest

from colpo import (
    CaptureCamera,
    DeviceDisconnectedError,
    EndOfStreamError,
    RecordingError,
    UnsupportedFormatError,
)
from conftest import SYNTH_FPS, SYNTH_FRAMES, SYNTH_SIZE, FakeCapture, FakeClock, count_frames
from conftest import factory_for as fixed_factory
from synthetic_video import decode_index


def _record_whole_file(cam: CaptureCamera) -> None:
    while True:
        try:
            cam.read()
        except EndOfStreamError:
            return


@pytest.mark.parametrize("suffix", [".mp4", ".avi", ".mkv"])
def test_records_every_frame_in_order(synthetic_video: Path, tmp_path: Path, suffix: str) -> None:
    out = tmp_path / f"video{suffix}"
    with CaptureCamera.for_source(synthetic_video) as cam:
        assert cam.start_recording(out) == out
        assert cam.is_recording
        _record_whole_file(cam)
        stats = cam.stop_recording()

    assert stats.path == out
    assert stats.frames_received == SYNTH_FRAMES
    assert stats.frames_written == SYNTH_FRAMES
    assert stats.frames_dropped == 0
    assert stats.duration_s == pytest.approx(SYNTH_FRAMES / SYNTH_FPS)

    n, fps, size, frames = count_frames(out)
    assert n == SYNTH_FRAMES
    assert fps == pytest.approx(SYNTH_FPS)
    assert size == SYNTH_SIZE
    assert [decode_index(f) for f in frames] == list(range(SYNTH_FRAMES))
    assert sorted(p.name for p in tmp_path.iterdir()) == [out.name]  # sin temporal


def test_partial_file_is_hidden_until_stop(synthetic_video: Path, tmp_path: Path) -> None:
    out = tmp_path / "video.avi"
    with CaptureCamera.for_source(synthetic_video) as cam:
        cam.start_recording(out)
        for _ in range(10):
            cam.read()
        assert not out.exists()
        assert (tmp_path / ".video.recording.avi").exists()
        cam.stop_recording()
    assert out.exists()
    assert not (tmp_path / ".video.recording.avi").exists()


def test_recording_errors(synthetic_video: Path, tmp_path: Path) -> None:
    existing = tmp_path / "ya.mp4"
    existing.write_bytes(b"x")
    with CaptureCamera.for_source(synthetic_video) as cam:
        with pytest.raises(RecordingError, match="No hay ninguna grabación"):
            cam.stop_recording()
        with pytest.raises(UnsupportedFormatError):
            cam.start_recording(tmp_path / "video.mov")
        with pytest.raises(RecordingError, match="ya existe"):
            cam.start_recording(existing)
        with pytest.raises(RecordingError, match="FPS fuera de rango"):
            cam.start_recording(tmp_path / "v.mp4", fps=0.5)
        cam.start_recording(tmp_path / "v.mp4")
        with pytest.raises(RecordingError, match="en curso"):
            cam.start_recording(tmp_path / "w.mp4")
        cam.read()
        cam.stop_recording()


def test_overwrite_replaces_existing_file(synthetic_video: Path, tmp_path: Path) -> None:
    out = tmp_path / "v.avi"
    out.write_bytes(b"viejo")
    with CaptureCamera.for_source(synthetic_video) as cam:
        cam.start_recording(out, overwrite=True)
        for _ in range(5):
            cam.read()
        cam.stop_recording()
    assert count_frames(out)[0] == 5


def test_stop_without_frames_creates_no_file(synthetic_video: Path, tmp_path: Path) -> None:
    out = tmp_path / "vacio.avi"
    with CaptureCamera.for_source(synthetic_video) as cam:
        cam.start_recording(out)
        with pytest.raises(RecordingError, match="ningún frame"):
            cam.stop_recording()
    assert list(tmp_path.iterdir()) == []


def test_close_finalizes_active_recording(synthetic_video: Path, tmp_path: Path) -> None:
    out = tmp_path / "v.avi"
    cam = CaptureCamera.for_source(synthetic_video)
    cam.open()
    cam.start_recording(out)
    for _ in range(15):
        cam.read()
    stats = cam.close()
    assert stats is not None and stats.frames_written == 15
    assert count_frames(out)[0] == 15


def test_slow_camera_frames_are_repeated_to_keep_real_duration(tmp_path: Path) -> None:
    clock = FakeClock(step=1 / 15)  # la cámara entrega 15 FPS
    fake = FakeCapture(clock=clock)
    out = tmp_path / "lento.avi"
    with CaptureCamera.for_index(0, capture_factory=fixed_factory(fake), clock=clock) as cam:
        cam.start_recording(out, fps=30)
        for _ in range(30):  # 2 s de cámara
            cam.read()
        stats = cam.stop_recording()
    assert stats.frames_received == 30
    assert stats.frames_written == pytest.approx(59, abs=1)  # ~2 s a 30 FPS
    assert stats.duration_s == pytest.approx(2.0, abs=0.05)


def test_fast_camera_frames_are_skipped_to_keep_real_duration(tmp_path: Path) -> None:
    clock = FakeClock(step=1 / 60)  # la cámara entrega 60 FPS
    fake = FakeCapture(clock=clock)
    out = tmp_path / "rapido.avi"
    with CaptureCamera.for_index(0, capture_factory=fixed_factory(fake), clock=clock) as cam:
        cam.start_recording(out, fps=30)
        for _ in range(120):  # 2 s de cámara
            cam.read()
        stats = cam.stop_recording()
    assert stats.frames_written == pytest.approx(60, abs=1)
    assert stats.frames_skipped == pytest.approx(60, abs=1)
    assert stats.frames_dropped == 0


def test_recording_uses_measured_fps_rounded_to_nominal(tmp_path: Path) -> None:
    clock = FakeClock(step=1 / 24.6)
    fake = FakeCapture(fps=0.0, clock=clock)  # el driver no informa FPS
    with CaptureCamera.for_index(0, capture_factory=fixed_factory(fake), clock=clock) as cam:
        cam.measure_fps(10)
        cam.start_recording(tmp_path / "v.avi")
        cam.read()
        stats = cam.stop_recording()
    assert stats.fps == 25.0


def test_disconnection_during_recording_keeps_recorded_part(tmp_path: Path) -> None:
    clock = FakeClock(step=1 / 30)
    fake = FakeCapture(fail_after=45, clock=clock)
    out = tmp_path / "corte.mp4"
    with CaptureCamera.for_index(
        0,
        warmup_frames=5,
        max_read_failures=3,
        capture_factory=fixed_factory(fake),
        clock=clock,
    ) as cam:
        cam.start_recording(out, fps=30)
        with pytest.raises(DeviceDisconnectedError):
            while True:
                cam.read()
        stats = cam.stop_recording()
    assert stats.frames_written == 40  # 45 leídos - 5 de calentamiento
    assert count_frames(out)[0] == 40


class _BrokenWriter:
    def __init__(self, *_args: object, opened: bool = True) -> None:
        self.opened = opened

    def isOpened(self) -> bool:  # noqa: N802 (API de OpenCV)
        return self.opened

    def write(self, _image: object) -> None:
        raise OSError("disco lleno (simulado)")

    def release(self) -> None:
        pass


def test_writer_that_cannot_open(synthetic_video: Path, tmp_path: Path) -> None:
    cam = CaptureCamera.for_source(
        synthetic_video, writer_factory=lambda *a: _BrokenWriter(*a, opened=False)
    )
    with cam, pytest.raises(RecordingError, match="No se pudo crear el video"):
        cam.start_recording(tmp_path / "v.mp4")
    assert list(tmp_path.iterdir()) == []


def test_writer_failure_is_reported(synthetic_video: Path, tmp_path: Path) -> None:
    with CaptureCamera.for_source(synthetic_video, writer_factory=_BrokenWriter) as cam:
        cam.start_recording(tmp_path / "v.mp4")
        cam.read()
        deadline = time.monotonic() + 5
        with pytest.raises(RecordingError, match="disco lleno"):
            while time.monotonic() < deadline:  # el hilo escritor falla de forma asíncrona
                cam.read()
                time.sleep(0.01)
        with pytest.raises(RecordingError, match="disco lleno"):
            cam.stop_recording()
        assert not cam.is_recording


def test_context_manager_does_not_hide_original_error(
    synthetic_video: Path, tmp_path: Path
) -> None:
    with pytest.raises(KeyError), CaptureCamera.for_source(synthetic_video) as cam:
        cam.start_recording(tmp_path / "v.avi")  # sin frames: cerrar fallará
        raise KeyError("error original")


class _SlowWriter:
    """Escritor real que tarda en cada frame: fuerza a llenar la cola."""

    def __init__(self, *args: object) -> None:
        self._writer = cv2.VideoWriter(*args)

    def isOpened(self) -> bool:  # noqa: N802 (API de OpenCV)
        return self._writer.isOpened()

    def write(self, image: object) -> None:
        time.sleep(0.02)
        self._writer.write(image)

    def release(self) -> None:
        self._writer.release()


def test_camera_full_queue_counts_dropped_frames_but_keeps_duration(tmp_path: Path) -> None:
    clock = FakeClock(step=1 / 30)
    fake = FakeCapture(clock=clock)
    out = tmp_path / "v.avi"
    with CaptureCamera.for_index(
        0, capture_factory=fixed_factory(fake), clock=clock, writer_factory=_SlowWriter
    ) as cam:
        cam.start_recording(out, fps=30, queue_size=2)
        for _ in range(60):
            cam.read()
        stats = cam.stop_recording()
    assert stats.frames_dropped > 0
    assert stats.frames_received + stats.frames_dropped == 60
    # Los huecos se rellenan repitiendo el frame siguiente: la duración se conserva.
    assert stats.frames_written >= stats.frames_received
    assert count_frames(out)[0] == stats.frames_written


def test_file_source_waits_for_slow_writer_instead_of_dropping(
    synthetic_video: Path, tmp_path: Path
) -> None:
    out = tmp_path / "v.avi"
    with CaptureCamera.for_source(synthetic_video, writer_factory=_SlowWriter) as cam:
        cam.start_recording(out, queue_size=2)
        for _ in range(20):
            cam.read()
        stats = cam.stop_recording()
    assert stats.frames_dropped == 0
    assert stats.frames_written == 20


def test_mp4_falls_back_to_mp4v_when_h264_is_unavailable(
    synthetic_video: Path, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from colpo import capture

    monkeypatch.setattr(capture, "video_codec_candidates", lambda _s: ("H264", "mp4v"))
    attempts: list[str] = []

    def writer_factory(path: str, fourcc: int, fps: float, size: tuple[int, int]):
        code = "".join(chr((fourcc >> 8 * i) & 0xFF) for i in range(4))
        attempts.append(code)
        if code == "H264":
            return _BrokenWriter(opened=False)  # p. ej. Windows "N" sin codificador H.264
        return cv2.VideoWriter(path, fourcc, fps, size)

    out = tmp_path / "v.mp4"
    with CaptureCamera.for_source(synthetic_video, writer_factory=writer_factory) as cam:
        cam.start_recording(out)
        for _ in range(10):
            cam.read()
        stats = cam.stop_recording()
    assert attempts == ["H264", "mp4v"]
    assert stats.codec == "mp4v"
    assert count_frames(out)[0] == 10
