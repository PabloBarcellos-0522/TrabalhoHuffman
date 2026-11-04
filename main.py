"""Ponto de entrada do Compactador de Arquivos — Huffman e LZ77."""

from __future__ import annotations

import sys


def main() -> int:
    try:
        import customtkinter  # noqa: F401
    except ImportError:
        print(
            "CustomTkinter não está instalado.\n"
            "Execute:  python -m pip install -r requirements.txt",
            file=sys.stderr,
        )
        return 1

    from interface import run

    run()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
