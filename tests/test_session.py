"""Sesión de captura: foto/video con JSON, espacio en disco, marca de agua desactivada."""

from __future__ import annotations

import errno
from datetime import datetime, timedelta, timezone
from pathlib import Path

import numpy as np
import pytest

from colpo import (
    CaptureCamera,
    DiskFullError,
    MetadataError,
    NotesRejectedError,
    RecordingError,
    SnapshotError,
)
from colpo.capture import video_codec_candidates
from colpo.metadata import read_sidecar, sha256_file
from colpo.session import CaptureSession
from colpo.storage import capture_path, is_disk_full_error
from colpo.watermark import WATERMARK_DISABLED, WatermarkOptions, apply_watermark
from conftest import count_frames

LIMA = timezone(timedelta(hours=-5))
FIXED_NOW = datetime(2026, 10, 26, 15, 4, 5, tzinfo=LIMA)
PLENTY = 10 * 1024**3


def _session(tmp_path: Path, **kwargs) -> CaptureSession:
    kwargs.setdefault("now", lambda: FIXED_NOW)
    kwargs.setdefault("free_bytes", lambda _p: PLENTY)
    return CaptureSession(tmp_path / "datos", **kwargs)


def test_photo_writes_png_and_closed_json(synthetic_video: Path, tmp_path: Path) -> None:
    session = _session(tmp_path)
    session.stage = "lugol"
    session.set_notes("Maniquí, zona de transformación tipo 1")
    with CaptureCamera.for_source(synthetic_video) as cam:
        cam.read()
        result = session.take_photo(cam, fps=29.97)

    assert result.media_path == session.study_dir / "foto_20261026-150405.png"
    assert result.metadata_path == result.media_path.with_suffix(".json")
    meta = read_sidecar(result.metadata_path)
    assert meta == result.metadata
    assert meta.id_estudio == session.study_id
    assert meta.timestamp == "2026-10-26T15:04:05-05:00"
    assert meta.etapa_ifcpc == "lugol"
    assert (meta.ancho, meta.alto, meta.fps, meta.tipo) == (320, 240, 29.97, "foto")
    assert meta.sha256 == sha256_file(result.media_path)
    assert meta.notas == "Maniquí, zona de transformación tipo 1"


def test_same_second_captures_do_not_overwrite(synthetic_video: Path, tmp_path: Path) -> None:
    session = _session(tmp_path)
    with CaptureCamera.for_source(synthetic_video) as cam:
        cam.read()
        names = [session.take_photo(cam).media_path.name for _ in range(3)]
    assert names == [
        "foto_20261026-150405.png",
        "foto_20261026-150405_2.png",
        "foto_20261026-150405_3.png",
    ]


def test_video_writes_mp4_and_json(synthetic_video: Path, tmp_path: Path) -> None:
    session = _session(tmp_path)
    session.stage = "acido_acetico"
    with CaptureCamera.for_source(synthetic_video) as cam:
        path = session.start_video(cam, fps=29.7)
        assert session.is_recording and path.suffix == ".mp4"
        session.stage = "lugol"  # cambiar la etapa durante la grabación no altera este video
        for _ in range(30):
            cam.read()
        result = session.stop_video(cam)
    assert not session.is_recording
    meta = read_sidecar(result.metadata_path)
    assert meta.tipo == "video"
    assert meta.etapa_ifcpc == "acido_acetico"
    assert meta.fps == 30.0
    assert meta.sha256 == sha256_file(result.media_path)
    assert result.codec in video_codec_candidates(".mp4")
    assert count_frames(result.media_path)[0] == 30


def test_rejected_notes_are_never_saved(synthetic_video: Path, tmp_path: Path) -> None:
    session = _session(tmp_path)
    session.set_notes("nota válida")
    with pytest.raises(NotesRejectedError):
        session.set_notes("DNI 45871236")
    assert session.notes is None
    with CaptureCamera.for_source(synthetic_video) as cam:
        cam.read()
        assert session.take_photo(cam).metadata.notas is None


def test_invalid_stage(tmp_path: Path) -> None:
    with pytest.raises(MetadataError):
        _session(tmp_path).stage = "vinagre"


def test_new_study_changes_id_but_not_while_recording(
    synthetic_video: Path, tmp_path: Path
) -> None:
    session = _session(tmp_path)
    first = session.study_id
    assert session.new_study() != first
    with CaptureCamera.for_source(synthetic_video) as cam:
        session.start_video(cam)
        with pytest.raises(RecordingError):
            session.new_study()
        cam.read()
        session.stop_video(cam)


