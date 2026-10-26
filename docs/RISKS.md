# Registro de riesgos — Open Colposcope (nombre provisional)

> Prototipo educativo. **No es un producto médico validado.**
> Este documento **no constituye asesoría legal ni regulatoria**. Las instituciones que
> adopten el software deben consultar a asesores en su jurisdicción.

**Escala:** Probabilidad (P) e Impacto (I): Baja / Media / Alta. Se revisa al cerrar cada fase.

## 1. Riesgos técnicos

| ID | Riesgo | P | I | Mitigación | Fase |
|---|---|---|---|---|---|
| T1 | El colposcopio **no es UVC** (protocolo propietario, video cifrado o tarjeta de captura interna). | M | A | Verificarlo en F0 antes de escribir código; rutas alternativas legítimas: capturadora UVC sobre salida de video, cámara UVC en puerto óptico, SDK publicado (ARCHITECTURE.md §6.6). | F0 |
| T2 | Dispositivos UVC **no conformes** (descriptores erróneos, formatos anunciados que no funcionan). | M | M | Perfiles con *quirks*; `diagnose`; probar formatos reales y no solo los anunciados. | F1–F3 |
| T3 | Diferencias entre backends del SO (MSMF vs DirectShow, V4L2, AVFoundation): resoluciones, latencia, nombres. | A | M | Selección de API por perfil; enumeración nativa complementaria; matriz de pruebas por SO en HARDWARE.md. | F1, F3 |
| T4 | OpenCV no expone la lista de formatos ni nombres de dispositivo de forma fiable. | A | M | Enumeración nativa por SO; evaluar Qt Multimedia como backend alternativo (F3). | F1, F3 |
| T5 | **Ancho de banda USB 2.0** insuficiente para 1080p sin compresión. | A | M | Preferir MJPEG; YUY2 a menor FPS solo para imagen fija; documentar por modelo. | F1 |
| T6 | Rendimiento insuficiente en **equipos antiguos** (CPU/RAM). | M | A | Equipo de referencia definido en F0; grabación MJPEG sin recodificar; vista previa reducida; perfiles de rendimiento. | F0–F2 |
| T7 | **SO antiguos** (Windows 7/8, 32 bits) no soportados por Python 3.11+/Qt 6. | M | A | Confirmar parque real en F0; si es significativo, evaluar variante ligera (Tkinter) o recomendar Linux ligero en el mismo equipo. | F0 |
| T8 | **Pérdida de datos** por corte de energía, cierre forzado o desconexión. | M | A | Escritura atómica + `fsync`; video segmentado; recuperación al inicio; confirmación solo tras persistir. | F1 |
| T9 | **Disco lleno** durante una grabación. | M | M | Verificación previa de espacio; umbral de parada segura; aviso visible. | F1–F2 |
| T10 | **Fidelidad de color** variable (balance de blancos automático), crítica en colposcopia (acetoblanco, lugol). | A | M | Bloqueo de AWB/exposición por perfil; registro de controles en metadatos; guía con carta de color. No se ofrece corrección "diagnóstica". | F3 |
| T11 | Permisos de cámara en macOS y paquetes sin firma (Gatekeeper, SmartScreen). | A | M | `NSCameraUsageDescription`; firma/notarización si hay fondos; guía para TI. | F4 |
| T12 | **Falsos positivos de antivirus** con ejecutables PyInstaller en redes hospitalarias. | A | M | Firma de código; alternativa Nuitka; reporte a proveedores AV; distribución también como paquete Python. | F4 |
| T13 | Tamaño del paquete (Qt + OpenCV) grande para distribución offline. | M | B | Excluir módulos Qt no usados; `opencv-python-headless`; medir en F4. | F4 |
| T14 | libuvc requiere desvincular/reemplazar el controlador del SO y puede dejar la cámara inutilizable para otras apps. | M | M | Backend opcional y no predeterminado; advertencias claras; instrucciones de reversión. | F3 |
| T15 | Licencias de dependencias (LGPL de Qt/FFmpeg, patentes de H.264). | M | M | SBOM; enlace dinámico de Qt; preferir MJPEG/códecs libres de regalías; revisión en F4. | F0, F4 |

## 2. Riesgos legales

