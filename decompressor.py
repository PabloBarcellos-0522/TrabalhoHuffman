"""Leitura e descompactação de arquivos ``.huff``.

Fluxo:

1. lê e valida o cabeçalho;
2. reconstrói a árvore de Huffman a partir das frequências;
3. decodifica a sequência de bits;
4. no modo híbrido, interpreta os tokens e desfaz o LZ77;
5. confere tamanho e SHA-256 antes de considerar a operação bem-sucedida.
"""

from __future__ import annotations

import hashlib
import hmac
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Dict, Optional

import file_format as ff
import lz77
from huffman import HuffmanError, Node, build_tree, decode_bytes


class DecompressionError(Exception):
    """Erro durante a descompactação."""


@dataclass
class DecompressionResult:
    compressed_path: Path
    output_path: Path
    original_name: str
    strategy_code: int
    original_size: int
    recovered_size: int
    integrity_ok: bool
    sha_expected: bytes
    sha_actual: bytes
    elapsed: float
    root: Optional[Node]
    freqs: Dict[int, int]
    bits_len: int
    intermediate_size: int
    payload_size: int

    @property
    def strategy_name(self) -> str:
        return ff.strategy_name(self.strategy_code)


def _safe_original_name(original_name: str, compressed_path: Path) -> str:
    """Evita que um nome malicioso no cabeçalho escape da pasta de destino."""

    safe = Path(original_name).name if original_name else ""
    if safe:
        return safe

    base = compressed_path.name
    if base.lower().endswith(".huff"):
        base = base[:-5]
    return base or "arquivo_recuperado"


def suggested_output_name(compressed_path, original_name: str) -> str:
    """Nome padrão do arquivo recuperado (``*_descompactado*``)."""

    compressed_path = Path(compressed_path)
    safe = _safe_original_name(original_name, compressed_path)
    path = Path(safe)

    stem = path.stem or "arquivo"
    suffix = path.suffix

    return f"{stem}_descompactado{suffix}"


def default_output_path(compressed_path, original_name: str) -> Path:
    """Caminho padrão livre, na mesma pasta do ``.huff``."""

    compressed_path = Path(compressed_path)
    directory = compressed_path.parent
    name = suggested_output_name(compressed_path, original_name)
    candidate = directory / name

    if not candidate.exists():
        return candidate

    path = Path(name)
    stem = path.stem
    suffix = path.suffix
    counter = 1
    while True:
        candidate = directory / f"{stem} ({counter}){suffix}"
        if not candidate.exists():
            return candidate
        counter += 1


def read_metadata(compressed_path) -> ff.HuffFile:
    """Lê e valida apenas os metadados de um arquivo ``.huff``."""

    compressed_path = Path(compressed_path)
    if not compressed_path.exists():
        raise DecompressionError(f"Arquivo não encontrado: {compressed_path}")
    if not compressed_path.is_file():
        raise DecompressionError(f"O caminho não é um arquivo: {compressed_path}")

    try:
        return ff.read_huff_file(compressed_path)
    except ff.HuffFormatError as exc:
        raise DecompressionError(str(exc)) from exc


def decompress_file(
    compressed_path,
    output_path=None,
    *,
    overwrite: bool = True,
) -> DecompressionResult:
    """Descompacta ``compressed_path`` e grava o arquivo recuperado."""

    compressed_path = Path(compressed_path)
    metadata = read_metadata(compressed_path)

    if output_path is None:
        output_path = default_output_path(compressed_path, metadata.original_name)
    else:
        output_path = Path(output_path)

    try:
        same_file = output_path.resolve() == compressed_path.resolve()
    except OSError:
        same_file = False
    if same_file:
        raise DecompressionError(
            "O arquivo recuperado não pode sobrescrever o próprio arquivo .huff."
        )

    if output_path.exists() and not overwrite:
        raise DecompressionError(f"O arquivo de saída já existe: {output_path}")

    started = time.perf_counter()

    root = build_tree(metadata.freqs)

    try:
        intermediate = decode_bytes(
            metadata.payload, metadata.bits_len, root
        )
    except HuffmanError as exc:
        raise DecompressionError(f"Falha ao decodificar Huffman: {exc}") from exc

    if metadata.strategy == ff.STRATEGY_HUFFMAN:
        data = intermediate
        if len(data) != metadata.original_size:
            raise DecompressionError(
                "Tamanho recuperado diferente do informado no cabeçalho."
            )
    elif metadata.strategy == ff.STRATEGY_LZ77_HUFFMAN:
        if len(intermediate) != metadata.intermediate_size:
            raise DecompressionError(
                "Tamanho dos dados intermediários diferente do cabeçalho."
            )

        try:
            tokens = lz77.deserialize_tokens(intermediate)
            data = lz77.decompress(tokens, expected_size=metadata.original_size)
        except lz77.LZ77Error as exc:
            raise DecompressionError(f"Falha ao descompactar LZ77: {exc}") from exc
    else:  # pragma: no cover - já validado no parser
        raise DecompressionError(
            f"Estratégia de compactação desconhecida: {metadata.strategy}"
        )

    if len(data) != metadata.original_size:
        raise DecompressionError(
            f"Tamanho recuperado ({len(data)}) diferente do original "
            f"({metadata.original_size})."
        )

    sha_actual = hashlib.sha256(data).digest()
    integrity_ok = hmac.compare_digest(sha_actual, metadata.sha256)

    if not integrity_ok:
        raise DecompressionError(
            "Falha na verificação de integridade (SHA-256 não confere). "
            "O arquivo pode estar corrompido."
        )

    try:
        output_path.write_bytes(data)
    except OSError as exc:
        raise DecompressionError(
            f"Não foi possível salvar o arquivo recuperado: {exc}"
        ) from exc

    elapsed = time.perf_counter() - started

    return DecompressionResult(
        compressed_path=compressed_path,
        output_path=output_path,
        original_name=metadata.original_name,
        strategy_code=metadata.strategy,
        original_size=metadata.original_size,
        recovered_size=len(data),
        integrity_ok=integrity_ok,
        sha_expected=metadata.sha256,
        sha_actual=sha_actual,
        elapsed=elapsed,
        root=root,
        freqs=metadata.freqs,
        bits_len=metadata.bits_len,
        intermediate_size=metadata.intermediate_size,
        payload_size=len(metadata.payload),
    )
