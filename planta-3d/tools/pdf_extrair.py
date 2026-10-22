#!/usr/bin/env python3
"""Extrai paredes, pilares e vãos de uma planta baixa em PDF VETORIAL (AutoCAD/Revit plotado), sem I.A.

Uso: python3 pdf_extrair.py planta.pdf --escala 50 --saida-dir saida [--pagina 1] [--regiao x0,y0,x1,y1]
                           [--cor-parede 0.5,0.5,0.5] [--cor-pilar 1,0.5,0]

  --escala N      denominador da escala do desenho (1:50 -> 50). Se omitido, procura "1:NN" no texto da página.
  --regiao        recorta uma parte da página (em pontos do PDF, origem no canto superior esquerdo): útil quando
                  a folha tem duas plantas.
  --cor-parede    cor do preenchimento das paredes (RGB 0-1). Sem ela, escolhe a cor cujos polígonos
                  parecem faixas de parede (retângulos alongados de 80 a 350 mm de espessura).

O que faz: lê os polígonos preenchidos da cor das paredes, monta uma máscara exata, decompõe em peças retas
(horizontais e verticais) com a espessura medida, acha os vãos (lacunas entre peças da mesma linha e trechos
rebaixados sob janelas) e classifica cada vão como porta (símbolo com arco/folha) ou janela por vetores.
NÃO lê texto desenhado como curva (cotas e etiquetas de muitos PDFs), então alturas e peitoris NÃO vêm
daqui: ficam como padrão e são marcados "inferida".

Escreve em --saida-dir: extracao_pdf.json e overlay.png (peças numeradas, vãos em cores).

Limites: paredes só ortogonais; paredes desenhadas como POLÍGONO PREENCHIDO (paredes em linha dupla sem
preenchimento ainda não são tratadas: o programa avisa e sai); uma planta por região.
"""
import argparse
import json
import re
import sys
from collections import deque
from pathlib import Path

import numpy as np
import pymupdf
from PIL import Image, ImageDraw

PX_POR_PT = 4                 # resolução da máscara: 0,25 pt/px (~4,4 mm em 1:50)
ESP_MIN_MM = 80.0
ESP_MAX_MM = 350.0
FINA_FRAC = 0.7               # trecho mais fino que isto x espessura = parede rebaixada (vira vão)
VAO_MIN_MM = 300.0
VAO_MAX_MM = 4000.0
AREA_MIN_FRAC = 0.5           # peça com área < 0,5 x esp^2 é migalha
PORTA_MAX_MM = 1600.0
TOL_LINHA_MM = 60.0           # tolerância para considerar duas peças na mesma linha de eixo
VIZINHO_MIN_T = 0.5           # peça vizinha de um vão: mínimo de 0,5 x espessura (toco entre a porta e a parede transversal)

PT_MM_1 = 25.4 / 72.0         # mm de papel por ponto


class ErroPDF(Exception):
    pass


def _cor(c):
    return None if c is None else tuple(round(float(v), 2) for v in c)


def _poligonos(item_lista):
    """Subcaminhos do desenho como polígonos (lista de listas de (x, y)). Um subcaminho novo começa onde
    um segmento não continua o anterior; cada um é preenchido sozinho (união), como um PDF de preenchimento
    'nonzero' com subcaminhos de mesmo sentido. Retorna [] se houver curva (não é faixa de parede)."""
    subs, atual = [], []

    def ponto(q):
        return (q.x, q.y)

    def fecha():
        nonlocal atual
        pts = []
        for q in atual:
            if not pts or abs(pts[-1][0] - q[0]) > 1e-6 or abs(pts[-1][1] - q[1]) > 1e-6:
                pts.append(q)
        if len(pts) >= 3:
            subs.append(pts)
        atual = []

    for it in item_lista:
        if it[0] == "c":
            return []
        if it[0] == "l":
            segs = [(ponto(it[1]), ponto(it[2]))]
        elif it[0] == "re":
            r = it[1]
            segs = [((r.x0, r.y0), (r.x1, r.y0)), ((r.x1, r.y0), (r.x1, r.y1)), ((r.x1, r.y1), (r.x0, r.y1)), ((r.x0, r.y1), (r.x0, r.y0))]
        elif it[0] == "qu":
            q = it[1]
            a, b, c, d = ponto(q.ul), ponto(q.ur), ponto(q.lr), ponto(q.ll)
            segs = [(a, b), (b, c), (c, d), (d, a)]
        else:
            continue
        for a, b in segs:
            if atual and (abs(atual[-1][0] - a[0]) > 1e-3 or abs(atual[-1][1] - a[1]) > 1e-3):
                fecha()
            if not atual:
                atual.append(a)
            atual.append(b)
    fecha()
    return subs


