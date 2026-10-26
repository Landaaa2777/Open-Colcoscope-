"""Metadatos por captura: un JSON junto a cada foto o video, con lista cerrada de campos.

Campos (y solo estos)::

    id_estudio   seudónimo aleatorio del estudio (no derivado de datos de la paciente)
    timestamp    fecha y hora local exactas al segundo, ISO 8601 con desfase UTC
    etapa_ifcpc  basal | solucion_salina | acido_acetico | lugol | filtro_verde
    resolucion   {"ancho": int, "alto": int}
    fps          FPS de la captura (foto: medidos en vivo; video: los del archivo)
    tipo         foto | video
    sha256       hash del archivo de imagen/video
    notas        texto libre opcional, sin datos identificables (o null)

No existen campos para nombre, documento, fecha de nacimiento, número de serie
del equipo ni nada parecido: el esquema rechaza cualquier campo adicional.
"""

from __future__ import annotations

import hashlib
import json
import os
import re
import secrets
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any

from colpo.capture import _atomic_write
from colpo.errors import MetadataError, NotesRejectedError

# Vocabulario IFCPC de etapas del examen colposcópico (códigos estables; la UI los traduce).
IFCPC_STAGES: tuple[str, ...] = (
    "basal",
    "solucion_salina",
    "acido_acetico",
    "lugol",
    "filtro_verde",
)
DEFAULT_STAGE = "basal"
CAPTURE_TYPES: tuple[str, ...] = ("foto", "video")
METADATA_FIELDS: tuple[str, ...] = (
    "id_estudio",
    "timestamp",
    "etapa_ifcpc",
    "resolucion",
    "fps",
    "tipo",
    "sha256",
    "notas",
)
MAX_NOTES_LENGTH = 500

# Sin 0/O, 1/I/L ni U: se leen sin ambigüedad si alguien los copia a mano.
_STUDY_ALPHABET = "23456789ABCDEFGHJKMNPQRSTVWXYZ"
_STUDY_ID_RE = re.compile(rf"^E-[{_STUDY_ALPHABET}]{{8}}$")
_TIMESTAMP_RE = re.compile(r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}[+-]\d{2}:\d{2}$")
_SHA256_RE = re.compile(r"^[0-9a-f]{64}$")

# Patrones de posibles identificadores en las notas. Es una red de seguridad, no
# una garantía: la responsabilidad de no escribir datos personales sigue siendo
# de quien escribe.
_IDENTIFIER_PATTERNS: dict[str, re.Pattern[str]] = {
    "email": re.compile(r"[\w.+-]+@[\w-]+\.[\w.-]+"),
    "fecha": re.compile(r"\b\d{1,2}[/.-]\d{1,2}[/.-]\d{2,4}\b"),
    # DNI (8 dígitos), celulares (9), historias clínicas: 7 o más dígitos seguidos,
    # admitiendo espacios, puntos o guiones entre ellos.
    "numero_largo": re.compile(r"\d(?:[\s.-]?\d){6,}"),
    "palabra_clave": re.compile(
        r"\b(dni|documento|pasaporte|carn[eé]|historia\s+cl[ií]nica|nombres?|apellidos?|"
        r"tel[eé]fono|celular|direcci[oó]n|domicilio|fecha\s+de\s+nacimiento|"
        r"name|surname|phone|address|passport|birth\s*date|date\s+of\s+birth)\b",
        re.IGNORECASE,
    ),
}


def new_study_id() -> str:
    """Seudónimo aleatorio de estudio, p. ej. ``E-7F3K2Q9M`` (~39 bits de azar)."""
    return "E-" + "".join(secrets.choice(_STUDY_ALPHABET) for _ in range(8))


def capture_timestamp(now: datetime | None = None) -> str:
    """Hora local exacta al segundo con desfase UTC: ``2026-10-26T15:04:05-05:00``."""
    moment = now or datetime.now()
    if moment.tzinfo is None:  # hora local del equipo, con su desfase UTC
        moment = moment.astimezone()
    return moment.replace(microsecond=0).isoformat()


def find_identifier_risks(text: str) -> tuple[str, ...]:
    """Códigos de los patrones de posibles identificadores encontrados en ``text``."""
    return tuple(code for code, pattern in _IDENTIFIER_PATTERNS.items() if pattern.search(text))


def clean_notes(text: str | None) -> str | None:
    """Normaliza las notas o lanza :class:`NotesRejectedError`.

    Devuelve ``None`` si están vacías.
    """
    if text is None:
        return None
    stripped = text.strip()
    if not stripped:
        return None
    if len(stripped) > MAX_NOTES_LENGTH:
        raise NotesRejectedError(
            f"Las notas superan {MAX_NOTES_LENGTH} caracteres.", ("demasiado_largo",)
        )
    risks = find_identifier_risks(stripped)
    if risks:
        raise NotesRejectedError(
            "Las notas parecen contener datos que identifican a la paciente "
            f"({', '.join(risks)}); no se guardarán.",
            risks,
        )
    return stripped


