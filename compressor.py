"""Integração dos algoritmos e geração dos arquivos ``.huff``.

Responsabilidades:

- aplicar Huffman puro, LZ77 + Huffman ou escolher automaticamente o menor;
- montar o arquivo completo (cabeçalho + metadados + dados);
- devolver informações para a interface (árvore, códigos, estatísticas).
"""

from __future__ import annotations

import hashlib
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Dict, Optional

import file_format as ff
import lz77
from huffman import (
    Node,
    build_tree,
    count_frequencies,
    encode_bytes,
    generate_codes,
)

STRATEGY_HUFFMAN = "huffman"
STRATEGY_HYBRID = "hybrid"
STRATEGY_AUTO = "auto"

STRATEGY_LABELS = {
    STRATEGY_HUFFMAN: "Huffman",
    STRATEGY_HYBRID: "LZ77 + Huffman",
    STRATEGY_AUTO: "Automático",
}


class CompressionError(Exception):
    """Erro durante a compactação."""


@dataclass
class LZ77Parameters:
    window: int = lz77.DEFAULT_WINDOW
    min_match: int = lz77.DEFAULT_MIN_MATCH
    max_match: int = lz77.DEFAULT_MAX_MATCH
    max_chain: int = lz77.DEFAULT_MAX_CHAIN


@dataclass
class BuildInfo:
    """Resultado interno de uma estratégia de compactação."""

    strategy_code: int
    payload: bytes
    bits_len: int
    freqs: Dict[int, int]
    root: Optional[Node]
    codes: Dict[int, str]
    intermediate_size: int
    intermediate: bytes = b""
    lz_stats: Optional[dict] = None
    data_for_tree: bytes = b""

    @property
    def strategy_name(self) -> str:
        return ff.strategy_name(self.strategy_code)


@dataclass
class CompressionResult:
    input_path: Path
    output_path: Path
    original_name: str
    original_size: int
    compressed_size: int
    strategy_code: int
    root: Optional[Node]
    freqs: Dict[int, int]
    codes: Dict[int, str]
    bits_len: int
    intermediate_size: int
    elapsed: float
    lz_params: LZ77Parameters
    lz_stats: Optional[dict] = None
    comparison: Optional[Dict[str, object]] = None
    intermediate: bytes = b""

    @property
    def strategy_name(self) -> str:
        return ff.strategy_name(self.strategy_code)

    @property
    def saved_bytes(self) -> int:
        return self.original_size - self.compressed_size

    @property
    def compression_ratio(self) -> float:
        """Tamanho original / tamanho compactado."""

        if self.compressed_size == 0:
            return 0.0
        return self.original_size / self.compressed_size

    @property
    def reduction_percent(self) -> float:
        if self.original_size == 0:
            return 0.0
        return (self.saved_bytes / self.original_size) * 100.0

    @property
    def grew(self) -> bool:
        return self.compressed_size > self.original_size


def _build_huffman(data: bytes) -> BuildInfo:
    freqs = count_frequencies(data)
    root = build_tree(freqs)
    codes = generate_codes(root)
    payload, bits_len = encode_bytes(data, codes)

    return BuildInfo(
        strategy_code=ff.STRATEGY_HUFFMAN,
        payload=payload,
        bits_len=bits_len,
        freqs=freqs,
        root=root,
        codes=codes,
        intermediate_size=0,
        data_for_tree=data,
    )


def _build_hybrid(data: bytes, params: LZ77Parameters) -> BuildInfo:
    tokens = lz77.compress(
        data,
        window=params.window,
        min_match=params.min_match,
        max_match=params.max_match,
        max_chain=params.max_chain,
    )
    intermediate = lz77.serialize_tokens(tokens)
    stats = lz77.token_stats(tokens)

    freqs = count_frequencies(intermediate)
    root = build_tree(freqs)
    codes = generate_codes(root)
    payload, bits_len = encode_bytes(intermediate, codes)

    return BuildInfo(
        strategy_code=ff.STRATEGY_LZ77_HUFFMAN,
        payload=payload,
        bits_len=bits_len,
        freqs=freqs,
        root=root,
        codes=codes,
        intermediate_size=len(intermediate),
        intermediate=intermediate,
        lz_stats=stats,
        data_for_tree=intermediate,
    )


