"""Testes automatizados dos algoritmos e do formato .huff.

Execute na raiz do projeto:

    python -m unittest discover -s tests -v
"""

from __future__ import annotations

import hashlib
import tempfile
import unittest
from pathlib import Path

import compressor
import decompressor
import file_format as ff
import lz77
from huffman import (
    build_tree,
    count_frequencies,
    decode_bytes,
    encode_bytes,
    generate_codes,
)


SAMPLES = {
    "simples": b"ABRACADABRA",
    "repeticoes": b"AAAAAAAAAABBBBBCCCCDD",
    "acentuado": (
        "Olá, mundo!\nEstamos estudando Grafos e o algoritmo de Huffman.\n"
    ).encode("utf-8"),
    "vazio": b"",
    "um_simbolo": b"A" * 20,
    "todos_os_bytes": bytes(range(256)) * 3,
    "sobreposto": b"ABABABABABABABABABAB",
}


class TestHuffman(unittest.TestCase):
    def test_frequencias(self):
        freqs = count_frequencies(b"ABRACADABRA")
        self.assertEqual(freqs[ord("A")], 5)
        self.assertEqual(freqs[ord("B")], 2)
        self.assertEqual(freqs[ord("R")], 2)
        self.assertEqual(freqs[ord("C")], 1)
        self.assertEqual(freqs[ord("D")], 1)

    def test_todos_os_simbolos_tem_codigo(self):
        data = SAMPLES["acentuado"]
        root = build_tree(count_frequencies(data))
        codes = generate_codes(root)
        self.assertEqual(set(codes), set(data))

    def test_codigos_livres_de_prefixo(self):
        root = build_tree(count_frequencies(SAMPLES["simples"]))
        codes = generate_codes(root)
        code_list = list(codes.values())
        for i, first in enumerate(code_list):
            for j, second in enumerate(code_list):
                if i != j:
                    self.assertFalse(
                        second.startswith(first),
                        f"{first!r} é prefixo de {second!r}",
                    )

    def test_ida_e_volta(self):
        for name, data in SAMPLES.items():
            with self.subTest(name=name):
                root = build_tree(count_frequencies(data))
                codes = generate_codes(root)
                packed, bits_len = encode_bytes(data, codes)
                self.assertEqual(bits_len, sum(len(codes[b]) for b in data))
                recovered = decode_bytes(packed, bits_len, root)
                self.assertEqual(recovered, data)

    def test_arvore_deterministica(self):
        freqs_a = {ord(c): i + 1 for i, c in enumerate("ABRACADABRA")}
        freqs_b = dict(reversed(list(freqs_a.items())))
        codes_a = generate_codes(build_tree(freqs_a))
        codes_b = generate_codes(build_tree(freqs_b))
        self.assertEqual(codes_a, codes_b)

    def test_arquivo_vazio(self):
        root = build_tree({})
        self.assertIsNone(root)
        packed, bits_len = encode_bytes(b"", {})
        self.assertEqual(packed, b"")
        self.assertEqual(bits_len, 0)
        self.assertEqual(decode_bytes(packed, bits_len, root), b"")

    def test_bits_incompletos(self):
        data = SAMPLES["simples"]
        root = build_tree(count_frequencies(data))
        codes = generate_codes(root)
        packed, bits_len = encode_bytes(data, codes)
        with self.assertRaises(Exception):
            decode_bytes(packed[: max(0, len(packed) - 1)], bits_len, root)


