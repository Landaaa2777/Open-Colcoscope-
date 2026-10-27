"""Perfiles de dispositivo: un JSON por modelo, con su VID:PID y datos de compatibilidad.

Los perfiles se distribuyen **dentro del paquete** (esta carpeta) y se leen sin
red. El formato está documentado en docs/DRIVER_GUIDE.md. Un perfil:

- se asocia a un dispositivo por ``vendor_id``/``product_id`` (si son ``null``,
  el perfil queda documentado pero no se aplica automáticamente);
- recomienda driver y API de captura;
- lista resoluciones preferidas; solo se solicitan a la cámara las que tienen
  ``"verificada": true``;
- declara controles conocidos (``true``/``false``/``null`` = desconocido).
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass
from functools import lru_cache
from importlib import resources
from typing import Any

from colpo.devices import DeviceInfo

SCHEMA = "colpo-perfil/1"
STATES = ("confirmado_uvc", "no_uvc", "desconocido")
_ID_RE = re.compile(r"^[a-z0-9][a-z0-9-]*$")
_REQUIRED = (
    "esquema",
    "id",
    "nombre",
    "fabricante",
    "modelo",
    "vendor_id",
    "product_id",
    "estado",
    "driver_recomendado",
    "api_recomendada",
    "resoluciones_preferidas",
    "controles",
    "notas",
)
_OPTIONAL = ("verificacion",)
_CONTROLS = ("zoom", "brillo", "balance_blancos")


class ProfileError(ValueError):
    """Perfil mal formado."""


@dataclass(frozen=True)
class PreferredMode:
    ancho: int
    alto: int
    fps: float
    formato: str
    verificada: bool


@dataclass(frozen=True)
class DeviceProfile:
    id: str
    nombre: str
    fabricante: str
    modelo: str
    vendor_id: int | None
    product_id: int | None
    estado: str
    driver_recomendado: str
    api_recomendada: str
    resoluciones_preferidas: tuple[PreferredMode, ...]
    controles: dict[str, bool | None]
    notas: tuple[str, ...]

    @property
    def vid_pid(self) -> str | None:
        if self.vendor_id is None or self.product_id is None:
            return None
        return f"{self.vendor_id:04X}:{self.product_id:04X}"

    def matches(self, device: DeviceInfo) -> bool:
        return (
            self.vendor_id is not None
            and self.product_id is not None
            and device.vendor_id == self.vendor_id
            and device.product_id == self.product_id
        )

    @property
    def verified_modes(self) -> tuple[PreferredMode, ...]:
        return tuple(m for m in self.resoluciones_preferidas if m.verificada)


def _parse_id(value: Any, field_name: str, source: str) -> int | None:
    if value is None:
        return None
    if isinstance(value, str) and re.fullmatch(r"(0x)?[0-9a-fA-F]{4}", value):
        return int(value, 16)
    raise ProfileError(f"{source}: '{field_name}' debe ser null o hexadecimal de 4 dígitos.")


def parse_profile(data: dict[str, Any], source: str = "<perfil>") -> DeviceProfile:
    """Valida un perfil (diccionario leído de JSON) y lo convierte en :class:`DeviceProfile`."""
    if not isinstance(data, dict):
        raise ProfileError(f"{source}: el perfil debe ser un objeto JSON.")
    missing = [k for k in _REQUIRED if k not in data]
    extra = [k for k in data if k not in _REQUIRED + _OPTIONAL]
    if missing or extra:
        raise ProfileError(f"{source}: faltan {missing}; sobran {extra}.")
    if data["esquema"] != SCHEMA:
        raise ProfileError(f"{source}: esquema debe ser '{SCHEMA}'.")
    if not _ID_RE.match(str(data["id"])):
        raise ProfileError(f"{source}: 'id' debe usar minúsculas, dígitos y guiones.")
    if data["estado"] not in STATES:
        raise ProfileError(f"{source}: 'estado' debe ser uno de {STATES}.")
    vendor = _parse_id(data["vendor_id"], "vendor_id", source)
    product = _parse_id(data["product_id"], "product_id", source)
    if (vendor is None) != (product is None):
        raise ProfileError(f"{source}: vendor_id y product_id van juntos (ambos o ninguno).")
    if data["api_recomendada"] not in ("auto", "dshow", "msmf", "v4l2", "avfoundation"):
        raise ProfileError(f"{source}: 'api_recomendada' no válida.")

    modes = []
    for i, mode in enumerate(data["resoluciones_preferidas"]):
        try:
            parsed = PreferredMode(
                ancho=int(mode["ancho"]),
                alto=int(mode["alto"]),
                fps=float(mode["fps"]),
                formato=str(mode["formato"]),
                verificada=bool(mode["verificada"]),
            )
        except (KeyError, TypeError, ValueError) as exc:
            raise ProfileError(
                f"{source}: resoluciones_preferidas[{i}] no válida ({exc})."
            ) from exc
        if parsed.ancho <= 0 or parsed.alto <= 0 or parsed.fps <= 0 or len(parsed.formato) != 4:
            raise ProfileError(f"{source}: resoluciones_preferidas[{i}] fuera de rango.")
        modes.append(parsed)

    controls = data["controles"]
    if not isinstance(controls, dict) or set(controls) != set(_CONTROLS):
        raise ProfileError(f"{source}: 'controles' debe tener exactamente {_CONTROLS}.")
    if any(v not in (True, False, None) for v in controls.values()):
        raise ProfileError(f"{source}: los controles valen true, false o null.")
    notes = data["notas"]
    if not isinstance(notes, list) or not all(isinstance(n, str) for n in notes):
        raise ProfileError(f"{source}: 'notas' debe ser una lista de textos.")

    return DeviceProfile(
        id=data["id"],
        nombre=str(data["nombre"]),
        fabricante=str(data["fabricante"]),
        modelo=str(data["modelo"]),
        vendor_id=vendor,
        product_id=product,
        estado=data["estado"],
        driver_recomendado=str(data["driver_recomendado"]),
        api_recomendada=data["api_recomendada"],
        resoluciones_preferidas=tuple(modes),
        controles=dict(controls),
        notas=tuple(notes),
    )


@lru_cache(maxsize=1)
def load_profiles() -> tuple[DeviceProfile, ...]:
    """Carga y valida todos los perfiles incluidos en el paquete."""
    profiles = []
    seen_ids: set[str] = set()
    seen_vid_pid: set[str] = set()
    for entry in sorted(resources.files(__name__).iterdir(), key=lambda p: p.name):
        if not entry.name.endswith(".json"):
            continue
        profile = parse_profile(json.loads(entry.read_text(encoding="utf-8")), entry.name)
        if profile.id in seen_ids:
            raise ProfileError(f"{entry.name}: id duplicado '{profile.id}'.")
        if profile.vid_pid and profile.vid_pid in seen_vid_pid:
            raise ProfileError(f"{entry.name}: VID:PID duplicado {profile.vid_pid}.")
        seen_ids.add(profile.id)
        if profile.vid_pid:
            seen_vid_pid.add(profile.vid_pid)
        profiles.append(profile)
    return tuple(profiles)


def find_profile(device: DeviceInfo) -> DeviceProfile | None:
    """Perfil cuyo VID:PID coincide con el dispositivo (o ``None``)."""
    return next((p for p in load_profiles() if p.matches(device)), None)