def _ler_escala(pagina):
    achou = re.search(r"1\s*[:/]\s*(\d{2,3})\b", pagina.get_text())
    return int(achou.group(1)) if achou else None


def _recorta(r, regiao):
    if regiao is None:
        return True
    x0, y0, x1, y1 = regiao
    return r.x0 >= x0 - 1 and r.x1 <= x1 + 1 and r.y0 >= y0 - 1 and r.y1 <= y1 + 1


def escolher_cor_parede(desenhos, escala, regiao):
    """Cor de preenchimento com mais 'faixas de parede': retângulos alongados com espessura plausível."""
    mm_pt = PT_MM_1 * escala
    pontos = {}
    for d in desenhos:
        cor = _cor(d.get("fill"))
        if cor is None or cor == (1.0, 1.0, 1.0) or not _recorta(d["rect"], regiao):
            continue
        r = d["rect"]
        curto, longo = sorted([r.width, r.height])
        if curto * mm_pt < ESP_MIN_MM or curto * mm_pt > ESP_MAX_MM or longo < 2 * curto:
            continue
        pontos[cor] = pontos.get(cor, 0.0) + longo * mm_pt
    if not pontos:
        return None
    return max(pontos, key=pontos.get)


def mascara_de(desenhos, cor, regiao, caixa):
    """Máscara booleana (linhas = y para baixo) dos polígonos preenchidos com `cor`."""
    x0, y0, x1, y1 = caixa
    K = PX_POR_PT
    img = Image.new("L", (int((x1 - x0) * K) + 2, int((y1 - y0) * K) + 2), 0)
    dr = ImageDraw.Draw(img)
    n = 0
    for d in desenhos:
        if _cor(d.get("fill")) != cor or not _recorta(d["rect"], regiao):
            continue
        for poly in _poligonos(d["items"]):
            dr.polygon([((x - x0) * K, (y - y0) * K) for x, y in poly], fill=255)
        n += 1
    return np.asarray(img) > 127, n


def comprimento_corridas(m, eixo):
    """Para cada pixel verdadeiro, o comprimento da corrida contínua que o contém (eixo=1: horizontal)."""
    a = m if eixo == 1 else m.T
    pad = np.zeros((a.shape[0], a.shape[1] + 2), dtype=bool)
    pad[:, 1:-1] = a
    flat = pad.ravel()
    ini = flat & ~np.concatenate(([False], flat[:-1]))
    ids = np.cumsum(ini)
    tam = np.bincount(ids[flat], minlength=ids.max() + 1)
    out = np.where(flat, tam[ids], 0).reshape(pad.shape)[:, 1:-1]
    return out if eixo == 1 else out.T


def rotular(m):
    """Componentes conexas (4-vizinhança) por BFS. Retorna lista de arrays (ys, xs)."""
    h, w = m.shape
    visto = np.zeros_like(m, dtype=bool)
    comps = []
    ys, xs = np.nonzero(m)
    for y0, x0 in zip(ys, xs):
        if visto[y0, x0]:
            continue
        fila = deque([(y0, x0)])
        visto[y0, x0] = True
        py, px = [], []
        while fila:
            y, x = fila.popleft()
            py.append(y)
            px.append(x)
            for yy, xx in ((y - 1, x), (y + 1, x), (y, x - 1), (y, x + 1)):
                if 0 <= yy < h and 0 <= xx < w and m[yy, xx] and not visto[yy, xx]:
                    visto[yy, xx] = True
                    fila.append((yy, xx))
        comps.append((np.array(py), np.array(px)))
    return comps


def espessura_tipica_px(m):
    hr, vr = comprimento_corridas(m, 1), comprimento_corridas(m, 0)
    esp = np.minimum(hr, vr)[m]
    esp = esp[esp >= 4]
    if esp.size == 0:
        raise ErroPDF("máscara de paredes vazia")
    cont = np.bincount(esp)
    # moda suavizada em janela de 3 px (o desenho tem variações de ~0,3 pt)
    suave = np.convolve(cont, np.ones(3), mode="same")
    return int(np.argmax(suave)), hr, vr


