"""Implementação manual do algoritmo LZ77 (janela deslizante).

A saída é uma lista de tokens:

- ``("L", byte)``                  -> símbolo literal;
- ``("R", distancia, comprimento)`` -> referência a uma ocorrência anterior.

As referências sobrepostas são permitidas: durante a descompactação os bytes
são copiados um a um, de modo que uma referência pode apontar para bytes que
estão sendo produzidos naquele mesmo momento.

A busca usa correntes de hash sobre trigramas (3 bytes) para não varrer a
janela inteira em cada posição. Todos os parâmetros são configuráveis.
"""

from __future__ import annotations

from typing import Iterable, List, Tuple

Token = Tuple
# Tipos de token:
#   ("L", byte)
#   ("R", distancia, comprimento)

DEFAULT_WINDOW = 32 * 1024
DEFAULT_MIN_MATCH = 3
DEFAULT_MAX_MATCH = 258
DEFAULT_MAX_CHAIN = 64

LITERAL_TAG = 0
REFERENCE_TAG = 1


class LZ77Error(Exception):
    """Erro na compressão/descompactação LZ77."""


def compress(
    data: bytes,
    window: int = DEFAULT_WINDOW,
    min_match: int = DEFAULT_MIN_MATCH,
    max_match: int = DEFAULT_MAX_MATCH,
    max_chain: int = DEFAULT_MAX_CHAIN,
) -> List[Token]:
    """Compacta ``data`` e devolve a lista de tokens LZ77."""

    if window < 1:
        raise LZ77Error("A janela deve ser maior que zero.")
    if min_match < 1:
        raise LZ77Error("O comprimento mínimo deve ser maior que zero.")
    if max_match < min_match:
        raise LZ77Error("O comprimento máximo deve ser >= comprimento mínimo.")

    n = len(data)
    if n == 0:
        return []

    tokens: List[Token] = []
    head: dict[bytes, int] = {}
    prev = [-1] * n

    i = 0
    while i < n:
        best_length = 0
        best_distance = 0

        if i + 3 <= n:
            key = data[i : i + 3]
            candidate = head.get(key, -1)
            chain = 0
            limit = min(max_match, n - i)

            while (
                candidate != -1
                and (i - candidate) <= window
                and chain < max_chain
            ):
                chain += 1

                # Verificação rápida antes de comparar o trecho inteiro.
                if (
                    best_length < limit
                    and data[candidate + best_length] == data[i + best_length]
                ):
                    length = 0
                    while length < limit and data[candidate + length] == data[i + length]:
                        length += 1

                    if length > best_length:
                        best_length = length
                        best_distance = i - candidate
                        if length >= limit:
                            break

                candidate = prev[candidate]

        if best_length >= min_match:
            tokens.append(("R", best_distance, best_length))
            end = i + best_length
            for position in range(i, end):
                if position + 3 <= n:
                    key = data[position : position + 3]
                    prev[position] = head.get(key, -1)
                    head[key] = position
            i = end
        else:
            tokens.append(("L", data[i]))
            if i + 3 <= n:
                key = data[i : i + 3]
                prev[i] = head.get(key, -1)
                head[key] = i
            i += 1

    return tokens


def decompress(tokens: Iterable[Token], expected_size: int | None = None) -> bytes:
    """Reconstrói os dados originais a partir dos tokens LZ77."""

    output = bytearray()

    for token in tokens:
        if not token:
            raise LZ77Error("Token LZ77 vazio.")

        kind = token[0]

        if kind == "L":
            if len(token) != 2:
                raise LZ77Error("Token literal malformado.")
            value = token[1]
            if not isinstance(value, int) or not (0 <= value <= 255):
                raise LZ77Error("Literal fora do intervalo de um byte.")
            output.append(value)

        elif kind == "R":
            if len(token) != 3:
                raise LZ77Error("Token de referência malformado.")
            distance = token[1]
            length = token[2]
            if not isinstance(distance, int) or not isinstance(length, int):
                raise LZ77Error("Referência com valores não inteiros.")
            if distance < 1 or length < 1:
                raise LZ77Error("Referência com distância/comprimento inválidos.")
            if distance > len(output):
                raise LZ77Error(
                    "Referência LZ77 inválida: distância maior que os dados já "
                    "produzidos."
                )

            start = len(output) - distance
            for offset in range(length):
                output.append(output[start + offset])

        else:
            raise LZ77Error(f"Tipo de token desconhecido: {kind!r}")

    if expected_size is not None and len(output) != expected_size:
        raise LZ77Error(
            f"Tamanho reconstruído ({len(output)}) diferente do esperado "
            f"({expected_size})."
        )

    return bytes(output)


