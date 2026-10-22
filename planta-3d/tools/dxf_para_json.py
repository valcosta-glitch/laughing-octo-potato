#!/usr/bin/env python3
"""Converte uma planta DXF simples no JSON intermediário (schema 0.1.0).

Convenção de camadas (nomes sem diferenciar maiúsculas):
  PAREDES  linhas ou polilinhas sobre o EIXO das paredes
  PORTAS   uma linha por porta, cobrindo o vão, apoiada sobre a parede
  JANELAS  uma linha por janela, cobrindo o vão, apoiada sobre a parede
  MOVEIS_<BLOCO>  um retângulo fechado (LWPOLYLINE de 4 pontos) por móvel, com a face de trás junto
           à parede; <BLOCO> é um bloco da biblioteca: MOVEIS_BALCAO_2_PORTAS, MOVEIS_AEREO_2_PORTAS,
           MOVEIS_GAVETEIRO_3_GAVETAS. Largura e profundidade vêm do retângulo; altura, chapa e
           elevação são padrões do bloco (BLOCOS_PADRAO).

Uso:
  python3 dxf_para_json.py planta.dxf saida.json [--unidade mm|cm|m]
      [--espessura 150] [--pe-direito 2700]
      [--calibracao x1,y1,x2,y2,medida_mm]

Limites desta versão: só paredes retas, um único contorno fechado (uma peça), móveis só
encostados (até 150 mm) numa parede e alinhados a ela, alturas de abertura padrão (a leitura do corte vem em outra fase). O que não vem do desenho
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

# Padrões por bloco (mm). "elevacao_mm" vai para o apoio; o resto vira "parametros".
BLOCOS_PADRAO = {
    "balcao_2_portas": {"altura_mm": 870, "portas": 2, "espessura_chapa_mm": 18, "socalo_mm": 100, "elevacao_mm": 0},
    "aereo_2_portas": {"altura_mm": 700, "portas": 2, "espessura_chapa_mm": 15, "elevacao_mm": 1400},
    "gaveteiro_3_gavetas": {"altura_mm": 870, "gavetas": 3, "espessura_chapa_mm": 18, "socalo_mm": 100, "elevacao_mm": 0},
}
ANCORA_MAX_MM = 150.0     # distância máxima da face de trás do móvel até a face interna da parede
PARALELO_GRAUS = 2.0      # tolerância de alinhamento do retângulo com a parede


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


def retangulo_da_entidade(e, fator):
    """Quatro cantos (mm) de um retângulo fechado, ou None."""
    t = e.dxftype()
    if t == "LWPOLYLINE" and e.closed:
        pts = [(p[0] * fator, p[1] * fator) for p in e.get_points("xy")]
    elif t == "POLYLINE" and e.is_closed:
        pts = [(v.dxf.location.x * fator, v.dxf.location.y * fator) for v in e.vertices]
    else:
        return None
    return pts if len(pts) == 4 else None


def ancorar_movel(pts, paredes):
    """Acha a parede de apoio do retângulo. Retorna (|omin|, parede, smin, smax, omin, omax) ou None.

    s = distância ao longo da parede a partir de 'inicio'; o = distância à face interna (para dentro)."""
    melhor = None
    for w in paredes:
        ax, ay = w["inicio"]["x"], w["inicio"]["y"]
        bx, by = w["fim"]["x"], w["fim"]["y"]
        L = math.hypot(bx - ax, by - ay)
        ux, uy = (bx - ax) / L, (by - ay) / L
        nx, ny = -uy, ux
        t = w["espessura_mm"]
        off_in = t / 2 if w["eixo"] == "centro" else (0.0 if w["eixo"] == "face_interna" else t)

        alinhado = True
        for i in range(4):
            ex, ey = pts[(i + 1) % 4][0] - pts[i][0], pts[(i + 1) % 4][1] - pts[i][1]
            el = math.hypot(ex, ey)
            if el < 1e-6:
                alinhado = False
                break
            if min(abs(ex * uy - ey * ux) / el, abs(ex * ux + ey * uy) / el) > math.sin(math.radians(PARALELO_GRAUS)):
                alinhado = False
                break
        if not alinhado:
            continue

        ss = [(x - ax) * ux + (y - ay) * uy for x, y in pts]
        oo = [(x - ax) * nx + (y - ay) * ny - off_in for x, y in pts]
        omin, omax, smin, smax = min(oo), max(oo), min(ss), max(ss)
        if abs(omin) > ANCORA_MAX_MM or smin < -ANCORA_MAX_MM or smax > L + ANCORA_MAX_MM:
            continue
        if melhor is None or abs(omin) < melhor[0]:
            melhor = (abs(omin), w, max(smin, 0.0), min(smax, L), omin, omax)
    return melhor


def ler_moveis(msp, fator, paredes, avisos):
    moveis = []
    contagem = {}
    for e in msp:
        camada = e.dxf.layer.upper()
        if not camada.startswith("MOVEIS_"):
            continue
        bloco = camada[len("MOVEIS_"):].lower()
        if bloco not in BLOCOS_PADRAO:
            avisos.append(f"camada {camada}: bloco '{bloco}' não existe na biblioteca ({sorted(BLOCOS_PADRAO)}); ignorada")
            continue
        pts = retangulo_da_entidade(e, fator)
        if pts is None:
            avisos.append(f"camada {camada}: entidade {e.dxftype()} não é um retângulo fechado de 4 pontos; ignorada")
            continue
        ancora = ancorar_movel(pts, paredes)
        if ancora is None:
            avisos.append(
                f"camada {camada}: retângulo em ({pts[0][0]:.0f},{pts[0][1]:.0f}) não está encostado (até {ANCORA_MAX_MM:g} mm) "
                f"nem alinhado a nenhuma parede; ignorado"
            )
            continue
        _, w, smin, smax, omin, omax = ancora
        afast = max(omin, 0.0)
        padrao = dict(BLOCOS_PADRAO[bloco])
        elevacao = padrao.pop("elevacao_mm")
        padrao["largura_mm"] = round(smax - smin, 1)
        padrao["profundidade_mm"] = round(omax - afast, 1)
        contagem[bloco] = contagem.get(bloco, 0) + 1
        moveis.append({
            "id": f"{bloco}_{contagem[bloco]}",
            "bloco": {"catalogo": "demo", "id": bloco, "versao": 1},
            "ambiente_id": "ambiente_1",
            "apoio": {"parede_id": w["id"], "distancia_do_inicio_mm": round(smin, 1),
                      "afastamento_mm": round(afast, 1), "elevacao_mm": elevacao},
            "parametros": padrao,
        })
    if moveis:
        avisos.append("Altura, espessura de chapa, zócalo e elevação dos móveis são padrões do bloco (não vêm do desenho).")
    return moveis


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
        pavimento["mobiliario"] = ler_moveis(msp, fator, paredes, avisos)
    elif any(e.dxf.layer.upper().startswith("MOVEIS_") for e in msp):
        avisos.append("Há móveis no DXF, mas sem um contorno fechado de paredes eles não são lidos.")

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
