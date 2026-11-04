"""Definição e leitura/escrita do formato binário ``.huff``.

Estrutura do arquivo (little-endian):

+----------------------+-----------------------------------------------+
| Campo                | Tipo / tamanho                                |
+======================+===============================================+
| Assinatura           | 4 bytes: ``HUFF``                             |
| Versão               | uint8 (atualmente 1)                          |
| Estratégia           | uint8: 0 = Huffman, 1 = LZ77 + Huffman        |
| Reservado (flags)    | uint16                                        |
| Janela LZ77          | uint32                                        |
| Comprimento máx. LZ  | uint32                                        |
| Comprimento mín. LZ  | uint16                                        |
| Tamanho original     | uint64 (bytes do arquivo .txt)                |
| Tamanho intermediário| uint64 (bytes após LZ77; 0 no modo Huffman)   |
| Bits codificados     | uint64 (bits reais, sem preenchimento)        |
| Nº de símbolos       | uint32 (entradas na tabela de frequências)    |
| Tam. nome original   | uint16                                        |
+----------------------+-----------------------------------------------+
| Nome original        | ``name_len`` bytes em UTF-8                   |
| Hash SHA-256         | 32 bytes                                      |
| Tabela de frequências| ``symbol_count`` × (uint8 símbolo + varint)   |
| Dados empacotados    | ``ceil(bits_len / 8)`` bytes                  |
+----------------------+-----------------------------------------------+

As frequências usam varint (LEB128) para reduzir o cabeçalho em arquivos com
muitos símbolos distintos, como acontece no modo híbrido.

A árvore de Huffman não é armazenada: ela é reconstruída a partir das
frequências, usando o mesmo critério determinístico de desempate.
"""

from __future__ import annotations

import struct
from dataclasses import dataclass, field
from typing import Dict

MAGIC = b"HUFF"
VERSION = 1

STRATEGY_HUFFMAN = 0
STRATEGY_LZ77_HUFFMAN = 1

STRATEGY_NAMES = {
    STRATEGY_HUFFMAN: "Huffman",
    STRATEGY_LZ77_HUFFMAN: "LZ77 + Huffman",
}

# 4s  B  B  H  I  I  H  Q  Q  Q  I  H
_FIXED_HEADER = struct.Struct("<4sBBHIIHQQQIH")
HASH_SIZE = 32
MAX_NAME_LENGTH = 65535
MAX_SYMBOLS = 256


class HuffFormatError(Exception):
    """Arquivo ``.huff`` inválido, incompleto ou incompatível."""


@dataclass
class HuffFile:
    """Representação em memória de um arquivo ``.huff`` já validado."""

    strategy: int
    original_size: int
    intermediate_size: int
    bits_len: int
    original_name: str
    sha256: bytes
    freqs: Dict[int, int] = field(default_factory=dict)
    payload: bytes = b""
    lz_window: int = 0
    lz_min_match: int = 0
    lz_max_match: int = 0
    version: int = VERSION

    @property
    def strategy_name(self) -> str:
        return STRATEGY_NAMES.get(self.strategy, "Desconhecida")

    @property
    def encoded_data_size(self) -> int:
        """Quantidade de bytes que passaram pelo Huffman."""

        if self.strategy == STRATEGY_LZ77_HUFFMAN:
            return self.intermediate_size
        return self.original_size

    @property
    def payload_size(self) -> int:
        return len(self.payload)


def strategy_name(strategy: int) -> str:
    return STRATEGY_NAMES.get(strategy, "Desconhecida")


def _encode_varint(value: int) -> bytes:
    output = bytearray()
    while True:
        byte = value & 0x7F
        value >>= 7
        if value:
            output.append(byte | 0x80)
        else:
            output.append(byte)
            return bytes(output)


def _decode_varint(data: bytes, offset: int) -> tuple[int, int]:
    result = 0
    shift = 0
    while True:
        if offset >= len(data):
            raise HuffFormatError("Tabela de frequências truncada (varint).")
        byte = data[offset]
        offset += 1
        result |= (byte & 0x7F) << shift
        if not (byte & 0x80):
            return result, offset
        shift += 7
        if shift > 63:
            raise HuffFormatError("Frequência inválida (varint muito grande).")


