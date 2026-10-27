# Matriz de compatibilidad de hardware

> Prototipo educativo. **No es un producto médico validado.** Que un equipo figure aquí
> significa únicamente que alguien pudo capturar video con él mediante interfaces
> estándar; no implica aval del fabricante ni idoneidad clínica.
>
> Las marcas mencionadas pertenecen a sus titulares y se citan solo para identificar el
> equipo (uso nominativo).

## Reglas para contribuir una fila

- **Nunca** incluyas números de serie, nombres de la institución ni imágenes de pacientes.
- Prueba con objetivos no humanos (carta de color, papel impreso, maniquí).
- Prueba **sin** el software del fabricante instalado y **sin** el dongle conectado.
- Si el dispositivo no es UVC, regístralo igualmente (estado ❌) y describe la salida de
  video disponible: es información valiosa.
- El dongle de licencia **no** es un dispositivo de captura: anótalo solo en la columna de
  notas como "dongle presente (no usado)"; no publiques sus identificadores ni análisis.

## Leyenda

**Compatibilidad UVC** (columna *UVC*, igual que el campo `estado` de los perfiles JSON):

| Estado | Significado |
|---|---|
| `confirmado_uvc` | Verificado: aparece como cámara UVC sin software del fabricante ni dongle. |
| `no_uvc` | Verificado que **no** es UVC. Ver vías alternativas en [NON_UVC.md](NON_UVC.md). |
| `desconocido` | Sin verificar todavía. |

**Funcionamiento con Open Colposcope** (columna *Estado*):

| Estado | Significado |
|---|---|
| ✅ | Funciona: vista previa, foto y video con el driver indicado. |
| 🟡 | Parcial o pendiente de prueba completa (ver notas). |
| ❌ | No funciona con ningún driver disponible. |
| ❔ | Sin probar. |

| Clase USB (abreviaturas) | Significado |
|---|---|
| `UVC` | USB Video Class: interfaz clase `0x0E` (subclases `0x01` control, `0x02` streaming). |
| `UVC-IAD` | Dispositivo compuesto (`0xEF/0x02/0x01`) con interfaces UVC (frecuente). |
| `UAC` | Además expone audio (USB Audio Class `0x01`); el software lo ignora por defecto. |
| `HID` | Expone botones/pedal como dispositivo de entrada (`0x03`). |
| `VENDOR` | Clase específica del fabricante (`0xFF`): **no soportado** por la vía estándar. |

## Matriz de colposcopios

| Marca | Modelo | VID:PID | UVC | Clase USB | Resolución(es) / formato / FPS verificados | SO probados | Driver / API | Perfil | Estado | Notas | Reportado |
|---|---|---|---|---|---|---|---|---|---|---|---|
| GOLDCARE | GC 3000E | **Pendiente** (`colpo list`) | `confirmado_uvc` | `UVC` | Pendiente (`colpo list --probe`); objetivo sin verificar 1280×720 MJPG @30 | Windows 10 | `uvc` / `auto` (DirectShow) | [`goldcare_gc3000e.json`](../src/colpo/drivers/profiles/goldcare_gc3000e.json) | 🟡 | Se ve en la app Cámara de Windows 10 **sin** software del fabricante y **sin** dongle. Pendiente: VID:PID, modos reales, prueba manual de F2/F3 (USER_GUIDE.md §10). El perfil no se aplica hasta completar el VID:PID. Dongle presente (no usado). Sitio piloto único. | 2026-10 |
| *Plantilla* | *Modelo* | `VVVV:PPPP` | `confirmado_uvc` / `no_uvc` / `desconocido` | `UVC` / `UVC-IAD` / `VENDOR` | `1920×1080 MJPG @30; …` | `Windows 11` | `uvc` / `dshow` | `fabricante_modelo.json` | ❔ | Controles, OSD, problemas conocidos. Dongle presente (no usado). | AAAA-MM |

## Capturadoras de video (para colposcopios con salida analógica o HDMI)

Vía 1 de [NON_UVC.md](NON_UVC.md). Una capturadora UVC funciona con el driver `uvc` sin código nuevo.