def test_disk_full_is_detected_before_capturing(synthetic_video: Path, tmp_path: Path) -> None:
    session = _session(tmp_path, free_bytes=lambda _p: 10 * 1024 * 1024)
    with CaptureCamera.for_source(synthetic_video) as cam:
        cam.read()
        with pytest.raises(DiskFullError, match="Espacio insuficiente"):
            session.take_photo(cam)
        with pytest.raises(DiskFullError):
            session.start_video(cam)
        with pytest.raises(DiskFullError):
            session.check_recording_space()
    assert not session.study_dir.exists() or not any(session.study_dir.iterdir())


def test_os_disk_full_is_reported_as_disk_full(
    synthetic_video: Path, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    session = _session(tmp_path)

    def full_disk(*_a: object, **_k: object) -> None:
        raise SnapshotError("No se pudo guardar") from OSError(errno.ENOSPC, "No space left")

    with CaptureCamera.for_source(synthetic_video) as cam:
        cam.read()
        monkeypatch.setattr(cam, "snapshot", full_disk)
        with pytest.raises(DiskFullError):
            session.take_photo(cam)


def test_stop_without_recording(synthetic_video: Path, tmp_path: Path) -> None:
    with CaptureCamera.for_source(synthetic_video) as cam, pytest.raises(RecordingError):
        _session(tmp_path).stop_video(cam)


def test_capture_path_and_disk_full_detection(tmp_path: Path) -> None:
    path = capture_path(tmp_path, "video", "2026-10-26T15:04:05-05:00", ".mp4")
    assert path.name == "video_20261026-150405.mp4"
    assert is_disk_full_error(OSError(errno.ENOSPC, "x"))
    assert not is_disk_full_error(OSError(errno.EACCES, "x"))
    assert not is_disk_full_error(None)


def test_watermark_is_disabled_by_default_but_hook_works(
    synthetic_video: Path, tmp_path: Path
) -> None:
    image = np.zeros((240, 320, 3), np.uint8)
    assert apply_watermark(image) is image
    assert apply_watermark(image, WATERMARK_DISABLED) is image
    marked = apply_watermark(image, WatermarkOptions(enabled=True))
    assert marked is not image and marked.any() and not image.any()

    assert _session(tmp_path).watermark.enabled is False
    session = _session(tmp_path, watermark=WatermarkOptions(enabled=True))
    with CaptureCamera.for_source(synthetic_video) as cam:
        frame = cam.read()
        result = session.take_photo(cam)
    assert result.metadata.sha256 == sha256_file(result.media_path)
    assert result.media_path.read_bytes() != b""
    assert frame.image.flags.writeable is False  # el frame original no se modifica


def test_mp4_codec_candidates() -> None:
    assert video_codec_candidates(".mp4", "Windows") == ("H264", "mp4v")
    assert video_codec_candidates(".mp4", "Linux") == ("mp4v",)
    assert video_codec_candidates(".avi", "Windows") == ("MJPG",)


def test_two_cameras_record_at_the_same_time_with_tags(tmp_path: Path) -> None:
    from colpo.drivers.mock import MockDriver

    session = _session(tmp_path)
    cams = [CaptureCamera(MockDriver(resolution=(320, 240), realtime=False)) for _ in range(2)]
    for cam in cams:
        cam.open()
    try:
        paths = [session.start_video(cam, fps=30, tag=f"mock{i}") for i, cam in enumerate(cams)]
        assert session.is_recording and all(session.is_recording_on(c) for c in cams)
        assert [p.name for p in paths] == [
            "video_20261026-150405_mock0.mp4",
            "video_20261026-150405_mock1.mp4",
        ]
        for _ in range(10):
            for cam in cams:
                cam.read()
        first = session.stop_video(cams[0])
        assert session.is_recording and not session.is_recording_on(cams[0])
        second = session.stop_video(cams[1])
    finally:
        for cam in cams:
            cam.close()
    assert not session.is_recording
    assert first.media_path != second.media_path
    assert read_sidecar(first.metadata_path).tipo == "video"


def _first_video_frame(path: Path) -> np.ndarray:
    import cv2

    cap = cv2.VideoCapture(str(path))
    ok, image = cap.read()
    cap.release()
    assert ok
    return image


def test_video_watermark_only_when_enabled(synthetic_video: Path, tmp_path: Path) -> None:
    from colpo.synthetic import make_frame

    original = make_frame(0, 320, 240).astype(np.int16)
    bottom = slice(200, 240)
    differences = {}
    for enabled in (False, True):
        session = _session(tmp_path / str(enabled), watermark=WatermarkOptions(enabled=enabled))
        with CaptureCamera.for_source(synthetic_video) as cam:
            session.start_video(cam)
            for _ in range(5):
                cam.read()
            result = session.stop_video(cam)
        frame = _first_video_frame(result.media_path).astype(np.int16)
        differences[enabled] = float(np.abs(frame[bottom] - original[bottom]).mean())
    # Sin marca de agua solo hay ruido de compresión; con ella, el texto cambia la franja.
    assert differences[False] < 6
    assert differences[True] > differences[False] + 5
