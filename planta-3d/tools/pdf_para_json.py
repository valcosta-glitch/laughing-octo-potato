#!/usr/bin/env python3
"""Da planta em PDF vetorial ao JSON intermediário (topologia livre) e ao script do SketchUp.

Uso:
  python3 pdf_para_json.py planta.pdf --saida-dir saida [--escala 50] [--regiao x0,y0,x1,y1]
      [--cor-parede r,g,b] [--cor-pilar r,g,b] [--pe-direito 2700] [--grade-mm 5] [--ajustes ajustes.json]

Escreve em --saida-dir: projeto.json, script_sketchup.py e overlay.png (peças e vãos numerados sobre a planta).

ajustes.json (opcional; o que a planta em PDF não traz, ou o que a pessoa/IA leu das etiquetas):
  {"pe_direito_mm": 2800,
   "vaos": {"5": {"tipo": "porta", "altura_mm": 2100, "peitoril_mm": 0},     # chave = número do vão no overlay
            "9": {"altura_mm": 600, "peitoril_mm": 1500},
            "12": {"remover": true}}}
Alturas padrão (porta 2100; janela 1200 com peitoril 1000) são marcadas 'inferida' e geram aviso.
"""
import argparse
import json
import sys
from pathlib import Path

from pdf_extrair import ErroPDF, analisar, montar, overlay
from gerar_script_sketchup import gerar_script
from validar import checar_projeto, SCHEMA_PADRAO

from jsonschema import Draft202012Validator

PE_DIREITO_PADRAO = 2700
PORTA_ALTURA = 2100
JANELA_ALTURA = 1200
JANELA_PEITORIL = 1000
CONF_PAREDE = 0.9
CONF_VAO = 0.8
CONF_ALTURA = 0.3


def _grade(v, g):
    return round(v / g) * g


def _caixa(p):
    a, b, t = p["inicio"], p["fim"], p["espessura_mm"]
    horiz = abs(a["y"] - b["y"]) < 1e-6
    x0, x1 = sorted([a["x"], b["x"]])
    y0, y1 = sorted([a["y"], b["y"]])
    return (x0, x1, y0 - t / 2, y1 + t / 2) if horiz else (x0 - t / 2, x1 + t / 2, y0, y1)


def aparar_sobreposicoes(paredes, g, minimo=10.0):
    """Quando duas caixas se sobrepõem, apara a ponta de uma delas (pilar nunca é aparado; entre paredes, a que
    atravessa a espessura inteira). Retorna quantas pontas foram aparadas e quantas sobreposições restaram."""
    aparadas, restam = 0, 0
    for i, P in enumerate(paredes):
        for Q in paredes[i + 1:]:
            bp, bq = _caixa(P), _caixa(Q)
            dx = min(bp[1], bq[1]) - max(bp[0], bq[0])
            dy = min(bp[3], bq[3]) - max(bp[2], bq[2])
            if dx <= minimo or dy <= minimo:
                continue
            ordem = [(Q, P)] if P["tipo"] == "pilar" else [(P, Q)] if Q["tipo"] == "pilar" else [(P, Q), (Q, P)]
            feito = False
            for A, B in ordem:                       # apara A contra B
                ba, bb = _caixa(A), _caixa(B)
                horiz = abs(A["inicio"]["y"] - A["fim"]["y"]) < 1e-6
                lo, hi = (ba[0], ba[1]) if horiz else (ba[2], ba[3])
                olo, ohi = ((max(ba[0], bb[0]), min(ba[1], bb[1])) if horiz else (max(ba[2], bb[2]), min(ba[3], bb[3])))
                cruzado = (dy if horiz else dx) >= A["espessura_mm"] - minimo      # a ponta de A atravessa B de lado a lado
                eixo = "x" if horiz else "y"
                if not cruzado:
                    continue
                if abs(olo - lo) < 1e-6 and ohi < hi:
                    novo = ohi
                    pts = ("inicio", "fim") if A["inicio"][eixo] <= A["fim"][eixo] else ("fim", "inicio")
                    A[pts[0]][eixo] = _grade(novo, g)
                    feito = True
                elif abs(ohi - hi) < 1e-6 and olo > lo:
                    novo = olo
                    pts = ("fim", "inicio") if A["inicio"][eixo] <= A["fim"][eixo] else ("inicio", "fim")
                    A[pts[0]][eixo] = _grade(novo, g)
                    feito = True
                if feito:
                    break
            if feito:
                aparadas += 1
            else:
                restam += 1
    return aparadas, restam


