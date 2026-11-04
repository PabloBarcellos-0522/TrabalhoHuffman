"""Visualização da árvore de Huffman com o Canvas do Tkinter.

A árvore exibida é sempre a árvore realmente usada na compactação (ou a árvore
reconstruída a partir do ``.huff``). Nenhuma biblioteca de grafos é utilizada:
o posicionamento é calculado manualmente e o desenho usa apenas primitivas do
Canvas.
"""

from __future__ import annotations

import math
import tkinter as tk
import tkinter.font as tkfont
from typing import Dict, Optional, Tuple

import customtkinter as ctk

from huffman import Node, leaf_count, tree_depth


def format_symbol(byte: int) -> str:
    """Representação legível de um byte para as folhas da árvore."""

    if byte == 32:
        return "ESPAÇO"
    if byte == 10:
        return "\\n"
    if byte == 9:
        return "\\t"
    if byte == 13:
        return "\\r"
    if 33 <= byte <= 126:
        return chr(byte)
    return f"0x{byte:02X}"


def _theme_colors() -> dict:
    if ctk.get_appearance_mode().lower() == "light":
        return {
            "bg": "#f4f5f7",
            "leaf_fill": "#bfe6cf",
            "leaf_outline": "#2e8b57",
            "leaf_text": "#10261a",
            "internal_fill": "#cfe2f3",
            "internal_outline": "#2b6cb0",
            "internal_text": "#102a43",
            "root_fill": "#ffd8a8",
            "root_outline": "#d97706",
            "root_text": "#3a2200",
            "edge": "#6f7480",
            "edge_label": "#2b2f36",
            "freq": "#3b4252",
        }

    return {
        "bg": "#1a1a1e",
        "leaf_fill": "#245c45",
        "leaf_outline": "#45c48a",
        "leaf_text": "#eafff5",
        "internal_fill": "#263f61",
        "internal_outline": "#5b9bd5",
        "internal_text": "#eaf3ff",
        "root_fill": "#6b3426",
        "root_outline": "#f0a35e",
        "root_text": "#fff1e6",
        "edge": "#8b8b93",
        "edge_label": "#d8d8de",
        "freq": "#c9c9d1",
    }


def _rounded_rect(canvas: tk.Canvas, x1, y1, x2, y2, radius, **kwargs):
    """Desenha um retângulo arredondado usando um polígono suavizado."""

    radius = min(radius, (x2 - x1) / 2, (y2 - y1) / 2)
    points = [
        x1 + radius, y1,
        x2 - radius, y1,
        x2, y1,
        x2, y1 + radius,
        x2, y2 - radius,
        x2, y2,
        x2 - radius, y2,
        x1 + radius, y2,
        x1, y2,
        x1, y2 - radius,
        x1, y1 + radius,
        x1, y1,
    ]
    return canvas.create_polygon(points, smooth=True, **kwargs)


