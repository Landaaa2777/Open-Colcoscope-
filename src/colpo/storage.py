"""Ubicación de las capturas en disco y comprobaciones de espacio libre.

Estructura::

    <carpeta de datos>/            por defecto %USERPROFILE%\\OpenColposcope
        E-7F3K2Q9M/                un directorio por estudio (seudónimo aleatorio)
            foto_20261026-150405.png
            foto_20261026-150405.json
            video_20261026-150412.mp4
            video_20261026-150412.json

La carpeta por defecto está fuera de "Documentos" a propósito: en muchos equipos
Windows, "Documentos" se sincroniza con OneDrive, y las capturas no deben salir
del equipo.
"""

from __future__ import annotations

import errno
import os
import shutil
from datetime import datetime
from pathlib import Path

from colpo.errors import DiskFullError

DATA_DIR_NAME = "OpenColposcope"

MB = 1024 * 1024
MIN_FREE_PHOTO_BYTES = 50 * MB
MIN_FREE_VIDEO_START_BYTES = 500 * MB
# Durante una grabación, por debajo de este umbral se detiene (guardando lo grabado).
MIN_FREE_VIDEO_CONTINUE_BYTES = 200 * MB

_WINDOWS_DISK_FULL = {112, 39}  # ERROR_DISK_FULL, ERROR_HANDLE_DISK_FULL


def default_data_dir() -> Path:
    """Carpeta de datos predeterminada: ``~/OpenColposcope``."""
    return Path.home() / DATA_DIR_NAME


def capture_path(directory: Path, tipo: str, timestamp: str, extension: str) -> Path:
    """Ruta libre para una captura: ``<tipo>_AAAAMMDD-HHMMSS<ext>``.

    Si ya existe una captura (o su JSON) en ese mismo segundo, añade ``_2``, ``_3``...
    """
    stamp = datetime.fromisoformat(timestamp).strftime("%Y%m%d-%H%M%S")
    base = f"{tipo}_{stamp}"
    candidate = directory / f"{base}{extension}"
    counter = 2
    while candidate.exists() or candidate.with_suffix(".json").exists():
        candidate = directory / f"{base}_{counter}{extension}"
        counter += 1
    return candidate


def free_bytes(path: str | os.PathLike[str]) -> int:
    """Bytes libres en el volumen de ``path`` (o de su ancestro existente más cercano)."""
    current = Path(path).resolve()
    while not current.exists() and current != current.parent:
        current = current.parent
    return shutil.disk_usage(current).free


def ensure_free_space(path: str | os.PathLike[str], required: int) -> None:
    """Lanza :class:`DiskFullError` si quedan menos de ``required`` bytes libres."""
    available = free_bytes(path)
    if available < required:
        raise DiskFullError(
            f"Espacio insuficiente en disco: quedan {available // MB} MB y se necesitan al "
            f"menos {required // MB} MB. Libere espacio o cambie la carpeta de datos."
        )


def is_disk_full_error(exc: BaseException | None) -> bool:
    """``True`` si la excepción (o alguna de sus causas) es un "disco lleno" del SO."""
    seen: set[int] = set()
    while exc is not None and id(exc) not in seen:
        seen.add(id(exc))
        if isinstance(exc, DiskFullError):
            return True
        if isinstance(exc, OSError) and (
            exc.errno in (errno.ENOSPC, errno.EDQUOT)
            or getattr(exc, "winerror", None) in _WINDOWS_DISK_FULL
        ):
            return True
        exc = exc.__cause__ or exc.__context__
    return False
