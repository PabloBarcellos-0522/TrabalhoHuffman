"""Interface gráfica principal (CustomTkinter + tkinterdnd2).

A interface apenas orquestra os módulos de algoritmo. Toda a compactação e
descompactação é feita em uma thread separada para não congelar a janela.
"""

from __future__ import annotations

import os
import queue
import subprocess
import sys
import threading
from pathlib import Path
from tkinter import filedialog, messagebox
from typing import Optional

import customtkinter as ctk

try:  # pragma: no cover - depende do ambiente
    import tkinterdnd2 as _tkdnd
    from tkinterdnd2 import DND_FILES

    DND_AVAILABLE = True
except Exception:  # pragma: no cover
    DND_FILES = None
    _tkdnd = None
    DND_AVAILABLE = False

import compressor
import decompressor
import file_format as ff
from huffman import build_tree
from tree_view import format_symbol, open_tree_window

APP_TITLE = "Compactador de Arquivos — Huffman e LZ77"


def format_size(value: int) -> str:
    """Formata bytes em unidade legível (B, KB, MB, GB)."""

    if value < 1024:
        return f"{value} B"

    number = float(value)
    for unit in ("KB", "MB", "GB"):
        number /= 1024.0
        if number < 1024.0 or unit == "GB":
            return f"{number:.2f} {unit}".replace(".", ",")

    return f"{number:.2f} GB"  # pragma: no cover


def format_int(value: int) -> str:
    return f"{value:,}".replace(",", ".")


def size_line(value: int) -> str:
    return f"{format_size(value)} ({format_int(value)} bytes)"


def _row(label: str, value: str, width: int = 28) -> str:
    return f"{label:<{width}}{value}"