class TestLZ77(unittest.TestCase):
    def test_ida_e_volta(self):
        for name, data in SAMPLES.items():
            with self.subTest(name=name):
                tokens = lz77.compress(data)
                self.assertEqual(lz77.decompress(tokens), data)

    def test_referencias_sobrepostas(self):
        data = b"A" * 100
        tokens = lz77.compress(data, min_match=3)
        self.assertTrue(any(token[0] == "R" for token in tokens))
        self.assertEqual(lz77.decompress(tokens), data)

    def test_serializacao(self):
        for name, data in SAMPLES.items():
            with self.subTest(name=name):
                tokens = lz77.compress(data)
                serialized = lz77.serialize_tokens(tokens)
                parsed = lz77.deserialize_tokens(serialized)
                self.assertEqual(parsed, tokens)
                self.assertEqual(lz77.decompress(parsed), data)

    def test_varint(self):
        for value in (0, 1, 127, 128, 300, 32768, 2**32):
            encoded = lz77.encode_varint(value)
            decoded, offset = lz77.decode_varint(encoded, 0)
            self.assertEqual(decoded, value)
            self.assertEqual(offset, len(encoded))

    def test_referencia_invalida(self):
        with self.assertRaises(lz77.LZ77Error):
            lz77.decompress([("R", 5, 3)])

    def test_tag_invalida(self):
        with self.assertRaises(lz77.LZ77Error):
            lz77.deserialize_tokens(b"\x02\x00")

    def test_estatisticas(self):
        tokens = lz77.compress(b"ABCABCABCABC")
        stats = lz77.token_stats(tokens)
        self.assertEqual(stats["tokens"], len(tokens))
        self.assertEqual(
            stats["literals"] + stats["references"], stats["tokens"]
        )


class TestFileFormat(unittest.TestCase):
    def _build(self, data: bytes) -> bytes:
        freqs = count_frequencies(data)
        root = build_tree(freqs)
        codes = generate_codes(root)
        payload, bits_len = encode_bytes(data, codes)
        return ff.build_huff_bytes(
            strategy=ff.STRATEGY_HUFFMAN,
            original_size=len(data),
            intermediate_size=0,
            bits_len=bits_len,
            original_name="teste.txt",
            sha256=hashlib.sha256(data).digest(),
            freqs=freqs,
            payload=payload,
        )

    def test_ida_e_volta(self):
        raw = self._build(SAMPLES["simples"])
        parsed = ff.parse_huff_bytes(bytes(raw))
        self.assertEqual(parsed.original_name, "teste.txt")
        self.assertEqual(parsed.original_size, len(SAMPLES["simples"]))
        self.assertEqual(parsed.strategy, ff.STRATEGY_HUFFMAN)
        self.assertEqual(parsed.freqs, count_frequencies(SAMPLES["simples"]))

    def test_assinatura_invalida(self):
        raw = bytearray(self._build(SAMPLES["simples"]))
        raw[0:4] = b"XXXX"
        with self.assertRaises(ff.HuffFormatError):
            ff.parse_huff_bytes(bytes(raw))

    def test_arquivo_truncado(self):
        raw = self._build(SAMPLES["simples"])
        with self.assertRaises(ff.HuffFormatError):
            ff.parse_huff_bytes(raw[:20])

    def test_payload_incompativel(self):
        raw = bytearray(self._build(SAMPLES["simples"]))
        raw[-1] = (raw[-1] + 1) & 0xFF
        with self.assertRaises(ff.HuffFormatError):
            ff.parse_huff_bytes(bytes(raw[:-1]))


