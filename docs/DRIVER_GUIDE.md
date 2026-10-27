# Guía para escribir un driver de cámara

> Prototipo educativo — no validado para diagnóstico clínico. Política **clean-room**:
> nada del software propietario, del firmware ni del dongle de ningún fabricante entra en
> este repositorio (ver [§7](#7-qué-no-hacer) y [RISKS.md §5](RISKS.md#5-por-qué-no-se-emula-el-dongle)).

Un **driver** sabe hablar con un tipo de dispositivo y nada más: lo encuentra, lo abre,
entrega frames y describe lo que sabe hacer. Fotos, video, metadatos, marca de agua,
almacenamiento e interfaz los pone el núcleo para cualquier driver.

```text
 UI (PySide6) ── solo conoce el registro y CaptureCamera ──┐
                                                           ▼
 colpo.live / colpo.session ──► CaptureCamera (foto, video, FPS, marca de agua)
                                        │  usa el contrato CameraDriver
                                        ▼
            ┌──────────────── DriverRegistry (entry points "colpo.drivers") ──────────────┐
            │  uvc → UVCCamera (OpenCV)   mock → MockDriver   tu_driver → TuDriver …       │
            └──────────────────────────────────────────────────────────────────────────────┘
                                        ▲
                         perfiles JSON por VID:PID (colpo/drivers/profiles/)
```

## 1. Registrar un driver nuevo en 3 pasos

1. **Crea el archivo** `src/colpo/drivers/<nombre>.py` (copia `mock.py`, que está comentado
   como ejemplo) e implementa el contrato ([§2](#2-el-contrato-cameradriver)).
2. **Regístralo** en `pyproject.toml` y reinstala:

   ```toml
   [project.entry-points."colpo.drivers"]
   uvc = "colpo.drivers.uvc:UVCCamera"
   mock = "colpo.drivers.mock:MockDriver"
   mi_equipo = "colpo.drivers.mi_equipo:MiEquipoDriver"   # ← nueva línea
   ```

   ```powershell
   pip install -e .
   colpo drivers          # debe aparecer "mi_equipo"
   ```

3. **Pasa la suite de contrato**:

   ```powershell
   pytest tests/test_driver_contract.py -k mi_equipo                         # forma y reglas
   $env:COLPO_CONTRACT_HARDWARE = "1"; pytest tests/test_driver_contract.py -k mi_equipo   # con el equipo conectado
   ```

No hace falta tocar el núcleo ni la interfaz: la app descubre el driver, lo muestra
agrupado en el selector y le da foto, video, metadatos y marca de agua.

También puedes distribuirlo **como paquete aparte** (`colpo-driver-mi-equipo`) con la misma
sección `[project.entry-points."colpo.drivers"]` en su propio `pyproject.toml`; al instalarlo
con `pip`, la app lo encuentra. (Así se verificó en F3 con un paquete de ejemplo.)

## 2. El contrato `CameraDriver`

Definido en `src/colpo/drivers/base.py`.

| Miembro | Tipo | Qué debe hacer |
|---|---|---|
| `name` | atributo de clase | Identificador único (`[a-z0-9_-]`), igual al nombre del *entry point*. |
| `display_name` | atributo de clase (opcional) | Texto de la cabecera del grupo en el selector. |
| `discover(**options)` | método de clase | Lista de `DeviceInfo` que el driver ve ahora. Ignora opciones desconocidas (la UI pasa `backend=`). Pon `driver=<name>` en cada `DeviceInfo`. |
| `probe(device_info)` | método de clase | `True` si puedes manejar ese dispositivo. Rápido, sin abrirlo. Rechaza dispositivos de otros drivers. |
| `for_device(device_info, **options)` | método de clase | Crea la instancia **sin abrir**. Aquí se aplica el perfil del dispositivo, si lo hay. |
| `open()` | instancia | Abre. Lanza `CameraNotFound`, `CameraBusy` o `FormatNotSupported`. |
| `close()` | instancia | Libera. **Idempotente**. |
| `read_frame()` | instancia | `numpy.ndarray` `uint8` BGR (alto × ancho × 3), **nuevo en cada llamada**. Bloquea como mucho unos segundos. Lanza `CameraNotOpenError`, `CameraDisconnected` o `EndOfStreamError` (archivos). |
| `capabilities()` | instancia | `Capabilities` coherentes, antes y después de abrir. Tras abrir, la resolución activa debe figurar en `resoluciones_soportadas`. |
| `metadata()` | instancia | `dict` serializable a JSON con las claves de `METADATA_KEYS` (usa `base_metadata()`). |
| `is_connected()` | instancia | `True` si está abierto y entregando frames. |

### `Capabilities`

| Campo | Tipo | Notas |
|---|---|---|
| `resoluciones_soportadas` | `tuple[(ancho, alto), ...]` | Las que el driver conoce. |
| `fps_por_resolucion` | `{(ancho, alto): (fps, ...)}` | Solo resoluciones de la lista; FPS > 0. |
| `formatos_pixel` | `tuple[str, ...]` | P. ej. `"MJPG"`, `"YUY2"`. |
| `tiene_control_zoom` / `_brillo` / `_balance_blancos` | `bool \| None` | `None` = desconocido. No afirmes lo que no sabes. |
| `es_uvc` | `bool` | |
| `notas` | `str` | Limitaciones, origen de los datos. |

### Errores de dominio (`colpo.drivers.errors`)

| Error | Cuándo |
|---|---|
| `CameraNotFound` | El dispositivo no existe (desenchufado, índice o archivo inexistente). |
| `CameraBusy` | Existe, pero no se puede usar (otra aplicación, permisos, no entrega frames al abrir). |
| `CameraDisconnected` | Dejó de responder durante el uso. |
| `FormatNotSupported` | La resolución, FPS o formato pedido no está disponible. |

Heredan de los errores del núcleo, así que la UI los muestra traducidos sin cambios.

### Reglas que verifica la suite

- El módulo del driver **no importa** PySide6/Qt, librerías de red, `shutil` ni `tempfile`.
- **No escribe archivos** (`open()`, `cv2.imwrite`, `VideoWriter`, `os.replace`, `Path.write_*`, `mkdir`, `unlink`…).
- `metadata()` no contiene números de serie, rutas del sistema ni datos de personas.

## 3. Esqueleto comentado

```python
"""Driver para <fabricante> <modelo>. Vía: <UVC | capturadora | SDK publicado>."""

from __future__ import annotations

from typing import Any, ClassVar

import numpy as np

from colpo.devices import DeviceInfo
from colpo.drivers.base import SOURCE_CAMERA, Capabilities, base_metadata
from colpo.drivers.errors import CameraBusy, CameraDisconnected, CameraNotFound
from colpo.errors import CameraNotOpenError


class MiEquipoDriver:
    name: ClassVar[str] = "mi_equipo"  # = nombre del entry point
    display_name: ClassVar[str] = "Mi equipo (SDK)"

    def __init__(self, device: DeviceInfo) -> None:  # no abre nada
        self._device = device
        self._handle = None

    @classmethod
    def discover(cls, **options: Any) -> list[DeviceInfo]:
        # Pregunta al SO o al SDK *publicado* por el fabricante. Sin red.
        return [DeviceInfo(index=0, name="Mi equipo", backend="sdk", driver=cls.name)]

    @classmethod
    def probe(cls, device_info: DeviceInfo) -> bool:
        return device_info.driver == cls.name

    @classmethod
    def for_device(cls, device_info: DeviceInfo, **options: Any) -> MiEquipoDriver:
        return cls(device_info)

    def open(self) -> None:
        if self._handle is not None:
            return
        # self._handle = sdk.open(...)   ← API documentada; traduce sus errores:
        #   "no existe" -> CameraNotFound, "en uso" -> CameraBusy
        raise CameraNotFound("Implementa la apertura")

    def close(self) -> None:
        self._handle = None  # idempotente

    def read_frame(self) -> np.ndarray:
        if self._handle is None:
            raise CameraNotOpenError("No está abierto.")
        # frame = sdk.read(self._handle)  → si falla repetidamente: raise CameraDisconnected
        raise CameraDisconnected("Implementa la lectura")

    def capabilities(self) -> Capabilities:
        return Capabilities(
            resoluciones_soportadas=((1280, 720),),
            fps_por_resolucion={(1280, 720): (30.0,)},
            formatos_pixel=("MJPG",),
            es_uvc=False,
            notas="Datos del manual público del equipo.",
        )

    def metadata(self) -> dict[str, Any]:
        return base_metadata(
            self.name,
            self._device,
            es_uvc=False,
            fuente=SOURCE_CAMERA,
            backend="sdk",
            fps_nominal=30.0,
            formato_pixel="MJPG",
            resolucion=(1280, 720) if self._handle else None,
        )

    def is_connected(self) -> bool:
        return self._handle is not None
```

Para probar sin hardware, añade un caso en `CASES` de `tests/test_driver_contract.py` con
una versión simulada (como hacen `uvc-simulada` y `mock`).

## 4. Perfiles de dispositivo (`src/colpo/drivers/profiles/*.json`)

Un archivo JSON por modelo. Se distribuyen dentro del paquete y se leen sin red. Ejemplo
real (Goldcare GC 3000E, VID:PID aún pendiente):

```json
{
  "esquema": "colpo-perfil/1",
  "id": "goldcare-gc3000e",
  "nombre": "GOLDCARE GC 3000E",
  "fabricante": "GOLDCARE",
  "modelo": "GC 3000E",
  "vendor_id": null,
  "product_id": null,
  "estado": "confirmado_uvc",
  "driver_recomendado": "uvc",
  "api_recomendada": "auto",
  "resoluciones_preferidas": [
    { "ancho": 1280, "alto": 720, "fps": 30, "formato": "MJPG", "verificada": false }
  ],
  "controles": { "zoom": null, "brillo": null, "balance_blancos": null },
  "notas": ["…"],
  "verificacion": { "fecha": "2026-10", "sistemas": ["Windows 10"], "metodo": "…" }
}
```

| Campo | Obligatorio | Formato |
|---|---|---|
| `esquema` | sí | `"colpo-perfil/1"` |
| `id` | sí | minúsculas, dígitos y guiones; único |
| `nombre`, `fabricante`, `modelo` | sí | texto (marcas solo como uso nominativo) |
| `vendor_id`, `product_id` | sí | `"0x1234"`/`"1234"` (hex, 4 dígitos) o `null` (ambos o ninguno). Con `null` el perfil no se aplica automáticamente |
| `estado` | sí | `confirmado_uvc`, `no_uvc` o `desconocido` |
| `driver_recomendado` | sí | nombre de un driver (`uvc`…) |
| `api_recomendada` | sí | `auto`, `dshow`, `msmf`, `v4l2`, `avfoundation` |
| `resoluciones_preferidas` | sí | lista de `{ancho, alto, fps, formato (4 caracteres), verificada}`. **Solo las `verificada: true` se solicitan a la cámara** |
| `controles` | sí | `zoom`, `brillo`, `balance_blancos`: `true`/`false`/`null` |
| `notas` | sí | lista de textos |
| `verificacion` | no | `fecha`, `sistemas`, `metodo` |

Cualquier otro campo (p. ej. un número de serie) se rechaza. Nombre de archivo recomendado:
`<fabricante>_<modelo>.json`. Una prueba valida todos los perfiles incluidos.

## 5. Checklist de aceptación de un driver

- [ ] Un archivo en `src/colpo/drivers/` (o un paquete aparte) y una línea en el *entry point*.
- [ ] `colpo drivers` lo lista y detecta el equipo.
- [ ] `pytest tests/test_driver_contract.py -k <nombre>` en verde (forma y reglas).
- [ ] Con el equipo: `COLPO_CONTRACT_HARDWARE=1 pytest tests/test_driver_contract.py -k <nombre>` en verde.
- [ ] Prueba manual en `colpo-ui`: abrir, foto, video, desconexión con aviso.
- [ ] Perfil JSON (si aplica) y fila en [HARDWARE.md](HARDWARE.md).
- [ ] Sin imágenes de pacientes en el PR, ni en los ejemplos ni en las pruebas.
- [ ] Declaración en el PR: implementado solo con documentación pública/estándares; sin código, firmware ni datos del fabricante.

## 6. Cómo funciona por dentro (para revisores)

- El registro carga *entry points* **solo de paquetes instalados** (`importlib.metadata`):
  no hay descarga de plugins por red ni importación de rutas arbitrarias. Un plugin roto se
  ignora y queda en `DriverRegistry.load_errors` (`colpo drivers` lo muestra).
- Instalar un paquete de driver es **ejecutar su código**: instala solo drivers de fuentes de
  confianza y revisados (ver RISKS.md T18).
- `CaptureCamera` valida cada frame (tipo, forma) y convierte excepciones inesperadas de un
  driver en `FrameReadError`, para que un driver con errores no tumbe la aplicación.

## 7. Qué NO hacer

Se rechazarán (y retirarán) contribuciones que:

- **Emulen, clonen, parcheen o eludan dongles** o cualquier mecanismo de licencia.
- Incluyan **binarios, DLL, firmware o recursos del fabricante** (*blobs* propietarios), o
  instrucciones para obtenerlos de forma no autorizada.
- Se basen en **ingeniería inversa binaria** (desensamblar/decompilar software o firmware del
  fabricante) o en capturas de tráfico de su software propietario.
- Usen un **SDK con licencia incompatible** con Apache-2.0 o que exija aceptar condiciones que
  impidan su distribución abierta (en ese caso, va como paquete aparte del usuario, no aquí).
- Abran conexiones de red, envíen telemetría o escriban archivos desde el driver.
- Incluyan imágenes o videos de pacientes.

Vías legítimas para equipos que no son UVC: [NON_UVC.md](NON_UVC.md).
