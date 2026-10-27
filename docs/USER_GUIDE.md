# Guía de uso — Open Colposcope (v0.3.0)

> **Prototipo educativo — no validado para diagnóstico clínico.**
> En esta etapa (F1–F3) se usa solo con maniquíes, objetivos de prueba y material educativo
> existente. Nunca con pacientes. Ver [PRIVACY.md](PRIVACY.md).

## 1. Requisitos

- Windows 10 u 11 de 64 bits.
- Python 3.11 o superior **de 64 bits** (python.org). Durante la instalación, marca
  "Add python.exe to PATH".
- Un colposcopio USB que funcione como cámara UVC (p. ej. Goldcare GC 3000E). Comprobación
  rápida: debe verse en la app **Cámara** de Windows sin el software del fabricante y sin el
  dongle conectado.

## 2. Instalación

En PowerShell, dentro de la carpeta del proyecto:

```powershell
py -3 -m venv .venv
.venv\Scripts\activate
python -m pip install --upgrade pip
pip install -e .
```

**Equipo sin Internet:** en otro equipo Windows con conexión, ejecuta `pip download -d wheels .`
dentro del proyecto y copia la carpeta del proyecto (con `wheels`) en una memoria USB. En el
equipo del sitio: `pip install --no-index --find-links wheels -e .`

El instalador para Windows (PyInstaller) llegará en F4.

## 3. Abrir la aplicación

| Forma | Comando | Cuándo usarla |
|---|---|---|
| Normal | `colpo-ui` | Uso diario. No abre ventana de consola. |
| Con consola | `python -m colpo.ui` | Si algo falla al arrancar: los mensajes aparecen en la consola. |
| Acceso directo | Crea un acceso directo a `…\.venv\Scripts\colpo-ui.exe` | Para abrirla con doble clic. |

Opciones:

| Opción | Efecto |
|---|---|
| `--lang en` | Abre en inglés (por defecto, español o el último idioma usado). |
| `--data-dir D:\Capturas` | Guarda en otra carpeta (por defecto `%USERPROFILE%\OpenColposcope`). |
| `--source demo.avi` | Añade un video como "cámara" de demostración (para practicar sin colposcopio). |
| `--demo` / `--demo 3` | Añade cámaras simuladas (2 por defecto) para practicar la vista dual sin hardware. |

Para crear un video de demostración: `python examples\synthetic_video.py demo.avi --frames 1800`.

## 4. La pantalla

```text
┌──────────────────────────────────────────────────────────────────────────────────────┐
│          Prototipo educativo — no validado para diagnóstico clínico   (siempre)        │
├──────────────────────────────────────────────────────────────────────────────────────┤
│ (mensajes de error, con ✕ para cerrarlos; solo aparecen si hay un problema)           │
├──────────────────────────────────────────────────────────────────────────────────────┤
│ Dispositivo: [UVC (OpenCV) ▸ 0 — GOLDCARE … · VID:PID ▼] API:[auto] [Actualizar]        │
│              [Abrir] [Abrir en pestaña nueva]        Idioma:[Español ▼] [Preferencias…] │
│ [UVC (OpenCV)] VID:PID … · UVC · Resoluciones: … · Formatos: … · Zoom: ? · Brillo: ?   │
├──────────────────────────────────────────────────────┬───────────────────────────────┤
│ [ 0 — GOLDCARE … ✕ ][ 1 — Webcam integrada ✕ ]        │ Estudio · ID: E-XXXXXXXX      │
│                                                      │ [Nuevo estudio]               │
│           VISTA PREVIA DE LA PESTAÑA ACTIVA          │ Etapa (IFCPC): [Basal ▼]      │
│                                                      │ Notas (opcional): [         ] │
│                                                      │ Captura en: 0 — GOLDCARE …    │
│                                                      │ [ Foto (F8) ]                 │
│                                                      │ [ Iniciar grabación (F9) ]    │
│ 1280×720 · 30.0 FPS              ● GRABANDO 00:10    │ Última captura: …             │
└──────────────────────────────────────────────────────┴───────────────────────────────┘
  (barra inferior: «Marca de agua: activada» solo si la activaste en Preferencias)
```

