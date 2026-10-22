#!/usr/bin/env python3
"""Gera uma planta baixa em PDF VETORIAL sintético (estilo AutoCAD plotado) com gabarito, para testar pdf_extrair.

Uso: python3 pdf_gerar_teste.py --seed 3 --saida-dir saida [--rotacao 0|90|180|270] [--estilo preenchido|linha_dupla]

Escreve planta.pdf e gabarito.json. Escala 1:50 (texto "ESC. 1:50" na folha, A3 retrato).
Estilo 'preenchido': paredes como retângulos cinza (0,5) fatiados como o CAD faz, pilares laranja nos 4 cantos,
vãos com linhas de batente, porta = folha (retângulo fino perpendicular), janela = 3 linhas paralelas.
Estilo 'contorno': cada peça de parede é uma polilinha FECHADA de traço 1,08 pt (face externa e interna), sem preenchimento
(o CAD de layouts de interiores); o extrator lê pela paridade dos contornos.
Estilo 'linha_dupla': as duas faces como linhas SOLTAS (sem formar polígono), para conferir que o extrator RECUSA com erro claro.

Planta: retângulo externo, uma parede interna vertical em T com uma porta, 1 janela e 1 porta externas.
A semente define dimensões e posições dos vãos. Alturas NÃO existem na planta (como nos PDFs reais).
"""
import argparse
import json
import random
import sys
from pathlib import Path

import pymupdf

ESCALA = 50
PT_POR_MM = 72.0 / 25.4 / ESCALA          # pontos do PDF por mm do projeto
ESP = 150
PILAR = 200
CINZA = (0.5, 0.5, 0.5)
LARANJA = (1.0, 0.5, 0.0)
CREME = (0.97, 0.91, 0.86)


def sorteio(seed):
    rng = random.Random(seed)
    W = rng.randrange(6000, 8500, 50)
    D = rng.randrange(4000, 5500, 50)
    xi = rng.randrange(2800, W - 2800, 50)                    # parede interna (eixo x)
    porta_i = rng.choice([700, 800, 900])
    janela = rng.choice([1000, 1200, 1500])
    porta_e = rng.choice([800, 900])
    return {
        "W": W, "D": D, "xi": xi,
        "aberturas": [
            {"tipo": "porta", "linha": "interna", "s0": rng.randrange(600, D - 600 - porta_i, 50), "largura": porta_i},   # ao longo de y
            {"tipo": "janela", "linha": "sul", "s0": rng.randrange(500, xi - 500 - janela, 50), "largura": janela},        # ao longo de x
            {"tipo": "porta", "linha": "norte", "s0": rng.randrange(xi + 500, W - 500 - porta_e, 50), "largura": porta_e},
        ],
    }


