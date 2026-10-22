#!/usr/bin/env python3
"""Extrai paredes e vãos de uma imagem de planta baixa por visão computacional clássica (numpy + Pillow).

Uso: python3 imagem_extrair.py planta.png --saida-dir saida [--tmin-px N] [--lmin-px N] [--gap-min-px N]

A imagem é desinclinada automaticamente (até ±4 graus) antes da extração.

Escreve em --saida-dir:
  extracao.json   paredes (eixo, de canto a canto, em pixels) e vãos candidatos (aberturas), numerados
  overlay.png     a imagem com as paredes e os vãos numerados, para conferência e para a etapa de classificação

O que faz: separa o que é parede (faixa escura GROSSA e longa, na horizontal ou na vertical) do que é
traço fino (arcos de porta, cotas, texto, móveis). Os vãos são as interrupções de uma parede.
NÃO decide se um vão é porta ou janela (isso é da classificação, que vem da I.A. ou da pessoa) e NÃO lê
a escala (idem).

Limites: paredes só horizontais e verticais (a imagem pode estar girada até ±4 graus); um contorno fechado;
paredes desenhadas como faixa escura SÓLIDA (linha dupla, hachura e traço muito claro não são reconhecidos: dá erro claro);
as paredes têm todas a mesma espessura; imagem limpa o bastante para o limiar de Otsu separar a tinta do papel.
"""
import argparse
import json
import sys
from pathlib import Path

import numpy as np
from PIL import Image, ImageDraw, ImageFont

LMIN_PADRAO_PX = None   # None = 1,5 x a espessura típica da parede (mín. 12 px)
LMIN_ESTIMATIVA_PX = 25
GIRO_MAX_GRAUS = 4.0
GIRO_MIN_CORRIGIR = 0.1
GAP_MIN_PADRAO_PX = 20
TOL_PX = 3.0


class ErroExtracao(Exception):
    pass


def otsu(a):
    hist, _ = np.histogram(a, bins=256, range=(0, 256))
    total = a.size
    soma = float(np.dot(np.arange(256), hist))
    soma_b = 0.0
    peso_b = 0
    melhor, limiar = -1.0, 128
    for t in range(256):
        peso_b += hist[t]
        if peso_b == 0:
            continue
        peso_f = total - peso_b
        if peso_f == 0:
            break
        soma_b += t * hist[t]
        m_b, m_f = soma_b / peso_b, (soma - soma_b) / peso_f
        var = peso_b * peso_f * (m_b - m_f) ** 2
        if var > melhor:
            melhor, limiar = var, t
    return limiar


def corridas(linha):
    """[(x0, x1_inclusivo)] das corridas de True de um vetor booleano."""
    d = np.diff(np.concatenate(([0], linha.astype(np.int8), [0])))
    ini = np.flatnonzero(d == 1)
    fim = np.flatnonzero(d == -1)
    return list(zip(ini.tolist(), (fim - 1).tolist()))


def comprimento_das_corridas(m):
    """Para cada pixel verdadeiro, o comprimento da corrida horizontal que o contém."""
    out = np.zeros(m.shape, dtype=np.int32)
    for i in range(m.shape[0]):
        for x0, x1 in corridas(m[i]):
            out[i, x0:x1 + 1] = x1 - x0 + 1
    return out