def converter_pdf(pdf, escala=None, regiao=None, cor_parede=None, cor_pilar=None, pe_direito=None, grade_mm=5.0, ajustes=None):
    """Retorna (projeto, avisos, r, a): projeto = JSON intermediário; r e a = extração, para o overlay."""
    ajustes = ajustes or {}
    r = montar(pdf, escala=escala, regiao=regiao, cor_parede=cor_parede, cor_pilar=cor_pilar)
    a = analisar(r)
    avisos = list(r["avisos"])
    mm_px, T = r["mm_px"], r["T"]
    g = grade_mm
    pecas, pilares = a["pecas"], r["pilares"]
    if not pecas:
        raise ErroPDF("nenhuma parede encontrada")

    todos_x = [p["x0"] for p in pecas] + [p["x1"] for p in pecas] + [q["x0"] for q in pilares] + [q["x1"] for q in pilares]
    todos_y = [p["y0"] for p in pecas] + [p["y1"] for p in pecas] + [q["y0"] for q in pilares] + [q["y1"] for q in pilares]
    x_min, y_max = min(todos_x), max(todos_y)

    def X(px):
        return _grade((px - x_min) * mm_px, g)

    def Y(py):
        return _grade((y_max - py) * mm_px, g)

    esp = _grade(a["Tv"] * mm_px, g)
    paredes, ajustadas = [], 0
    for k, p in enumerate(sorted(pecas, key=lambda p: (p["orient"], p["c"], p["a0"])), 1):
        medida = (p["y1"] - p["y0"] if p["orient"] == "h" else p["x1"] - p["x0"]) * mm_px
        if abs(medida - esp) <= 0.2 * esp:
            t = esp                       # variações de até 20% (o desenho tem paredes de 150 a 160 mm) viram a espessura típica
        else:
            t = _grade(medida, g)
            ajustadas += 1
        if p["orient"] == "h":
            ini, fim = {"x": X(p["a0"]), "y": Y(p["c"])}, {"x": X(p["a1"]), "y": Y(p["c"])}
        else:
            ini, fim = {"x": X(p["c"]), "y": Y(p["a0"])}, {"x": X(p["c"]), "y": Y(p["a1"])}
        paredes.append({"id": f"p{k}", "inicio": ini, "fim": fim, "espessura_mm": t, "eixo": "centro",
                        "tipo": "parede", "origem": "medida", "confianca": CONF_PAREDE})
    for k, q in enumerate(sorted(pilares, key=lambda q: (q["y0"], q["x0"])), 1):
        cy = (q["y0"] + q["y1"]) / 2
        paredes.append({"id": f"pil{k}", "inicio": {"x": X(q["x0"]), "y": Y(cy)}, "fim": {"x": X(q["x1"]), "y": Y(cy)},
                        "espessura_mm": _grade((q["y1"] - q["y0"]) * mm_px, g), "eixo": "centro",
                        "tipo": "pilar", "origem": "medida", "confianca": CONF_PAREDE})
    aparadas, restam = aparar_sobreposicoes(paredes, g)
    if aparadas:
        avisos.append(f"{aparadas} ponta(s) de parede aparada(s) para não sobrepor outra caixa (colagem de vértices, até ~35 mm)")
    if ajustadas:
        avisos.append(f"{ajustadas} parede(s) com espessura diferente da típica ({esp:g} mm) (>20%) mantiveram a espessura medida; as demais foram normalizadas para {esp:g} mm")

    vaos, altura_inferida = [], 0
    adj = ajustes.get("vaos", {})
    passagens = []
    for n, v in enumerate(a["vaos"], 1):
        aj = adj.get(str(n), {})
        if aj.get("remover"):
            avisos.append(f"vão {n} removido pelos ajustes")
            continue
        tipo = aj.get("tipo", v["tipo_sugerido"])
        larg = _grade((v["a1"] - v["a0"]) * mm_px, g)
        if v["orient"] == "h":
            centro, eixo = {"x": X((v["a0"] + v["a1"]) / 2), "y": Y(v["c"])}, "x"
        else:
            centro, eixo = {"x": X(v["c"]), "y": Y((v["a0"] + v["a1"]) / 2)}, "y"
        alt = aj.get("altura_mm", PORTA_ALTURA if tipo == "porta" else JANELA_ALTURA)
        peit = aj.get("peitoril_mm", 0 if tipo == "porta" else JANELA_PEITORIL)
        inferida = "altura_mm" not in aj
        altura_inferida += inferida
        ev = (f"{v['paralelas']} linhas paralelas na faixa da parede" if tipo == "janela"
              else f"folha de porta ({v['folhas']}) e linhas de batente {v['batentes']}")
        vaos.append({"id": f"v{n}", "tipo": tipo, "eixo": eixo, "centro": centro, "largura_mm": larg,
                     "espessura_mm": esp, "altura_mm": alt, "peitoril_mm": peit,
                     "origem": "medida" if not inferida else "inferida",
                     "confianca": CONF_VAO if not inferida else CONF_ALTURA, "evidencia": ev})
    for d in a["descartados"]:
        if min(d["batentes"]) >= 1 and (d["a1"] - d["a0"]) * mm_px <= 1600:
            passagens.append(round((d["a1"] - d["a0"]) * mm_px))
    if altura_inferida:
        avisos.append(f"{altura_inferida} vão(s) com altura/peitoril PADRÃO (porta {PORTA_ALTURA} mm; janela {JANELA_ALTURA} mm a {JANELA_PEITORIL} mm do piso): "
                      "a planta baixa não traz alturas; confirme pela legenda ou pelo corte (--ajustes).")
    if passagens:
        avisos.append(f"{len(passagens)} passagem(ns) com batente e sem folha (larguras {passagens} mm) ficam ABERTAS (sem parede, sem esquadria).")
    avisos.append(f"Vãos sem símbolo reconhecível (folha de porta, 3+ linhas de janela) foram tratados como espaço aberto: {len(a['descartados'])} candidato(s) descartado(s).")
    avisos.append(f"Máscara de paredes coberta em {r['cobertura'] * 100:.1f}% pelas peças ({r['migalhas']} migalha(s) ignorada(s)). "
                  f"Resolução da extração: {mm_px:.1f} mm/px; bordas coladas nos vértices do desenho.")
    if pe_direito is None:
        pe_direito = ajustes.get("pe_direito_mm")
    if pe_direito is None:
        pe_direito = PE_DIREITO_PADRAO
        avisos.append(f"Pé-direito PADRÃO {PE_DIREITO_PADRAO} mm (a planta baixa não o traz; use o corte ou --pe-direito).")
    avisos.append("O piso é uma laje retangular sob a caixa envolvente das paredes (não segue o contorno real).")

    maior = max((p for p in paredes if p["tipo"] == "parede"), key=lambda p: abs(p["fim"]["x"] - p["inicio"]["x"]) + abs(p["fim"]["y"] - p["inicio"]["y"]))
    comp = abs(maior["fim"]["x"] - maior["inicio"]["x"]) + abs(maior["fim"]["y"] - maior["inicio"]["y"])
    projeto = {
        "schema_version": "0.1.0",
        "projeto": {"nome": Path(pdf).stem, "unidade": "mm",
                    "calibracao": {"ponto_a": maior["inicio"], "ponto_b": maior["fim"], "medida_mm": comp,
                                   "origem": "usuario" if escala is not None else "inferida"}},
        "fonte": {"tipo": "pdf_vetorial", "arquivo": Path(pdf).name, "confianca_global": CONF_VAO},
        "pavimentos": [{"id": "pav1", "nome": "Pavimento", "cota_piso_mm": 0, "pe_direito_mm": pe_direito,
                        "topologia": "livre", "paredes": paredes, "vaos": vaos}],
    }
    avisos.append(f"Calibração: escala 1:{r['escala']} do desenho (1 pt = {r['mm_pt']:.3f} mm); conferir com uma cota impressa.")
    return projeto, avisos, r, a


