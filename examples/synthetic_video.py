"""Genera un video sintético para probar la captura sin colposcopio.

El video no contiene imágenes humanas: barras de color, un círculo en
movimiento y, en la franja superior, el número de frame codificado en bloques
blanco/negro (resistente a la compresión) para que las pruebas verifiquen que
no se pierden ni se desordenan frames.

Uso:
    python examples/synthetic_video.py demo.avi --frames 300 --fps 30 --size 1280x720
    colpo preview --source demo.avi
"""

from __future__ import annotations

import argparse
from pathlib import Path

import cv2

from colpo.synthetic import BLOCK, CODE_BITS, MIN_WIDTH, decode_index, make_frame

__all__ = ["BLOCK", "CODE_BITS", "MIN_WIDTH", "decode_index", "generate", "main", "make_frame"]

_CODECS = {".avi": "MJPG", ".mkv": "MJPG", ".mp4": "mp4v"}


def generate(
    path: str | Path,
    *,
    frames: int = 90,
    fps: float = 30.0,
    size: tuple[int, int] = (640, 480),
) -> Path:
    """Escribe el video sintético en ``path`` (.avi/.mkv con MJPEG, .mp4 con mp4v)."""
    target = Path(path)
    codec = _CODECS.get(target.suffix.lower())
    if codec is None:
        raise ValueError(f"Extensión no soportada: {target.suffix} (use {', '.join(_CODECS)})")
    target.parent.mkdir(parents=True, exist_ok=True)
    width, height = size
    writer = cv2.VideoWriter(str(target), cv2.VideoWriter_fourcc(*codec), fps, (width, height))
    if not writer.isOpened():
        raise RuntimeError(f"No se pudo crear {target}")
    try:
        for index in range(frames):
            writer.write(make_frame(index, width, height))
    finally:
        writer.release()
    return target


def _parse_size(text: str) -> tuple[int, int]:
    width, _, height = text.lower().partition("x")
    return int(width), int(height)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("out", type=Path, help="archivo de salida (.avi, .mkv o .mp4)")
    parser.add_argument("--frames", type=int, default=300)
    parser.add_argument("--fps", type=float, default=30.0)
    parser.add_argument("--size", type=_parse_size, default=(1280, 720), help="ANCHOxALTO")
    args = parser.parse_args(argv)
    path = generate(args.out, frames=args.frames, fps=args.fps, size=args.size)
    print(f"Video sintético: {path} ({args.frames} frames a {args.fps:g} FPS)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