class App(ctk.CTk):
    """Janela principal do compactador."""

    def __init__(self) -> None:
        ctk.set_appearance_mode("dark")
        ctk.set_default_color_theme("blue")
        super().__init__()

        self.TkdndVersion = None
        if DND_AVAILABLE and _tkdnd is not None:
            try:
                self.TkdndVersion = _tkdnd.TkinterDnD._require(self)  # type: ignore[union-attr]
            except Exception:
                self.TkdndVersion = None

        self.title(APP_TITLE)
        self.geometry("1020x920")
        self.minsize(880, 720)

        # Estado da aplicação.
        self.selected_path: Path | None = None
        self.selected_kind: str | None = None  # "txt" | "huff"
        self.metadata: ff.HuffFile | None = None

        self.last_compression: compressor.CompressionResult | None = None
        self.last_decompression: decompressor.DecompressionResult | None = None
        self.last_output_path: Path | None = None

        self.last_tree_root = None
        self.last_tree_strategy: str | None = None
        self.last_tree_desc: str | None = None
        self.last_tree_available = False

        self.busy = False
        self._closing = False
        self._ui_queue: "queue.Queue" = queue.Queue()

        self.dnd_enabled = False

        self._build_ui()
        self._apply_theme()
        self._update_buttons()
        self._set_result_text(
            "Bem-vindo!\n\n"
            "1. Selecione ou arraste um arquivo .txt para compactar.\n"
            "2. Escolha a estratégia (Huffman, LZ77 + Huffman ou Automático).\n"
            "3. Clique em COMPACTAR ARQUIVO.\n\n"
            "Para descompactar, selecione um arquivo .huff gerado pelo programa e "
            "clique em DESCOMPACTAR ARQUIVO.\n\n"
            "Os resultados detalhados aparecerão aqui."
        )

        self.protocol("WM_DELETE_WINDOW", self._on_close)
        self.after(80, self._poll_queue)

    # ------------------------------------------------------------------
    # Construção da interface
    # ------------------------------------------------------------------

    def _build_ui(self) -> None:
        self.grid_columnconfigure(0, weight=1)
        self.grid_rowconfigure(0, weight=1)

        self.scroll = ctk.CTkScrollableFrame(self, fg_color=("gray92", "gray10"))
        self.scroll.grid(row=0, column=0, sticky="nsew")
        self.scroll.grid_columnconfigure(0, weight=1)

        # Cabeçalho -----------------------------------------------------
        header = ctk.CTkFrame(self.scroll, fg_color="transparent")
        header.grid(row=0, column=0, sticky="ew", padx=24, pady=(22, 6))
        header.grid_columnconfigure(0, weight=1)

        ctk.CTkLabel(
            header,
            text="COMPACTADOR DE ARQUIVOS",
            font=ctk.CTkFont(size=26, weight="bold"),
            anchor="w",
        ).grid(row=0, column=0, sticky="w")

        self.theme_var = ctk.StringVar(value="dark")
        ctk.CTkSwitch(
            header,
            text="Tema claro",
            variable=self.theme_var,
            onvalue="light",
            offvalue="dark",
            command=self._apply_theme,
        ).grid(row=0, column=1, sticky="e")

        ctk.CTkLabel(
            header,
            text="Huffman + LZ77",
            font=ctk.CTkFont(size=16, weight="bold"),
            text_color=("#2f6fd0", "#6ea8ff"),
            anchor="w",
        ).grid(row=1, column=0, sticky="w", pady=(2, 0))

        ctk.CTkLabel(
            header,
            text=(
                "Compacte arquivos de texto com Huffman puro, com a combinação "
                "LZ77 + Huffman ou deixe o programa escolher automaticamente a "
                "menor saída. A descompactação recupera o conteúdo original e "
                "confere a integridade por SHA-256."
            ),
            font=ctk.CTkFont(size=12),
            text_color=("#4a4a55", "#b8b8c2"),
            justify="left",
            anchor="w",
            wraplength=900,
        ).grid(row=2, column=0, columnspan=2, sticky="ew", pady=(8, 0))

        # Área de seleção / arrastar e soltar ---------------------------
        drop_card = self._card(row=1, title=None)
        drop_card.grid_columnconfigure(0, weight=1)

        self.drop_frame = ctk.CTkFrame(
            drop_card,
            corner_radius=14,
            border_width=2,
            border_color=("#9aa4b2", "#3a4150"),
            fg_color=("#eef2f7", "#15171c"),
        )
        self.drop_frame.grid(row=0, column=0, sticky="ew", padx=16, pady=16)
        self.drop_frame.grid_columnconfigure(0, weight=1)

        self.drop_title = ctk.CTkLabel(
            self.drop_frame,
            text="Arraste seu arquivo aqui",
            font=ctk.CTkFont(size=17, weight="bold"),
        )
        self.drop_title.grid(row=0, column=0, pady=(20, 2))

        dnd_hint = (
            ".txt para compactar  •  .huff para descompactar"
            if DND_AVAILABLE
            else "Arrastar e soltar indisponível neste ambiente — use o botão abaixo"
        )
        self.drop_hint = ctk.CTkLabel(
            self.drop_frame,
            text=dnd_hint,
            font=ctk.CTkFont(size=12),
            text_color=("#5a5a66", "#a8a8b4"),
        )
        self.drop_hint.grid(row=1, column=0, pady=(0, 10))

        self.btn_select = ctk.CTkButton(
            self.drop_frame,
            text="Selecionar arquivo",
            width=200,
            height=38,
            command=self._select_file,
        )
        self.btn_select.grid(row=2, column=0, pady=(0, 20))

        if DND_AVAILABLE:
            for widget in (
                self.drop_frame,
                self.drop_title,
                self.drop_hint,
                self.btn_select,
            ):
                self._register_dnd(widget)

        # Informações do arquivo ---------------------------------------
        info_card = self._card(row=2, title="Arquivo selecionado")
        self.info_name = self._info_row(info_card, 0, "Nome")
        self.info_path = self._info_row(info_card, 1, "Caminho")
        self.info_size = self._info_row(info_card, 2, "Tamanho")
        self.info_details = self._info_row(info_card, 3, "Detalhes")

        # Estratégia ----------------------------------------------------
        strategy_card = self._card(row=3, title="Estratégia de compactação")
        self.strategy_var = ctk.StringVar(value=compressor.STRATEGY_AUTO)

        ctk.CTkRadioButton(
            strategy_card,
            text="Huffman — aplica somente o algoritmo de Huffman",
            variable=self.strategy_var,
            value=compressor.STRATEGY_HUFFMAN,
        ).grid(row=1, column=0, sticky="w", padx=18, pady=(4, 2))

        ctk.CTkRadioButton(
            strategy_card,
            text="LZ77 + Huffman — substitui repetições por referências e depois aplica Huffman",
            variable=self.strategy_var,
            value=compressor.STRATEGY_HYBRID,
        ).grid(row=2, column=0, sticky="w", padx=18, pady=2)

        ctk.CTkRadioButton(
            strategy_card,
            text="Automático — testa as duas estratégias e escolhe o menor arquivo (recomendado)",
            variable=self.strategy_var,
            value=compressor.STRATEGY_AUTO,
        ).grid(row=3, column=0, sticky="w", padx=18, pady=(2, 16))

        # Ações ---------------------------------------------------------
        actions = ctk.CTkFrame(self.scroll, fg_color="transparent")
        actions.grid(row=4, column=0, sticky="ew", padx=24, pady=(6, 4))
        actions.grid_columnconfigure(0, weight=1)
        actions.grid_columnconfigure(1, weight=1)

        self.btn_compress = ctk.CTkButton(
            actions,
            text="COMPACTAR ARQUIVO",
            height=46,
            font=ctk.CTkFont(size=14, weight="bold"),
            fg_color="#1f9d63",
            hover_color="#178a56",
            command=self._compress,
        )
        self.btn_compress.grid(row=0, column=0, sticky="ew", padx=(0, 6))

        self.btn_decompress = ctk.CTkButton(
            actions,
            text="DESCOMPACTAR ARQUIVO",
            height=46,
            font=ctk.CTkFont(size=14, weight="bold"),
            fg_color="#2f6fd0",
            hover_color="#255db3",
            command=self._decompress,
        )
        self.btn_decompress.grid(row=0, column=1, sticky="ew", padx=(6, 0))

        # Progresso -----------------------------------------------------
        progress_frame = ctk.CTkFrame(self.scroll, fg_color="transparent")
        progress_frame.grid(row=5, column=0, sticky="ew", padx=24, pady=(4, 2))
        progress_frame.grid_columnconfigure(0, weight=1)

        self.progress = ctk.CTkProgressBar(progress_frame, height=6)
        self.progress.grid(row=0, column=0, sticky="ew")
        self.progress.set(0)

        self.status_label = ctk.CTkLabel(
            progress_frame,
            text="Nenhum arquivo selecionado.",
            font=ctk.CTkFont(size=12),
            anchor="w",
            text_color=("#4a4a55", "#b8b8c2"),
        )
        self.status_label.grid(row=1, column=0, sticky="w", pady=(4, 0))

        # Resultados ----------------------------------------------------
        result_card = self._card(row=6, title="Resultado")
        result_card.grid_columnconfigure(0, weight=1)

        self.result_box = ctk.CTkTextbox(
            result_card,
            height=310,
            wrap="word",
            font=ctk.CTkFont(family="Consolas", size=12),
        )
        self.result_box.grid(row=1, column=0, sticky="ew", padx=16, pady=(0, 8))
        self.result_box.configure(state="disabled")

        buttons = ctk.CTkFrame(result_card, fg_color="transparent")
        buttons.grid(row=2, column=0, sticky="ew", padx=16, pady=(0, 16))
        for column in range(3):
            buttons.grid_columnconfigure(column, weight=1)

        self.btn_open_folder = ctk.CTkButton(
            buttons,
            text="Visualizar arquivo na pasta",
            height=36,
            command=self._open_folder,
            state="disabled",
        )
        self.btn_open_folder.grid(row=0, column=0, sticky="ew", padx=(0, 4))

        self.btn_tree = ctk.CTkButton(
            buttons,
            text="Visualizar árvore de Huffman",
            height=36,
            command=self._show_tree,
            state="disabled",
        )
        self.btn_tree.grid(row=0, column=1, sticky="ew", padx=4)

        self.btn_details = ctk.CTkButton(
            buttons,
            text="Informações dos algoritmos",
            height=36,
            command=self._show_details,
            state="disabled",
        )
        self.btn_details.grid(row=0, column=2, sticky="ew", padx=(4, 0))

        footer = ctk.CTkLabel(
            self.scroll,
            text=(
                "Trabalho de Grafos — árvore binária de Huffman, fila de prioridade "
                "e janela deslizante LZ77 implementados manualmente."
            ),
            font=ctk.CTkFont(size=11),
            text_color=("#5a5a66", "#8f8f9a"),
        )
        footer.grid(row=7, column=0, pady=(10, 22))

    def _card(self, row: int, title: str | None) -> ctk.CTkFrame:
        card = ctk.CTkFrame(self.scroll, corner_radius=16)
        card.grid(row=row, column=0, sticky="ew", padx=24, pady=7)
        card.grid_columnconfigure(0, weight=1)

        if title:
            ctk.CTkLabel(
                card,
                text=title,
                font=ctk.CTkFont(size=14, weight="bold"),
                anchor="w",
            ).grid(row=0, column=0, sticky="ew", padx=18, pady=(14, 6))
            card.grid_rowconfigure(0, weight=0)

        return card

    def _info_row(self, parent: ctk.CTkFrame, row: int, label: str) -> ctk.CTkLabel:
        # A linha 0 do card pode conter o título; por isso o offset.
        offset = 1 if parent.grid_slaves(row=0, column=0) else 0

        ctk.CTkLabel(
            parent,
            text=label,
            width=100,
            anchor="w",
            font=ctk.CTkFont(size=12, weight="bold"),
        ).grid(row=row + offset, column=0, sticky="nw", padx=(18, 10), pady=4)

        value = ctk.CTkLabel(
            parent,
            text="—",
            anchor="w",
            justify="left",
            font=ctk.CTkFont(size=12),
            wraplength=720,
        )
        value.grid(row=row + offset, column=1, sticky="ew", padx=(0, 18), pady=4)
        parent.grid_columnconfigure(1, weight=1)
        return value

    # ------------------------------------------------------------------
    # Arrastar e soltar
    # ------------------------------------------------------------------

    def _register_dnd(self, widget) -> None:
        try:
            widget.drop_target_register(DND_FILES)
            widget.dnd_bind("<<Drop>>", self._on_drop)
            self.dnd_enabled = True
        except Exception:
            pass

    def _on_drop(self, event):
        try:
            paths = self.tk.splitlist(event.data)
        except Exception:
            paths = [event.data]

        paths = [path for path in paths if path]
        if paths:
            if len(paths) > 1:
                messagebox.showinfo(
                    "Vários arquivos",
                    "Apenas o primeiro arquivo será carregado.",
                    parent=self,
                )
            self._load_file(Path(paths[0]))

        return "copy"

    # ------------------------------------------------------------------
    # Tema e estado
    # ------------------------------------------------------------------

    def _apply_theme(self) -> None:
        mode = self.theme_var.get()
        ctk.set_appearance_mode(mode if mode in ("dark", "light") else "dark")

    def _set_busy(self, busy: bool, message: str = "") -> None:
        self.busy = busy

        if busy:
            self.progress.configure(mode="indeterminate")
            self.progress.start()
            self.status_label.configure(
                text=message or "Processando...",
                text_color=("#2f6fd0", "#6ea8ff"),
            )
            self.btn_select.configure(state="disabled")
            self.btn_compress.configure(state="disabled")
            self.btn_decompress.configure(state="disabled")
        else:
            self.progress.stop()
            self.progress.configure(mode="determinate")
            self.progress.set(0)
            self._update_buttons()

    def _update_buttons(self) -> None:
        if self.busy:
            return

        self.btn_select.configure(state="normal")
        self.btn_compress.configure(
            state="normal" if self.selected_kind == "txt" else "disabled"
        )
        self.btn_decompress.configure(
            state="normal" if self.selected_kind == "huff" else "disabled"
        )
        self.btn_open_folder.configure(
            state="normal" if self.last_output_path else "disabled"
        )
        self.btn_tree.configure(
            state="normal" if self.last_tree_available else "disabled"
        )
        self.btn_details.configure(
            state="normal" if self.last_compression else "disabled"
        )

    def _set_status(self, text: str, kind: str = "info") -> None:
        colors = {
            "info": ("#4a4a55", "#b8b8c2"),
            "success": ("#177245", "#5fd39a"),
            "error": ("#b02a2a", "#ff8a8a"),
        }
        self.status_label.configure(text=text, text_color=colors.get(kind, colors["info"]))

    def _set_result_text(self, text: str) -> None:
        self.result_box.configure(state="normal")
        self.result_box.delete("1.0", "end")
        self.result_box.insert("1.0", text)
        self.result_box.configure(state="disabled")

    def _reset_results(self) -> None:
        self.last_compression = None
        self.last_decompression = None
        self.last_output_path = None
        self.last_tree_root = None
        self.last_tree_strategy = None
        self.last_tree_desc = None
        self.last_tree_available = False
        self._update_buttons()

    # ------------------------------------------------------------------
    # Seleção de arquivos
    # ------------------------------------------------------------------

    def _select_file(self) -> None:
        if self.busy:
            return

        path = filedialog.askopenfilename(
            parent=self,
            title="Selecione um arquivo",
            filetypes=[
                ("Arquivos suportados", "*.txt *.huff"),
                ("Arquivos de texto", "*.txt"),
                ("Arquivos compactados", "*.huff"),
                ("Todos os arquivos", "*.*"),
            ],
        )
        if path:
            self._load_file(Path(path))

    def _load_file(self, path: Path) -> bool:
        path = Path(path)

        if not path.exists():
            messagebox.showerror("Arquivo não encontrado", str(path), parent=self)
            return False

        if not path.is_file():
            messagebox.showerror(
                "Caminho inválido",
                "Selecione um arquivo, não uma pasta.",
                parent=self,
            )
            return False

        suffix = path.suffix.lower()

        if suffix == ".txt":
            return self._load_txt(path)
        if suffix == ".huff":
            return self._load_huff(path)

        messagebox.showerror(
            "Extensão não suportada",
            "Use arquivos .txt para compactar ou .huff para descompactar.",
            parent=self,
        )
        return False

    def _load_txt(self, path: Path) -> bool:
        try:
            data = path.read_bytes()
        except OSError as exc:
            messagebox.showerror(
                "Falha ao ler o arquivo",
                f"Não foi possível ler:\n{path}\n\n{exc}",
                parent=self,
            )
            return False

        encoding = self._detect_encoding(data)
        if encoding is None:
            messagebox.showerror(
                "Codificação incompatível",
                "O arquivo selecionado não é um texto válido.",
                parent=self,
            )
            return False

        self.selected_path = path
        self.selected_kind = "txt"
        self.metadata = None
        self._reset_results()

        self.info_name.configure(text=path.name)
        self.info_path.configure(text=str(path))
        self.info_size.configure(text=size_line(len(data)))
        self.info_details.configure(
            text=f"Texto {encoding} válido • {format_int(len(data))} bytes"
        )

        self._set_status("Arquivo pronto para compactação.", "success")
        self._set_result_text(
            "Arquivo carregado com sucesso.\n\n"
            "Escolha uma estratégia e clique em COMPACTAR ARQUIVO.\n"
            "O arquivo .huff será salvo na mesma pasta do original."
        )
        self._update_buttons()
        return True

    @staticmethod
    def _detect_encoding(data: bytes) -> Optional[str]:
        if data.startswith(b"\xef\xbb\xbf"):
            try:
                data.decode("utf-8-sig")
                return "UTF-8"
            except UnicodeDecodeError:
                return None
        try:
            data.decode("utf-8")
            return "UTF-8"
        except UnicodeDecodeError:
            pass
        for encoding in ("cp1252", "latin-1"):
            try:
                data.decode(encoding)
                return encoding.upper()
            except UnicodeDecodeError:
                continue
        return None

    def _load_huff(self, path: Path) -> bool:
        try:
            metadata = decompressor.read_metadata(path)
        except decompressor.DecompressionError as exc:
            messagebox.showerror(
                "Arquivo .huff inválido",
                f"Não foi possível validar o arquivo:\n{path}\n\n{exc}",
                parent=self,
            )
            return False

        self.selected_path = path
        self.selected_kind = "huff"
        self.metadata = metadata
        self._reset_results()

        try:
            file_size = path.stat().st_size
        except OSError:
            file_size = 0

        details = (
            f"Estratégia: {metadata.strategy_name} • "
            f"Original: {format_int(metadata.original_size)} bytes • "
            f"Bits: {format_int(metadata.bits_len)}"
        )

        self.info_name.configure(text=path.name)
        self.info_path.configure(text=str(path))
        self.info_size.configure(text=size_line(file_size))
        self.info_details.configure(text=details)

        self.last_tree_root = build_tree(metadata.freqs)
        self.last_tree_strategy = metadata.strategy_name
        self.last_tree_desc = (
            "bytes da representação intermediária gerada pelo LZ77"
            if metadata.strategy == ff.STRATEGY_LZ77_HUFFMAN
            else "bytes do arquivo original"
        )
        self.last_tree_available = True

        self._set_status("Arquivo .huff validado. Pronto para descompactar.", "success")
        self._set_result_text(
            "Cabeçalho e metadados validados com sucesso.\n\n"
            f"Estratégia usada na compactação: {metadata.strategy_name}\n"
            f"Tamanho original informado: {size_line(metadata.original_size)}\n\n"
            "Clique em DESCOMPACTAR ARQUIVO para recuperar o conteúdo."
        )
        self._update_buttons()
        return True

    # ------------------------------------------------------------------
    # Compactação
    # ------------------------------------------------------------------

    def _compress(self) -> None:
        if self.busy:
            return

        if self.selected_kind != "txt" or self.selected_path is None:
            messagebox.showwarning(
                "Selecione um arquivo",
                "Escolha um arquivo .txt antes de compactar.",
                parent=self,
            )
            return

        output_path = self.selected_path.with_suffix(".huff")

        if output_path.exists():
            confirm = messagebox.askyesno(
                "Substituir arquivo?",
                f"Já existe um arquivo:\n{output_path}\n\nDeseja substituí-lo?",
                parent=self,
            )
            if not confirm:
                return

        strategy = self.strategy_var.get()
        input_path = self.selected_path

        self._set_busy(True, "Compactando arquivo...")

        def work():
            return compressor.compress_file(
                input_path,
                strategy=strategy,
                output_path=output_path,
                overwrite=True,
            )

        self._run_async(work, self._on_compress_done, self._on_compress_error)

    def _on_compress_done(self, result: compressor.CompressionResult) -> None:
        self.last_compression = result
        self.last_decompression = None
        self.last_output_path = result.output_path

        self.last_tree_root = result.root
        self.last_tree_strategy = result.strategy_name
        self.last_tree_desc = (
            "bytes da representação intermediária gerada pelo LZ77"
            if result.strategy_code == ff.STRATEGY_LZ77_HUFFMAN
            else "bytes do arquivo original"
        )
        self.last_tree_available = True

        self._set_busy(False)
        self._set_status("Compactação concluída com sucesso.", "success")
        self._set_result_text(self._format_compression_result(result))
        self._update_buttons()

    def _on_compress_error(self, error: Exception) -> None:
        self._set_busy(False)
        self._set_status("Falha na compactação.", "error")
        self._set_result_text(
            "A compactação não pôde ser concluída.\n\n"
            f"Detalhes: {error}"
        )
        messagebox.showerror("Erro na compactação", str(error), parent=self)

    # ------------------------------------------------------------------
    # Descompactação
    # ------------------------------------------------------------------

    def _decompress(self) -> None:
        if self.busy:
            return

        if self.selected_kind != "huff" or self.selected_path is None:
            messagebox.showwarning(
                "Selecione um arquivo",
                "Escolha um arquivo .huff antes de descompactar.",
                parent=self,
            )
            return

        metadata = self.metadata
        original_name = metadata.original_name if metadata else ""

        suggested = decompressor.suggested_output_name(self.selected_path, original_name)
        suffix = Path(suggested).suffix

        chosen = filedialog.asksaveasfilename(
            parent=self,
            title="Salvar arquivo recuperado como",
            initialdir=str(self.selected_path.parent),
            initialfile=suggested,
            defaultextension=suffix,
            filetypes=[("Todos os arquivos", "*.*")],
        )
        if not chosen:
            return

        output_path = Path(chosen)

        if output_path.exists():
            confirm = messagebox.askyesno(
                "Substituir arquivo?",
                f"Já existe um arquivo:\n{output_path}\n\nDeseja substituí-lo?",
                parent=self,
            )
            if not confirm:
                return

        input_path = self.selected_path
        self._set_busy(True, "Descompactando arquivo...")

        def work():
            return decompressor.decompress_file(
                input_path,
                output_path=output_path,
                overwrite=True,
            )

        self._run_async(work, self._on_decompress_done, self._on_decompress_error)

    def _on_decompress_done(self, result: decompressor.DecompressionResult) -> None:
        self.last_decompression = result
        self.last_compression = None
        self.last_output_path = result.output_path

        self.last_tree_root = result.root
        self.last_tree_strategy = result.strategy_name
        self.last_tree_desc = "frequências reconstruídas a partir do arquivo .huff"
        self.last_tree_available = True

        self._set_busy(False)
        self._set_status("Descompactação concluída. Integridade confirmada.", "success")
        self._set_result_text(self._format_decompression_result(result))
        self._update_buttons()

    def _on_decompress_error(self, error: Exception) -> None:
        self._set_busy(False)
        self._set_status("Falha na descompactação.", "error")
        self._set_result_text(
            "A descompactação não pôde ser concluída.\n\n"
            f"Detalhes: {error}"
        )
        messagebox.showerror("Erro na descompactação", str(error), parent=self)

    # ------------------------------------------------------------------
    # Formatação dos resultados
    # ------------------------------------------------------------------

    def _format_compression_result(
        self, result: compressor.CompressionResult
    ) -> str:
        lines = []
        lines.append("COMPACTAÇÃO CONCLUÍDA")
        lines.append("")
        lines.append(_row("Arquivo original", result.original_name))
        lines.append(_row("Estratégia utilizada", result.strategy_name))
        lines.append(_row("Tamanho original", size_line(result.original_size)))
        lines.append(_row("Tamanho compactado", size_line(result.compressed_size)))

        if result.grew:
            lines.append(
                _row(
                    "Espaço economizado",
                    f"aumento de {format_int(abs(result.saved_bytes))} bytes",
                )
            )
        else:
            lines.append(_row("Espaço economizado", size_line(result.saved_bytes)))

        if result.original_size == 0:
            lines.append(_row("Redução", "n/d (arquivo vazio)"))
        else:
            reduction = f"{result.reduction_percent:.2f}%".replace(".", ",")
            lines.append(_row("Percentual de redução", reduction))

        if result.compressed_size == 0:
            lines.append(_row("Taxa de compactação", "n/d"))
        else:
            ratio = f"{result.compression_ratio:.3f}x".replace(".", ",")
            lines.append(_row("Taxa de compactação", ratio))

        elapsed = f"{result.elapsed:.4f} s".replace(".", ",")
        lines.append(_row("Tempo de processamento", elapsed))
        lines.append(_row("Arquivo gerado", str(result.output_path)))

        if result.strategy_code == ff.STRATEGY_LZ77_HUFFMAN and result.lz_stats:
            stats = result.lz_stats
            lines.append("")
            lines.append("LZ77")
            lines.append(_row("Tokens gerados", format_int(stats["tokens"])))
            lines.append(_row("Literais", format_int(stats["literals"])))
            lines.append(_row("Referências", format_int(stats["references"])))
            lines.append(
                _row("Bytes cobertos por referências", format_int(stats["matched_bytes"]))
            )
            lines.append(
                _row("Representação intermediária", size_line(result.intermediate_size))
            )
            lines.append(_row("Bits após Huffman", format_int(result.bits_len)))

        if result.comparison:
            huffman_value = result.comparison.get("huffman")
            hybrid_value = result.comparison.get("hybrid")
            huffman_size = huffman_value if isinstance(huffman_value, int) else 0
            hybrid_size = hybrid_value if isinstance(hybrid_value, int) else 0
            selected_label = (
                "LZ77 + Huffman"
                if result.strategy_code == ff.STRATEGY_LZ77_HUFFMAN
                else "Huffman"
            )

            lines.append("")
            lines.append("COMPARAÇÃO — MODO AUTOMÁTICO")
            lines.append(_row("Huffman", size_line(huffman_size)))
            lines.append(_row("LZ77 + Huffman", size_line(hybrid_size)))
            lines.append(_row("Estratégia selecionada", selected_label))
            lines.append(
                "Critério: menor tamanho completo do arquivo .huff "
                "(cabeçalho + metadados + dados + preenchimento)."
            )

        if result.grew:
            lines.append("")
            lines.append(
                "Atenção: o arquivo compactado ficou maior que o original. "
                "Isso pode acontecer em arquivos muito pequenos por causa do "
                "cabeçalho e dos metadados."
            )

        return "\n".join(lines)

    def _format_decompression_result(
        self, result: decompressor.DecompressionResult
    ) -> str:
        elapsed = f"{result.elapsed:.4f} s".replace(".", ",")

        lines = [
            "DESCOMPACTAÇÃO CONCLUÍDA",
            "",
            _row("Arquivo compactado", result.compressed_path.name),
            _row("Arquivo recuperado", result.output_path.name),
            _row("Tamanho recuperado", size_line(result.recovered_size)),
            _row("Estratégia", result.strategy_name),
            _row("Integridade", "OK — SHA-256 confere"),
            _row("SHA-256", result.sha_actual.hex()),
            _row("Tempo de processamento", elapsed),
            _row("Salvo em", str(result.output_path)),
        ]

        if result.strategy_code == ff.STRATEGY_LZ77_HUFFMAN:
            lines.append(
                _row(
                    "Dados intermediários",
                    size_line(result.intermediate_size),
                )
            )

        return "\n".join(lines)

    # ------------------------------------------------------------------
    # Ações auxiliares
    # ------------------------------------------------------------------

    def _open_folder(self) -> None:
        path = self.last_output_path
        if path is None or not Path(path).exists():
            messagebox.showwarning(
                "Nenhum arquivo",
                "Ainda não há um arquivo gerado para mostrar.",
                parent=self,
            )
            return

        path = Path(path)
        try:
            path = path.resolve()
        except OSError:
            pass

        try:
            if sys.platform.startswith("win"):
                # O Explorer precisa das aspas apenas no caminho. Se o comando
                # inteiro for passado como um único argumento, caminhos com
                # espaços fazem o Windows abrir a pasta padrão.
                try:
                    subprocess.Popen(f'explorer /select,"{path}"')
                except Exception:
                    os.startfile(str(path.parent))  # type: ignore[attr-defined]
            elif sys.platform == "darwin":
                subprocess.Popen(["open", "-R", str(path)])
            else:
                subprocess.Popen(["xdg-open", str(path.parent)])
        except Exception as exc:
            messagebox.showerror(
                "Falha ao abrir a pasta",
                f"Não foi possível abrir o gerenciador de arquivos.\n\n{exc}",
                parent=self,
            )

    def _show_tree(self) -> None:
        if not self.last_tree_available:
            messagebox.showwarning(
                "Árvore indisponível",
                "Compacte ou selecione um arquivo .huff primeiro.",
                parent=self,
            )
            return

        open_tree_window(
            self,
            self.last_tree_root,
            self.last_tree_strategy or "—",
            self.last_tree_desc or "—",
        )

    def _show_details(self) -> None:
        result = self.last_compression
        if result is None:
            messagebox.showwarning(
                "Informações indisponíveis",
                "As informações detalhadas ficam disponíveis após uma compactação.",
                parent=self,
            )
            return

        window = ctk.CTkToplevel(self)
        window.title("Informações dos algoritmos")
        window.geometry("840x660")
        window.minsize(640, 480)
        window.grid_columnconfigure(0, weight=1)
        window.grid_rowconfigure(1, weight=1)

        ctk.CTkLabel(
            window,
            text=f"Informações da compactação — {result.strategy_name}",
            font=ctk.CTkFont(size=17, weight="bold"),
            anchor="w",
        ).grid(row=0, column=0, sticky="ew", padx=18, pady=(16, 8))

        textbox = ctk.CTkTextbox(
            window,
            wrap="none",
            font=ctk.CTkFont(family="Consolas", size=11),
        )
        textbox.grid(row=1, column=0, sticky="nsew", padx=18, pady=(0, 8))

        lines = []
        lines.append(f"Arquivo: {result.original_name}")
        lines.append(f"Estratégia: {result.strategy_name}")
        lines.append(f"Tamanho original: {size_line(result.original_size)}")
        lines.append(f"Tamanho do .huff: {size_line(result.compressed_size)}")
        lines.append(f"Bits codificados: {format_int(result.bits_len)}")
        lines.append("")

        if result.strategy_code == ff.STRATEGY_LZ77_HUFFMAN:
            stats = result.lz_stats or {}
            lines.append("ETAPA 1 — LZ77")
            lines.append(f"Janela de busca: {format_int(result.lz_params.window)} bytes")
            lines.append(f"Comprimento mínimo: {result.lz_params.min_match}")
            lines.append(f"Comprimento máximo: {result.lz_params.max_match}")
            lines.append(f"Tokens: {format_int(stats.get('tokens', 0))}")
            lines.append(f"Literais: {format_int(stats.get('literals', 0))}")
            lines.append(f"Referências: {format_int(stats.get('references', 0))}")
            lines.append(
                f"Bytes cobertos por referências: "
                f"{format_int(stats.get('matched_bytes', 0))}"
            )
            lines.append(
                f"Representação intermediária: "
                f"{size_line(result.intermediate_size)}"
            )
            lines.append("")
            lines.append("ETAPA 2 — Huffman sobre a representação intermediária")
            base_description = "bytes da representação intermediária (LZ77)"
        else:
            lines.append("HUFFMAN SOBRE O ARQUIVO ORIGINAL")
            base_description = "bytes do arquivo original"

        lines.append(f"Base das frequências: {base_description}")
        lines.append(f"Símbolos distintos: {len(result.freqs)}")
        lines.append(f"Bits antes do empacotamento: {format_int(result.bits_len)}")
        lines.append(
            f"Bytes empacotados: {format_int((result.bits_len + 7) // 8)}"
        )
        lines.append("")
        lines.append("SÍMBOLO       FREQUÊNCIA        CÓDIGO                              BITS")
        lines.append("-" * 92)

        for symbol in sorted(result.freqs):
            label = format_symbol(symbol)
            code = result.codes.get(symbol, "")
            lines.append(
                f"{label:<14}{format_int(result.freqs[symbol]):>12}    "
                f"{code:<36}{len(code):>6}"
            )

        textbox.insert("1.0", "\n".join(lines))
        textbox.configure(state="disabled")

        buttons = ctk.CTkFrame(window, fg_color="transparent")
        buttons.grid(row=2, column=0, sticky="ew", padx=18, pady=(0, 16))
        buttons.grid_columnconfigure(0, weight=1)

        def copy_to_clipboard():
            self.clipboard_clear()
            self.clipboard_append("\n".join(lines))
            self._set_status("Informações copiadas para a área de transferência.")

        ctk.CTkButton(
            buttons,
            text="Copiar informações",
            width=160,
            command=copy_to_clipboard,
        ).grid(row=0, column=0, sticky="w")

        ctk.CTkButton(
            buttons,
            text="Fechar",
            width=120,
            command=window.destroy,
        ).grid(row=0, column=1, sticky="e")

    # ------------------------------------------------------------------
    # Threads
    # ------------------------------------------------------------------

    def _run_async(self, work, on_done, on_error) -> None:
        def runner():
            try:
                result = work()
            except Exception as exc:  # noqa: BLE001 - convertido em mensagem amigável
                self._ui_queue.put(lambda error=exc: on_error(error))
            else:
                self._ui_queue.put(lambda value=result: on_done(value))

        threading.Thread(target=runner, daemon=True).start()

    def _poll_queue(self) -> None:
        if self._closing:
            return

        try:
            while True:
                callback = self._ui_queue.get_nowait()
                try:
                    callback()
                except Exception as exc:  # pragma: no cover
                    messagebox.showerror("Erro inesperado", str(exc), parent=self)
        except queue.Empty:
            pass

        try:
            self.after(80, self._poll_queue)
        except Exception:  # pragma: no cover
            pass

    def _on_close(self) -> None:
        self._closing = True
        self.destroy()


def run() -> None:
    app = App()
    app.mainloop()
