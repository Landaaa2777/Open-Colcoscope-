# Privacidad y protección de datos

> Prototipo educativo. **No es un producto médico validado.** Este documento describe el
> diseño del software y las condiciones de uso acordadas; **no es asesoría legal**. Cada
> institución debe validarlo con su oficial de protección de datos y su asesoría legal.

## 1. Principios

1. **Sin identificadores personales.** El software no tiene campos para nombre, iniciales,
   documento de identidad, fecha de nacimiento, edad exacta, historia clínica, dirección ni
   teléfono. No existen en el esquema.
2. **Hora exacta sí, identidad no.** Cada captura registra la fecha y hora local exactas al
   segundo (ISO 8601 con desfase UTC). La hora describe *la captura*, no *a la persona*. Son
   dimensiones distintas y así se tratan (ver §3).
3. **100 % offline.** Sin red, sin telemetría, sin cuentas, sin actualizaciones automáticas.
   Verificado por pruebas automáticas ([ARCHITECTURE.md §8.6](ARCHITECTURE.md#86-garantía-sin-red)).
4. **Sin audio.** Las conversaciones pueden contener nombres.
5. **Sin metadatos incrustados.** Los PNG no llevan EXIF/XMP/GPS.
6. **Seudónimo aleatorio.** El `id_estudio` es aleatorio. Si la institución necesita
   volver a vincular un estudio con una persona, la tabla de correspondencia se guarda **fuera
   de la aplicación**, bajo custodia institucional.
7. **Lista blanca.** El esquema de metadatos rechaza cualquier campo no definido.

## 2. Inventario de datos

Desde v0.2.0-ui cada captura lleva un JSON con **exactamente** estos campos (ver
[ARCHITECTURE.md §8.3](ARCHITECTURE.md#83-metadatos-por-captura-esquema-f2-lista-cerrada)):

| Dato | Dónde | ¿Identifica a la paciente? |
|---|---|---|
| Imagen PNG / video MP4 | Archivo | La imagen colposcópica en sí no suele identificar, pero puede contener texto superpuesto (OSD) u objetos identificables: revisar antes de compartir. |
| `id_estudio` (seudónimo aleatorio) | JSON y nombre de carpeta | No por sí mismo. |
| `timestamp` (hora exacta al segundo) | JSON y nombre de archivo | No directamente; es cuasi-identificador (§3). |
| `etapa_ifcpc`, `resolucion`, `fps`, `tipo`, `sha256` | JSON | No. |
| `notas` (opcional) | JSON | Riesgo: pueden contener datos personales. Se filtran (DNI, teléfonos, fechas, correos, palabras como "nombre") y, si parecen contener identificadores, **no se guardan**. El filtro es una red de seguridad, no una garantía. |
| VID:PID / modelo del colposcopio | **No se guarda** en F2 | — |
| Número de serie del equipo, usuario de Windows, nombre del PC, ubicación | **Nunca** | **Nunca** | — |

## 3. Hora exacta: decisión y riesgo residual

**Decisión (F0):** se registra la hora exacta al segundo porque es necesaria para el uso
educativo (secuencia de etapas, tiempos tras ácido acético o lugol).

**Riesgo residual:** combinada con la agenda del servicio o el registro de citas del sitio, la
hora puede permitir saber a quién corresponde una captura. Por eso, en sentido estricto, los
datos con hora exacta son **seudonimizados**, no anónimos, mientras alguien pueda acceder a esas
agendas. Mitigaciones:

- Control de acceso a la carpeta de datos (cuenta de Windows con contraseña; solo personal autorizado).
- Cifrado del disco (BitLocker o "Cifrado de dispositivo" de Windows).
- Revisión antes de compartir; los paquetes educativos se generan con el exportador (F2), que
  reasigna `id_estudio` y excluye el texto libre.
- No publicar capturas junto con fechas de servicio, nombres de sala u otros datos del sitio.
- Si un comité de ética lo exige, se podrá añadir una opción de exportación que desplace las
  horas. Estará desactivada por defecto y la hora original no se modifica.

## 4. Uso por fases

### F1–F3: sin pacientes

Solo **maniquíes, objetivos de prueba y material educativo ya existente**. El material
existente debe contar con los permisos y la anonimización con que fue producido; no se
incorpora al repositorio ni a las pruebas (las pruebas usan video sintético).

### F4 en adelante: captura clínica educativa en entorno controlado

Solo puede iniciarse cuando **todas** estas condiciones se cumplan y estén documentadas:

- [ ] **Aprobación del comité de ética institucional** (p. ej., Comité Institucional de Ética en
      Investigación) del protocolo de captura y uso educativo.
- [ ] **Consentimiento informado** escrito, específico para la captura y el uso educativo de
      las imágenes, revocable, con formato aprobado por el comité. La persona puede negarse
      sin consecuencias en su atención.
- [ ] **Cumplimiento de la Ley N.° 29733**, Ley de Protección de Datos Personales del Perú, y su
      reglamento vigente. Los datos de salud son **datos sensibles** y requieren consentimiento
      expreso y por escrito. La institución, como titular del banco de datos, define finalidad,
      plazos de conservación, medidas de seguridad, atención de derechos (acceso, rectificación,
      cancelación y oposición) e inscripción del banco de datos ante la Autoridad Nacional de
      Protección de Datos Personales cuando corresponda.
- [ ] **Anonimización obligatoria** antes de cualquier uso fuera del sitio de captura: ningún
      identificador personal; revisión visual de cada imagen (texto superpuesto, objetos
      identificables); `id_estudio` reasignado; tabla de correspondencia, si existe, solo en
      custodia institucional.
- [ ] **Seguridad del equipo:** cuenta con contraseña, disco cifrado, carpeta de datos excluida
      de OneDrive u otra sincronización, sin acceso de terceros.
- [ ] **Seguridad eléctrica** revisada por ingeniería biomédica (equipo médico + PC no médico en
      el entorno del paciente; ver [RISKS.md](RISKS.md) R3).
- [ ] Personal capacitado en el uso del software y en estas reglas.

El software **no** almacena el consentimiento ni datos del consentimiento: estos se gestionan con
los procedimientos de la institución.

## 5. Conservación, eliminación y copias

- La institución define los plazos de conservación.
- Borrar archivos en SSD/flash no garantiza que sean irrecuperables: de ahí el cifrado de disco.
- Las copias de seguridad deben tener el mismo nivel de protección que el original.

## 6. Compartir y contribuir

- **Nunca** adjuntes imágenes o videos de pacientes en issues, PR, chats o correos del proyecto.
- Para reportar problemas, usa el video sintético (`examples/synthetic_video.py`) o capturas de
  un objetivo no humano.
- Los reportes de hardware no incluyen números de serie ni rutas completas de dispositivos.

## 7. Responsabilidades

| Parte | Responsabilidad |
|---|---|
| Proyecto Open Colposcope | Diseño con privacidad por defecto; sin red; documentación clara; corrección de defectos de privacidad. |
| Institución usuaria | Base legal, comité de ética, consentimiento, seguridad del equipo, conservación, atención de derechos, cumplimiento de la Ley 29733 (u otra ley local). |
| Personas usuarias | Usar el software según este documento; no introducir datos identificatorios. |