## 5. Flujo de captura paso a paso

1. **Prepara el equipo:** conecta el colposcopio por USB y cierra la app Cámara, el software
   del fabricante y cualquier videollamada (una cámara solo la puede usar una aplicación a la vez).
2. **Abre la app** (`colpo-ui`).
3. **Elige el dispositivo** en la lista *Dispositivo*. Está agrupada por driver (p. ej.
   "UVC (OpenCV)"); cada entrada muestra `índice — nombre · VID:PID`. Debajo se ven sus
   **capacidades** (UVC sí/no, resoluciones, formatos, controles; "?" = desconocido). En un
   portátil, el índice 0 suele ser la webcam integrada. Si no aparece, pulsa **Actualizar**.
4. Pulsa **Abrir**. Se crea una pestaña con la imagen y, debajo, la resolución y los FPS reales.
5. **Segundo dispositivo (opcional):** elige otro (p. ej. la webcam o una capturadora) y pulsa
   **Abrir en pestaña nueva**. Ambos siguen capturando a la vez; los botones Foto y Grabar
   actúan sobre la **pestaña activa** (lo indica "Captura en: …").
6. **Cambiar de dispositivo sin reiniciar:** con una pestaña activa, elige otro dispositivo y
   pulsa **Abrir**: la pestaña cierra el anterior (guardando un video en curso) y abre el nuevo.
7. **Estudio:** cada vez que abres la app se crea un *ID de estudio* aleatorio. Pulsa
   **Nuevo estudio** cuando empieces con otro maniquí o caso de práctica.
8. **Elige la etapa** (Basal, Solución salina, Ácido acético, Lugol, Filtro verde).
9. **Notas (opcional):** solo observaciones educativas. Si escribes algo que parece un dato
   personal (DNI, teléfono, fecha, correo, palabras como "nombre"), aparece un aviso en rojo y
   **esas notas no se guardan**.
10. **Foto:** **Foto** o **F8**. **Video:** **Iniciar grabación** o **F9**; la pestaña muestra
    `● ` en su título y `● GRABANDO mm:ss`. Para terminar, **F9** otra vez.
11. **Marca de agua (opcional):** **Preferencias… → Añadir marca de agua «Uso educativo»**. Está
    desactivada por defecto, se guarda para tu usuario (no en el estudio) y se aplica a las
    fotos y videos que captures después.
12. **Idioma:** Español / English en cualquier momento, sin cortar la vista previa.
13. Cierra una pestaña con su **✕**; si cierras la app mientras grabas, el video se guarda.

## 6. Qué hace cada control

| Control | Función |
|---|---|
| Banner amarillo | Recordatorio permanente: prototipo educativo, no validado para diagnóstico. No se puede ocultar. |
| Dispositivo | Dispositivos de todos los drivers instalados, agrupados por driver, con índice, nombre y VID:PID. |
| Línea de capacidades | UVC sí/no, resoluciones y FPS conocidos, formatos de pixel y controles (zoom, brillo, balance de blancos). "?" = el driver no puede saberlo. |
| API | Interfaz de captura de Windows para el driver UVC: `auto` (DirectShow), `dshow` o `msmf`. Cambia a `msmf` solo si la cámara no funciona con `auto`. |
| Actualizar | Vuelve a preguntar a todos los drivers qué dispositivos hay. |
| Abrir | Abre el dispositivo en la pestaña activa (o en una nueva si no hay ninguna). Sirve para cambiar de dispositivo en caliente. |
| Abrir en pestaña nueva | Abre el dispositivo en otra pestaña (vista dual). Un mismo dispositivo no se puede abrir dos veces. |
| Pestañas | Una por dispositivo abierto; ✕ la cierra. `● ` en el título = grabando. |
| Idioma | Español / English, en caliente. Se recuerda para la próxima vez. |
| Preferencias… | Marca de agua "Uso educativo" para fotos y videos (desactivada por defecto). |
| ID de estudio / Nuevo estudio | Seudónimo aleatorio de la carpeta de capturas. No se puede cambiar mientras alguna pestaña graba. |
| Etapa (IFCPC) | Se guarda en el JSON de cada captura. En videos se guarda la etapa vigente al iniciar. |
| Notas | Texto educativo opcional (máx. 500 caracteres), sin datos de la paciente. |
| Foto (F8) | Guarda el último frame de la pestaña activa como PNG sin pérdida + JSON. |
| Iniciar / Detener grabación (F9) | Graba MP4 de la pestaña activa (H.264 si Windows lo ofrece; si no, `mp4v`) + JSON. |
| Última captura | Archivo guardado más reciente y, en video, el códec usado. |
| Abrir carpeta del estudio | Abre el Explorador de archivos en la carpeta del estudio actual. |

