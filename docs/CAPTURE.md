# Captura UVC (F1)

> Prototipo educativo. **No es un producto médico validado.** En F1–F3 solo se capturan
> maniquíes, objetivos de prueba y material educativo existente; nunca pacientes.

Este documento describe qué hace la captura de F1 (`src/colpo/capture.py` y la CLI `colpo`),
sus limitaciones conocidas y qué se espera del **Goldcare GC 3000E** del sitio piloto.

## 1. Vía principal: UVC + OpenCV

```text
Colposcopio (UVC) ──USB──► controlador UVC genérico del SO ──► OpenCV VideoCapture ──► UVCCamera ──► PNG / MP4
                           (usbvideo.sys en Windows)            (DirectShow por defecto)
```

- No se usa el software del fabricante ni el dongle. Ver [RISKS.md §5](RISKS.md#5-por-qué-no-se-emula-el-dongle).
- La capturadora externa y el SDK del fabricante son **vías de contingencia**
  ([ARCHITECTURE.md §6.6](ARCHITECTURE.md#66-dispositivos-no-uvc)), no el camino principal.

## 2. Instalación (Windows 10/11 x64)

Requisitos: Python 3.11 o superior **de 64 bits** (python.org), con la opción "Add python.exe to PATH".

```powershell
cd Open-Colcoscope-
py -3 -m venv .venv
.venv\Scripts\activate
python -m pip install --upgrade pip
pip install -e .
colpo --version
```

Instalación **sin Internet** en el equipo del sitio: en un equipo con conexión y el mismo SO,
`pip download -d wheels .` y copia la carpeta `wheels` junto con el repositorio; en el equipo
del sitio, `pip install --no-index --find-links wheels -e .`.

## 3. Comandos

| Comando | Qué hace |
|---|---|
| `colpo list` | Lista cámaras: índice, `VID:PID` y nombre. |
| `colpo list --probe` | Además abre cada cámara y mide resolución y FPS **reales**. |
| `colpo list --json` | Igual, en JSON (útil para reportar en HARDWARE.md). |
| `colpo preview --index N` | Ventana de vista previa. `S`/`Espacio`: foto PNG; `R`: inicia/detiene video MP4; `Q`/`Esc`: salir. Guarda en `.\capturas` (cambiar con `--out-dir`). |
| `colpo record --index N --out test.mp4 --duration 5` | Graba 5 s de video. |
| `colpo snapshot --index N --out foto.png` | Guarda una foto PNG. |

Opciones comunes a `preview`, `record` y `snapshot`:

| Opción | Uso |
|---|---|
| `--source VIDEO` | Usa un archivo de video en lugar de una cámara (demostración y pruebas). Excluyente con `--index`. |
| `--backend {auto,dshow,msmf,any}` | API de Windows. `auto` = DirectShow. Probar `msmf` si DirectShow falla. |
| `--width W --height H` | Resolución solicitada (la cámara puede ignorarla; se informa la real). |
| `--fourcc MJPG` | Formato solicitado. `MJPG` permite 1080p a 30 FPS por USB 2.0; `YUY2` es sin compresión pero lento. |
| `--fps F` | FPS solicitados a la cámara. |
| `-v` | Mensajes de diagnóstico (incluidos los avisos internos de OpenCV y la ruta del dispositivo). |

Códigos de salida: `0` correcto · `1` error de captura (mensaje en español en stderr) ·
`2` uso incorrecto · `130` interrumpido con Ctrl+C (el video grabado hasta ese momento se conserva).

Demostración sin colposcopio:

```powershell
python examples\synthetic_video.py demo.avi --frames 300
colpo preview --source demo.avi
colpo record --source demo.avi --out demo.mp4 --duration 5
```

## 4. Comportamiento esperado de `UVCCamera`

| Aspecto | Comportamiento |
|---|---|
| Apertura | Abre por índice con el backend elegido; aplica `fourcc` → resolución → FPS (en DirectShow el orden importa); descarta 5 frames de calentamiento (exposición y balance de blancos). |
| Resolución real | Se mide sobre el primer frame recibido, no se confía en lo que dice el driver. Si difiere de la pedida, se avisa. |
| FPS reales | `measure_fps()` (y `colpo record`) cronometra frames reales. El FPS que informa el driver se muestra aparte, porque a menudo no coincide. |
| `read_frame()` | Devuelve un `Frame` BGR de solo lectura, con marca de tiempo monotónica y número de secuencia. |
| Foto (`snapshot`) | PNG sin pérdida, sin EXIF, escrito de forma **atómica** (temporal → `fsync` → renombrar). No sobrescribe salvo `overwrite=True`. Funciona con rutas con tildes y ñ. |
| Video | Hilo escritor con cola acotada (~1 s). El archivo se escribe como `.<nombre>.recording.mp4` y solo se renombra al nombre final al cerrarse bien. |
| Ritmo del video | Constante, según las marcas de tiempo reales: si la cámara entrega menos FPS de los nominales se repiten frames, y si entrega más se omiten. Así la duración del video coincide con el tiempo real. |
| FPS del video | Los medidos, redondeados a la tasa estándar más cercana (p. ej. 29,7 → 30). |
| Pérdidas | Con una cámara, si el disco o la CPU no dan abasto, los frames perdidos se cuentan y se informan (`frames_dropped`); nunca se ocultan. Con `--source` (archivo) no hay tiempo real: la lectura espera al escritor y no se pierde ningún frame. |
| Desconexión | Tras 10 lecturas fallidas seguidas se lanza `DeviceDisconnectedError`; `colpo record` cierra el video y conserva lo grabado. |
| Audio | No se graba audio (OpenCV no lo captura; además es una decisión de privacidad). |

Formatos de salida:

| Extensión | Códec | Notas |
|---|---|---|
| `.mp4` | Windows: **H.264** (codificador de Media Foundation del propio Windows); si no está disponible, MPEG-4 Part 2 (`mp4v`). Otros SO: `mp4v`. | El códec usado se informa en `RecordingStats.codec` y en la UI. Con pérdida; recodifica (usa CPU). |
| `.avi` | MJPEG | Más calidad por frame y menos CPU; archivos más grandes. Recomendado si hay frames perdidos. |
| `.mkv` | MJPEG | Igual que `.avi`, en contenedor Matroska. |
| `.png` | — | Única opción para fotos (sin pérdida). |

Las ruedas de OpenCV no incluyen un codificador H.264 propio (licencias y patentes); en
Windows se usa el que trae el sistema operativo. En ediciones "N" sin *Media Feature Pack*
no existe, y se graba con `mp4v`.

Errores (todos heredan de `ColpoError`):

| Excepción | Causa típica | Qué hacer |
|---|---|---|
| `DeviceOpenError` | Índice inexistente, cámara en uso por otra app, permiso de cámara denegado, cámara que no entrega imágenes. | Cerrar la app Cámara u otras; revisar *Configuración > Privacidad y seguridad > Cámara > Permitir que las aplicaciones de escritorio accedan a la cámara*; `colpo list`; probar `--backend msmf`. |
| `BackendUnavailableError` | Backend no válido en este SO. | Usar `auto`. |
| `DeviceDisconnectedError` | Cable USB desconectado o la cámara dejó de responder. | Reconectar; abrir de nuevo. |
| `EndOfStreamError` | Fin del archivo usado con `--source`. | Normal en demostraciones. |
| `RecordingError` | Archivo ya existe, ruta no válida, fallo del códec o del disco. | Otro nombre, `--overwrite`, `.avi`, liberar espacio. |
| `SnapshotError` / `UnsupportedFormatError` | Archivo ya existe / extensión no soportada. | Otro nombre / usar `.png`. |
| `CameraNotOpenError` | Uso de la API sin `open()`. | Error de programación. |

## 5. Limitaciones conocidas (UVC + OpenCV)

1. **OpenCV no puede listar los formatos que soporta la cámara.** Se puede *pedir* un formato,
   pero el driver puede ignorarlo; por eso se informa siempre lo real. Para ver la lista
   completa de formatos en Windows hace falta otra herramienta (p. ej. el diálogo de
   propiedades de DirectShow); queda para F3 (`diagnose`).
2. **Una cámara UVC solo la usa una aplicación a la vez** en Windows. Cierra la app Cámara,
   videollamadas y el software del fabricante antes de usar `colpo`.
3. **Los índices dependen del backend y del orden de conexión.** En un portátil, el índice 0
   suele ser la webcam integrada y el colposcopio puede ser el 1. Identifícalo por nombre o
   `VID:PID` con `colpo list` (desconecta y reconecta el colposcopio para ver qué fila cambia).
4. **DirectShow y Media Foundation se comportan distinto** (resoluciones disponibles, tiempo
   de apertura, FPS). Si una resolución no funciona con uno, prueba con el otro.
5. **Ancho de banda USB 2.0:** 1080p sin compresión (YUY2) no llega a 30 FPS; usa `--fourcc MJPG`.
6. **Exposición automática:** con poca luz, muchas cámaras UVC bajan los FPS para alargar la
   exposición. El video mantiene la duración real (frames repetidos), pero se verá menos fluido.
7. **Balance de blancos y exposición** no se controlan en F1 (llega con los perfiles de F3).
   El color puede variar entre sesiones: no usar para comparaciones de color.
8. **Detección de desconexión:** según el driver, `read()` puede tardar varios segundos en fallar.
9. **Rutas con tildes o ñ:** las fotos funcionan; `VideoWriter` de OpenCV puede fallar en
   Windows con rutas no ASCII. Si ocurre, graba en una carpeta sin tildes.
10. **Botón físico de la cámara y pedal:** no se soportan en F1. En F2 se dispara con teclado o
    ratón; un pedal que emule teclado funcionará sin cambios.
11. **Vista previa en el hilo de la UI:** suficiente para depurar; en F2 la lectura pasa a un
    hilo propio. La clase `UVCCamera` no es *thread-safe*.
12. **Metadatos:** F1.a todavía no escribe el *sidecar* JSON (hora exacta, etapa IFCPC,
    VID:PID). Las fotos y videos de `preview` llevan la hora exacta en el nombre
    (`foto_AAAAMMDD-HHMMSS_secuencia.png`). El sidecar llega en F1.b.

## 6. Goldcare GC 3000E: comportamiento esperado y protocolo de prueba

**Confirmado (F0):** el GC 3000E se ve como cámara UVC en la app "Cámara" de Windows 10, sin el
software del fabricante y sin el dongle conectado. Por tanto, el controlador `usbvideo.sys`
de Windows lo maneja y OpenCV debería abrirlo como cualquier webcam.

**Aún no verificado con `colpo`** (no lo invento: lo medirá la prueba siguiente): nombre que
reporta el driver, VID:PID, resolución y formato por defecto, resoluciones disponibles, FPS
reales y diferencias entre DirectShow y Media Foundation.

### Protocolo de prueba manual (F1.10)

Usa un objetivo **no humano** (carta de color, página impresa o maniquí) y el software del
fabricante cerrado y el dongle desconectado.

1. Conecta el GC 3000E y cierra la app Cámara.
2. `colpo list` → anota índice, nombre y `VID:PID` del colposcopio.
3. `colpo list --probe` → anota resolución, formato y FPS (informados y medidos).
4. `colpo preview --index N` → comprueba imagen, foco y color; pulsa `S` (foto) y `R` dos veces (video corto).
5. `colpo record --index N --out test.mp4 --duration 5` → abre `test.mp4` en VLC; debe durar ~5 s.
6. Repite 3–5 con `--backend msmf` y, si la cámara lo admite, con `--fourcc MJPG --width 1920 --height 1080`.
7. Desconecta el USB durante `colpo record --index N --out corte.mp4 --duration 30`: el comando
   debe terminar con un error claro y `corte.mp4` debe reproducirse hasta el corte.
8. Registra los resultados en [HARDWARE.md](HARDWARE.md) (sin números de serie ni rutas completas).

## 7. Uso desde Python

```python
from colpo import UVCCamera, DeviceDisconnectedError

for dev in UVCCamera.list_devices():
    print(dev.index, dev.vid_pid, dev.name)

with UVCCamera(index=1, fourcc="MJPG", width=1920, height=1080) as cam:
    print(cam.stream_info, cam.measure_fps())
    cam.snapshot("capturas/foto.png")
    cam.start_recording("capturas/video.mp4")
    try:
        for _ in range(150):
            cam.read_frame()
    except DeviceDisconnectedError:
        pass
    stats = cam.stop_recording()
    print(stats.duration_s, stats.frames_dropped)
```
