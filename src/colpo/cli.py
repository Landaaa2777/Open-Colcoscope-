"""Interfaz de línea de comandos ``colpo``.

Comandos:
    colpo list [--backend B] [--probe] [--json]
    colpo preview (--index N | --source VIDEO) [--out-dir DIR]
    colpo record  (--index N | --source VIDEO) --out ARCHIVO.mp4 --duration S
    colpo snapshot (--index N | --source VIDEO) --out ARCHIVO.png

Códigos de salida: 0 correcto, 1 error de captura, 2 uso incorrecto,
130 interrumpido por el usuario.
"""

from __future__ import annotations

import argparse
import json
import logging
import sys
from collections.abc import Sequence
from pathlib import Path

import cv2

from colpo import DISCLAIMER, __version__
from colpo.capture import UVCCamera
from colpo.devices import DeviceInfo, available_backends, list_devices
from colpo.errors import ColpoError, DeviceDisconnectedError, EndOfStreamError

EXIT_OK, EXIT_ERROR, EXIT_USAGE, EXIT_INTERRUPTED = 0, 1, 2, 130


def _positive_float(text: str) -> float:
    value = float(text)
    if value <= 0:
        raise argparse.ArgumentTypeError("debe ser mayor que 0")
    return value


def _add_source_args(parser: argparse.ArgumentParser) -> None:
    group = parser.add_mutually_exclusive_group(required=True)
    group.add_argument("--index", type=int, help="índice de la cámara (ver 'colpo list')")
    group.add_argument(
        "--source", type=Path, help="archivo de video como fuente (demostración/pruebas)"
    )
    parser.add_argument(
        "--backend",
        default="auto",
        choices=("auto", *available_backends()),
        help="API de captura del SO (por defecto: auto)",
    )
    parser.add_argument("--width", type=int, help="ancho solicitado (requiere --height)")
    parser.add_argument("--height", type=int, help="alto solicitado (requiere --width)")
    parser.add_argument("--fps", type=_positive_float, help="FPS solicitados a la cámara")
    parser.add_argument("--fourcc", help="formato solicitado a la cámara, p. ej. MJPG o YUY2")


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="colpo",
        description="Open Colposcope: captura UVC offline. " + DISCLAIMER,
    )
    parser.add_argument("--version", action="version", version=f"%(prog)s {__version__}")
    parser.add_argument("-v", "--verbose", action="store_true", help="mensajes de diagnóstico")
    sub = parser.add_subparsers(dest="command", required=True, metavar="COMANDO")

    p_list = sub.add_parser("list", help="lista las cámaras detectadas")
    p_list.add_argument("--backend", default="auto", choices=("auto", *available_backends()))
    p_list.add_argument(
        "--probe", action="store_true", help="abre cada cámara y mide resolución y FPS reales"
    )
    p_list.add_argument("--json", action="store_true", help="salida en JSON")
    p_list.set_defaults(handler=cmd_list)

    p_preview = sub.add_parser("preview", help="ventana de vista previa ([S] foto, [R] grabar)")
    _add_source_args(p_preview)
    p_preview.add_argument(
        "--out-dir", type=Path, default=Path("capturas"), help="carpeta para fotos y videos"
    )
    p_preview.set_defaults(handler=cmd_preview)

    p_record = sub.add_parser("record", help="graba video durante un tiempo fijo")
    _add_source_args(p_record)
    p_record.add_argument("--out", type=Path, required=True, help="archivo .mp4, .avi o .mkv")
    p_record.add_argument(
        "--duration", type=_positive_float, required=True, help="duración en segundos"
    )
    p_record.add_argument("--overwrite", action="store_true", help="sobrescribir si existe")
    p_record.set_defaults(handler=cmd_record)

    p_snap = sub.add_parser("snapshot", help="guarda una foto PNG")
    _add_source_args(p_snap)
    p_snap.add_argument("--out", type=Path, required=True, help="archivo .png")
    p_snap.add_argument("--overwrite", action="store_true", help="sobrescribir si existe")
    p_snap.set_defaults(handler=cmd_snapshot)
    return parser


def _camera_from_args(args: argparse.Namespace) -> UVCCamera:
    return UVCCamera(
        index=args.index,
        source=args.source,
        backend=args.backend,
        width=args.width,
        height=args.height,
        fps=args.fps,
        fourcc=args.fourcc,
    )


def _print_stream(cam: UVCCamera) -> None:
    info = cam.stream_info
    reported = f"{info.fps_reported:.1f}" if info.fps_reported > 0 else "?"
    print(
        f"Fuente: {info.source} (backend {info.backend})  "
        f"{info.width}x{info.height} {info.fourcc or '?'}  FPS informados: {reported}"
    )


# ------------------------------------------------------------------ comandos
def cmd_list(args: argparse.Namespace) -> int:
    devices = list_devices(args.backend)
    probes: dict[int, str] = {}
    if args.probe:
        for dev in devices:
            probes[dev.index] = _probe(dev)

    if args.json:
        rows = []
        for dev in devices:
            row: dict[str, object] = {
                "index": dev.index,
                "name": dev.name,
                "backend": dev.backend,
                "vendor_id": dev.vendor_id,
                "product_id": dev.product_id,
                "vid_pid": dev.vid_pid,
            }
            if args.verbose:
                row["path"] = dev.path
            if args.probe:
                row["probe"] = probes[dev.index]
            rows.append(row)
        print(json.dumps(rows, ensure_ascii=False, indent=2))
        return EXIT_OK

    if not devices:
        print(
            "No se detectaron cámaras. Compruebe la conexión USB, que ninguna otra aplicación "
            "esté usando la cámara y los permisos de cámara del sistema.",
            file=sys.stderr,
        )
        return EXIT_OK

    backend = devices[0].backend
    print(f"Cámaras detectadas (backend {backend}):")
    print(f"  {'ÍNDICE':<7}{'VID:PID':<11}NOMBRE")
    for dev in devices:
        print(f"  {dev.index:<7}{dev.vid_pid:<11}{dev.name}")
        if args.verbose and dev.path:
            print(f"  {'':<7}{'':<11}ruta: {dev.path}")
        if args.probe:
            print(f"  {'':<7}{'':<11}{probes[dev.index]}")
    return EXIT_OK