F8 y F9 funcionan aunque estés escribiendo en las notas. Un pedal USB que emule esas teclas
también sirve.

## 7. Dónde se guardan los archivos

Por defecto en `%USERPROFILE%\OpenColposcope` (por ejemplo `C:\Users\docente\OpenColposcope`).
Esta carpeta está **fuera de "Documentos"** a propósito: en muchos equipos "Documentos" se
sincroniza con OneDrive y las capturas no deben salir del equipo.

```text
OpenColposcope\
└── E-ZC858XX2\                            ← un estudio
    ├── foto_20261026-150405_uvc0.png       ← foto (PNG sin pérdida, sin EXIF)
    ├── foto_20261026-150405_uvc0.json      ← sus metadatos
    ├── video_20261026-150412_uvc0.mp4      ← video (sin audio)
    ├── video_20261026-150412_uvc0.json
    └── foto_20261026-150430_uvc1.png       ← del segundo dispositivo (pestaña 2)
```

Ejemplo real de JSON (generado por la app):

```json
{
  "id_estudio": "E-ZC858XX2",
  "timestamp": "2026-10-26T15:04:05-05:00",
  "etapa_ifcpc": "acido_acetico",
  "resolucion": { "ancho": 1280, "alto": 720 },
  "fps": 30.0,
  "tipo": "foto",
  "sha256": "a66e6c28bb41570e6be1573f613133186f001998714282039049b9fbebfcabd3",
  "notas": "Maniquí de práctica, ZT tipo 1"
}
```

El final del nombre (`_uvc0`, `_uvc1`, `_mock0`…) indica el dispositivo: driver + índice.
Si activaste la marca de agua, el SHA-256 corresponde al archivo con la marca. Los campos son siempre esos ocho; no existen campos de nombre, documento ni fecha de
nacimiento. Para comprobar que un archivo no se alteró:

```powershell
(Get-FileHash .\foto_20261026-150405_uvc0.png -Algorithm SHA256).Hash.ToLower()
```

El resultado debe coincidir con `sha256` del JSON.

## 8. Mensajes de error

| Mensaje | Qué hacer |
|---|---|
| No se encontró el dispositivo | Conéctalo y pulsa **Actualizar**. |
| El dispositivo no admite el formato solicitado | Revisa el perfil del dispositivo (resolución verificada) o usa otra API. |
| Ese dispositivo ya está abierto en otra pestaña | Usa la pestaña existente; una cámara no se puede abrir dos veces. |
| No se pudo abrir el dispositivo (ocupado) | Cierra la app Cámara, el software del fabricante y videollamadas. Revisa *Configuración > Privacidad y seguridad > Cámara > Permitir que las aplicaciones de escritorio accedan a la cámara*. Prueba otra API. |
| Se perdió la conexión con la cámara | Revisa el cable USB y pulsa **Conectar**. Lo grabado hasta ese momento ya está guardado. |
| Disco lleno o casi lleno | Libera espacio. Se necesitan al menos 50 MB para una foto y 500 MB para empezar un video; con menos de 200 MB, la grabación se detiene y se guarda sola. |
| La grabación falló | Vuelve a intentarlo. Si se repite, anota el "Detalle técnico" y repórtalo. |
| No se pudo guardar la foto / los metadatos | Revisa el espacio y los permisos de la carpeta de datos. |

