#!/usr/bin/env python3
"""Converte uma planta DXF simples no JSON intermediário (schema 0.1.0).

Convenção de camadas (nomes sem diferenciar maiúsculas):
  PAREDES  linhas ou polilinhas sobre o EIXO das paredes
  PORTAS   uma linha por porta, cobrindo o vão, apoiada sobre a parede
  JANELAS  uma linha por janela, cobrindo o vão, apoiada sobre a parede

Uso:
  python3 dxf_para_json.py planta.dxf saida.json [--unidade mm|cm|m]
      [--espessura 150] [--pe-direito 2700]
      [--calibracao x1,y1,x2,y2,medida_mm]

Limites desta versão: só paredes retas, um único contorno fechado (uma peça), alturas
de abertura padrão (a leitura do corte vem em outra fase). O que não vem do desenho
sai marcado com origem 'inferida' para a tela de conferência.
"""
import argparse
import json
import math
import sys
from pathlib import Path

import ezdxf
from jsonschema import Draft202012Validator

from validar import SCHEMA_PADRAO, checar_projeto

INSUNITS_PARA_MM = {1: 25.4, 2: 304.8, 4: 1.0, 5: 10.0, 6: 1000.0}
UNIDADE_PARA_MM = {"mm": 1.0, "cm": 10.0, "m": 1000.0}

SNAP_MM = 2.0
ALTURA_PORTA_MM = 2100
ALTURA_JANELA_MM = 1000
PEITORIL_JANELA_MM = 1100
CONFIANCA_INFERIDA = 0.5


class ErroConversao(Exception):
    pass


def fator_unidade(doc, unidade_arg, avisos):
    if unidade_arg:
        return UNIDADE_PARA_MM[unidade_arg]
    codigo = doc.header.get("$INSUNITS", 0)
    if codigo in INSUNITS_PARA_MM:
        return INSUNITS_PARA_MM[codigo]
    raise ErroConversao(
        "O DXF não declara a unidade ($INSUNITS). Informe --unidade mm|cm|m."
    )


def segmentos_da_entidade(e, fator):
    """Devolve segmentos ((x1,y1),(x2,y2)) em mm de uma entidade."""
    t = e.dxftype()
    if t == "LINE":
        a, b = e.dxf.start, e.dxf.end
        return [((a.x * fator, a.y * fator), (b.x * fator, b.y * fator))]
    if t == "LWPOLYLINE":
        if any(abs(b) > 1e-9 for _, _, _, _, b in e.get_points("xyseb")):
            raise ErroConversao("Polilinha com arco: paredes curvas não são suportadas.")
        pts = [(p[0] * fator, p[1] * fator) for p in e.get_points("xy")]
    elif t == "POLYLINE":
        pts = [(v.dxf.location.x * fator, v.dxf.location.y * fator) for v in e.vertices]
    else:
        return []
    if e.closed and pts:
        pts = pts + [pts[0]]
    return list(zip(pts, pts[1:]))


def entidades_da_camada(msp, nome):
    return [e for e in msp if e.dxf.layer.upper() == nome]


def agrupar_pontos(segmentos):
    """Junta pontos a menos de SNAP_MM; devolve segmentos com pontos canônicos."""
    canonicos = []

    def canonico(p):
        for c in canonicos:
            if math.hypot(c[0] - p[0], c[1] - p[1]) <= SNAP_MM:
                return c
        canonicos.append(p)
        return p

    saida = []
    for a, b in segmentos:
        ca, cb = canonico(a), canonico(b)
        if ca != cb:
            saida.append((ca, cb))
    return saida


def ordenar_contorno_antihorario(segmentos):
    """Ordena segmentos em um único contorno fechado anti-horário, ou None."""
    adj = {}
    for i, (a, b) in enumerate(segmentos):
        adj.setdefault(a, []).append(i)
        adj.setdefault(b, []).append(i)
    if any(len(v) != 2 for v in adj.values()):
        return None

    usados, ordem = {0}, []
    atual = segmentos[0][1]
    ordem.append(segmentos[0])
    while True:
        proximos = [i for i in adj[atual] if i not in usados]
        if not proximos:
            break
        i = proximos[0]
        usados.add(i)
        a, b = segmentos[i]
        if a != atual:
            a, b = b, a
        ordem.append((a, b))
        atual = b
    if len(usados) != len(segmentos) or atual != ordem[0][0]:
        return None

    area = sum(a[0] * b[1] - b[0] * a[1] for a, b in ordem) / 2
    if area < 0:
        ordem = [(b, a) for a, b in reversed(ordem)]
    return ordem