| ID | Riesgo | P | I | Mitigación | Fase |
|---|---|---|---|---|---|
| L1 | Acusación de **elusión de medidas tecnológicas de protección** (dongle). | B* | A | El proyecto **no** interactúa con el dongle ni con el software propietario (ver §5). Política de contribuciones que rechaza cracks/emuladores. *Baja mientras se cumpla la política. | Todas |
| L2 | **Incumplimiento del EULA** del software del fabricante. | B | M | No se instala, ejecuta, decompila ni redistribuye el software propietario; solo se usa la cámara vía estándar UVC. Revisar EULA y condiciones de compra del equipo en F0. | F0 |
| L3 | Uso de **marcas registradas** del fabricante. | M | B | Nombre del proyecto sin marcas de terceros; mención nominativa solo en HARDWARE.md ("compatible con…"); sin logotipos. | Todas |
| L4 | Contribuciones con **código o firmware de terceros** sin licencia. | M | A | DCO (`Signed-off-by`) o CLA; revisión obligatoria; política explícita; retirada inmediata. | F5 |
| L5 | **Responsabilidad** por uso clínico indebido. | M | A | Licencia sin garantía; declaración de uso previsto visible; sin funciones diagnósticas; ver §3. | Todas |
| L6 | Ingeniería inversa de un **protocolo de video** propietario, en zona gris según jurisdicción. | B | A | Fuera de alcance por defecto; solo con revisión legal documentada y en repositorio separado; preferir rutas de hardware estándar. | F3+ |
| L7 | Carta de cese y desista de un fabricante. | B | M | Arquitectura limpia y documentada; ninguna dependencia de material del fabricante; procedimiento de respuesta en GOVERNANCE.md. | F5 |

## 3. Riesgos regulatorios y de seguridad del paciente

| ID | Riesgo | P | I | Mitigación | Fase |
|---|---|---|---|---|---|
| R1 | El software podría ser considerado **software como dispositivo médico (SaMD)** si se usa o promociona para diagnóstico (p. ej., MDR UE 2017/745 regla 11; FDA; ANVISA; COFEPRIS; ANMAT; INVIMA; ISP; DIGEMID). | M | A | Uso previsto exclusivamente **educativo**; sin funciones de diagnóstico, medición o apoyo a la decisión; lenguaje cuidadoso en documentación y difusión. | Todas |
| R2 | **Desviación de uso** (*intended use creep*): una institución lo usa en atención clínica rutinaria. | M | A | Aviso en arranque, "Acerca de", metadatos (`intended_use`) y marca de agua en exportaciones; guía institucional; plantilla de acuerdo de uso. | F2, F5 |
| R3 | Conectar un **PC no médico** a un equipo médico en el entorno del paciente (IEC 60601-1, sistemas electromédicos): corrientes de fuga. | M | A | Guía: consultar a ingeniería biomédica; usar portátil con batería o aislamiento galvánico USB / transformador de aislamiento; no tocar al paciente y al PC simultáneamente. | F2, F4 |
| R4 | Conectar el software puede afectar la **garantía o conformidad** del equipo del fabricante. | M | M | Recomendar uso en equipos fuera de servicio clínico o con autorización de la institución; documentar. | F0 |
| R5 | Si en el futuro se quisiera uso clínico, se necesitarían procesos (ISO 13485, IEC 62304, ISO 14971, IEC 62366-1) que el proyecto no tiene. | — | — | Registrar como no-objetivo; buenas prácticas (trazabilidad, pruebas, ADR) facilitarían un fork certificado por terceros. | — |

## 4. Riesgos de privacidad y protección de datos

| ID | Riesgo | P | I | Mitigación | Fase |
|---|---|---|---|---|---|
| P1 | Introducción de **PII en texto libre** (notas, nombres de archivo). | A | A | Texto libre desactivado por defecto; nombres de archivo generados; exportación excluye texto libre sin revisión. | F1–F2 |
| P2 | **Texto superpuesto (OSD)** de la cámara con fecha/hora o nombre de la clínica. | M | M | Máscaras de privacidad por perfil; detección en F0 de qué modelos lo hacen. | F0, F3 |
| P3 | **Audio** con nombres o conversaciones. | M | A | Sin pista de audio por defecto. | F1 |
| P4 | Robo o pérdida del equipo con datos sin cifrar. | M | A | Recomendar cifrado de disco completo; opción futura de cifrado a nivel de app. | F4 |
| P5 | **Re-identificación** al combinar imágenes con otras fuentes (fecha/hora exacta). | B | A | Precisión temporal reducida por defecto; reasignación de `study_id` al exportar. | F1–F2 |
| P6 | Contribuidores adjuntan **imágenes de pacientes en issues** públicos. | M | A | Advertencias en plantillas; moderación y borrado; nunca aceptar imágenes clínicas en el repositorio. | F5 |
| P7 | Huellas en el SO: miniaturas, archivos recientes, copias de seguridad automáticas en la nube. | M | M | Guía para TI; carpeta de datos excluible de sincronización; sin integración con el *shell*. | F4 |
| P8 | Cumplimiento de leyes de protección de datos (RGPD, LGPD, Ley 25.326, LFPDPPP, Ley 1581, Ley 19.628/21.719, etc.). | M | A | Minimización por diseño; responsabilidad del responsable del tratamiento (la institución); plantilla de DPIA en F5. | F5 |

