"""El generador sintético debe ser fiable: las demás pruebas dependen de él."""

from __future__ import annotations

from pathlib import Path

import pytest

from conftest import count_frames
from synthetic_video import MIN_WIDTH, decode_index, generate, main, make_frame


@pytest.mark.parametrize("index", [0, 1, 2, 255, 1023, 65535])
def test_index_roundtrip(index: int) -> None:
    assert decode_index(make_frame(index, 320, 240)) == index


def test_generate_and_cli(tmp_path: Path) -> None:
    path = generate(tmp_path / "a.mp4", frames=12, fps=24, size=(MIN_WIDTH, 128))
    n, fps, size, frames = count_frames(path)
    assert (n, size) == (12, (MIN_WIDTH, 128))
    assert fps == pytest.approx(24)
    assert [decode_index(f) for f in frames] == list(range(12))
    assert main([str(tmp_path / "b.avi"), "--frames", "3", "--size", "320x240"]) == 0


def test_rejects_too_small_or_unknown_format(tmp_path: Path) -> None:
    with pytest.raises(ValueError):
        make_frame(0, 100, 100)
    with pytest.raises(ValueError):
        generate(tmp_path / "a.mov")
