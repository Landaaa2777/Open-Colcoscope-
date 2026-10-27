"""Registro de drivers: descubrimiento por *entry points* y registro manual.

Los drivers se declaran en ``pyproject.toml`` del paquete que los distribuye::

    [project.entry-points."colpo.drivers"]
    uvc = "colpo.drivers.uvc:UVCCamera"
    mock = "colpo.drivers.mock:MockDriver"

Seguridad: solo se cargan *entry points* de paquetes **ya instalados** en el
entorno de Python (``importlib.metadata``). No hay descarga de plugins por red
ni importación de rutas arbitrarias. Un plugin que falla al cargar se registra
en :attr:`DriverRegistry.load_errors` y se ignora (no tumba la aplicación).
"""

from __future__ import annotations

import logging
import re
from importlib.metadata import entry_points
from typing import Any

from colpo.devices import DeviceInfo
from colpo.drivers.base import (
    DRIVER_CLASS_MEMBERS,
    DRIVER_INSTANCE_MEMBERS,
    CameraDriver,
    Capabilities,
)
from colpo.drivers.errors import DriverContractError

log = logging.getLogger(__name__)

ENTRY_POINT_GROUP = "colpo.drivers"
_NAME_RE = re.compile(r"^[a-z0-9][a-z0-9_-]*$")


def validate_driver_class(cls: object) -> str:
    """Comprueba que ``cls`` cumple la forma del contrato. Devuelve su ``name``."""
    if not isinstance(cls, type):
        raise DriverContractError(f"{cls!r} no es una clase.")
    name = getattr(cls, "name", None)
    if not isinstance(name, str) or not _NAME_RE.match(name):
        raise DriverContractError(
            f"{cls.__name__}.name debe ser un texto con minúsculas, dígitos, '_' o '-'."
        )
    missing = [
        m
        for m in DRIVER_CLASS_MEMBERS + DRIVER_INSTANCE_MEMBERS
        if not callable(getattr(cls, m, None))
    ]
    if missing:
        raise DriverContractError(f"{cls.__name__} no implementa: {', '.join(missing)}.")
    return name


class DriverRegistry:
    """Conjunto de clases de driver disponibles, por nombre."""

    def __init__(self) -> None:
        self._drivers: dict[str, type[CameraDriver]] = {}
        self.load_errors: dict[str, str] = {}

    # ------------------------------------------------------------- registro
    def register(self, cls: type[CameraDriver], *, replace: bool = False) -> str:
        """Registra una clase de driver (uso manual, p. ej. en pruebas)."""
        name = validate_driver_class(cls)
        if name in self._drivers and self._drivers[name] is not cls and not replace:
            raise DriverContractError(f"Ya hay un driver registrado con el nombre '{name}'.")
        self._drivers[name] = cls
        return name

    def unregister(self, name: str) -> None:
        self._drivers.pop(name, None)

    def load_entry_points(self) -> list[str]:
        """Carga los drivers declarados por paquetes instalados. Devuelve los nombres cargados."""
        loaded = []
        for ep in entry_points(group=ENTRY_POINT_GROUP):
            try:
                cls = ep.load()
                name = validate_driver_class(cls)
                if name != ep.name:
                    raise DriverContractError(
                        f"el entry point '{ep.name}' apunta a un driver llamado '{name}'"
                    )
                self.register(cls)
            except Exception as exc:  # un plugin roto no debe impedir arrancar
                self.load_errors[ep.name] = str(exc)
                log.warning("No se pudo cargar el driver '%s': %s", ep.name, exc)
                continue
            loaded.append(name)
        return loaded

    # ------------------------------------------------------------- consulta
    def list_drivers(self) -> dict[str, type[CameraDriver]]:
        return dict(self._drivers)

    def get(self, name: str) -> type[CameraDriver]:
        try:
            return self._drivers[name]
        except KeyError:
            raise DriverContractError(f"No hay ningún driver llamado '{name}'.") from None

    def probe_all(self, **options: Any) -> list[tuple[type[CameraDriver], DeviceInfo]]:
        """Dispositivos detectados por todos los drivers, con el driver que los maneja.

        ``options`` se pasan a ``discover()`` de cada driver (p. ej. ``backend=``).
        Un driver que falla al descubrir se ignora y queda en :attr:`load_errors`.
        """
        found: list[tuple[type[CameraDriver], DeviceInfo]] = []
        for name, cls in self._drivers.items():
            try:
                devices = cls.discover(**options)
            except Exception as exc:
                self.load_errors[name] = f"discover(): {exc}"
                log.warning("El driver '%s' falló al buscar dispositivos: %s", name, exc)
                continue
            found.extend((cls, device) for device in devices if cls.probe(device))
        return found

    def create(self, name: str, device: DeviceInfo, **options: Any) -> CameraDriver:
        """Instancia (sin abrir) el driver ``name`` para ``device``."""
        cls = self.get(name)
        if not cls.probe(device):
            raise DriverContractError(
                f"El driver '{name}' no maneja el dispositivo {device.name!r}."
            )
        return cls.for_device(device, **options)

    def describe(self, name: str, device: DeviceInfo, **options: Any) -> Capabilities:
        """Capacidades de un dispositivo sin abrirlo."""
        return self.create(name, device, **options).capabilities()


_default: DriverRegistry | None = None


def default_registry() -> DriverRegistry:
    """Registro de la aplicación: drivers de los *entry points* instalados.

    Si el paquete se ejecuta sin instalar (no hay *entry points*), se registran
    los drivers incluidos para que la aplicación siga funcionando.
    """
    global _default
    if _default is None:
        registry = DriverRegistry()
        registry.load_entry_points()
        if not registry.list_drivers():
            from colpo.drivers.mock import MockDriver
            from colpo.drivers.uvc import UVCCamera

            registry.register(UVCCamera)
            registry.register(MockDriver)
        _default = registry
    return _default