## 5. Por qué NO se emula el dongle

Esta es una decisión **definitiva y no negociable** del proyecto. Ninguna contribución que
emule, clone, parchee, eluda, analice o documente el mecanismo de licencia (dongle,
*keygen*, *crack*, parche de binario, servidor de licencias falso o similar) será aceptada,
y cualquier contenido de ese tipo será retirado.

### 5.1 Razones

1. **Es ilegal en la mayoría de las jurisdicciones, sin importar la finalidad.** El dongle es
   una *medida tecnológica de protección* del software del fabricante. Eludirla o distribuir
   herramientas para hacerlo está prohibido por normas como la DMCA §1201 (EE. UU.), la
   Directiva 2001/29/CE art. 6 (UE) y disposiciones equivalentes presentes en muchas leyes de
   derecho de autor de América Latina (frecuentemente incorporadas por tratados comerciales).
   Las excepciones de interoperabilidad existentes son estrechas y en general no amparan la
   distribución pública de herramientas de elusión. El fin educativo o benéfico **no** es,
   por sí solo, una excepción.
2. **Es innecesario.** El dongle licencia el *software* del fabricante, no la óptica ni la
   cámara. Si la cámara implementa UVC, el controlador genérico del SO ya la puede leer:
   nuestro software nunca necesita que el software propietario funcione.
3. **Pone en riesgo a las personas e instituciones.** Contribuidores, universidades, ONG y
   hospitales públicos quedarían expuestos a responsabilidad legal. Ninguna institución
   seria podría adoptar el proyecto, lo que anularía su propósito de bien público.
4. **Pone en riesgo la plataforma del proyecto.** Los repositorios con herramientas de
   elusión son objeto de solicitudes de retirada, lo que podría eliminar el proyecto entero.
5. **Es un riesgo de seguridad.** Los emuladores y *cracks* de dongles son un vector habitual
   de malware; en una estación que maneja imágenes de pacientes es inaceptable.
6. **Contradice la integridad regulatoria.** Ejecutar el software certificado del fabricante
   en estado modificado lo convierte en un sistema no conforme y engañoso; nuestro enfoque es
   un software separado, transparente y claramente etiquetado como educativo.
7. **No es sostenible.** La emulación se rompe con cada actualización del fabricante; los
   estándares abiertos (UVC) son estables por décadas.

### 5.2 Qué hacemos en su lugar

- Capturar mediante **USB Video Class** y los controladores genéricos del SO.
- Usar **salidas de video estándar** del equipo con capturadoras UVC genéricas.
- Usar el **puerto óptico** del colposcopio (divisor de haz / montura C) con una cámara UVC genérica.
- Integrar **SDK o documentación publicados** por fabricantes con licencias compatibles, como plugins.
- **Solicitar formalmente** documentación de interoperabilidad a los fabricantes y documentar la respuesta.

### 5.3 Procedimiento ante contribuciones prohibidas

1. Cerrar el PR/issue sin fusionar y ocultar o eliminar el contenido.
2. Si el contenido llegó a la rama principal: revertir, purgar del historial si es necesario y publicar un aviso.
3. Recordar la política al autor; reincidencia → aplicación del código de conducta.

## 6. Riesgos de proyecto y comunidad

| ID | Riesgo | P | I | Mitigación | Fase |
|---|---|---|---|---|---|
| C1 | **Bus factor** bajo (una sola persona mantenedora). | A | A | ≥ 2 mantenedores en F5; documentación y ADR; automatización de publicación. | F5 |
| C2 | Contribuidores **sin acceso a hardware**. | A | M | Backend `replay`; pruebas de contrato; programa de préstamo/pruebas remotas. | F1, F5 |
| C3 | **Crecimiento de alcance** (IA, PACS, historia clínica). | M | M | No-objetivos explícitos; ADR obligatorio para ampliar alcance. | Todas |
| C4 | Falta de **validación con usuarios reales** (docentes). | M | A | Entrevistas en F0; pruebas de usabilidad en F2. | F0, F2 |
| C5 | Abandono de dependencias clave (bindings, librerías). | B | M | Arquitectura de adaptadores; dependencias mínimas y populares. | Todas |