def _assemble_file(
    data: bytes,
    original_name: str,
    info: BuildInfo,
    params: LZ77Parameters,
) -> bytes:
    sha256 = hashlib.sha256(data).digest()

    return ff.build_huff_bytes(
        strategy=info.strategy_code,
        original_size=len(data),
        intermediate_size=info.intermediate_size,
        bits_len=info.bits_len,
        original_name=original_name,
        sha256=sha256,
        freqs=info.freqs,
        payload=info.payload,
        lz_window=params.window if info.strategy_code == ff.STRATEGY_LZ77_HUFFMAN else 0,
        lz_min_match=params.min_match if info.strategy_code == ff.STRATEGY_LZ77_HUFFMAN else 0,
        lz_max_match=params.max_match if info.strategy_code == ff.STRATEGY_LZ77_HUFFMAN else 0,
    )


def compress_data(
    data: bytes,
    original_name: str,
    strategy: str = STRATEGY_AUTO,
    params: Optional[LZ77Parameters] = None,
) -> tuple[bytes, BuildInfo, Optional[Dict[str, object]]]:
    """Compacta ``data`` e devolve ``(arquivo, info, comparação)``.

    ``comparação`` só é preenchida no modo automático.
    """

    if params is None:
        params = LZ77Parameters()

    if strategy == STRATEGY_HUFFMAN:
        info = _build_huffman(data)
        return _assemble_file(data, original_name, info, params), info, None

    if strategy == STRATEGY_HYBRID:
        info = _build_hybrid(data, params)
        return _assemble_file(data, original_name, info, params), info, None

    if strategy != STRATEGY_AUTO:
        raise CompressionError(f"Estratégia desconhecida: {strategy!r}")

    huffman_info = _build_huffman(data)
    huffman_file = _assemble_file(data, original_name, huffman_info, params)

    hybrid_info = _build_hybrid(data, params)
    hybrid_file = _assemble_file(data, original_name, hybrid_info, params)

    comparison: Dict[str, object] = {
        "huffman": len(huffman_file),
        "hybrid": len(hybrid_file),
    }

    if len(hybrid_file) < len(huffman_file):
        comparison["selected"] = STRATEGY_HYBRID
        return hybrid_file, hybrid_info, comparison

    comparison["selected"] = STRATEGY_HUFFMAN
    return huffman_file, huffman_info, comparison


def compress_file(
    input_path,
    strategy: str = STRATEGY_AUTO,
    output_path=None,
    *,
    overwrite: bool = True,
    params: Optional[LZ77Parameters] = None,
) -> CompressionResult:
    """Lê ``input_path``, compacta e grava o arquivo ``.huff``."""

    input_path = Path(input_path)
    if params is None:
        params = LZ77Parameters()

    if not input_path.exists():
        raise CompressionError(f"Arquivo não encontrado: {input_path}")

    if not input_path.is_file():
        raise CompressionError(f"O caminho não é um arquivo: {input_path}")

    try:
        data = input_path.read_bytes()
    except OSError as exc:
        raise CompressionError(f"Não foi possível ler o arquivo: {exc}") from exc

    output_path = Path(output_path) if output_path else input_path.with_suffix(".huff")

    try:
        same_file = output_path.resolve() == input_path.resolve()
    except OSError:
        same_file = False
    if same_file:
        raise CompressionError(
            "O arquivo de saída não pode ser o mesmo do arquivo original."
        )

    if output_path.exists() and not overwrite:
        raise CompressionError(f"O arquivo de saída já existe: {output_path}")

    started = time.perf_counter()
    file_bytes, info, comparison = compress_data(
        data, input_path.name, strategy, params
    )
    elapsed = time.perf_counter() - started

    try:
        output_path.write_bytes(file_bytes)
    except OSError as exc:
        raise CompressionError(f"Não foi possível salvar o arquivo: {exc}") from exc

    return CompressionResult(
        input_path=input_path,
        output_path=output_path,
        original_name=input_path.name,
        original_size=len(data),
        compressed_size=len(file_bytes),
        strategy_code=info.strategy_code,
        root=info.root,
        freqs=info.freqs,
        codes=info.codes,
        bits_len=info.bits_len,
        intermediate_size=info.intermediate_size,
        elapsed=elapsed,
        lz_params=params,
        lz_stats=info.lz_stats,
        comparison=comparison,
        intermediate=info.intermediate,
    )
