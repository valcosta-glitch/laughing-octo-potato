#!/usr/bin/env python3
"""Valida um projeto intermediário contra o esquema e confere a coerência geométrica.

Uso: python3 validar.py caminho/projeto.json [--schema caminho/projeto.schema.json]

Saída: lista de erros (esquema ou geometria) e avisos. Código de saída 1 se houver erro.
"""
import argparse
import json
import math
import sys
from pathlib import Path

from jsonschema import Draft202012Validator

from acabamentos import ACABAMENTOS, CATALOGO_ID
from blocos import BLOCOS, FRENTES, LADOS, altura_do_movel, caixa_parede, extremos, completar, faltando, retangulo_movel

SCHEMA_PADRAO = Path(__file__).resolve().parent.parent / "schema" / "projeto.schema.json"


def comprimento(parede):
    a, b = parede["inicio"], parede["fim"]
    return math.hypot(b["x"] - a["x"], b["y"] - a["y"])


def checar_ids_unicos(itens, rotulo, erros):
    vistos = set()
    for item in itens:
        if item["id"] in vistos:
            erros.append(f"{rotulo}: id duplicado '{item['id']}'")
        vistos.add(item["id"])


def area_interna_aprox(paredes_do_ambiente):
    """Área interna para contorno convexo de ângulos retos e espessura uniforme.

    Retorna None quando a aproximação não vale (outro formato de contorno).
    """
    pts = [p["inicio"] for p in paredes_do_ambiente]
    n = len(pts)
    if n != 4:
        return None
    espessuras = {p["espessura_mm"] for p in paredes_do_ambiente}
    if len(espessuras) != 1 or any(p["eixo"] != "centro" for p in paredes_do_ambiente):
        return None
    t = espessuras.pop()
    area = 0.0
    for i in range(n):
        x1, y1 = pts[i]["x"], pts[i]["y"]
        x2, y2 = pts[(i + 1) % n]["x"], pts[(i + 1) % n]["y"]
        area += x1 * y2 - x2 * y1
    area = area / 2
    if area <= 0:  # contorno horário
        return None
    perimetro = sum(comprimento(p) for p in paredes_do_ambiente)
    return (area - perimetro * t / 2 + n * t * t / 4) / 1e6


def checar_livre(pav, erros, avisos):
    """Topologia livre: sem contorno fechado; confere vãos e sobreposição de caixas."""
    ctx = f"pavimento '{pav['id']}'"
    checar_ids_unicos(pav["paredes"], f"{ctx} paredes", erros)
    checar_ids_unicos(pav.get("vaos", []), f"{ctx} vãos", erros)
    checar_ids_unicos(pav.get("mobiliario", []), f"{ctx} mobiliario", erros)
    if pav.get("aberturas") or pav.get("ambientes"):
        erros.append(f"{ctx}: topologia 'livre' usa 'vaos' e móveis por 'lado'; 'aberturas' e 'ambientes' não são suportados")
    caixas = []
    for p in pav["paredes"]:
        if comprimento(p) == 0:
            erros.append(f"parede '{p['id']}': comprimento zero")
        a, b, t = p["inicio"], p["fim"], p["espessura_mm"]
        if abs(a["x"] - b["x"]) > 1e-6 and abs(a["y"] - b["y"]) > 1e-6:
            erros.append(f"parede '{p['id']}': não ortogonal (topologia livre só aceita paredes horizontais/verticais)")
            continue
        caixas.append((p["id"], min(a["x"], b["x"]) - (t / 2 if a["x"] == b["x"] else 0),
                       max(a["x"], b["x"]) + (t / 2 if a["x"] == b["x"] else 0),
                       min(a["y"], b["y"]) - (t / 2 if a["y"] == b["y"] else 0),
                       max(a["y"], b["y"]) + (t / 2 if a["y"] == b["y"] else 0)))
    for i in range(len(caixas)):
        for j in range(i + 1, len(caixas)):
            _, ax0, ax1, ay0, ay1 = caixas[i]
            _, bx0, bx1, by0, by1 = caixas[j]
            dx, dy = min(ax1, bx1) - max(ax0, bx0), min(ay1, by1) - max(ay0, by0)
            if dx > 20 and dy > 20:
                avisos.append(f"paredes '{caixas[i][0]}' e '{caixas[j][0]}' se sobrepõem em {dx:.0f} x {dy:.0f} mm (faces coplanares no topo)")
    for v in pav.get("vaos", []):
        c, w, e = v["centro"], v["largura_mm"], v["espessura_mm"]
        ret = (c["x"] - w / 2, c["x"] + w / 2, c["y"] - e / 2, c["y"] + e / 2) if v["eixo"] == "x" else \
              (c["x"] - e / 2, c["x"] + e / 2, c["y"] - w / 2, c["y"] + w / 2)
        for pid, bx0, bx1, by0, by1 in caixas:
            dx, dy = min(ret[1], bx1) - max(ret[0], bx0), min(ret[3], by1) - max(ret[2], by0)
            if dx > 20 and dy > 20:
                avisos.append(f"vão '{v['id']}' se sobrepõe à parede '{pid}' em {dx:.0f} x {dy:.0f} mm")
        if v.get("peitoril_mm", 0) + v["altura_mm"] > pav["pe_direito_mm"]:
            erros.append(f"vão '{v['id']}': ultrapassa o pé-direito")
        if v["tipo"] in ("porta", "porta_correr") and v.get("peitoril_mm", 0) != 0:
            avisos.append(f"vão '{v['id']}': porta com peitoril diferente de zero")
        if v["tipo"] == "porta_correr" and not 2 <= v.get("folhas", 3) <= 6:
            erros.append(f"vão '{v['id']}': porta de correr com {v.get('folhas')} folhas (2 a 6)")
        if v["tipo"] != "porta_correr" and "folhas" in v:
            erros.append(f"vão '{v['id']}': 'folhas' só vale para porta de correr")
    checar_moveis_livre(pav, erros, avisos)
    checar_acabamentos_livre(pav, erros)