def decompor(m):
    """Peças retas da máscara. Cada peça: dict(orient, c0, c1, a0, a1) em pixels (meio aberto, [a0, a1) ao longo)."""
    T, hr, vr = espessura_tipica_px(m)
    # fino = estreito E comprido (parede rebaixada sob janela); toco curto e gordo continua sendo parede
    fina = (np.minimum(hr, vr) < FINA_FRAC * T) & (np.maximum(hr, vr) >= 1.5 * T)
    solido = m & ~fina
    hr, vr = comprimento_corridas(solido, 1), comprimento_corridas(solido, 0)
    horiz = solido & (hr >= vr)
    vert = solido & (vr > hr)
    pecas, migalhas = [], 0
    for orient, mk in (("h", horiz), ("v", vert)):
        for ys, xs in rotular(mk):
            y0, y1, x0, x1 = ys.min(), ys.max() + 1, xs.min(), xs.max() + 1
            if len(ys) < AREA_MIN_FRAC * T * T:
                migalhas += 1
                continue
            cheio = len(ys) / float((y1 - y0) * (x1 - x0))
            pecas.append({"orient": orient, "x0": int(x0), "x1": int(x1), "y0": int(y0), "y1": int(y1), "cheio": round(cheio, 3)})
    return T, _absorver_tampas(pecas, T), migalhas, solido


def _absorver_tampas(pecas, T, tol=None):
    """Um quadradinho T x T na ponta de uma peça perpendicular, com a mesma largura dela e encostado na sua
    ponta, é a continuação dessa peça (o desenho o cortou como 'horizontal' por empate de corridas)."""
    tol = tol if tol is not None else max(3, int(0.25 * T))
    mudou = True
    while mudou:
        mudou = False
        for S in pecas:
            comp = max(S["x1"] - S["x0"], S["y1"] - S["y0"])
            if comp > 1.5 * T:
                continue
            for P in pecas:
                if P is S or P["orient"] == S["orient"]:
                    continue
                if P["orient"] == "v":      # S horizontal sobre a ponta (cima/baixo) de P vertical
                    if abs(S["x0"] - P["x0"]) <= tol and abs(S["x1"] - P["x1"]) <= tol and \
                            (abs(S["y1"] - P["y0"]) <= tol or abs(S["y0"] - P["y1"]) <= tol):
                        P["y0"], P["y1"] = min(P["y0"], S["y0"]), max(P["y1"], S["y1"])
                        pecas.remove(S)
                        mudou = True
                        break
                else:                       # S vertical na ponta (esq/dir) de P horizontal
                    if abs(S["y0"] - P["y0"]) <= tol and abs(S["y1"] - P["y1"]) <= tol and \
                            (abs(S["x1"] - P["x0"]) <= tol or abs(S["x0"] - P["x1"]) <= tol):
                        P["x0"], P["x1"] = min(P["x0"], S["x0"]), max(P["x1"], S["x1"])
                        pecas.remove(S)
                        mudou = True
                        break
            if mudou:
                break
    return pecas


def montar(pdf, pagina_n=1, escala=None, regiao=None, cor_parede=None, cor_pilar=None):
    doc = pymupdf.open(pdf)
    pg = doc[pagina_n - 1]
    avisos = []
    if pg.rotation:
        avisos.append(f"página girada {pg.rotation} graus: coordenadas lidas no espaço não girado do desenho")
    if escala is None:
        escala = _ler_escala(pg)
        if escala is None:
            raise ErroPDF("escala não informada e não encontrada no texto da página: use --escala N")
        avisos.append(f"escala 1:{escala} lida do texto da página")
    desenhos = pg.get_drawings()
    cor = cor_parede or escolher_cor_parede(desenhos, escala, regiao)
    if cor is None:
        raise ErroPDF("nenhum preenchimento parece parede (faixas alongadas de 80 a 350 mm). "
                      "Paredes em linha dupla sem preenchimento ainda não são suportadas.")
    caixa = tuple(regiao) if regiao else (0.0, 0.0, pg.rect.width, pg.rect.height)
    m, n_poly = mascara_de(desenhos, cor, regiao, caixa)
    mm_pt = PT_MM_1 * escala
    mm_px = mm_pt / PX_POR_PT

    # pilares: retângulos de outra cor dada (opcional); recortados da máscara de paredes
    pilares = []
    if cor_pilar:
        mp, _ = mascara_de(desenhos, tuple(cor_pilar), regiao, caixa)
        for ys, xs in rotular(mp):
            if len(ys) < 25:
                continue
            pilares.append({"x0": int(xs.min()), "x1": int(xs.max()) + 1, "y0": int(ys.min()), "y1": int(ys.max()) + 1})
        m = m & ~mp

    T, pecas, migalhas, solido = decompor(m)
    esp_mm = T * mm_px
    if not ESP_MIN_MM <= esp_mm <= ESP_MAX_MM:
        avisos.append(f"espessura típica {esp_mm:.0f} mm fora de 80–350 mm: confira a escala (1:{escala})")
    cobertura = 0.0
    if m.sum():
        cob = np.zeros_like(m)
        for p in pecas:
            cob[p["y0"]:p["y1"], p["x0"]:p["x1"]] = True
        cobertura = float((cob & m).sum()) / float(m.sum())
    return {"doc": doc, "pagina": pg, "desenhos": desenhos, "escala": escala, "cor": cor, "n_poly": n_poly, "caixa": caixa,
            "m": m, "solido": solido, "T": T, "pecas": pecas, "migalhas": migalhas, "pilares": pilares, "mm_px": mm_px,
            "cobertura": cobertura, "avisos": avisos, "mm_pt": mm_pt}


