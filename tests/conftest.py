"""Fixtures compartidas: video sintético y una cámara simulada (sin hardware)."""

from __future__ import annotations

from pathlib import Path

import cv2
import numpy as np
import pytest

from synthetic_video import generate, make_frame

SYNTH_FRAMES = 90
SYNTH_FPS = 30.0
SYNTH_SIZE = (320, 240)


@pytest.fixture(scope="session")
def synthetic_video(tmp_path_factory: pytest.TempPathFactory) -> Path:
    """Video MJPEG de 3 s (90 frames a 30 FPS, 320x240)."""
    path = tmp_path_factory.mktemp("synthetic") / "synthetic.avi"
    return generate(path, frames=SYNTH_FRAMES, fps=SYNTH_FPS, size=SYNTH_SIZE)


class FakeClock:
    """Reloj manual: cada frame leído avanza ``step`` segundos."""

    def __init__(self, step: float) -> None:
        self.now = 1000.0
        self.step = step

    def __call__(self) -> float:
        return self.now

    def tick(self) -> None:
        self.now += self.step


class FakeCapture:
    """Imita ``cv2.VideoCapture`` para una cámara UVC.

    ``fail_after``: tras ese número de lecturas, ``read()`` devuelve ``False``
    siempre (simula desconexión). ``opened=False`` simula una cámara inexistente.
    """

    def __init__(
        self,
        *,
        opened: bool = True,
        fail_after: int | None = None,
        size: tuple[int, int] = SYNTH_SIZE,
        fps: float = 30.0,
        clock: FakeClock | None = None,
    ) -> None:
        self.opened = opened
        self.fail_after = fail_after
        self.size = size
        self.props: dict[int, float] = {
            cv2.CAP_PROP_FPS: fps,
            cv2.CAP_PROP_FOURCC: float(cv2.VideoWriter_fourcc(*"MJPG")),
        }
        self.set_calls: list[tuple[int, float]] = []
        self.reads = 0
        self.released = False
        self.clock = clock

    def isOpened(self) -> bool:  # noqa: N802 (API de OpenCV)
        return self.opened

    def read(self) -> tuple[bool, np.ndarray | None]:
        if self.fail_after is not None and self.reads >= self.fail_after:
            return False, None
        frame = make_frame(self.reads, *self.size)
        self.reads += 1
        if self.clock is not None:
            self.clock.tick()
        return True, frame

    def get(self, prop: int) -> float:
        return self.props.get(prop, 0.0)

    def set(self, prop: int, value: float) -> bool:
        self.set_calls.append((prop, value))
        return True

    def release(self) -> None:
        self.released = True


def factory_for(capture: FakeCapture):
    """``capture_factory`` que siempre devuelve la misma instancia simulada."""

    def factory(*_args: object) -> FakeCapture:
        return capture

    return factory


def count_frames(path: Path) -> tuple[int, float, tuple[int, int], list[np.ndarray]]:
    """Lee un video completo: (frames, fps, (ancho, alto), lista de frames)."""
    cap = cv2.VideoCapture(str(path))
    assert cap.isOpened(), f"no se puede abrir {path}"
    frames = []
    while True:
        ok, image = cap.read()
        if not ok:
            break
        frames.append(image)
    fps = cap.get(cv2.CAP_PROP_FPS)
    cap.release()
    size = (frames[0].shape[1], frames[0].shape[0]) if frames else (0, 0)
    return len(frames), fps, size, frames