def sha256_file(path: str | os.PathLike[str], chunk_size: int = 1 << 20) -> str:
    """SHA-256 hexadecimal de un archivo, leído por bloques."""
    digest = hashlib.sha256()
    with open(path, "rb") as fh:
        while chunk := fh.read(chunk_size):
            digest.update(chunk)
    return digest.hexdigest()


@dataclass(frozen=True)
class CaptureMetadata:
    """Metadatos de una captura. Se valida al construirse."""

    id_estudio: str
    timestamp: str
    etapa_ifcpc: str
    ancho: int
    alto: int
    fps: float
    tipo: str
    sha256: str
    notas: str | None = None

    def __post_init__(self) -> None:
        if not _STUDY_ID_RE.match(self.id_estudio):
            raise MetadataError(f"id_estudio no válido: {self.id_estudio!r}")
        if not _TIMESTAMP_RE.match(self.timestamp):
            raise MetadataError(f"timestamp debe ser ISO 8601 al segundo: {self.timestamp!r}")
        if self.etapa_ifcpc not in IFCPC_STAGES:
            raise MetadataError(f"etapa_ifcpc no válida: {self.etapa_ifcpc!r}")
        if self.tipo not in CAPTURE_TYPES:
            raise MetadataError(f"tipo no válido: {self.tipo!r}")
        if not _SHA256_RE.match(self.sha256):
            raise MetadataError("sha256 debe tener 64 caracteres hexadecimales en minúscula.")
        if self.ancho <= 0 or self.alto <= 0:
            raise MetadataError("La resolución debe ser positiva.")
        if self.fps < 0:
            raise MetadataError("fps no puede ser negativo.")
        object.__setattr__(self, "fps", round(float(self.fps), 2))
        object.__setattr__(self, "notas", clean_notes(self.notas))

    def to_dict(self) -> dict[str, Any]:
        """Diccionario con exactamente :data:`METADATA_FIELDS`, en ese orden."""
        return {
            "id_estudio": self.id_estudio,
            "timestamp": self.timestamp,
            "etapa_ifcpc": self.etapa_ifcpc,
            "resolucion": {"ancho": self.ancho, "alto": self.alto},
            "fps": self.fps,
            "tipo": self.tipo,
            "sha256": self.sha256,
            "notas": self.notas,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> CaptureMetadata:
        """Valida un diccionario leído de disco (lista cerrada de campos)."""
        if not isinstance(data, dict) or set(data) != set(METADATA_FIELDS):
            extra = sorted(set(data) - set(METADATA_FIELDS)) if isinstance(data, dict) else []
            missing = sorted(set(METADATA_FIELDS) - set(data)) if isinstance(data, dict) else []
            raise MetadataError(
                f"Campos de metadatos no válidos. Sobran: {extra}; faltan: {missing}."
            )
        resolution = data["resolucion"]
        if not isinstance(resolution, dict) or set(resolution) != {"ancho", "alto"}:
            raise MetadataError("resolucion debe ser {'ancho': int, 'alto': int}.")
        return cls(
            id_estudio=data["id_estudio"],
            timestamp=data["timestamp"],
            etapa_ifcpc=data["etapa_ifcpc"],
            ancho=int(resolution["ancho"]),
            alto=int(resolution["alto"]),
            fps=float(data["fps"]),
            tipo=data["tipo"],
            sha256=data["sha256"],
            notas=data["notas"],
        )


def sidecar_path(media_path: str | os.PathLike[str]) -> Path:
    """Ruta del JSON de una captura: mismo nombre, extensión ``.json``."""
    return Path(media_path).with_suffix(".json")


def write_sidecar(media_path: str | os.PathLike[str], metadata: CaptureMetadata) -> Path:
    """Escribe el JSON junto a la captura, de forma atómica. Devuelve su ruta."""
    target = sidecar_path(media_path)
    text = json.dumps(metadata.to_dict(), ensure_ascii=False, indent=2) + "\n"
    _atomic_write(target, text.encode("utf-8"))
    return target


def read_sidecar(path: str | os.PathLike[str]) -> CaptureMetadata:
    """Lee y valida un JSON de metadatos."""
    try:
        data = json.loads(Path(path).read_text(encoding="utf-8"))
    except (OSError, ValueError) as exc:
        raise MetadataError(f"No se pudo leer '{path}': {exc}") from exc
    return CaptureMetadata.from_dict(data)