def encode_varint(value: int) -> bytes:
    """Codifica um inteiro não negativo em LEB128 (varint)."""

    if value < 0:
        raise LZ77Error("Varint não aceita valores negativos.")

    output = bytearray()
    while True:
        byte = value & 0x7F
        value >>= 7
        if value:
            output.append(byte | 0x80)
        else:
            output.append(byte)
            break
    return bytes(output)


def decode_varint(data: bytes, offset: int) -> tuple[int, int]:
    """Lê um varint de ``data`` a partir de ``offset`` e devolve (valor, novo_offset)."""

    result = 0
    shift = 0

    while True:
        if offset >= len(data):
            raise LZ77Error("Varint incompleto.")
        byte = data[offset]
        offset += 1
        result |= (byte & 0x7F) << shift

        if not (byte & 0x80):
            return result, offset

        shift += 7
        if shift > 63:
            raise LZ77Error("Varint muito grande.")


GROUP_SIZE = 8


def serialize_tokens(tokens: Iterable[Token]) -> bytes:
    """Serializa os tokens para a representação intermediária binária.

    Os tokens são agrupados de 8 em 8. Para cada grupo é gravado um byte de
    controle, no qual o bit ``i`` vale 1 se o ``i``-ésimo token for uma
    referência e 0 se for um literal. Em seguida vêm os dados dos tokens:

    - literal:    1 byte com o valor do símbolo;
    - referência: varint(distância) + varint(comprimento).

    Essa representação é compacta, reversível e preserva a distribuição dos
    bytes literais, o que ajuda o Huffman aplicado na etapa seguinte.
    """

    token_list = list(tokens)
    output = bytearray()

    for start in range(0, len(token_list), GROUP_SIZE):
        group = token_list[start : start + GROUP_SIZE]
        control = 0

        for bit, token in enumerate(group):
            if not token:
                raise LZ77Error("Token LZ77 vazio.")
            kind = token[0]
            if kind == "R":
                if len(token) != 3:
                    raise LZ77Error("Token de referência malformado.")
                distance = token[1]
                length = token[2]
                if not isinstance(distance, int) or not isinstance(length, int):
                    raise LZ77Error("Referência com valores não inteiros.")
                if distance < 1 or length < 1:
                    raise LZ77Error("Referência com distância/comprimento inválidos.")
                control |= 1 << bit
            elif kind == "L":
                if len(token) != 2:
                    raise LZ77Error("Token literal malformado.")
                value = token[1]
                if not isinstance(value, int) or not (0 <= value <= 255):
                    raise LZ77Error("Literal fora do intervalo de um byte.")
            else:
                raise LZ77Error(f"Tipo de token desconhecido: {kind!r}")

        output.append(control)

        for token in group:
            if token[0] == "L":
                output.append(token[1])
            else:
                output.extend(encode_varint(token[1]))
                output.extend(encode_varint(token[2]))

    return bytes(output)


def deserialize_tokens(data: bytes) -> List[Token]:
    """Interpreta a representação intermediária e devolve os tokens."""

    tokens: List[Token] = []
    offset = 0
    size = len(data)

    while offset < size:
        control = data[offset]
        offset += 1

        for bit in range(GROUP_SIZE):
            if offset >= size:
                # Fim dos dados: os bits restantes do grupo devem ser zero.
                remaining_mask = (0xFF << bit) & 0xFF
                if control & remaining_mask:
                    raise LZ77Error(
                        "Representação intermediária truncada ou inconsistente."
                    )
                break

            if control & (1 << bit):
                distance, offset = decode_varint(data, offset)
                length, offset = decode_varint(data, offset)
                if distance < 1 or length < 1:
                    raise LZ77Error(
                        "Referência inválida na representação intermediária."
                    )
                tokens.append(("R", distance, length))
            else:
                tokens.append(("L", data[offset]))
                offset += 1

    return tokens


def token_stats(tokens: Iterable[Token]) -> dict:
    """Estatísticas úteis para a apresentação acadêmica."""

    total = 0
    literals = 0
    references = 0
    matched_bytes = 0

    for token in tokens:
        total += 1
        if token and token[0] == "L":
            literals += 1
        elif token and token[0] == "R":
            references += 1
            matched_bytes += token[2]

    return {
        "tokens": total,
        "literals": literals,
        "references": references,
        "matched_bytes": matched_bytes,
    }