def projetar(parede, p):
    """Distância ao longo da parede (a partir de 'inicio') e desvio perpendicular."""
    a, b = parede["inicio"], parede["fim"]
    dx, dy = b["x"] - a["x"], b["y"] - a["y"]
    comp = math.hypot(dx, dy)
    ux, uy = dx / comp, dy / comp
    rx, ry = p[0] - a["x"], p[1] - a["y"]
    return rx * ux + ry * uy, abs(rx * uy - ry * ux)


def construir_aberturas(msp, camada, tipo, paredes, espessura, fator, avisos):
    aberturas = []
    for e in entidades_da_camada(msp, camada):
        for p1, p2 in segmentos_da_entidade(e, fator):
            melhor = None
            for parede in paredes:
                s1, d1 = projetar(parede, p1)
                s2, d2 = projetar(parede, p2)
                if max(d1, d2) <= max(espessura, 50):
                    melhor = (parede, s1, s2)
                    break
            if melhor is None:
                avisos.append(
                    f"{tipo}: linha ({p1[0]:.0f},{p1[1]:.0f})-({p2[0]:.0f},{p2[1]:.0f}) "
                    f"não está sobre nenhuma parede; ignorada"
                )
                continue
            parede, s1, s2 = melhor
            ini, fim = sorted((s1, s2))
            aberturas.append({"tipo": tipo, "parede": parede, "posicao_mm": ini, "largura_mm": fim - ini})

    saida = []
    contagem = {}
    for ab in sorted(aberturas, key=lambda a: (a["parede"]["id"], a["posicao_mm"])):
        contagem[ab["tipo"]] = contagem.get(ab["tipo"], 0) + 1
        porta = ab["tipo"] == "porta"
        saida.append(
            {
                "id": f"{ab['tipo']}_{contagem[ab['tipo']]}",
                "tipo": ab["tipo"],
                "parede_id": ab["parede"]["id"],
                "posicao_mm": round(ab["posicao_mm"], 1),
                "largura_mm": round(ab["largura_mm"], 1),
                "altura_mm": ALTURA_PORTA_MM if porta else ALTURA_JANELA_MM,
                "peitoril_mm": 0 if porta else PEITORIL_JANELA_MM,
                "sentido_abertura": "nenhum",
                "origem": "inferida",
                "confianca": CONFIANCA_INFERIDA,
            }
        )
    return saida


