#!/usr/bin/env python3
"""Gera uma planta baixa sintética (imagem) com gabarito, para testar a leitura por imagem.

Uso: python3 imagem_gerar_teste.py --seed 7 --saida-dir saida [--forma retangulo|L] [--ruido]

Escreve em --saida-dir:
  planta.png      a imagem (paredes pretas grossas, portas com folha e arco, janelas com 3 linhas, cota, rótulo,
                  e retângulos finos que imitam mobiliário/ruído de desenho)
  gabarito.json   a verdade: contorno do eixo (mm, anti-horário), espessura, aberturas e a cota desenhada
Com --ruido: ruído gaussiano, desfoque e JPEG (planta.jpg em vez de .png), para ver a robustez.

A semente define tudo (tamanhos, posições). Paredes sempre ortogonais; escala de 100 px por metro.
"""
import argparse
import io
import json
import math
import random
import sys
from pathlib import Path

import numpy as np
from PIL import Image, ImageDraw, ImageFilter, ImageFont

PX_POR_MM = 0.1       # 100 px por metro
MARGEM_PX = 110
ESPESSURA_MM = 150


def contorno(rng, forma):
    w = rng.randrange(4000, 7000, 50)
    d = rng.randrange(3000, 5000, 50)
    if forma == "L":
        w2 = rng.randrange(2000, w - 1500, 50)     # largura da perna alta
        d1 = rng.randrange(1500, d - 1000, 50)     # altura da perna larga
        return [(0, 0), (w, 0), (w, d1), (w2, d1), (w2, d), (0, d)]
    return [(0, 0), (w, 0), (w, d), (0, d)]


def posicionar_aberturas(rng, pts):
    """1 porta e 2 janelas, em paredes diferentes quando possível, longe dos cantos."""
    n = len(pts)
    paredes = []
    for i in range(n):
        a, b = pts[i], pts[(i + 1) % n]
        paredes.append(math.hypot(b[0] - a[0], b[1] - a[1]))
    candidatas = [i for i in range(n) if paredes[i] >= 2200]
    rng.shuffle(candidatas)
    pedidos = [("porta", rng.choice([800, 900])), ("janela", rng.choice([1000, 1200, 1500])), ("janela", rng.choice([1000, 1200, 1500]))]
    saida = []
    for k, (tipo, largura) in enumerate(pedidos):
        parede = candidatas[k % len(candidatas)]
        L = paredes[parede]
        for _ in range(50):
            s0 = rng.randrange(400, int(L - largura - 400), 50)
            if all(not (o["parede"] == parede and s0 < o["s0_mm"] + o["largura_mm"] + 400 and o["s0_mm"] < s0 + largura + 400) for o in saida):
                saida.append({"parede": parede, "tipo": tipo, "s0_mm": s0, "largura_mm": largura})
                break
    return saida


