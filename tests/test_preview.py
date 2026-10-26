"""Pruebas de la ventana de vista previa en modo *offscreen* (sin pantalla)."""

from __future__ import annotations

import os
from pathlib import Path

import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
qt_widgets = pytest.importorskip("PySide6.QtWidgets", reason="PySide6 no disponible")

from colpo import UVCCamera  # noqa: E402
from colpo.preview import PreviewResult, PreviewWindow, frame_to_qimage, run_preview  # noqa: E402


@pytest.fixture(scope="module")
def qapp():
    return qt_widgets.QApplication.instance() or qt_widgets.QApplication([])


def test_frame_to_qimage_keeps_size_and_colors(synthetic_video: Path, qapp) -> None:
    with UVCCamera(source=synthetic_video) as cam:
        frame = cam.read_frame()
    qimage = frame_to_qimage(frame)
    assert (qimage.width(), qimage.height()) == (frame.width, frame.height)
    blue, green, red = (int(c) for c in frame.image[100, 5])
    color = qimage.pixelColor(5, 100)
    assert (color.red(), color.green(), color.blue()) == (red, green, blue)


def test_run_preview_shows_frames(synthetic_video: Path, tmp_path: Path, qapp) -> None:
    with UVCCamera(source=synthetic_video) as cam:
        result = run_preview(cam, out_dir=tmp_path, max_frames=5)
    assert result.frames_shown == 5
    assert result.error is None


def test_preview_snapshot_and_recording_keys(synthetic_video: Path, tmp_path: Path, qapp) -> None:
    result = PreviewResult()
    with UVCCamera(source=synthetic_video) as cam:
        window = PreviewWindow(cam, tmp_path, result)
        window._timer.stop()  # se avanza a mano para que la prueba sea determinista
        window._tick()
        window.take_snapshot()
        window.toggle_recording()
        for _ in range(10):
            window._tick()
        window.toggle_recording()
        window.close()

    assert len(result.snapshots) == 1 and result.snapshots[0].exists()
    assert len(result.recordings) == 1
    assert result.recordings[0].path.suffix == ".mp4"
    assert result.recordings[0].frames_written == 10