def checar_acabamentos_livre(pav, erros):
    """Acabamentos na topologia livre: alvo 'parede' (com lado opcional) ou 'piso'; o item tem de existir no catálogo."""
    paredes = {p["id"]: p for p in pav["paredes"]}
    checar_ids_unicos(pav.get("acabamentos", []), f"pavimento '{pav['id']}' acabamentos", erros)
    vistos = set()
    for ac in pav.get("acabamentos", []):
        alvo, tex = ac["alvo"], ac["textura"]
        if tex["catalogo"] != CATALOGO_ID or tex["id"] not in ACABAMENTOS:
            erros.append(f"acabamento '{ac['id']}': '{tex['catalogo']}/{tex['id']}' não existe no catálogo de acabamentos")
        elif alvo["tipo"] == "parede" and "parede" not in ACABAMENTOS[tex["id"]]["uso"]:
            erros.append(f"acabamento '{ac['id']}': '{tex['id']}' não é para parede")
        elif alvo["tipo"] == "piso" and "piso" not in ACABAMENTOS[tex["id"]]["uso"]:
            erros.append(f"acabamento '{ac['id']}': '{tex['id']}' não é para piso")
        if alvo["tipo"] not in ("parede", "piso"):
            erros.append(f"acabamento '{ac['id']}': alvo '{alvo['tipo']}' ainda não é suportado na topologia livre (use 'parede' ou 'piso'; a frente do móvel é o parâmetro 'frente')")
            continue
        if alvo["tipo"] == "parede":
            p = paredes.get(alvo["id"])
            if p is None:
                erros.append(f"acabamento '{ac['id']}': parede '{alvo['id']}' não existe")
            elif p.get("tipo") == "pilar":
                erros.append(f"acabamento '{ac['id']}': '{alvo['id']}' é pilar")
            elif alvo.get("lado") and alvo["lado"] not in LADOS[eixo_da(p)]:
                erros.append(f"acabamento '{ac['id']}': a parede '{p['id']}' corre ao longo de {eixo_da(p).upper()}; o lado é {' ou '.join(LADOS[eixo_da(p)])}")
        chave = (alvo["tipo"], alvo["id"], alvo.get("lado"))
        if chave in vistos:
            erros.append(f"acabamento '{ac['id']}': já existe outro acabamento para o mesmo alvo ({alvo['tipo']} {alvo['id']}{' ' + alvo['lado'] if alvo.get('lado') else ''})")
        vistos.add(chave)


def eixo_da(p):
    return extremos(p)[0]