def build_huff_bytes(
    *,
    strategy: int,
    original_size: int,
    intermediate_size: int,
    bits_len: int,
    original_name: str,
    sha256: bytes,
    freqs: Dict[int, int],
    payload: bytes,
    lz_window: int = 0,
    lz_min_match: int = 0,
    lz_max_match: int = 0,
) -> bytes:
    """Monta o conteúdo binário completo de um arquivo ``.huff``."""

    if strategy not in STRATEGY_NAMES:
        raise HuffFormatError("Estratégia de compactação inválida.")

    if original_size < 0 or intermediate_size < 0 or bits_len < 0:
        raise HuffFormatError("Tamanhos não podem ser negativos.")

    if len(sha256) != HASH_SIZE:
        raise HuffFormatError("Hash SHA-256 deve ter 32 bytes.")

    if len(freqs) > MAX_SYMBOLS:
        raise HuffFormatError("Tabela de frequências excede 256 símbolos.")

    expected_payload = (bits_len + 7) // 8
    if len(payload) != expected_payload:
        raise HuffFormatError(
            "Tamanho dos dados empacotados não corresponde à quantidade de bits."
        )

    name_bytes = original_name.encode("utf-8")
    if len(name_bytes) > MAX_NAME_LENGTH:
        raise HuffFormatError("Nome do arquivo original é muito longo.")

    for symbol, freq in freqs.items():
        if not (0 <= symbol <= 255):
            raise HuffFormatError("Símbolo fora do intervalo de um byte.")
        if freq <= 0:
            raise HuffFormatError("Frequência deve ser positiva.")

    parts = [
        _FIXED_HEADER.pack(
            MAGIC,
            VERSION,
            strategy,
            0,
            lz_window,
            lz_max_match,
            lz_min_match,
            original_size,
            intermediate_size,
            bits_len,
            len(freqs),
            len(name_bytes),
        ),
        name_bytes,
        sha256,
    ]

    for symbol in sorted(freqs):
        parts.append(bytes([symbol]))
        parts.append(_encode_varint(freqs[symbol]))

    parts.append(payload)

    return b"".join(parts)


def parse_huff_bytes(data: bytes) -> HuffFile:
    """Valida e interpreta o conteúdo binário de um arquivo ``.huff``."""

    if len(data) < _FIXED_HEADER.size + HASH_SIZE:
        raise HuffFormatError("Arquivo muito pequeno para ser um .huff válido.")

    (
        magic,
        version,
        strategy,
        _flags,
        lz_window,
        lz_max_match,
        lz_min_match,
        original_size,
        intermediate_size,
        bits_len,
        symbol_count,
        name_length,
    ) = _FIXED_HEADER.unpack_from(data, 0)

    if magic != MAGIC:
        raise HuffFormatError(
            "Assinatura inválida: o arquivo não parece ter sido gerado por este "
            "programa."
        )

    if version != VERSION:
        raise HuffFormatError(
            f"Versão de formato não suportada: {version} (esperado {VERSION})."
        )

    if strategy not in STRATEGY_NAMES:
        raise HuffFormatError(f"Estratégia desconhecida: {strategy}.")

    if symbol_count > MAX_SYMBOLS:
        raise HuffFormatError("Quantidade de símbolos inválida.")

    offset = _FIXED_HEADER.size

    if offset + name_length > len(data):
        raise HuffFormatError("Nome original truncado.")

    name_bytes = data[offset : offset + name_length]
    offset += name_length

    try:
        original_name = name_bytes.decode("utf-8")
    except UnicodeDecodeError as exc:
        raise HuffFormatError("Nome original não está em UTF-8 válido.") from exc

    if offset + HASH_SIZE > len(data):
        raise HuffFormatError("Hash SHA-256 truncado.")

    sha256 = data[offset : offset + HASH_SIZE]
    offset += HASH_SIZE

    freqs: Dict[int, int] = {}
    for _ in range(symbol_count):
        if offset >= len(data):
            raise HuffFormatError("Tabela de frequências truncada.")
        symbol = data[offset]
        offset += 1
        freq, offset = _decode_varint(data, offset)
        if symbol in freqs:
            raise HuffFormatError("Símbolo duplicado na tabela de frequências.")
        if freq <= 0:
            raise HuffFormatError("Frequência inválida na tabela.")
        freqs[symbol] = freq

    payload = data[offset:]

    expected_payload = (bits_len + 7) // 8
    if len(payload) != expected_payload:
        raise HuffFormatError(
            "Tamanho dos dados compactados não corresponde ao cabeçalho."
        )

    total_freq = sum(freqs.values())
    expected_total = (
        intermediate_size
        if strategy == STRATEGY_LZ77_HUFFMAN
        else original_size
    )
    if total_freq != expected_total:
        raise HuffFormatError(
            "Metadados inconsistentes: soma das frequências diferente do tamanho "
            "esperado."
        )

    if symbol_count == 0 and bits_len != 0:
        raise HuffFormatError("Arquivo sem símbolos, mas com bits codificados.")

    if strategy == STRATEGY_LZ77_HUFFMAN and intermediate_size > 0 and not freqs:
        raise HuffFormatError("Dados intermediários sem tabela de frequências.")

    return HuffFile(
        strategy=strategy,
        original_size=original_size,
        intermediate_size=intermediate_size,
        bits_len=bits_len,
        original_name=original_name,
        sha256=sha256,
        freqs=freqs,
        payload=payload,
        lz_window=lz_window,
        lz_min_match=lz_min_match,
        lz_max_match=lz_max_match,
        version=version,
    )


def read_huff_file(path) -> HuffFile:
    """Lê e valida um arquivo ``.huff`` do disco."""

    try:
        data = path.read_bytes()
    except OSError as exc:
        raise HuffFormatError(f"Não foi possível ler o arquivo: {exc}") from exc

    return parse_huff_bytes(data)