def gerar(seed, destino, rotacao=0, estilo="preenchido"):
    g = sorteio(seed)
    W, D, xi = g["W"], g["D"], g["xi"]
    doc = pymupdf.open()
    pg = doc.new_page(width=842, height=1191)
    ox, oy = 120.0, 250.0

    def P(x, y):                                  # mm (y para cima) -> pt (y para baixo)
        return pymupdf.Point(ox + x * PT_POR_MM, oy + (D - y) * PT_POR_MM)

    def ret(x0, y0, x1, y1, **kw):
        a, b = P(x0, y1), P(x1, y0)
        pg.draw_rect(pymupdf.Rect(a, b), **kw)

    def linha(x0, y0, x1, y1, w=0.48):
        pg.draw_line(P(x0, y0), P(x1, y1), color=(0, 0, 0), width=w)

    def peca(x0, y0, x1, y1):
        if estilo == "preenchido":
            ret(x0, y0, x1, y1, color=CINZA, fill=CINZA, width=0)
        elif estilo == "contorno":
            pg.draw_polyline([P(x0, y0), P(x1, y0), P(x1, y1), P(x0, y1), P(x0, y0)], color=(0, 0, 0), width=1.08, closePath=True)
        else:
            if x1 - x0 >= y1 - y0:
                linha(x0, y0, x1, y0, 1.44)
                linha(x0, y1, x1, y1, 1.44)
            else:
                linha(x0, y0, x0, y1, 1.44)
                linha(x1, y0, x1, y1, 1.44)

    def parede_h(c, a, b, ab):
        """Parede horizontal na linha y=c, de x=a a x=b, com aberturas ab=[(s0, s1, tipo)] (x em mm)."""
        marcos = [a]
        for s0, s1, _ in ab:
            marcos += [s0, s1]
        marcos.append(b)
        for i in range(0, len(marcos), 2):
            if marcos[i + 1] > marcos[i]:
                peca(marcos[i], c - ESP / 2, marcos[i + 1], c + ESP / 2)
        for s0, s1, tipo in ab:
            linha(s0, c - ESP / 2, s0, c + ESP / 2, 0.84)
            linha(s1, c - ESP / 2, s1, c + ESP / 2, 0.84)
            if tipo == "janela":
                for dy in (-ESP / 2, 0, ESP / 2):
                    linha(s0, c + dy, s1, c + dy)
            else:
                lado = ESP / 2 if c < D / 2 else -ESP / 2                    # folha aberta para dentro
                y0, y1 = (c + lado, c + lado + (s1 - s0) * (1 if lado > 0 else -1))
                ret(s1 - 40, min(y0, y1), s1, max(y0, y1), color=(0, 0, 0), fill=CREME, width=0.24)

    def parede_v(c, a, b, ab):
        marcos = [a]
        for s0, s1, _ in ab:
            marcos += [s0, s1]
        marcos.append(b)
        for i in range(0, len(marcos), 2):
            if marcos[i + 1] > marcos[i]:
                peca(c - ESP / 2, marcos[i], c + ESP / 2, marcos[i + 1])
        for s0, s1, tipo in ab:
            linha(c - ESP / 2, s0, c + ESP / 2, s0, 0.84)
            linha(c - ESP / 2, s1, c + ESP / 2, s1, 0.84)
            if tipo == "janela":
                for dx in (-ESP / 2, 0, ESP / 2):
                    linha(c + dx, s0, c + dx, s1)
            else:
                x0, x1 = c + ESP / 2, c + ESP / 2 + (s1 - s0)
                ret(x0, s1 - 40, x1, s1, color=(0, 0, 0), fill=CREME, width=0.24)

    por_linha = {"sul": [], "norte": [], "interna": []}
    for a in g["aberturas"]:
        por_linha[a["linha"]].append((a["s0"], a["s0"] + a["largura"], a["tipo"]))
    # horizontais corridas de ponta a ponta (como o CAD); verticais entre as faces das horizontais
    parede_h(0, -ESP / 2, W + ESP / 2, por_linha["sul"])
    parede_h(D, -ESP / 2, W + ESP / 2, por_linha["norte"])
    parede_v(0, ESP / 2, D - ESP / 2, [])
    parede_v(W, ESP / 2, D - ESP / 2, [])
    parede_v(xi, ESP / 2, D - ESP / 2, por_linha["interna"])
    if estilo in ("preenchido", "contorno"):
        for x, y in ((0, 0), (W, 0), (0, D), (W, D)):
            ret(x - PILAR / 2, y - PILAR / 2, x + PILAR / 2, y + PILAR / 2, color=LARANJA, fill=LARANJA, width=0)
    pg.insert_text((ox, oy + D * PT_POR_MM + 80), "PLANTA BAIXA  ESC. 1:50", fontsize=10)
    if rotacao:
        pg.set_rotation(rotacao)
    doc.save(destino)
    gab = {"seed": seed, "estilo": estilo, "rotacao": rotacao, "largura_eixos_mm": W, "profundidade_eixos_mm": D,
           "parede_interna_x_mm": xi, "espessura_mm": ESP, "pilar_mm": PILAR, "aberturas": g["aberturas"]}
    return gab


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--seed", type=int, required=True)
    ap.add_argument("--saida-dir", type=Path, required=True)
    ap.add_argument("--rotacao", type=int, default=0, choices=[0, 90, 180, 270])
    ap.add_argument("--estilo", choices=["preenchido", "contorno", "linha_dupla"], default="preenchido")
    args = ap.parse_args()
    args.saida_dir.mkdir(parents=True, exist_ok=True)
    gab = gerar(args.seed, args.saida_dir / "planta.pdf", args.rotacao, args.estilo)
    (args.saida_dir / "gabarito.json").write_text(json.dumps(gab, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"OK: {args.saida_dir / 'planta.pdf'} (gabarito.json escrito; não o leia antes de testar a leitura)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