def converter(caminho_dxf, unidade=None, espessura=150.0, pe_direito=2700.0, calibracao=None):
    """Retorna (projeto_dict, avisos)."""
    avisos = []
    doc = ezdxf.readfile(str(caminho_dxf))
    msp = doc.modelspace()
    fator = fator_unidade(doc, unidade, avisos)

    brutos = []
    for e in entidades_da_camada(msp, "PAREDES"):
        brutos.extend(segmentos_da_entidade(e, fator))
    if not brutos:
        raise ErroConversao("Nenhuma parede encontrada na camada PAREDES.")
    segmentos = agrupar_pontos(brutos)

    contorno = ordenar_contorno_antihorario(segmentos)
    if contorno is None:
        avisos.append(
            "As paredes não formam um único contorno fechado: nenhum ambiente foi criado e a "
            "orientação (lado interno à esquerda) NÃO é garantida. Confira na tela de conferência."
        )
        contorno = segmentos

    paredes = []
    for i, (a, b) in enumerate(contorno, 1):
        paredes.append(
            {
                "id": f"p_{i}",
                "inicio": {"x": round(a[0], 1), "y": round(a[1], 1)},
                "fim": {"x": round(b[0], 1), "y": round(b[1], 1)},
                "espessura_mm": espessura,
                "eixo": "centro",
                "origem": "inferida",
                "confianca": CONFIANCA_INFERIDA,
            }
        )
    avisos.append(f"Espessura das paredes assumida em {espessura:g} mm (não vem do desenho).")

    aberturas = construir_aberturas(msp, "PORTAS", "porta", paredes, espessura, fator, avisos)
    aberturas += construir_aberturas(msp, "JANELAS", "janela", paredes, espessura, fator, avisos)
    if aberturas:
        avisos.append(
            "Alturas de porta/janela e peitoril são padrão; a leitura do corte ainda não está implementada."
        )

    if calibracao:
        x1, y1, x2, y2, medida = calibracao
        cal = {
            "ponto_a": {"x": round(x1 * fator, 1), "y": round(y1 * fator, 1)},
            "ponto_b": {"x": round(x2 * fator, 1), "y": round(y2 * fator, 1)},
            "medida_mm": medida,
            "origem": "usuario",
        }
    else:
        p = paredes[0]
        comp = math.hypot(p["fim"]["x"] - p["inicio"]["x"], p["fim"]["y"] - p["inicio"]["y"])
        cal = {
            "ponto_a": p["inicio"],
            "ponto_b": p["fim"],
            "medida_mm": round(comp, 1),
            "origem": "inferida",
        }
        avisos.append(
            "Sem --calibracao: a escala vem só da unidade do DXF. Informe uma medida conhecida para "
            "calibrar de verdade."
        )

    pavimento = {
        "id": "terreo",
        "nome": "Térreo",
        "cota_piso_mm": 0,
        "pe_direito_mm": pe_direito,
        "paredes": paredes,
        "aberturas": aberturas,
        "ambientes": [],
        "mobiliario": [],
        "acabamentos": [],
    }
    if contorno is not segmentos:
        pavimento["ambientes"].append(
            {"id": "ambiente_1", "nome": "Ambiente 1", "paredes_ids": [p["id"] for p in paredes]}
        )

    projeto = {
        "schema_version": "0.1.0",
        "projeto": {
            "nome": Path(caminho_dxf).stem,
            "unidade": "mm",
            "calibracao": cal,
            "tolerancia_mm": 10,
        },
        "fonte": {"tipo": "dxf", "arquivo": Path(caminho_dxf).name, "confianca_global": CONFIANCA_INFERIDA},
        "pavimentos": [pavimento],
        "vistas": [],
        "historico_ajustes": [],
    }
    return projeto, avisos


def validar(projeto):
    schema = json.loads(SCHEMA_PADRAO.read_text(encoding="utf-8"))
    erros = [
        f"esquema em {'/'.join(str(p) for p in e.path) or '(raiz)'}: {e.message}"
        for e in Draft202012Validator(schema).iter_errors(projeto)
    ]
    if erros:
        return erros, []
    return checar_projeto(projeto)


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("dxf", type=Path)
    ap.add_argument("saida", type=Path)
    ap.add_argument("--unidade", choices=sorted(UNIDADE_PARA_MM))
    ap.add_argument("--espessura", type=float, default=150.0)
    ap.add_argument("--pe-direito", type=float, default=2700.0)
    ap.add_argument("--calibracao", help="x1,y1,x2,y2,medida_mm (pontos nas unidades do DXF)")
    args = ap.parse_args()

    calibracao = None
    if args.calibracao:
        try:
            calibracao = [float(v) for v in args.calibracao.split(",")]
            assert len(calibracao) == 5
        except (ValueError, AssertionError):
            ap.error("--calibracao precisa de 5 números: x1,y1,x2,y2,medida_mm")

    try:
        projeto, avisos = converter(args.dxf, args.unidade, args.espessura, args.pe_direito, calibracao)
    except ErroConversao as e:
        print(f"ERRO: {e}")
        return 1

    erros, avisos_geo = validar(projeto)
    for w in avisos + avisos_geo:
        print(f"AVISO: {w}")
    if erros:
        for e in erros:
            print(f"ERRO: {e}")
        return 1

    args.saida.write_text(json.dumps(projeto, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    pav = projeto["pavimentos"][0]
    print(
        f"OK: {args.saida} ({len(pav['paredes'])} paredes, {len(pav['aberturas'])} aberturas, "
        f"{len(pav['ambientes'])} ambiente(s))"
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