Cada mensaje incluye un "Detalle técnico" (en español) útil para reportar problemas.

## 9. Cómo verificar que la app no usa la red

La app no tiene ningún código de red: no hay telemetría, ni actualizaciones automáticas, ni
cuentas. Puedes comprobarlo tú mismo:

1. **Modo avión:** activa el modo avión (o desconecta el cable de red) y usa la app con
   normalidad. Todo funciona igual.
2. **Monitor de recursos:** con la app abierta, ejecuta `resmon`, pestaña **Red** →
   *Procesos con actividad de red*. No debe aparecer `python.exe`, `pythonw.exe` ni `colpo-ui.exe`.
3. **PowerShell** (con la app abierta):

   ```powershell
   $ids = (Get-Process python, pythonw, colpo-ui -ErrorAction SilentlyContinue).Id
   Get-NetTCPConnection -ErrorAction SilentlyContinue | Where-Object OwningProcess -in $ids
   Get-NetUDPEndpoint  -ErrorAction SilentlyContinue | Where-Object OwningProcess -in $ids
   ```

   Ambos comandos no deben mostrar nada.
4. **Pruebas automáticas:** `pytest tests/test_no_network.py` verifica que ningún módulo
   importa librerías de red y que capturar funciona con los sockets bloqueados.

## 10. Prueba manual de aceptación (con el colposcopio real)

Con un maniquí u objetivo de prueba, el Goldcare conectado y la webcam del portátil (u otra
cámara UVC):

**F2 (5 minutos)**

- [ ] `colpo-ui` abre y el colposcopio aparece en la lista con su índice, nombre y VID:PID.
- [ ] Vista previa fluida; ~30 FPS a 1280×720 (o la resolución nativa).
- [ ] Foto en etapa *Basal*: aparecen el PNG y el JSON; el SHA-256 coincide (§7).
- [ ] Cambia a *Ácido acético*, graba ~10 s: el MP4 se reproduce en VLC y en el Reproductor
      multimedia de Windows; su JSON dice `acido_acetico`.
- [ ] Cambia el idioma a English y de vuelta sin que se corte la vista previa.
- [ ] Desconecta el USB durante una grabación: aparece el aviso y el video se conserva.

**F3 (multi-dispositivo y marca de agua)**

- [ ] La lista muestra el Goldcare y la webcam agrupados bajo "UVC (OpenCV)", con capacidades.
- [ ] Abre el Goldcare, luego la webcam en **pestaña nueva**: ambas imágenes siguen vivas al
      cambiar de pestaña.
- [ ] Intenta abrir otra vez el Goldcare en pestaña nueva: aparece "ya está abierto en otra
      pestaña". Luego, en una pestaña, elige otro dispositivo y pulsa **Abrir** (cambio en caliente).
- [ ] Foto y video **sin** marca de agua (por defecto): no hay texto añadido.
- [ ] Activa la marca de agua en **Preferencias**; foto y video nuevos llevan "Uso educativo -
      no diagnostico" abajo a la izquierda. Desactívala y verifica que desaparece.
- [ ] Ningún cierre inesperado.

Anota los resultados (y el VID:PID que muestra la lista) en [HARDWARE.md](HARDWARE.md) y en el
perfil `src/colpo/drivers/profiles/goldcare_gc3000e.json`.

## 11. Problemas frecuentes

| Problema | Solución |
|---|---|
| `colpo-ui` no se reconoce como comando | Activa el entorno: `.venv\Scripts\activate`. |
| La lista de cámaras está vacía | Conecta el USB, espera unos segundos y pulsa **Actualizar**. Prueba la API `msmf`. |
| La imagen va lenta | Cierra otros programas; usa un puerto USB del propio equipo (no un hub). |
| El video se ve pero dice `mp4v` en vez de H.264 | Tu Windows no ofrece el codificador H.264 (p. ej. ediciones "N" sin *Media Feature Pack*). El MP4 sigue siendo válido. |