def desenhar(pts, aberturas, rng, ruido):
    xs = [p[0] for p in pts]
    ys = [p[1] for p in pts]
    t = ESPESSURA_MM
    largura_px = int((max(xs) - min(xs) + t) * PX_POR_MM) + 2 * MARGEM_PX
    altura_px = int((max(ys) - min(ys) + t) * PX_POR_MM) + 2 * MARGEM_PX + 40

    def px(x, y):   # mm (y para cima) -> pixel (y para baixo)
        return (MARGEM_PX + (x - min(xs) + t / 2) * PX_POR_MM, altura_px - MARGEM_PX - 40 - (y - min(ys) + t / 2) * PX_POR_MM)

    img = Image.new("L", (largura_px, altura_px), 255)
    dr = ImageDraw.Draw(img)
    n = len(pts)
    meia = t * PX_POR_MM / 2

    # paredes: retângulos com extremidades prolongadas em t/2 (preenche os cantos)
    for i in range(n):
        a, b = pts[i], pts[(i + 1) % n]
        (x0, y0), (x1, y1) = px(*a), px(*b)
        if abs(y0 - y1) < 1e-6:
            dr.rectangle([min(x0, x1) - meia, y0 - meia, max(x0, x1) + meia - 1, y0 + meia - 1], fill=0)
        else:
            dr.rectangle([x0 - meia, min(y0, y1) - meia, x0 + meia - 1, max(y0, y1) + meia - 1], fill=0)

    # aberturas: apaga o vão e desenha o símbolo
    for ab in aberturas:
        a, b = pts[ab["parede"]], pts[(ab["parede"] + 1) % n]
        L = math.hypot(b[0] - a[0], b[1] - a[1])
        ux, uy = (b[0] - a[0]) / L, (b[1] - a[1]) / L
        nx, ny = -uy, ux                                         # normal para dentro (contorno anti-horário)
        p0 = px(a[0] + ux * ab["s0_mm"], a[1] + uy * ab["s0_mm"])
        p1 = px(a[0] + ux * (ab["s0_mm"] + ab["largura_mm"]), a[1] + uy * (ab["s0_mm"] + ab["largura_mm"]))
        pn = (nx * PX_POR_MM, -ny * PX_POR_MM)                   # normal em pixels (y invertido)
        if abs(p0[1] - p1[1]) < 1e-6:
            dr.rectangle([min(p0[0], p1[0]), p0[1] - meia - 1, max(p0[0], p1[0]) - 1, p0[1] + meia], fill=255)
        else:
            dr.rectangle([p0[0] - meia - 1, min(p0[1], p1[1]), p0[0] + meia, max(p0[1], p1[1]) - 1], fill=255)
        wpx = ab["largura_mm"] * PX_POR_MM
        if ab["tipo"] == "janela":
            for k in (-1, 0, 1):
                q0 = (p0[0] + pn[0] * k * meia, p0[1] + pn[1] * k * meia)
                q1 = (p1[0] + pn[0] * k * meia, p1[1] + pn[1] * k * meia)
                dr.line([q0, q1], fill=0, width=1)
        else:
            tip = (p0[0] + pn[0] * wpx / PX_POR_MM * 1.0, p0[1] + pn[1] * wpx / PX_POR_MM * 1.0)
            tip = (p0[0] + (nx * wpx), p0[1] - (ny * wpx))
            dr.line([p0, tip], fill=0, width=2)                  # folha
            ux_px, uy_px = (p1[0] - p0[0]) / wpx, (p1[1] - p0[1]) / wpx
            pts_arco = []
            for k in range(0, 31):
                th = math.radians(90 * k / 30)
                pts_arco.append((p0[0] + wpx * (math.cos(th) * ux_px + math.sin(th) * nx),
                                 p0[1] + wpx * (math.cos(th) * uy_px - math.sin(th) * ny)))
            dr.line(pts_arco, fill=0, width=1)                   # arco da porta

    # distratores finos: retângulos que imitam móveis (não são paredes)
    for _ in range(3):
        cx, cy = rng.randrange(int(min(xs) + 900), int(max(xs) - 900)), rng.randrange(int(min(ys) + 900), int(max(ys) - 900))
        # só desenha se estiver dentro do polígono (teste simples por caixa dos eixos; pode cair fora num L: então é ruído)
        (x0, y0), (x1, y1) = px(cx - 300, cy - 200), px(cx + 300, cy + 200)
        dr.rectangle([min(x0, x1), min(y0, y1), max(x0, x1), max(y0, y1)], outline=0, width=1)

    # cota (face externa a face externa da base) e rótulo
    ext_mm = max(xs) - min(xs) + t
    yb = altura_px - 28
    xa, xb = MARGEM_PX, MARGEM_PX + ext_mm * PX_POR_MM
    dr.line([(xa, yb), (xb, yb)], fill=0, width=1)
    for xx in (xa, xb):
        dr.line([(xx, yb - 6), (xx, yb + 6)], fill=0, width=1)
    fonte = ImageFont.load_default(size=14)
    texto = f"{ext_mm / 1000:.2f} m".replace(".", ",")
    dr.text(((xa + xb) / 2, yb - 18), texto, fill=0, font=fonte, anchor="mm")
    cx_px, cy_px = px((min(xs) + max(xs)) / 2, (min(ys) + max(ys)) / 2)
    dr.text((cx_px, cy_px), "SALA", fill=0, font=ImageFont.load_default(size=16), anchor="mm")

    if ruido:
        a = np.asarray(img, dtype=float)
        a += np.random.default_rng(rng.randrange(10 ** 6)).normal(0, 12, a.shape)
        img = Image.fromarray(np.clip(a, 0, 255).astype("uint8")).filter(ImageFilter.GaussianBlur(0.8))
    return img, {"texto": texto, "medida_mm": ext_mm}


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--seed", type=int, required=True)
    ap.add_argument("--saida-dir", type=Path, required=True)
    ap.add_argument("--forma", choices=["retangulo", "L"], default="retangulo")
    ap.add_argument("--ruido", action="store_true")
    args = ap.parse_args()

    rng = random.Random(args.seed)
    pts = contorno(rng, args.forma)
    aberturas = posicionar_aberturas(rng, pts)
    img, cota = desenhar(pts, aberturas, rng, args.ruido)

    args.saida_dir.mkdir(parents=True, exist_ok=True)
    nome = "planta.jpg" if args.ruido else "planta.png"
    if args.ruido:
        buf = io.BytesIO()
        img.save(buf, "JPEG", quality=70)
        (args.saida_dir / nome).write_bytes(buf.getvalue())
    else:
        img.save(args.saida_dir / nome)
    gab = {"seed": args.seed, "forma": args.forma, "ruido": args.ruido, "px_por_mm": PX_POR_MM, "espessura_mm": ESPESSURA_MM,
           "contorno_eixo_mm": [list(p) for p in pts], "aberturas": aberturas, "cota": cota}
    (args.saida_dir / "gabarito.json").write_text(json.dumps(gab, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"OK: {args.saida_dir / nome} {img.size[0]}x{img.size[1]} px (gabarito.json escrito; não o leia antes de testar a leitura)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