def retangulos(mask, tol=2):
    """Decompõe uma máscara em retângulos empilhando corridas de linhas consecutivas.

    Retorna [(x0, x1, y0, y1)] inclusivos. As extremidades x0/x1 são percentis (70 / 30) das extremidades de
    cada linha da faixa, não o máximo: um traço fino que invade só parte da espessura da parede (a folha ou o
    arco de uma porta, que nascem no eixo da parede) não encurta o vão."""
    abertos, prontos = [], []
    for y in range(mask.shape[0]):
        novos, usados = [], set()
        for x0, x1 in corridas(mask[y]):
            achou = None
            for k, r in enumerate(abertos):
                if k not in usados and r["y1"] == y - 1 and abs(r["x0s"][-1] - x0) <= tol and abs(r["x1s"][-1] - x1) <= tol:
                    achou = k
                    break
            if achou is None:
                novos.append({"x0s": [x0], "x1s": [x1], "y0": y, "y1": y})
            else:
                r = abertos[achou]
                r["y1"] = y
                r["x0s"].append(x0)
                r["x1s"].append(x1)
                usados.add(achou)
                novos.append(r)
        prontos.extend(r for k, r in enumerate(abertos) if k not in usados)
        abertos = novos
    prontos.extend(abertos)
    return [(int(round(np.percentile(r["x0s"], 70))), int(round(np.percentile(r["x1s"], 30))), r["y0"], r["y1"]) for r in prontos]


def segmentos_da_mascara(mask, tmin, lmin, horizontal):
    """Faixas grossas e longas -> segmentos {c, a, b, esp} (c = coordenada do eixo da faixa, a..b = extensão)."""
    m = mask if horizontal else mask.T
    segs = []
    for x0, x1, y0, y1 in retangulos(m):
        esp = y1 - y0 + 1
        comp = x1 - x0 + 1
        if esp >= tmin and comp >= lmin:
            segs.append({"c": (y0 + y1 + 1) / 2.0, "a": float(x0), "b": float(x1 + 1), "esp": float(esp)})
    return segs


def agrupar(segs, gap_min):
    """Agrupa segmentos colineares (mesmo c) numa parede; as quebras maiores que gap_min viram vãos.
    Retorna [{c, a, b, esp, vaos: [(ini, fim)]}]."""
    segs = sorted(segs, key=lambda s: (s["c"], s["a"]))
    grupos = []
    for s in segs:
        for g in grupos:
            if abs(g["c"] - s["c"]) <= TOL_PX:
                g["partes"].append(s)
                break
        else:
            grupos.append({"c": s["c"], "partes": [s]})
    paredes = []
    for g in grupos:
        partes = sorted(g["partes"], key=lambda s: s["a"])
        vaos = []
        fim = partes[0]["b"]
        for p in partes[1:]:
            if p["a"] - fim > gap_min:
                vaos.append((fim, p["a"]))
            fim = max(fim, p["b"])
        paredes.append({
            "c": float(np.mean([p["c"] for p in partes])),
            "a": partes[0]["a"], "b": fim,
            "esp": float(np.median([p["esp"] for p in partes])),
            "vaos": vaos,
        })
    return paredes