def _vertices_vetoriais(r):
    """Coordenadas (em px da máscara) dos vértices dos polígonos de parede e de pilar: servem para colar as bordas
    das peças nas coordenadas exatas do desenho."""
    K = PX_POR_PT
    x0, y0 = r["caixa"][0], r["caixa"][1]
    xs, ys = [], []
    for d in r["desenhos"]:
        if _cor(d.get("fill")) != r["cor"] or not _recorta(d["rect"], None):
            continue
        for poly in _poligonos(d["items"]):
            for x, y in poly:
                xs.append((x - x0) * K)
                ys.append((y - y0) * K)
    return np.array(sorted(set(np.round(xs, 3)))), np.array(sorted(set(np.round(ys, 3))))


def _cola(v, grade, tol=1.5):
    if grade.size == 0:
        return float(v)
    i = int(np.argmin(np.abs(grade - v)))
    return float(grade[i]) if abs(grade[i] - v) <= tol else float(v)


def analisar(r):
    """Peças refinadas em mm, vãos (com tipo sugerido por vetores) e pilares. Coordenadas: x para a direita,
    y para CIMA, origem no canto inferior esquerdo da caixa das paredes."""
    K, mm_px, T = PX_POR_PT, r["mm_px"], r["T"]
    gx, gy = _vertices_vetoriais(r)
    # espessura vetorial: mediana das dimensões curtas dos retângulos de parede (em px)
    curtas = []
    for d in r["desenhos"]:
        if _cor(d.get("fill")) == r["cor"]:
            rc = d["rect"]
            c = min(rc.width, rc.height) * K
            if 0.8 * T <= c <= 1.25 * T:
                curtas.append(c)
    Tv = float(np.median(curtas)) if curtas else float(T)

    pecas = []
    for p in r["pecas"]:
        x0, x1 = _cola(p["x0"], gx), _cola(p["x1"], gx)
        y0, y1 = _cola(p["y0"], gy), _cola(p["y1"], gy)
        pecas.append({"orient": p["orient"], "x0": x0, "x1": x1, "y0": y0, "y1": y1})
    # eixo e vão ao longo
    for p in pecas:
        if p["orient"] == "h":
            p["c"], p["a0"], p["a1"] = (p["y0"] + p["y1"]) / 2, p["x0"], p["x1"]
        else:
            p["c"], p["a0"], p["a1"] = (p["x0"] + p["x1"]) / 2, p["y0"], p["y1"]
    # alinha eixos colineares (média do grupo)
    for o in ("h", "v"):
        grupo = sorted([p for p in pecas if p["orient"] == o], key=lambda p: p["c"])
        cluster = []
        for p in grupo:
            if cluster and abs(p["c"] - cluster[-1][-1]["c"]) * mm_px <= TOL_LINHA_MM:
                cluster[-1].append(p)
            else:
                cluster.append([p])
        for cl in cluster:
            media = sum(q["c"] for q in cl) / len(cl)
            for q in cl:
                q["c"] = media
                q["linha"] = round(media, 1)

    ocup = r["solido"].copy()
    for q in r["pilares"]:
        ocup[q["y0"]:q["y1"], q["x0"]:q["x1"]] = True

    vaos = []
    por_linha = {}
    for p in pecas:
        por_linha.setdefault((p["orient"], p["linha"]), []).append(p)
    H, W = ocup.shape
    max_px = int(VAO_MAX_MM / mm_px)

    def faixa_ocupada(o, c, ini, fim):
        """Para cada posição ao longo da parede entre ini e fim, há tinta na faixa central (±T/4)?"""
        lo, hi = int(round(c - T / 4)), int(round(c + T / 4)) + 1
        ini, fim = max(ini, 0), min(fim, W if o == "h" else H)
        if fim <= ini:
            return np.zeros(0, dtype=bool)
        return ocup[lo:hi, ini:fim].any(axis=0) if o == "h" else ocup[ini:fim, lo:hi].any(axis=1)

    achados = {}
    for (o, c), L in por_linha.items():
        for A in L:
            if A["a1"] - A["a0"] < 2 * T:
                continue                                         # toco curto não origina vão (origina falso vão de nicho)
            for sentido in (1, -1):
                ponta = A["a1"] if sentido == 1 else A["a0"]
                if sentido == 1:
                    faixa = faixa_ocupada(o, c, int(round(ponta)), int(round(ponta)) + max_px + int(3 * T))
                else:
                    faixa = faixa_ocupada(o, c, int(round(ponta)) - max_px - int(3 * T), int(round(ponta)))[::-1]
                if faixa.size == 0:
                    continue
                n = len(faixa)
                i = 0
                while i < n and faixa[i] and i <= 2.5 * T:      # pula tocos de parede colados na peça
                    i += 1
                if i > 2.5 * T:
                    continue
                j = i
                while j < n and not faixa[j]:
                    j += 1
                if j >= n:
                    continue                                     # sem tinta do outro lado: espaço aberto, não vão
                larg = (j - i) * mm_px
                if not VAO_MIN_MM <= larg <= VAO_MAX_MM:
                    continue
                v0, v1 = (int(round(ponta)) + i, int(round(ponta)) + j) if sentido == 1 else (int(round(ponta)) - j, int(round(ponta)) - i)
                grade = gx if o == "h" else gy
                v0, v1 = _cola(v0, grade), _cola(v1, grade)
                chave = (o, round(c / 3), round(v0 / 4), round(v1 / 4))
                achados[chave] = {"orient": o, "c": c, "a0": v0, "a1": v1}
    vaos = sorted(achados.values(), key=lambda v: (v["orient"], v["c"], v["a0"]))

    # evidências vetoriais dentro da faixa de cada vão
    mm_pt_ = r["mm_pt"]
    for v in vaos:
        w = v["a1"] - v["a0"]
        if v["orient"] == "h":
            band = (v["a0"] / K, (v["c"] - T / 2) / K, v["a1"] / K, (v["c"] + T / 2) / K)
        else:
            band = ((v["c"] - T / 2) / K, v["a0"] / K, (v["c"] + T / 2) / K, v["a1"] / K)
        band = (band[0] + r["caixa"][0], band[1] + r["caixa"][1], band[2] + r["caixa"][0], band[3] + r["caixa"][1])
        wpt = w / K
        par = 0
        for d in r["desenhos"]:
            for it in d["items"]:
                if it[0] != "l":
                    continue
                p1, p2 = it[1], it[2]
                if (min(p1.x, p2.x) >= band[0] - 1 and max(p1.x, p2.x) <= band[2] + 1
                        and min(p1.y, p2.y) >= band[1] - 1 and max(p1.y, p2.y) <= band[3] + 1):
                    along = abs(p2.x - p1.x) if v["orient"] == "h" else abs(p2.y - p1.y)
                    if along >= 0.6 * wpt:
                        par += 1
        # folha de porta: retângulo fino, perpendicular à parede, com comprimento ~ largura do vão, encostado na faixa
        folhas = 0
        for d in r["desenhos"]:
            R = d["rect"]
            curto, longo = sorted([R.width, R.height])
            if curto > 3.2 or not 0.6 * wpt <= longo <= 1.3 * wpt:
                continue
            if v["orient"] == "h":
                perpendicular = R.height > R.width
                dentro = min(abs(R.x0 - band[0]), abs(R.x1 - band[0]), abs(R.x0 - band[2]), abs(R.x1 - band[2])) <= 4.0
                encosta = abs(R.y1 - band[1]) <= 2.5 or abs(R.y0 - band[3]) <= 2.5
            else:
                perpendicular = R.width > R.height
                dentro = min(abs(R.y0 - band[1]), abs(R.y1 - band[1]), abs(R.y0 - band[3]), abs(R.y1 - band[3])) <= 4.0
                encosta = abs(R.x1 - band[0]) <= 2.5 or abs(R.x0 - band[2]) <= 2.5
            if perpendicular and dentro and encosta:
                folhas += 1
            # folha aberta a 90 graus contra a parede: paralela, colada à face, com uma ponta junto a uma ponta do vão
            elif not perpendicular:
                if v["orient"] == "h":
                    colada = abs(R.y1 - band[1]) <= 4.5 or abs(R.y0 - band[3]) <= 4.5
                    pts_leaf, pts_vao = (R.x0, R.x1), (band[0], band[2])
                else:
                    colada = abs(R.x1 - band[0]) <= 4.5 or abs(R.x0 - band[2]) <= 4.5
                    pts_leaf, pts_vao = (R.y0, R.y1), (band[1], band[3])
                cobre = min(abs(x - y) for x in pts_leaf for y in pts_vao) <= 10.0
                if colada and cobre and 0.7 * wpt <= longo <= 1.05 * wpt:
                    folhas += 1
        # linhas de batente: traço perpendicular que atravessa a espessura da parede, junto a cada ponta do vão
        pontas = [0, 0]
        for d in r["desenhos"]:
            for it in d["items"]:
                if it[0] != "l":
                    continue
                p1, p2 = it[1], it[2]
                if v["orient"] == "h":
                    perp = abs(p1.x - p2.x) < 0.3 and 0.7 * (T / K) <= abs(p1.y - p2.y) <= 1.6 * (T / K)
                    pos, lo, hi = p1.x, min(p1.y, p2.y), max(p1.y, p2.y)
                    cruza = lo <= band[3] - 0.5 * (T / K) and hi >= band[1] + 0.5 * (T / K)
                    ini, fim = band[0], band[2]
                else:
                    perp = abs(p1.y - p2.y) < 0.3 and 0.7 * (T / K) <= abs(p1.x - p2.x) <= 1.6 * (T / K)
                    pos, lo, hi = p1.y, min(p1.x, p2.x), max(p1.x, p2.x)
                    cruza = lo <= band[2] - 0.5 * (T / K) and hi >= band[0] + 0.5 * (T / K)
                    ini, fim = band[1], band[3]
                if perp and cruza:
                    if abs(pos - ini) <= 6.0:
                        pontas[0] += 1
                    if abs(pos - fim) <= 6.0:
                        pontas[1] += 1
        v["paralelas"], v["folhas"], v["batentes"] = par, folhas, pontas
        v["tipo_sugerido"] = "janela" if par >= 3 else ("porta" if folhas and wpt * mm_pt_ <= PORTA_MAX_MM else None)
    descartados = [v for v in vaos if v["tipo_sugerido"] is None]
    vaos = [v for v in vaos if v["tipo_sugerido"] is not None]
    return {"Tv": Tv, "pecas": pecas, "vaos": vaos, "descartados": descartados}