def checar_moveis_livre(pav, erros, avisos):
    """Móveis na topologia livre: cabem na parede, na altura, sem bater em outra parede, em outro móvel ou num vão."""
    paredes = {p["id"]: p for p in pav["paredes"]}
    tol = 1.0
    ocupados = []                                  # (id, parede_id, lado, s0, s1, z0, z1, retângulo em planta)
    for m in pav.get("mobiliario", []):
        mid, ap, par = m["id"], m["apoio"], m["parametros"]
        if m["bloco"]["id"] not in BLOCOS:
            erros.append(f"móvel '{mid}': bloco '{m['bloco']['id']}' sem desenho (conhecidos: {', '.join(sorted(BLOCOS))})")
            continue
        par = completar(m["bloco"]["id"], par)
        falta = faltando(m["bloco"]["id"], par)
        if falta:
            erros.append(f"móvel '{mid}': faltam parâmetros {', '.join(falta)}")
            continue
        if par.get("frente") is not None and par["frente"] not in FRENTES:
            erros.append(f"móvel '{mid}': frente '{par['frente']}' desconhecida (conhecidas: {', '.join(sorted(FRENTES))})")
        p = paredes.get(ap["parede_id"])
        if p is None:
            erros.append(f"móvel '{mid}': parede '{ap['parede_id']}' não existe")
            continue
        if p.get("tipo") == "pilar":
            erros.append(f"móvel '{mid}': não se apoia em pilar ('{p['id']}')")
            continue
        if abs(p["inicio"]["x"] - p["fim"]["x"]) > 1e-6 and abs(p["inicio"]["y"] - p["fim"]["y"]) > 1e-6:
            continue                               # parede não ortogonal já foi reportada
        lado = ap.get("lado")
        eixo, c, a0, a1 = extremos(p)
        if lado is None:
            erros.append(f"móvel '{mid}': falta o lado da parede '{p['id']}' ({' ou '.join(LADOS[eixo])})")
            continue
        if lado not in LADOS[eixo]:
            erros.append(f"móvel '{mid}': a parede '{p['id']}' corre ao longo de {eixo.upper()}; o lado é {' ou '.join(LADOS[eixo])}, não {lado}")
            continue
        W, D = par["largura_mm"], par.get("profundidade_mm", par.get("espessura_mm"))
        H = altura_do_movel(pav, m)
        s0 = ap["distancia_do_inicio_mm"]
        s1 = s0 + W
        z0 = ap.get("elevacao_mm", 0)
        z1 = z0 + H
        if s1 > (a1 - a0) + tol:
            erros.append(f"móvel '{mid}': passa do fim da parede '{p['id']}' ({s1:.0f} mm de {a1 - a0:.0f} mm)")
        if z1 > pav["pe_direito_mm"] + tol:
            erros.append(f"móvel '{mid}': ultrapassa o pé-direito ({z1:.0f} mm de {pav['pe_direito_mm']:.0f} mm)")
        ret = retangulo_movel(p, m, W, D)
        for q in pav["paredes"]:
            if q["id"] == p["id"] or abs(q["inicio"]["x"] - q["fim"]["x"]) > 1e-6 and abs(q["inicio"]["y"] - q["fim"]["y"]) > 1e-6:
                continue
            bx0, bx1, by0, by1 = caixa_parede(q)
            dx, dy = min(ret[1], bx1) - max(ret[0], bx0), min(ret[3], by1) - max(ret[2], by0)
            if dx > 20 and dy > 20:
                erros.append(f"móvel '{mid}' bate na parede '{q['id']}' ({dx:.0f} x {dy:.0f} mm dentro dela); ajuste a posição ou a largura")
        for v in pav.get("vaos", []):
            if v["eixo"] != eixo or abs((v["centro"]["y"] if eixo == "x" else v["centro"]["x"]) - c) > p["espessura_mm"] / 2 + 1:
                continue
            ca = v["centro"]["x"] if eixo == "x" else v["centro"]["y"]
            ov_s = min(a0 + s1, ca + v["largura_mm"] / 2) - max(a0 + s0, ca - v["largura_mm"] / 2)
            ov_z = min(z1, v.get("peitoril_mm", 0) + v["altura_mm"]) - max(z0, v.get("peitoril_mm", 0))
            if ov_s > tol and ov_z > tol:
                avisos.append(f"móvel '{mid}' cobre o vão '{v['id']}' ({ov_s:.0f} mm de largura)")
        for o in ocupados:
            ov_z = min(z1, o[6]) - max(z0, o[5])
            if o[1] == p["id"] and o[2] == lado and min(s1, o[4]) - max(s0, o[3]) > tol and ov_z > tol:
                erros.append(f"móveis '{o[0]}' e '{mid}' se sobrepõem na parede '{p['id']}' (lado {lado})")
            elif o[1] != p["id"] and ov_z > tol:
                dx, dy = min(ret[1], o[7][1]) - max(ret[0], o[7][0]), min(ret[3], o[7][3]) - max(ret[2], o[7][2])
                if dx > 20 and dy > 20:
                    avisos.append(f"móveis '{o[0]}' e '{mid}' se cruzam em planta ({dx:.0f} x {dy:.0f} mm)")
        ocupados.append((mid, p["id"], lado, s0, s1, z0, z1, ret))


