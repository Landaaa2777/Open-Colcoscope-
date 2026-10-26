"""Metadatos por captura: lista cerrada de campos, hora exacta y notas sin identificadores."""

from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

from colpo import MetadataError, NotesRejectedError
from colpo.metadata import (
    IFCPC_STAGES,
    METADATA_FIELDS,
    CaptureMetadata,
    capture_timestamp,
    clean_notes,
    find_identifier_risks,
    new_study_id,
    read_sidecar,
    sha256_file,
    sidecar_path,
    write_sidecar,
)

SHA = "a" * 64


def _meta(**overrides: object) -> CaptureMetadata:
    values: dict[str, object] = {
        "id_estudio": new_study_id(),
        "timestamp": "2026-10-26T15:04:05-05:00",
        "etapa_ifcpc": "acido_acetico",
        "ancho": 1280,
        "alto": 720,
        "fps": 29.97,
        "tipo": "foto",
        "sha256": SHA,
        "notas": None,
    }
    values.update(overrides)
    return CaptureMetadata(**values)  # type: ignore[arg-type]


def test_ifcpc_vocabulary_and_closed_field_list() -> None:
    assert IFCPC_STAGES == ("basal", "solucion_salina", "acido_acetico", "lugol", "filtro_verde")
    assert list(_meta().to_dict()) == list(METADATA_FIELDS)
    assert METADATA_FIELDS == (
        "id_estudio", "timestamp", "etapa_ifcpc", "resolucion", "fps", "tipo", "sha256", "notas",
    )  # fmt: skip


def test_study_ids_are_random_and_well_formed() -> None:
    ids = {new_study_id() for _ in range(200)}
    assert len(ids) == 200
    assert all(len(i) == 10 and i.startswith("E-") for i in ids)


def test_timestamp_is_exact_to_the_second_with_utc_offset() -> None:
    lima = timezone(timedelta(hours=-5))
    moment = datetime(2026, 10, 26, 15, 4, 5, 987654, tzinfo=lima)
    assert capture_timestamp(moment) == "2026-10-26T15:04:05-05:00"
    assert len(capture_timestamp()) == len("2026-10-26T15:04:05-05:00")


@pytest.mark.parametrize(
    "overrides",
    [
        {"id_estudio": "Maria Perez"},
        {"timestamp": "2026-10-26"},  # sin hora: no se acepta baja precisión
        {"timestamp": "2026-10-26T15:04:05.123-05:00"},
        {"etapa_ifcpc": "vinagre"},
        {"tipo": "audio"},
        {"sha256": "abc"},
        {"ancho": 0},
        {"fps": -1},
    ],
)
def test_invalid_values_are_rejected(overrides: dict[str, object]) -> None:
    with pytest.raises(MetadataError):
        _meta(**overrides)


@pytest.mark.parametrize(
    ("text", "reason"),
    [
        ("DNI 45871236", "numero_largo"),
        ("cel 987 654 321", "numero_largo"),
        ("nació el 03/04/1990", "fecha"),
        ("escribir a ana@example.org", "email"),
        ("Nombre: X", "palabra_clave"),
        ("historia clínica pendiente", "palabra_clave"),
        ("patient name withheld", "palabra_clave"),
    ],
)
def test_notes_with_possible_identifiers_are_rejected(text: str, reason: str) -> None:
    assert reason in find_identifier_risks(text)
    with pytest.raises(NotesRejectedError) as excinfo:
        clean_notes(text)
    assert reason in excinfo.value.reasons
    with pytest.raises(NotesRejectedError):
        _meta(notas=text)


@pytest.mark.parametrize(
    "text",
    ["Zona de transformación tipo 2", "Epitelio acetoblanco tenue a los 60 s", "Maniquí 3"],
)
def test_educational_notes_are_accepted(text: str) -> None:
    assert clean_notes(f"  {text}  ") == text


def test_empty_and_too_long_notes() -> None:
    assert clean_notes("   ") is None
    assert clean_notes(None) is None
    with pytest.raises(NotesRejectedError) as excinfo:
        clean_notes("a" * 501)
    assert excinfo.value.reasons == ("demasiado_largo",)


def test_sidecar_roundtrip_and_extra_fields_rejected(tmp_path: Path) -> None:
    media = tmp_path / "foto_20261026-150405.png"
    media.write_bytes(b"png")
    meta = _meta(sha256=sha256_file(media), notas="Maniquí 1")
    path = write_sidecar(media, meta)
    assert path == sidecar_path(media) == tmp_path / "foto_20261026-150405.json"
    assert read_sidecar(path) == meta

    data = json.loads(path.read_text(encoding="utf-8"))
    data["nombre"] = "no permitido"
    path.write_text(json.dumps(data), encoding="utf-8")
    with pytest.raises(MetadataError, match="Sobran"):
        read_sidecar(path)


def test_sha256_file(tmp_path: Path) -> None:
    f = tmp_path / "x.bin"
    f.write_bytes(b"abc")
    assert sha256_file(f) == "ba7816bf8f01cfea414140de5dae2223b00361a396177a9cb410ff61f20015ad"
