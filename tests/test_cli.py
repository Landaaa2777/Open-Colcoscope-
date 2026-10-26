"""Pruebas de la CLI ``colpo`` con video sintético."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from colpo import DeviceInfo, cli
from conftest import SYNTH_FPS, count_frames
from synthetic_video import decode_index


def test_record_from_synthetic_source(synthetic_video: Path, tmp_path: Path, capsys) -> None:
    out = tmp_path / "test.mp4"
    code = cli.main(
        ["record", "--source", str(synthetic_video), "--out", str(out), "--duration", "1"]
    )
    assert code == cli.EXIT_OK
    n, fps, _size, frames = count_frames(out)
    assert n == pytest.approx(SYNTH_FPS, abs=1)  # 1 s (+ el frame que alcanza el límite)
    assert fps == pytest.approx(SYNTH_FPS)
    assert decode_index(frames[0]) == 0
    assert "Video guardado" in capsys.readouterr().out


def test_record_longer_than_source_stops_at_end(
    synthetic_video: Path, tmp_path: Path, capsys
) -> None:
    out = tmp_path / "test.avi"
    code = cli.main(
        ["record", "--source", str(synthetic_video), "--out", str(out), "--duration", "60"]
    )
    assert code == cli.EXIT_OK
    assert "terminó antes" in capsys.readouterr().out
    assert count_frames(out)[0] == 90


def test_record_refuses_to_overwrite(synthetic_video: Path, tmp_path: Path, capsys) -> None:
    out = tmp_path / "test.mp4"
    out.write_bytes(b"x")
    args = ["record", "--source", str(synthetic_video), "--out", str(out), "--duration", "1"]
    assert cli.main(args) == cli.EXIT_ERROR
    assert "ya existe" in capsys.readouterr().err
    assert cli.main([*args, "--overwrite"]) == cli.EXIT_OK


def test_snapshot_command(synthetic_video: Path, tmp_path: Path) -> None:
    out = tmp_path / "foto.png"
    assert cli.main(["snapshot", "--source", str(synthetic_video), "--out", str(out)]) == 0
    assert out.read_bytes().startswith(b"\x89PNG")


def test_missing_camera_returns_error(tmp_path: Path, capsys) -> None:
    code = cli.main(
        ["record", "--index", "57", "--out", str(tmp_path / "x.mp4"), "--duration", "1"]
    )
    assert code == cli.EXIT_ERROR
    assert "No se pudo abrir la cámara" in capsys.readouterr().err
    assert list(tmp_path.iterdir()) == []


@pytest.mark.parametrize(
    "argv",
    [
        ["record", "--index", "0", "--out", "x.mp4"],  # falta --duration
        ["record", "--index", "0", "--out", "x.mp4", "--duration", "0"],
        ["record", "--index", "0", "--source", "a.avi", "--out", "x.mp4", "--duration", "1"],
        ["preview", "--index", "0", "--width", "640"],
        ["preview", "--index", "0", "--fourcc", "MJPEG"],
        ["preview", "--index", "-1"],
    ],
)
def test_usage_errors_exit_with_code_2(argv: list[str]) -> None:
    with pytest.raises(SystemExit) as excinfo:
        cli.main(argv)
    assert excinfo.value.code == cli.EXIT_USAGE


def _fake_devices(backend: str = "auto") -> list[DeviceInfo]:
    return [
        DeviceInfo(index=0, name="Cámara integrada", backend="dshow"),
        DeviceInfo(
            index=1,
            name="USB Camera",
            backend="dshow",
            vendor_id=0x1234,
            product_id=0xABCD,
            path=r"\\?\usb#vid_1234&pid_abcd#instancia",
        ),
    ]


def test_list_table(monkeypatch: pytest.MonkeyPatch, capsys) -> None:
    monkeypatch.setattr(cli, "list_devices", _fake_devices)
    assert cli.main(["list"]) == 0
    out = capsys.readouterr().out
    assert "1234:ABCD" in out and "USB Camera" in out and "????:????" in out
    assert "instancia" not in out  # la ruta del SO solo se muestra con --verbose


def test_list_json(monkeypatch: pytest.MonkeyPatch, capsys) -> None:
    monkeypatch.setattr(cli, "list_devices", _fake_devices)
    assert cli.main(["list", "--json"]) == 0
    rows = json.loads(capsys.readouterr().out)
    assert rows[1]["vid_pid"] == "1234:ABCD"
    assert "path" not in rows[1]


def test_list_without_cameras(monkeypatch: pytest.MonkeyPatch, capsys) -> None:
    monkeypatch.setattr(cli, "list_devices", lambda backend="auto": [])
    assert cli.main(["list"]) == 0
    assert "No se detectaron cámaras" in capsys.readouterr().err


def test_version(capsys) -> None:
    with pytest.raises(SystemExit) as excinfo:
        cli.main(["--version"])
    assert excinfo.value.code == 0
    assert "colpo" in capsys.readouterr().out
