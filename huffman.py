"""Implementação manual do algoritmo de Huffman.

O módulo não utiliza nenhuma biblioteca de compressão. A árvore é construída
com nós próprios e uma fila de prioridade (``heapq``), exatamente como descrito
na teoria de grafos: cada folha é um símbolo, cada nó interno guarda a soma dos
pesos dos filhos e cada aresta representa um bit (esquerda = 0, direita = 1).
"""

from __future__ import annotations

import heapq
from collections import Counter
from typing import Dict, Optional


class HuffmanError(Exception):
    """Erro de codificação/decodificação Huffman."""


class Node:
    """Nó da árvore binária de Huffman.

    - ``symbol`` é o byte representado quando o nó é folha (``None`` em nós
      internos);
    - ``freq`` é o peso do nó;
    - ``left``/``right`` são as conexões (arestas) para os filhos;
    - ``order`` é um contador usado apenas para desempate determinístico.
    """

    __slots__ = ("symbol", "freq", "left", "right", "order")

    def __init__(
        self,
        symbol: Optional[int] = None,
        freq: int = 0,
        left: Optional["Node"] = None,
        right: Optional["Node"] = None,
        order: int = 0,
    ) -> None:
        self.symbol = symbol
        self.freq = freq
        self.left = left
        self.right = right
        self.order = order

    @property
    def is_leaf(self) -> bool:
        return self.left is None and self.right is None

    def __repr__(self) -> str:  # pragma: no cover - apenas depuração
        kind = f"symbol={self.symbol}" if self.is_leaf else "internal"
        return f"Node({kind}, freq={self.freq})"


def count_frequencies(data: bytes) -> Dict[int, int]:
    """Conta a frequência de cada byte dos dados."""

    return dict(Counter(data))


def build_tree(freqs: Dict[int, int]) -> Optional[Node]:
    """Constrói a árvore de Huffman a partir do dicionário de frequências.

    O critério de desempate é determinístico:

    1. folhas são criadas em ordem crescente de valor do byte;
    2. nós com a mesma frequência são retirados da fila na ordem em que foram
       criados (contador ``order``).

    Como o arquivo ``.huff`` armazena as frequências, a mesma árvore pode ser
    reconstruída na descompactação.
    """

    if not freqs:
        return None

    heap = []
    order = 0

    for symbol in sorted(freqs):
        freq = freqs[symbol]
        if freq <= 0:
            continue
        node = Node(symbol=symbol, freq=freq, order=order)
        heapq.heappush(heap, (freq, order, node))
        order += 1

    if not heap:
        return None

    while len(heap) > 1:
        freq_left, _order_left, left = heapq.heappop(heap)
        freq_right, _order_right, right = heapq.heappop(heap)

        parent = Node(
            symbol=None,
            freq=freq_left + freq_right,
            left=left,
            right=right,
            order=order,
        )
        order += 1
        heapq.heappush(heap, (parent.freq, order, parent))

    return heap[0][2]


def generate_codes(root: Optional[Node]) -> Dict[int, str]:
    """Gera o dicionário ``símbolo -> código binário`` percorrendo a árvore."""

    codes: Dict[int, str] = {}
    if root is None:
        return codes

    if root.is_leaf:
        assert root.symbol is not None
        codes[root.symbol] = "0"
        return codes

    stack = [(root, "")]
    while stack:
        node, prefix = stack.pop()
        if node.is_leaf:
            assert node.symbol is not None
            codes[node.symbol] = prefix or "0"
        else:
            if node.left is not None:
                stack.append((node.left, prefix + "0"))
            if node.right is not None:
                stack.append((node.right, prefix + "1"))

    return codes


def encode_bytes(data: bytes, codes: Dict[int, str]) -> tuple[bytes, int]:
    """Codifica ``data`` usando ``codes`` e empacota os bits em bytes.

    Retorna ``(bytes_empacotados, quantidade_de_bits)``. O último byte pode
    conter bits de preenchimento; por isso a quantidade exata de bits é
    devolvida e deve ser armazenada no cabeçalho do arquivo.
    """

    if not data:
        return b"", 0

    if not codes:
        raise HuffmanError("Não há códigos de Huffman para codificar os dados.")

    pairs = {symbol: (int(code, 2), len(code)) for symbol, code in codes.items()}

    output = bytearray()
    buffer = 0
    buffered_bits = 0
    total_bits = 0

    for byte in data:
        try:
            value, length = pairs[byte]
        except KeyError as exc:  # pragma: no cover - proteção defensiva
            raise HuffmanError(f"Símbolo sem código: 0x{byte:02X}") from exc

        buffer = (buffer << length) | value
        buffered_bits += length
        total_bits += length

        while buffered_bits >= 8:
            buffered_bits -= 8
            output.append((buffer >> buffered_bits) & 0xFF)

        buffer &= (1 << buffered_bits) - 1

    if buffered_bits:
        output.append((buffer << (8 - buffered_bits)) & 0xFF)

    return bytes(output), total_bits


def decode_bytes(packed: bytes, bits_len: int, root: Optional[Node]) -> bytes:
    """Decodifica ``packed`` usando a árvore, lendo exatamente ``bits_len`` bits."""

    if bits_len == 0:
        return b""

    if root is None:
        raise HuffmanError("Árvore de Huffman ausente para dados não vazios.")

    if root.is_leaf:
        # Caso especial: arquivo com um único símbolo distinto.
        assert root.symbol is not None
        return bytes([root.symbol]) * bits_len

    expected_bytes = (bits_len + 7) // 8
    if len(packed) < expected_bytes:
        raise HuffmanError("Sequência de bits incompleta.")

    output = bytearray()
    node = root
    read = 0

    for byte in packed:
        for shift in range(7, -1, -1):
            if read >= bits_len:
                break

            bit = (byte >> shift) & 1
            node = node.right if bit else node.left

            if node is None:
                raise HuffmanError("Sequência de bits inválida para esta árvore.")

            if node.is_leaf:
                assert node.symbol is not None
                output.append(node.symbol)
                node = root

            read += 1

        if read >= bits_len:
            break

    if read != bits_len:
        raise HuffmanError("Sequência de bits incompleta.")

    return bytes(output)


def tree_depth(root: Optional[Node]) -> int:
    """Profundidade da árvore (0 para árvore vazia)."""

    if root is None:
        return 0

    depth = 0
    stack = [(root, 1)]
    while stack:
        node, level = stack.pop()
        depth = max(depth, level)
        if node.left is not None:
            stack.append((node.left, level + 1))
        if node.right is not None:
            stack.append((node.right, level + 1))
    return depth


def leaf_count(root: Optional[Node]) -> int:
    """Quantidade de folhas (símbolos distintos) da árvore."""

    if root is None:
        return 0

    count = 0
    stack = [root]
    while stack:
        node = stack.pop()
        if node.is_leaf:
            count += 1
        else:
            if node.left is not None:
                stack.append(node.left)
            if node.right is not None:
                stack.append(node.right)
    return count
