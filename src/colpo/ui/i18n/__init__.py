"""Traducciones de la interfaz: catálogos JSON planos (``es.json``, ``en.json``).

Por qué JSON y no ``.ts``/``.qm`` de Qt Linguist:

- **Sin paso de compilación**: los ``.ts`` deben compilarse a ``.qm`` con
  ``lrelease``; un JSON se edita y se usa tal cual (también desde PyInstaller).
- **Fácil de contribuir**: cualquier editor de texto sirve y los cambios se
  revisan bien en un *diff*; no hace falta instalar Qt Linguist.
- **Cambio de idioma en caliente** trivial: la ventana vuelve a pedir sus textos.
- **Verificable en CI**: una prueba exige que todos los idiomas tengan las mismas
  claves y los mismos marcadores ``{...}``.

Contras asumidos: no hay soporte automático de plurales ni la herramienta
visual de Qt Linguist; si el proyecto crece mucho en idiomas, se puede migrar.
Español es el idioma por defecto y de respaldo para claves faltantes.
"""

from __future__ import annotations

import json
from importlib import resources

LANGUAGES: dict[str, str] = {"es": "Español", "en": "English"}
DEFAULT_LANGUAGE = "es"


def load_catalog(language: str) -> dict[str, str]:
    """Carga el catálogo de un idioma (diccionario plano clave -> texto)."""
    if language not in LANGUAGES:
        raise ValueError(f"Idioma no soportado: {language!r}")
    text = resources.files(__name__).joinpath(f"{language}.json").read_text(encoding="utf-8")
    data = json.loads(text)
    if not all(isinstance(k, str) and isinstance(v, str) for k, v in data.items()):
        raise ValueError(f"El catálogo {language}.json debe ser un objeto plano de textos.")
    return data


class Translator:
    """Traduce claves al idioma activo; cae a español si falta una clave."""

    def __init__(self, language: str = DEFAULT_LANGUAGE) -> None:
        self._fallback = load_catalog(DEFAULT_LANGUAGE)
        self._language = DEFAULT_LANGUAGE
        self._catalog = self._fallback
        self.set_language(language)

    @property
    def language(self) -> str:
        return self._language

    def set_language(self, language: str) -> None:
        self._catalog = load_catalog(language)
        self._language = language

    def has(self, key: str) -> bool:
        return key in self._catalog or key in self._fallback

    def tr(self, key: str, **params: object) -> str:
        text = self._catalog.get(key) or self._fallback.get(key) or key
        return text.format(**params) if params else text
