"""Garantía "sin red" (ARCHITECTURE.md §8.6).

1. Análisis estático: ningún módulo del paquete importa librerías de red.
2. Prueba dinámica: una grabación completa funciona con los sockets bloqueados.
"""

from __future__ import annotations

import ast
import socket
from pathlib import Path

import pytest

from colpo import cli

PACKAGE_DIR = Path(__file__).resolve().parents[1] / "src" / "colpo"
FORBIDDEN = {
    "socket",
    "ssl",
    "http",
    "urllib",
    "urllib3",
    "requests",
    "httpx",
    "aiohttp",
    "ftplib",
    "smtplib",
    "poplib",
    "imaplib",
    "telnetlib",
    "xmlrpc",
    "websocket",
    "websockets",
    "asyncio",
    "socketserver",
    "webbrowser",
    "PySide6.QtNetwork",
    "PySide6.QtWebEngineCore",
    "PySide6.QtWebEngineWidgets",
}


def _imported_modules(path: Path) -> set[str]:
    tree = ast.parse(path.read_text(encoding="utf-8"))
    names: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            names.update(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module:
            names.add(node.module)
    return names


def _is_forbidden(module: str) -> bool:
    return any(module == f or module.startswith(f + ".") for f in FORBIDDEN)


def test_package_has_source_files() -> None:
    assert len(list(PACKAGE_DIR.glob("*.py"))) >= 5


@pytest.mark.parametrize("path", sorted(PACKAGE_DIR.glob("*.py")), ids=lambda p: p.name)
def test_no_network_imports(path: Path) -> None:
    offending = sorted(m for m in _imported_modules(path) if _is_forbidden(m))
    assert not offending, f"{path.name} importa módulos de red: {offending}"


def test_capture_flow_works_with_sockets_blocked(
    synthetic_video: Path, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    def blocked(*_args: object, **_kwargs: object) -> None:
        raise AssertionError("Intento de abrir un socket de red")

    monkeypatch.setattr(socket, "socket", blocked)
    monkeypatch.setattr(socket, "create_connection", blocked)
    out = tmp_path / "v.mp4"
    args = ["record", "--source", str(synthetic_video), "--out", str(out), "--duration", "1"]
    assert cli.main(args) == 0
    assert (
        cli.main(["snapshot", "--source", str(synthetic_video), "--out", str(tmp_path / "f.png")])
        == 0
    )