def _cor(txt):
    return tuple(float(v) for v in txt.split(","))


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("pdf", type=Path)
    ap.add_argument("--saida-dir", type=Path, required=True)
    ap.add_argument("--pagina", type=int, default=1)
    ap.add_argument("--escala", type=int)
    ap.add_argument("--regiao", help="x0,y0,x1,y1 em pontos do PDF")
    ap.add_argument("--cor-parede")
    ap.add_argument("--cor-pilar")
    ap.add_argument("--pe-direito", type=float)
    ap.add_argument("--grade-mm", type=float, default=5.0)
    ap.add_argument("--ajustes", type=Path)
    args = ap.parse_args()

    ajustes = json.loads(args.ajustes.read_text(encoding="utf-8")) if args.ajustes else None
    regiao = tuple(float(v) for v in args.regiao.split(",")) if args.regiao else None
    try:
        projeto, avisos, r, a = converter_pdf(args.pdf, args.escala, regiao, _cor(args.cor_parede) if args.cor_parede else None,
                                              _cor(args.cor_pilar) if args.cor_pilar else None, args.pe_direito, args.grade_mm, ajustes)
    except ErroPDF as e:
        print(f"ERRO: {e}")
        return 1
    schema = json.loads(SCHEMA_PADRAO.read_text(encoding="utf-8"))
    erros = [e.message for e in Draft202012Validator(schema).iter_errors(projeto)]
    avisos_geo = []
    if not erros:
        erros, avisos_geo = checar_projeto(projeto)
    for w in avisos + avisos_geo:
        print(f"AVISO: {w}")
    if erros:
        for e in erros:
            print(f"ERRO: {e}")
        return 1
    args.saida_dir.mkdir(parents=True, exist_ok=True)
    (args.saida_dir / "projeto.json").write_text(json.dumps(projeto, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    script = gerar_script(projeto)
    (args.saida_dir / "script_sketchup.py").write_text(script, encoding="utf-8")
    overlay(r, a, args.saida_dir / "overlay.png")
    pav = projeto["pavimentos"][0]
    print(f"OK: {len(pav['paredes'])} caixas (paredes e pilares), {len(pav['vaos'])} vãos. Escrito em {args.saida_dir}/ "
          f"(projeto.json, script_sketchup.py: {len(script)} caracteres, overlay.png).")
    return 0


if __name__ == "__main__":
    sys.exit(main())