def estimar_giro(img):
    """Ângulo (graus) que, aplicado à imagem, deixa as paredes alinhadas aos eixos: maximiza a nitidez dos
    perfis de soma por linha e por coluna da máscara escura. Busca grossa em ±GIRO_MAX e refino de 0,05."""
    pequena = img if max(img.size) <= 900 else img.resize((img.width * 900 // max(img.size), img.height * 900 // max(img.size)))
    lim = otsu(np.asarray(pequena, dtype=float))

    def nitidez(ang):
        r = np.asarray(pequena.rotate(ang, resample=Image.BILINEAR, fillcolor=255), dtype=float) <= lim
        return float(np.var(r.sum(axis=1)) + np.var(r.sum(axis=0)))

    grossos = np.arange(-GIRO_MAX_GRAUS, GIRO_MAX_GRAUS + 1e-9, 0.25)
    melhor = max(grossos, key=nitidez)
    finos = np.arange(melhor - 0.25, melhor + 0.25 + 1e-9, 0.05)
    return float(max(finos, key=nitidez))


def extrair(caminho, tmin_px=None, lmin_px=LMIN_PADRAO_PX, gap_min_px=GAP_MIN_PADRAO_PX, limiar=None):
    """Retorna o dicionário da extração (coordenadas em pixels; y para baixo)."""
    avisos = []
    img = Image.open(caminho).convert("L")
    giro = estimar_giro(img)
    if abs(giro) >= GIRO_MIN_CORRIGIR:
        img = img.rotate(giro, resample=Image.BICUBIC, fillcolor=255)
        avisos.append(f"Imagem desinclinada em {giro:+.2f} graus antes da extração (o overlay mostra a imagem já corrigida).")
    a = np.asarray(img, dtype=float)
    limiar = otsu(a) if limiar is None else limiar
    escuro = a <= limiar

    h_run = comprimento_das_corridas(escuro)
    v_run = comprimento_das_corridas(escuro.T).T

    if tmin_px is None:
        # espessura típica da parede: moda da espessura (corrida do outro sentido) nos pixels de corridas longas
        cand = np.concatenate([v_run[(h_run >= LMIN_ESTIMATIVA_PX) & (v_run >= 4)], h_run[(v_run >= LMIN_ESTIMATIVA_PX) & (h_run >= 4)]])
        if cand.size == 0:
            raise ErroExtracao(
                "Nenhuma faixa escura grossa e longa encontrada: não há paredes reconhecíveis. Causas comuns: paredes desenhadas em "
                "linha dupla/hachuradas (sem preenchimento sólido), resolução muito baixa, traço muito claro; "
                "ajuste --tmin-px/--lmin-px ou prepare a imagem (preencher as paredes)."
            )
        vals, cont = np.unique(cand, return_counts=True)
        tipica = int(vals[np.argmax(cont)])
        tmin_px = max(5, int(round(tipica * 0.6)))
        avisos.append(f"Espessura típica estimada em {tipica} px; --tmin-px = {tmin_px}.")
        if lmin_px is None:
            lmin_px = max(12, int(round(tipica * 1.5)))
    if lmin_px is None:
        lmin_px = 40

    m_h = (v_run >= tmin_px) & (h_run >= lmin_px)
    m_v = (h_run >= tmin_px) & (v_run >= lmin_px)
    H = agrupar(segmentos_da_mascara(m_h, tmin_px, lmin_px, True), gap_min_px)
    V = agrupar(segmentos_da_mascara(m_v, tmin_px, lmin_px, False), gap_min_px)
    if not H or not V:
        raise ErroExtracao("Só há paredes em uma direção: não há contorno fechado.")

    esp = float(np.median([p["esp"] for p in H + V]))
    if esp < 6:
        avisos.append(f"RESOLUÇÃO MUITO BAIXA: a parede tem só {esp:.0f} px de espessura. Vãos e trechos curtos de parede podem ser PERDIDOS "
                      f"sem erro; use uma imagem maior (parede com 8 px ou mais) e confira o overlay.")
    elif esp < 10:
        avisos.append(f"Resolução baixa: a parede tem {esp:.0f} px de espessura; a precisão cai (erro de 1 a 2 px) e vãos pequenos podem se perder. "
                      f"Confira o overlay.")

    # cantos: o fim de uma parede encosta numa perpendicular cujo eixo está a esp/2 do fim
    def ajustar(paredes, perp, esp_perp):
        for p in paredes:
            for ponta, sinal in (("a", +1), ("b", -1)):
                alvo = p[ponta] + sinal * esp_perp / 2
                achou = [q for q in perp if abs(q["c"] - alvo) <= TOL_PX and q["a"] - TOL_PX <= p["c"] <= q["b"] + TOL_PX]
                if achou:
                    p[ponta + "_corner"] = achou[0]["c"]
                else:
                    p[ponta + "_corner"] = None
    ajustar(H, V, esp)
    ajustar(V, H, esp)
    livres = 0
    for p in H + V:
        for ponta in ("a", "b"):
            if p[ponta + "_corner"] is not None:
                p[ponta] = p[ponta + "_corner"]
            else:
                livres += 1
    if livres:
        avisos.append(f"{livres} ponta(s) de parede sem parede perpendicular: o contorno pode não estar fechado.")

    paredes_json, aberturas = [], []
    for i, p in enumerate(H + V):
        horizontal = i < len(H)
        ini = [p["a"], p["c"]] if horizontal else [p["c"], p["a"]]
        fim = [p["b"], p["c"]] if horizontal else [p["c"], p["b"]]
        paredes_json.append({"id": i, "direcao": "H" if horizontal else "V", "inicio_px": ini, "fim_px": fim})
    for i, p in enumerate(H + V):
        for (v0, v1) in sorted(p["vaos"]):
            horizontal = i < len(H)
            aberturas.append({
                "id": len(aberturas) + 1, "parede": i,
                "inicio_px": [v0, p["c"]] if horizontal else [p["c"], v0],
                "fim_px": [v1, p["c"]] if horizontal else [p["c"], v1],
                "largura_px": round(v1 - v0, 1),
            })
    return {
        "imagem": {"arquivo": Path(caminho).name, "largura_px": int(a.shape[1]), "altura_px": int(a.shape[0]), "giro_corrigido_graus": round(giro, 2)},
        "parametros": {"limiar": int(limiar), "tmin_px": int(tmin_px), "lmin_px": int(lmin_px), "gap_min_px": int(gap_min_px)},
        "espessura_px": esp,
        "paredes": paredes_json,
        "aberturas": aberturas,
        "avisos": avisos,
    }


def desenhar_overlay(caminho_imagem, extracao, destino):
    img = Image.open(caminho_imagem).convert("L")
    giro = extracao["imagem"].get("giro_corrigido_graus", 0.0)
    if abs(giro) >= GIRO_MIN_CORRIGIR:
        img = img.rotate(giro, resample=Image.BICUBIC, fillcolor=255)
    img = img.convert("RGB")
    d = ImageDraw.Draw(img)
    fonte = ImageFont.load_default(size=15)
    for p in extracao["paredes"]:
        d.line([tuple(p["inicio_px"]), tuple(p["fim_px"])], fill=(0, 120, 255), width=1)
    for ab in extracao["aberturas"]:
        (x0, y0), (x1, y1) = ab["inicio_px"], ab["fim_px"]
        d.line([(x0, y0), (x1, y1)], fill=(255, 0, 0), width=3)
        cx, cy = (x0 + x1) / 2, (y0 + y1) / 2
        d.text((cx, cy - 18 if abs(y0 - y1) < 1 else cy), str(ab["id"]), fill=(255, 0, 0), font=fonte, anchor="mm")
    img.save(destino)


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("imagem", type=Path)
    ap.add_argument("--saida-dir", type=Path, required=True)
    ap.add_argument("--tmin-px", type=int)
    ap.add_argument("--lmin-px", type=int, default=LMIN_PADRAO_PX, help="padrão: 1,5 x a espessura típica")
    ap.add_argument("--gap-min-px", type=int, default=GAP_MIN_PADRAO_PX)
    args = ap.parse_args()
    try:
        ext = extrair(args.imagem, args.tmin_px, args.lmin_px, args.gap_min_px)
    except ErroExtracao as e:
        print(f"ERRO: {e}")
        return 1
    args.saida_dir.mkdir(parents=True, exist_ok=True)
    (args.saida_dir / "extracao.json").write_text(json.dumps(ext, indent=2), encoding="utf-8")
    desenhar_overlay(args.imagem, ext, args.saida_dir / "overlay.png")
    for w in ext["avisos"]:
        print(f"AVISO: {w}")
    print(f"OK: {len(ext['paredes'])} paredes, {len(ext['aberturas'])} vãos candidatos, espessura {ext['espessura_px']:.1f} px. "
          f"Escreveu extracao.json e overlay.png em {args.saida_dir}/")
    return 0


if __name__ == "__main__":
    sys.exit(main())