class TestIntegracao(unittest.TestCase):
    def setUp(self):
        self._tempdir = tempfile.TemporaryDirectory()
        self.temp = Path(self._tempdir.name)

    def tearDown(self):
        self._tempdir.cleanup()

    def _write(self, name: str, data: bytes) -> Path:
        path = self.temp / name
        path.write_bytes(data)
        return path

    def test_todas_as_estrategias(self):
        for sample_name, data in SAMPLES.items():
            for strategy in (
                compressor.STRATEGY_HUFFMAN,
                compressor.STRATEGY_HYBRID,
                compressor.STRATEGY_AUTO,
            ):
                with self.subTest(sample=sample_name, strategy=strategy):
                    source = self._write(f"{sample_name}.txt", data)

                    result = compressor.compress_file(
                        source, strategy=strategy
                    )

                    self.assertTrue(result.output_path.exists())
                    self.assertEqual(
                        result.compressed_size,
                        result.output_path.stat().st_size,
                    )

                    output = self.temp / f"{sample_name}_{strategy}_out.txt"
                    restored = decompressor.decompress_file(
                        result.output_path, output
                    )

                    self.assertTrue(restored.integrity_ok)
                    self.assertEqual(restored.recovered_size, len(data))
                    self.assertEqual(output.read_bytes(), data)
                    self.assertEqual(
                        hashlib.sha256(data).digest(), restored.sha_actual
                    )

    def test_automatico_escolhe_menor(self):
        data = SAMPLES["repeticoes"] * 20
        source = self._write("auto.txt", data)

        result = compressor.compress_file(
            source, strategy=compressor.STRATEGY_AUTO
        )

        self.assertIsNotNone(result.comparison)
        comparison = result.comparison or {}
        huffman_value = comparison.get("huffman")
        hybrid_value = comparison.get("hybrid")
        assert isinstance(huffman_value, int)
        assert isinstance(hybrid_value, int)
        huffman_size = huffman_value
        hybrid_size = hybrid_value

        self.assertEqual(
            result.compressed_size, min(huffman_size, hybrid_size)
        )
        self.assertEqual(
            result.compressed_size, result.output_path.stat().st_size
        )

    def test_hash_e_tamanho_no_cabecalho(self):
        data = SAMPLES["acentuado"]
        source = self._write("hash.txt", data)
        result = compressor.compress_file(source, strategy=compressor.STRATEGY_HUFFMAN)

        metadata = ff.parse_huff_bytes(result.output_path.read_bytes())
        self.assertEqual(metadata.original_size, len(data))
        self.assertEqual(metadata.sha256, hashlib.sha256(data).digest())
        self.assertEqual(metadata.original_name, "hash.txt")

    def test_arquivo_corrompido_falha(self):
        data = SAMPLES["simples"] * 4
        source = self._write("corromper.txt", data)
        result = compressor.compress_file(
            source, strategy=compressor.STRATEGY_HUFFMAN
        )

        raw = bytearray(result.output_path.read_bytes())
        metadata = ff.parse_huff_bytes(bytes(raw))
        payload_start = len(raw) - len(metadata.payload)
        raw[payload_start] ^= 0xFF

        corrupted = self.temp / "corrompido.huff"
        corrupted.write_bytes(bytes(raw))

        with self.assertRaises(decompressor.DecompressionError):
            decompressor.decompress_file(corrupted, self.temp / "saida.txt")

    def test_metadados_invalidos(self):
        source = self._write("ok.txt", b"conteudo")
        result = compressor.compress_file(source, strategy=compressor.STRATEGY_HUFFMAN)
        raw = bytearray(result.output_path.read_bytes())
        raw[0:4] = b"NOPE"
        invalid = self.temp / "invalido.huff"
        invalid.write_bytes(bytes(raw))

        with self.assertRaises(decompressor.DecompressionError):
            decompressor.read_metadata(invalid)

    def test_nome_padrao_compactado(self):
        source = self._write("documento.txt", b"abc")
        result = compressor.compress_file(source, strategy=compressor.STRATEGY_HUFFMAN)
        self.assertEqual(result.output_path.name, "documento.huff")

    def test_nome_de_saida_padrao(self):
        source = self._write("documento.txt", b"abc")
        result = compressor.compress_file(source, strategy=compressor.STRATEGY_HUFFMAN)

        first = decompressor.default_output_path(result.output_path, "documento.txt")
        self.assertEqual(first.name, "documento_descompactado.txt")

        first.write_bytes(b"x")
        second = decompressor.default_output_path(result.output_path, "documento.txt")
        self.assertNotEqual(first, second)

    def test_estrategia_detectada(self):
        data = SAMPLES["repeticoes"] * 10
        source = self._write("detect.txt", data)

        for strategy, expected in (
            (compressor.STRATEGY_HUFFMAN, ff.STRATEGY_HUFFMAN),
            (compressor.STRATEGY_HYBRID, ff.STRATEGY_LZ77_HUFFMAN),
        ):
            with self.subTest(strategy=strategy):
                result = compressor.compress_file(source, strategy=strategy)
                metadata = decompressor.read_metadata(result.output_path)
                self.assertEqual(metadata.strategy, expected)


if __name__ == "__main__":
    unittest.main(verbosity=2)