def _probe(dev: DeviceInfo) -> str:
    try:
        with UVCCamera(index=dev.index, backend=dev.backend, warmup_frames=3) as cam:
            info = cam.stream_info
            measured = cam.measure_fps(20)
            reported = f"{info.fps_reported:.1f}" if info.fps_reported > 0 else "?"
            return (
                f"{info.width}x{info.height} {info.fourcc or '?'}, "
                f"FPS informados {reported}, medidos {measured:.1f}"
            )
    except ColpoError as exc:
        return f"no se pudo abrir: {exc}"


def cmd_preview(args: argparse.Namespace) -> int:
    try:
        from colpo.preview import run_preview
    except ImportError as exc:
        raise ColpoError(
            f"La vista previa necesita PySide6 ({exc}). Instale con: pip install PySide6-Essentials"
        ) from exc

    with _camera_from_args(args) as cam:
        _print_stream(cam)
        print("Teclas: [S]/[Espacio] foto, [R] grabar/detener, [Q]/[Esc] salir.")
        result = run_preview(cam, out_dir=args.out_dir)

    for path in result.snapshots:
        print(f"Foto: {path}")
    for stats in result.recordings:
        print(f"Video: {stats.path} ({stats.duration_s:.1f} s, {stats.frames_dropped} perdidos)")
    if result.error is not None:
        raise result.error
    return EXIT_OK


def cmd_record(args: argparse.Namespace) -> int:
    exit_code = EXIT_OK
    with _camera_from_args(args) as cam:
        _print_stream(cam)
        if not cam.is_file_source:
            print("Midiendo FPS reales...")
            print(f"FPS medidos: {cam.measure_fps():.1f}")
        out = cam.start_recording(args.out, overwrite=args.overwrite)
        print(f"Grabando {args.duration:g} s en {out} (Ctrl+C para detener antes)...")

        first: float | None = None
        last_second = -1
        try:
            while True:
                frame = cam.read_frame()
                if first is None:
                    first = frame.timestamp
                elapsed = frame.timestamp - first
                if elapsed >= args.duration:
                    break
                if int(elapsed) != last_second:
                    last_second = int(elapsed)
                    print(f"  {last_second:>4d} s", flush=True)
        except EndOfStreamError:
            print("Aviso: el video de origen terminó antes de la duración pedida.")
        except DeviceDisconnectedError as exc:
            print(f"Error: {exc} Se conserva lo grabado hasta ese momento.", file=sys.stderr)
            exit_code = EXIT_ERROR
        except KeyboardInterrupt:
            print("Interrumpido por el usuario; cerrando el archivo...")
            exit_code = EXIT_INTERRUPTED

        stats = cam.stop_recording()

    print(
        f"Video guardado: {stats.path}\n"
        f"  duración {stats.duration_s:.2f} s a {stats.fps:g} FPS ({stats.codec}), "
        f"{stats.frames_written} frames escritos, {stats.frames_received} recibidos, "
        f"{stats.frames_dropped} perdidos"
    )
    if stats.frames_dropped:
        print(
            "Aviso: se perdieron frames por falta de CPU o disco. Pruebe .avi (MJPEG) o "
            "una resolución menor.",
            file=sys.stderr,
        )
    return exit_code


def cmd_snapshot(args: argparse.Namespace) -> int:
    with _camera_from_args(args) as cam:
        _print_stream(cam)
        path = cam.snapshot(args.out, overwrite=args.overwrite)
    print(f"Foto guardada: {path}")
    return EXIT_OK


def _silence_opencv_warnings() -> None:
    """Oculta los avisos internos de OpenCV (p. ej. al sondear índices sin cámara)."""
    logging_mod = getattr(getattr(cv2, "utils", None), "logging", None)
    if logging_mod is not None and hasattr(logging_mod, "setLogLevel"):
        logging_mod.setLogLevel(logging_mod.LOG_LEVEL_ERROR)


def main(argv: Sequence[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    if hasattr(args, "index"):
        if (args.width is None) != (args.height is None):
            parser.error("--width y --height deben indicarse juntos")
        if args.fourcc is not None and len(args.fourcc) != 4:
            parser.error("--fourcc debe tener 4 caracteres, p. ej. MJPG")
        if args.index is not None and args.index < 0:
            parser.error("--index debe ser >= 0")
    logging.basicConfig(
        level=logging.INFO if args.verbose else logging.WARNING,
        format="%(levelname)s: %(message)s",
    )
    if not args.verbose:
        _silence_opencv_warnings()
    try:
        return int(args.handler(args))
    except ColpoError as exc:
        print(f"Error: {exc}", file=sys.stderr)
        return EXIT_ERROR
    except KeyboardInterrupt:
        return EXIT_INTERRUPTED


if __name__ == "__main__":
    sys.exit(main())