class HuffmanTreeWindow(ctk.CTkToplevel):
    """Janela com a árvore de Huffman desenhada em um Canvas com rolagem."""

    def __init__(
        self,
        master,
        root: Optional[Node],
        strategy_label: str,
        data_description: str,
    ) -> None:
        super().__init__(master)
        self.title("Árvore de Huffman")
        self.geometry("1120x760")
        self.minsize(720, 480)

        self._tree_root = root
        self._colors = _theme_colors()
        self._zoom = 1.0
        self._zoom_min = 0.35
        self._zoom_max = 3.0
        self._zoom_step = 1.15
        self._zoom_focus: Optional[Tuple[float, float, float, float, float]] = None

        self.grid_columnconfigure(0, weight=1)
        self.grid_rowconfigure(1, weight=1)

        header = ctk.CTkFrame(self, corner_radius=0)
        header.grid(row=0, column=0, sticky="ew")
        header.grid_columnconfigure(0, weight=1)

        ctk.CTkLabel(
            header,
            text="Árvore de Huffman efetivamente utilizada",
            font=ctk.CTkFont(size=18, weight="bold"),
            anchor="w",
        ).grid(row=0, column=0, sticky="ew", padx=18, pady=(14, 2))

        info = (
            f"Estratégia: {strategy_label}    |    "
            f"Frequências calculadas sobre: {data_description}"
        )
        ctk.CTkLabel(
            header,
            text=info,
            font=ctk.CTkFont(size=12),
            anchor="w",
            text_color=("#4a4a55", "#b8b8c2"),
        ).grid(row=1, column=0, sticky="ew", padx=18, pady=(0, 4))

        stats = (
            f"Símbolos distintos: {leaf_count(root)}    |    "
            f"Profundidade máxima: {tree_depth(root)}"
        )
        ctk.CTkLabel(
            header,
            text=stats,
            font=ctk.CTkFont(size=12),
            anchor="w",
            text_color=("#4a4a55", "#b8b8c2"),
        ).grid(row=2, column=0, sticky="ew", padx=18, pady=(0, 12))

        body = ctk.CTkFrame(self, corner_radius=0, fg_color="transparent")
        body.grid(row=1, column=0, sticky="nsew")
        body.grid_columnconfigure(0, weight=1)
        body.grid_rowconfigure(0, weight=1)

        self.canvas = tk.Canvas(
            body,
            background=self._colors["bg"],
            highlightthickness=0,
            borderwidth=0,
        )
        self.canvas.grid(row=0, column=0, sticky="nsew")

        vbar = ctk.CTkScrollbar(body, command=self.canvas.yview)
        vbar.grid(row=0, column=1, sticky="ns")
        hbar = ctk.CTkScrollbar(
            body, command=self.canvas.xview, orientation="horizontal"
        )
        hbar.grid(row=1, column=0, sticky="ew")

        self.canvas.configure(
            yscrollcommand=vbar.set,
            xscrollcommand=hbar.set,
        )

        footer = ctk.CTkFrame(self, corner_radius=0, fg_color="transparent")
        footer.grid(row=2, column=0, sticky="ew")
        footer.grid_columnconfigure(0, weight=1)

        legend = ctk.CTkLabel(
            footer,
            text=(
                "Aresta esquerda = 0   |   Aresta direita = 1   |   "
                "Nós verdes = folhas (símbolo + frequência)   |   "
                "Nós azuis = nós internos (soma dos pesos)   |   "
                "Nó laranja = raiz   |   Ctrl + scroll = zoom"
            ),
            font=ctk.CTkFont(size=11),
            text_color=("#4a4a55", "#b8b8c2"),
            anchor="w",
        )
        legend.grid(row=0, column=0, sticky="ew", padx=18, pady=10)

        self.zoom_label = ctk.CTkLabel(
            footer,
            text="Zoom: 100%",
            font=ctk.CTkFont(size=11, weight="bold"),
            text_color=("#4a4a55", "#b8b8c2"),
        )
        self.zoom_label.grid(row=0, column=1, padx=10, pady=10)

        ctk.CTkButton(
            footer,
            text="Fechar",
            width=120,
            command=self.destroy,
        ).grid(row=0, column=2, padx=18, pady=10)

        self.canvas.bind("<MouseWheel>", self._on_mousewheel)
        self.canvas.bind("<Shift-MouseWheel>", self._on_shift_mousewheel)
        self.canvas.bind("<Control-MouseWheel>", self._on_ctrl_mousewheel)
        self.canvas.bind("<Button-4>", self._on_linux_wheel)
        self.canvas.bind("<Button-5>", self._on_linux_wheel)
        self.canvas.bind("<Control-Button-4>", self._on_ctrl_button)
        self.canvas.bind("<Control-Button-5>", self._on_ctrl_button)

        self.after(30, self._draw)

    # ------------------------------------------------------------------
    # Rolagem
    # ------------------------------------------------------------------

    def _on_mousewheel(self, event):
        self.canvas.yview_scroll(int(-event.delta / 120), "units")
        return "break"

    def _on_shift_mousewheel(self, event):
        self.canvas.xview_scroll(int(-event.delta / 120), "units")
        return "break"

    def _on_linux_wheel(self, event):
        delta = -1 if event.num == 4 else 1
        if event.state & 0x0001:
            self.canvas.xview_scroll(delta, "units")
        else:
            self.canvas.yview_scroll(delta, "units")
        return "break"

    def _on_ctrl_mousewheel(self, event):
        if event.delta == 0:
            return "break"
        factor = self._zoom_step if event.delta > 0 else 1.0 / self._zoom_step
        self._zoom_at(event.x, event.y, factor)
        return "break"

    def _on_ctrl_button(self, event):
        factor = self._zoom_step if event.num == 4 else 1.0 / self._zoom_step
        self._zoom_at(event.x, event.y, factor)
        return "break"

    def _zoom_at(self, x: int, y: int, factor: float) -> None:
        old_zoom = self._zoom
        new_zoom = max(self._zoom_min, min(self._zoom_max, old_zoom * factor))
        if abs(new_zoom - old_zoom) < 1e-9:
            return

        old_x = self.canvas.canvasx(x)
        old_y = self.canvas.canvasy(y)
        self._zoom = new_zoom
        self._zoom_focus = (
            old_x,
            old_y,
            float(x),
            float(y),
            new_zoom / old_zoom,
        )
        self._draw()

    # ------------------------------------------------------------------
    # Desenho
    # ------------------------------------------------------------------

    def _draw(self) -> None:
        canvas = self.canvas
        canvas.delete("all")

        zoom = self._zoom
        self.zoom_label.configure(text=f"Zoom: {int(round(zoom * 100))}%")

        root = self._tree_root
        if root is None:
            canvas.create_text(
                30 * zoom,
                30 * zoom,
                anchor="nw",
                text="Árvore vazia: o arquivo não possui símbolos.",
                fill=self._colors["edge_label"],
                font=("Segoe UI", max(8, int(round(14 * zoom)))),
            )
            canvas.configure(
                scrollregion=(0, 0, max(700.0, 700.0 * zoom), 200.0 * zoom)
            )
            return

        symbol_size = max(6, int(round(10 * zoom)))
        freq_size = max(6, int(round(8 * zoom)))
        symbol_font = tkfont.Font(family="Segoe UI", size=symbol_size, weight="bold")
        freq_font = tkfont.Font(family="Segoe UI", size=freq_size)
        edge_font = tkfont.Font(family="Segoe UI", size=symbol_size, weight="bold")

        # 1. Posiciona as folhas da esquerda para a direita e calcula os nós
        #    internos como a média dos filhos (desenho de árvore binária).
        positions: Dict[int, Tuple[float, float, float, float]] = {}
        leaf_counter = [0]
        node_height = max(28.0, 46.0 * zoom)

        def assign(node: Node, depth: int) -> float:
            if node.is_leaf:
                x_index = leaf_counter[0]
                leaf_counter[0] += 1
                assert node.symbol is not None
                label = format_symbol(node.symbol)
                width = max(58.0 * zoom, symbol_font.measure(label) + 18.0 * zoom)
                positions[id(node)] = (x_index, depth, width, node_height)
                return float(x_index)

            left_x = assign(node.left, depth + 1) if node.left else None
            right_x = assign(node.right, depth + 1) if node.right else None

            if left_x is not None and right_x is not None:
                x_index = (left_x + right_x) / 2
            elif left_x is not None:
                x_index = left_x
            else:
                x_index = right_x if right_x is not None else 0.0

            label = str(node.freq)
            width = max(52.0 * zoom, symbol_font.measure(label) + 18.0 * zoom)
            positions[id(node)] = (x_index, depth, width, node_height)
            return x_index

        assign(root, 0)

        # 2. Calcula dimensões da tela.
        max_width = max(entry[2] for entry in positions.values())
        cell_width = max(80.0 * zoom, max_width + 22.0 * zoom)
        level_height = 84.0 * zoom
        margin = 50.0 * zoom
        max_depth = max(entry[1] for entry in positions.values())

        total_width = max(720.0, leaf_counter[0] * cell_width + 2 * margin)
        total_height = max(420.0, (max_depth + 1) * level_height + 2 * margin)

        def screen_xy(node: Node) -> Tuple[float, float]:
            x_index, depth, _w, height = positions[id(node)]
            return (
                margin + x_index * cell_width + cell_width / 2,
                margin + depth * level_height + height / 2,
            )

        colors = self._colors
        root_id = id(root)
        edge_width = max(1, int(round(2 * zoom)))

        # 3. Arestas.
        def draw_edges(node: Node) -> None:
            if node.is_leaf:
                return
            px, py = screen_xy(node)
            for child, bit in ((node.left, "0"), (node.right, "1")):
                if child is None:
                    continue
                cx, cy = screen_xy(child)
                canvas.create_line(
                    px,
                    py,
                    cx,
                    cy,
                    fill=colors["edge"],
                    width=edge_width,
                )

                mid_x = (px + cx) / 2
                mid_y = (py + cy) / 2
                dx = cx - px
                dy = cy - py
                length = math.hypot(dx, dy) or 1.0
                offset_x = (-dy / length) * 11.0 * zoom
                offset_y = (dx / length) * 11.0 * zoom

                canvas.create_text(
                    mid_x + offset_x,
                    mid_y + offset_y,
                    text=bit,
                    fill=colors["edge_label"],
                    font=edge_font,
                )
                draw_edges(child)

        draw_edges(root)

        # 4. Nós.
        def draw_node(node: Node) -> None:
            x, y = screen_xy(node)
            _xi, _depth, width, height = positions[id(node)]

            is_root = id(node) == root_id
            if is_root:
                fill = colors["root_fill"]
                outline = colors["root_outline"]
                text_color = colors["root_text"]
            elif node.is_leaf:
                fill = colors["leaf_fill"]
                outline = colors["leaf_outline"]
                text_color = colors["leaf_text"]
            else:
                fill = colors["internal_fill"]
                outline = colors["internal_outline"]
                text_color = colors["internal_text"]

            _rounded_rect(
                canvas,
                x - width / 2,
                y - height / 2,
                x + width / 2,
                y + height / 2,
                radius=max(4.0, 12.0 * zoom),
                fill=fill,
                outline=outline,
                width=max(1, int(round((3 if is_root else 2) * zoom))),
            )

            if node.is_leaf:
                assert node.symbol is not None
                canvas.create_text(
                    x,
                    y - 8.0 * zoom,
                    text=format_symbol(node.symbol),
                    fill=text_color,
                    font=symbol_font,
                )
                canvas.create_text(
                    x,
                    y + 12.0 * zoom,
                    text=str(node.freq),
                    fill=colors["freq"] if not is_root else text_color,
                    font=freq_font,
                )
            else:
                canvas.create_text(
                    x,
                    y,
                    text=str(node.freq),
                    fill=text_color,
                    font=symbol_font,
                )

            if node.left is not None:
                draw_node(node.left)
            if node.right is not None:
                draw_node(node.right)

        draw_node(root)

        canvas.configure(scrollregion=(0, 0, total_width, total_height))

        self.update_idletasks()
        viewport_width = max(1, canvas.winfo_width())
        viewport_height = max(1, canvas.winfo_height())

        focus = self._zoom_focus
        self._zoom_focus = None

        if focus is not None:
            old_x, old_y, view_x, view_y, scale = focus
            new_x = old_x * scale
            new_y = old_y * scale
            left = max(0.0, min(total_width - viewport_width, new_x - view_x))
            top = max(0.0, min(total_height - viewport_height, new_y - view_y))
            canvas.xview_moveto(left / total_width if total_width else 0.0)
            canvas.yview_moveto(top / total_height if total_height else 0.0)
            return

        # Centraliza a visualização na raiz no primeiro desenho.
        root_x, _ = screen_xy(root)
        if total_width > viewport_width:
            fraction = (root_x - viewport_width / 2) / total_width
            canvas.xview_moveto(max(0.0, min(1.0, fraction)))
        else:
            canvas.xview_moveto(0.0)
        canvas.yview_moveto(0.0)


def open_tree_window(
    master,
    root: Optional[Node],
    strategy_label: str,
    data_description: str,
) -> HuffmanTreeWindow:
    """Abre (e mantém viva) uma janela de visualização da árvore."""

    windows = getattr(master, "_tree_windows", None)
    if windows is None:
        windows = []
        setattr(master, "_tree_windows", windows)

    window = HuffmanTreeWindow(master, root, strategy_label, data_description)
    windows.append(window)

    def cleanup(_event=None):
        if window in windows:
            windows.remove(window)

    window.protocol("WM_DELETE_WINDOW", lambda: (cleanup(), window.destroy()))
    return window