def checar_pavimento(pav, vistas, erros, avisos):
    if pav.get("topologia") == "livre":
        checar_livre(pav, erros, avisos)
        return
    ctx = f"pavimento '{pav['id']}'"
    paredes = {p["id"]: p for p in pav["paredes"]}
    checar_ids_unicos(pav["paredes"], f"{ctx} paredes", erros)
    checar_ids_unicos(pav.get("aberturas", []), f"{ctx} aberturas", erros)
    checar_ids_unicos(pav.get("ambientes", []), f"{ctx} ambientes", erros)
    checar_ids_unicos(pav.get("mobiliario", []), f"{ctx} mobiliario", erros)

    for p in pav["paredes"]:
        if comprimento(p) == 0:
            erros.append(f"parede '{p['id']}': comprimento zero")
        altura = p.get("altura_mm", pav["pe_direito_mm"])
        if altura > pav["pe_direito_mm"]:
            avisos.append(f"parede '{p['id']}': altura {altura} maior que o pé-direito")

    por_parede = {}
    for a in pav.get("aberturas", []):
        parede = paredes.get(a["parede_id"])
        if parede is None:
            erros.append(f"abertura '{a['id']}': parede '{a['parede_id']}' não existe")
            continue
        fim = a["posicao_mm"] + a["largura_mm"]
        if fim > comprimento(parede) + 1e-6:
            erros.append(
                f"abertura '{a['id']}': ocupa até {fim:.0f} mm, mas a parede "
                f"'{parede['id']}' tem {comprimento(parede):.0f} mm"
            )
        altura = parede.get("altura_mm", pav["pe_direito_mm"])
        if a.get("peitoril_mm", 0) + a["altura_mm"] > altura:
            erros.append(f"abertura '{a['id']}': ultrapassa a altura da parede '{parede['id']}'")
        por_parede.setdefault(parede["id"], []).append(a)

    for pid, itens in por_parede.items():
        itens.sort(key=lambda a: a["posicao_mm"])
        for anterior, atual in zip(itens, itens[1:]):
            if atual["posicao_mm"] < anterior["posicao_mm"] + anterior["largura_mm"]:
                erros.append(f"aberturas '{anterior['id']}' e '{atual['id']}' se sobrepõem em '{pid}'")

    ambientes = {a["id"]: a for a in pav.get("ambientes", [])}
    for amb in ambientes.values():
        lista = []
        for pid in amb["paredes_ids"]:
            if pid not in paredes:
                erros.append(f"ambiente '{amb['id']}': parede '{pid}' não existe")
            else:
                lista.append(paredes[pid])
        if len(lista) != len(amb["paredes_ids"]):
            continue
        for atual, seguinte in zip(lista, lista[1:] + lista[:1]):
            f, i = atual["fim"], seguinte["inicio"]
            if math.hypot(f["x"] - i["x"], f["y"] - i["y"]) > 1.0:
                erros.append(
                    f"ambiente '{amb['id']}': parede '{atual['id']}' não encosta em '{seguinte['id']}' (contorno aberto)"
                )
        declarada = amb.get("area_declarada_m2")
        calculada = area_interna_aprox(lista)
        if declarada is not None and calculada is not None:
            if abs(calculada - declarada) / declarada > 0.05:
                avisos.append(
                    f"ambiente '{amb['id']}': área declarada {declarada:.2f} m² x calculada {calculada:.2f} m² (>5%)"
                )

    for m in pav.get("mobiliario", []):
        parede = paredes.get(m["apoio"]["parede_id"])
        if parede is None:
            erros.append(f"móvel '{m['id']}': parede '{m['apoio']['parede_id']}' não existe")
            continue
        amb = ambientes.get(m.get("ambiente_id"))
        if amb is None:
            erros.append(f"móvel '{m['id']}': ambiente '{m.get('ambiente_id')}' não existe (obrigatório no modo contorno)")
        elif parede["id"] not in amb["paredes_ids"]:
            erros.append(f"móvel '{m['id']}': parede '{parede['id']}' não pertence ao ambiente '{amb['id']}'")
        largura = m["parametros"].get("largura_mm")
        if largura is not None:
            fim = m["apoio"]["distancia_do_inicio_mm"] + largura
            if fim > comprimento(parede) + 1e-6:
                erros.append(f"móvel '{m['id']}': passa do fim da parede '{parede['id']}'")

    # móveis que ocupam o mesmo espaço (mesma parede, intervalos de s e de z se cruzam)
    movs = pav.get("mobiliario", [])
    for i in range(len(movs)):
        for j in range(i + 1, len(movs)):
            a, b = movs[i], movs[j]
            if a["apoio"]["parede_id"] != b["apoio"]["parede_id"]:
                continue
            sa0 = a["apoio"]["distancia_do_inicio_mm"]
            sa1 = sa0 + a["parametros"].get("largura_mm", 0)
            sb0 = b["apoio"]["distancia_do_inicio_mm"]
            sb1 = sb0 + b["parametros"].get("largura_mm", 0)
            za0 = a["apoio"].get("elevacao_mm", 0)
            za1 = za0 + a["parametros"].get("altura_mm", 0)
            zb0 = b["apoio"].get("elevacao_mm", 0)
            zb1 = zb0 + b["parametros"].get("altura_mm", 0)
            if min(sa1, sb1) - max(sa0, sb0) > 1e-6 and min(za1, zb1) - max(za0, zb0) > 1e-6:
                erros.append(f"móveis '{a['id']}' e '{b['id']}' se sobrepõem na parede '{a['apoio']['parede_id']}'")

    # móvel que cruza porta ou janela da mesma parede (aviso: pode ser intencional, ex. aéreo acima da janela)
    for m in movs:
        sm0 = m["apoio"]["distancia_do_inicio_mm"]
        sm1 = sm0 + m["parametros"].get("largura_mm", 0)
        zm0 = m["apoio"].get("elevacao_mm", 0)
        zm1 = zm0 + m["parametros"].get("altura_mm", 0)
        for ab in pav.get("aberturas", []):
            if ab["parede_id"] != m["apoio"]["parede_id"]:
                continue
            za0 = ab.get("peitoril_mm", 0)
            za1 = za0 + ab["altura_mm"]
            if (min(sm1, ab["posicao_mm"] + ab["largura_mm"]) - max(sm0, ab["posicao_mm"]) > 1e-6
                    and min(zm1, za1) - max(zm0, za0) > 1e-6):
                avisos.append(f"móvel '{m['id']}' cruza a abertura '{ab['id']}'")

    ids_alvo = (
        set(paredes)
        | {m["id"] for m in pav.get("mobiliario", [])}
        | set(ambientes)
    )
    for ac in pav.get("acabamentos", []):
        alvo = ac["alvo"]
        if alvo["tipo"] != "piso" and alvo["id"] not in ids_alvo:
            erros.append(f"acabamento '{ac['id']}': alvo '{alvo['id']}' não existe")


