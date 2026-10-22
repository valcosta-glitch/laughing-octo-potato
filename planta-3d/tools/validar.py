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


def checar_pavimento(pav, vistas, erros, avisos):
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
        amb = ambientes.get(m["ambiente_id"])
        if amb is None:
            erros.append(f"móvel '{m['id']}': ambiente '{m['ambiente_id']}' não existe")
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