def overlay(r, a, caminho, zoom=1.6):
    """Planta ao fundo (esmaecida), peças em azul, pilares em laranja, vãos numerados (porta vermelho, janela verde)."""
    pg, K = r["pagina"], PX_POR_PT
    x0, y0, x1, y1 = r["caixa"]
    pix = pg.get_pixmap(matrix=pymupdf.Matrix(zoom, zoom), clip=pymupdf.Rect(x0, y0, x1, y1))
    img = Image.frombytes("RGB", (pix.width, pix.height), pix.samples).convert("L").point(lambda v: 150 + v * 105 // 255).convert("RGB")
    dr = ImageDraw.Draw(img, "RGBA")
    f = zoom / K

    def caixa(p, cor):
        dr.rectangle([p["x0"] * f, p["y0"] * f, p["x1"] * f, p["y1"] * f], fill=cor, outline=(0, 0, 160, 255))

    for p in a["pecas"]:
        caixa(p, (40, 90, 255, 110))
    for q in r["pilares"]:
        caixa(q, (255, 140, 0, 200))
    for i, v in enumerate(a["vaos"], 1):
        h = v["orient"] == "h"
        ret = ([v["a0"] * f, (v["c"] - r["T"] / 2) * f, v["a1"] * f, (v["c"] + r["T"] / 2) * f] if h
               else [(v["c"] - r["T"] / 2) * f, v["a0"] * f, (v["c"] + r["T"] / 2) * f, v["a1"] * f])
        cor = (230, 30, 30, 170) if v["tipo_sugerido"] == "porta" else (20, 170, 60, 170)
        dr.rectangle(ret, fill=cor)
        dr.text((ret[0] + 2, ret[1] - 12), str(i), fill=(0, 0, 0, 255))
    img.save(caminho)