def checar_projeto(dados):
    erros, avisos = [], []

    cal = dados["projeto"]["calibracao"]
    a, b = cal["ponto_a"], cal["ponto_b"]
    medida = math.hypot(b["x"] - a["x"], b["y"] - a["y"])
    tol = dados["projeto"].get("tolerancia_mm", 10)
    if abs(medida - cal["medida_mm"]) > tol:
        erros.append(
            f"calibração: pontos distam {medida:.1f} mm, mas a medida informada é {cal['medida_mm']} mm (tolerância {tol})"
        )

    checar_ids_unicos(dados["pavimentos"], "pavimentos", erros)
    for pav in dados["pavimentos"]:
        checar_pavimento(pav, dados.get("vistas", []), erros, avisos)

    pavs = {p["id"] for p in dados["pavimentos"]}
    for v in dados.get("vistas", []):
        if v["pavimento_id"] not in pavs:
            erros.append(f"vista '{v['id']}': pavimento '{v['pavimento_id']}' não existe")

    return erros, avisos


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("projeto", type=Path)
    ap.add_argument("--schema", type=Path, default=SCHEMA_PADRAO)
    args = ap.parse_args()

    schema = json.loads(args.schema.read_text(encoding="utf-8"))
    dados = json.loads(args.projeto.read_text(encoding="utf-8"))

    problemas = sorted(Draft202012Validator(schema).iter_errors(dados), key=lambda e: list(e.path))
    if problemas:
        for e in problemas:
            caminho = "/".join(str(p) for p in e.path) or "(raiz)"
            print(f"ERRO esquema em {caminho}: {e.message}")
        return 1

    erros, avisos = checar_projeto(dados)
    for e in erros:
        print(f"ERRO: {e}")
    for w in avisos:
        print(f"AVISO: {w}")
    if not erros:
        print(f"OK: {args.projeto.name} ({len(avisos)} aviso(s))")
    return 1 if erros else 0


if __name__ == "__main__":
    sys.exit(main())
