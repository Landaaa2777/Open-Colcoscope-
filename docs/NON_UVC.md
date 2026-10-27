# Equipos que no son UVC: vías legítimas

> Prototipo educativo — no validado para diagnóstico clínico. Este documento **no contiene
> código**: describe caminos para que un colaborador implemente soporte de forma legal.

La vía principal del proyecto es **UVC + OpenCV** (el Goldcare GC 3000E del sitio piloto lo es).
Si en otro sitio o con otro modelo el colposcopio **no** aparece como cámara en la app
"Cámara" de Windows sin el software del fabricante, hay tres alternativas, en este orden de
preferencia.

## Política clean-room (se aplica a las tres)

- **Nunca** se emula, clona, parchea ni elude el dongle o la licencia del software del
  fabricante. Razones: [RISKS.md §5](RISKS.md#5-por-qué-no-se-emula-el-dongle).
- **Nunca** entra al repositorio software, firmware, DLL, *drivers* ni recursos del fabricante.
- **Nunca** se hace ingeniería inversa binaria (desensamblar o decompilar) del software o del
  firmware, ni se analizan capturas de tráfico de su software propietario.
- Solo se usan **estándares públicos** (UVC, HDMI, SDI…) y **documentación o SDK publicados**
  por el fabricante con licencia compatible.
- Ante la duda, **pregunta antes de escribir código** (issue con la etiqueta `legal`).

## 1. Capturadora UVC conectada a la salida de video del equipo

Muchos colposcopios tienen una salida de video estándar (HDMI, SDI, S-Video o compuesto) para
un monitor. Una **capturadora USB que se presente como UVC** convierte esa señal en una
"cámara" más.

| | |
|---|---|
| Ventajas | No toca el equipo ni su software. Funciona con el driver `uvc` existente: **no hace falta código**. |
| Inconvenientes | Calidad limitada por la salida (p. ej. analógica); posible texto superpuesto (OSD) del equipo; latencia. |
| Hardware | Capturadora "UVC" / "driverless" (aparece en la app Cámara de Windows sin instalar nada). |

**Camino para un colaborador:**

1. Comprueba que la capturadora aparece en la app Cámara sin instalar software.
2. `colpo drivers` y `colpo list --probe` → anota VID:PID, resolución y FPS reales.
3. Añade un **perfil JSON** de la capturadora (DRIVER_GUIDE.md §4) y una fila en
   [HARDWARE.md](HARDWARE.md) (sección de capturadoras).
4. Si el equipo superpone texto con datos (fecha, nombre de la clínica), anótalo: en F4 se
   añadirán máscaras de privacidad por perfil.
5. Usa la vista dual de la app (pestaña nueva) para comparar con otra fuente si lo necesitas.

## 2. Cámara UVC en el puerto óptico del colposcopio

Muchos colposcopios ópticos tienen un divisor de haz o una montura (p. ej. C-mount) para
acoplar una cámara. Se puede montar una **cámara UVC genérica** (industrial o de microscopía).

| | |
|---|---|
| Ventajas | Imagen digital directa con buena calidad; independiente del fabricante; **sin código nuevo**. |
| Inconvenientes | Requiere adaptador óptico adecuado; ajustar foco/parfocalidad; coste de la cámara. |

**Camino para un colaborador:**

1. Documenta adaptador, cámara y montaje (fotos del montaje **sin pacientes**).
2. Verifica la cámara en la app Cámara de Windows y con `colpo list --probe`.
3. Perfil JSON de la cámara, con resoluciones **verificadas** (`"verificada": true`).
4. Fila en [HARDWARE.md](HARDWARE.md) indicando "puerto óptico + cámara UVC".
5. Consulta a ingeniería biomédica antes de modificar físicamente el equipo (garantía y
   seguridad eléctrica, RISKS.md R3–R4).

## 3. SDK o documentación publicados por el fabricante

Algunos fabricantes publican un SDK o un protocolo documentado para integrar su cámara.

| | |
|---|---|
| Ventajas | Acceso a funciones propias del equipo (controles, botón de captura). |
| Inconvenientes | Depende de la licencia del SDK; puede ser solo para Windows; mantenimiento. |

**Camino para un colaborador:**

1. Obtén el SDK **por un canal oficial** y lee su licencia. Comprueba que permite su uso en un
   proyecto Apache-2.0 y la redistribución que necesites.
2. Si la licencia **no** permite incluirlo aquí, el driver se publica como **paquete aparte**
   (`colpo-driver-<equipo>`) que el usuario instala junto con el SDK; este repositorio solo
   lo referencia en la documentación.
3. Implementa el contrato `CameraDriver` (DRIVER_GUIDE.md §2–3): `discover` y `open` usando
   la API documentada; traduce sus errores a `CameraNotFound`/`CameraBusy`/
   `CameraDisconnected`/`FormatNotSupported`.
4. El driver **no** debe requerir el dongle de licencia del software clínico; si el SDK lo
   exige, esta vía no es aplicable.
5. Pasa la suite de contrato con el equipo conectado (`COLPO_CONTRACT_HARDWARE=1`).
6. Perfil JSON + fila en HARDWARE.md con estado `no_uvc` y driver recomendado.

## Si ninguna vía es posible

- Registra el modelo en [HARDWARE.md](HARDWARE.md) como `no_uvc` (❌) con las salidas de
  video que tenga: es información útil para otros sitios.
- Puedes **solicitar formalmente** al fabricante documentación de interoperabilidad o un SDK
  (plantilla de carta prevista en F5) y dejar constancia de la respuesta.
- No intentes "abrir" el protocolo propietario: queda fuera del alcance del proyecto.
