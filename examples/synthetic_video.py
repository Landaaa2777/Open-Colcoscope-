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
import numpy as np

CODE_BITS = 16
BLOCK = 16
MIN_WIDTH = CODE_BITS * BLOCK

# BGR: blanco, amarillo, cian, verde, magenta, rojo, azul, negro.
_BARS = (
    (255, 255, 255),
    (0, 255, 255),
    (255, 255, 0),
    (0, 255, 0),
    (255, 0, 255),
    (0, 0, 255),
    (255, 0, 0),
    (0, 0, 0),
)
_CODECS = {".avi": "MJPG", ".mkv": "MJPG", ".mp4": "mp4v"}


def make_frame(index: int, width: int = 640, height: int = 480) -> np.ndarray:
    """Devuelve el frame ``index`` (BGR, uint8)."""
    if width < MIN_WIDTH or height < 4 * BLOCK:
        raise ValueError(f"Tamaño mínimo: {MIN_WIDTH}x{4 * BLOCK}")
    image = np.zeros((height, width, 3), np.uint8)
    bar_width = -(-width // len(_BARS))
    for i, color in enumerate(_BARS):
        image[:, i * bar_width : (i + 1) * bar_width] = color

    radius = max(8, height // 8)
    x = radius + (index * 7) % max(1, width - 2 * radius)
    cv2.circle(image, (x, height // 2), radius, (40, 40, 200), thickness=-1)
    cv2.putText(
        image,
        f"SINTETICO {index:05d}",
        (8, height - 12),
        cv2.FONT_HERSHEY_SIMPLEX,
        max(0.4, height / 600),
        (128, 128, 128),
        2,
        cv2.LINE_AA,
    )
    _encode_index(image, index)
    return image


def _encode_index(image: np.ndarray, index: int) -> None:
    image[: 2 * BLOCK, :] = 0
    for bit in range(CODE_BITS):
        if (index >> bit) & 1:
            image[: 2 * BLOCK, bit * BLOCK : (bit + 1) * BLOCK] = 255


def decode_index(image: np.ndarray) -> int:
    """Lee el número de frame codificado por :func:`make_frame`."""
    value = 0
    margin = BLOCK // 4
    for bit in range(CODE_BITS):
        cell = image[margin : 2 * BLOCK - margin, bit * BLOCK + margin : (bit + 1) * BLOCK - margin]
        if float(cell.mean()) > 127:
            value |= 1 << bit
    return value


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