| Marca | Modelo | VID:PID | Entrada (HDMI / S-Video / compuesto / SDI) | UVC | Resolución(es) / formato / FPS verificados | SO probados | Perfil | Estado | Notas | Reportado |
|---|---|---|---|---|---|---|---|---|---|---|
| *Plantilla* | *Modelo* | `VVVV:PPPP` | `HDMI` | `confirmado_uvc` | `1920×1080 MJPG @30` | `Windows 11` | — | ❔ | Equipo conectado, OSD visible, latencia. | AAAA-MM |

## Cámaras en puerto óptico

Vía 2 de [NON_UVC.md](NON_UVC.md).

| Cámara | VID:PID | Adaptador / montura | UVC | Resolución(es) verificadas | Colposcopio | Estado | Notas | Reportado |
|---|---|---|---|---|---|---|---|---|
| *Plantilla* | `VVVV:PPPP` | `C-mount 0.5x` | `confirmado_uvc` | `1920×1080 MJPG @30` | *Modelo* | ❔ | Foco, parfocalidad. | AAAA-MM |

## Cómo obtener los datos

### VID:PID y clase USB

**Forma recomendada (Windows 10/11):** con el colposcopio conectado, ejecutar
`colpo list` (columna `VID:PID`), `colpo list --probe` (resolución y FPS reales) y
`colpo drivers` (qué driver lo maneja y sus capacidades). En `colpo-ui`, el VID:PID y las
capacidades aparecen junto al selector de dispositivo.

Alternativa en PowerShell:

```powershell
Get-PnpDevice -Class Camera,Image -PresentOnly | Select-Object FriendlyName, InstanceId
```

En `InstanceId` (p. ej. `USB\VID_XXXX&PID_YYYY&MI_00\...`) copia **solo** `VID_XXXX` y
`PID_YYYY`. **No** copies el resto de la cadena: puede contener un número de serie o un
identificador único del equipo.

| SO | Comando / herramienta |
|---|---|
| Linux | `lsusb` (VID:PID) y `lsusb -v -d VID:PID` (clases de interfaz). `v4l2-ctl --list-devices` y `v4l2-ctl -d /dev/videoN --list-formats-ext` (formatos). |
| Windows | Administrador de dispositivos → Propiedades → Detalles → *Id. de hardware* (`USB\VID_xxxx&PID_xxxx`). Controlador `usbvideo.sys` ⇒ UVC. *USB Device Tree Viewer* para descriptores. |
| macOS | `system_profiler SPUSBDataType` (VID/PID); `ioreg -p IOUSB -l` para descriptores. |

A partir de F1/F3 el comando `diagnose` de la aplicación generará un reporte anonimizado
con estos datos.

### Comprobación rápida "¿es UVC?"

1. Desinstala o no instales el software del fabricante; desconecta el dongle.
2. Conecta el colposcopio.
3. Abre una app genérica: Cámara (Windows), VLC → *Dispositivo de captura*, `guvcview`/`qv4l2`
   (Linux), QuickTime → *Nueva grabación de película* (macOS).
4. Si ves imagen: es UVC (o compatible) → ✅/🟡. Si no aparece como cámara: revisa la clase
   USB; si es `VENDOR` (`0xFF`) → ❌, documenta salidas de video alternativas.

## Plantilla de reporte detallado (opcional, una por modelo)

```markdown
### <Marca> <Modelo>

- VID:PID: `xxxx:xxxx`
- Año aproximado / versión de hardware:
- Conexión: USB 2.0 / USB 3.x / capturadora (indicar)
- Clase(s) USB de interfaces: 
- Formatos anunciados (salida de `--list-formats-ext` o equivalente, SIN números de serie):
- Formatos que realmente funcionan:
- Controles disponibles (brillo, exposición, balance de blancos, enfoque, zoom…):
- ¿Botón de captura físico? ¿Pedal? ¿Cómo se presenta (HID/UVC)?
- ¿Texto superpuesto (OSD) en la imagen? ¿Dónde?
- ¿Audio (UAC)? 
- SO y versiones probados:
- Backend usado y versión del software:
- Problemas conocidos / soluciones:
- Salidas de video alternativas del equipo (HDMI, S-Video, compuesto, puerto óptico):
```
