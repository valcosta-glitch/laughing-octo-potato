#!/usr/bin/env python3
"""Da extração de uma imagem (paredes e vãos em pixels) ao JSON intermediário e ao script do SketchUp.

Uso:
  python3 imagem_para_json.py extracao.json classificacao.json --saida-dir saida [--grade-mm 10] [--pe-direito 2700]

  extracao.json       saída de imagem_extrair.py
  classificacao.json  o que a imagem diz e a geometria não: o tipo de cada vão, a escala e (opcional) o nome do ambiente

classificacao.json:
  {
    "calibracao": {"parede": 1, "referencia": "externa", "medida_mm": 6150, "origem": "cota lida: 6,15 m"},
    "aberturas": {"1": "janela", "2": "janela", "3": "porta"},     # id do vão -> "porta" | "janela" | "ignorar"
    "ambiente": "SALA"
  }
  referencia: "externa" (face a face externa da parede), "eixo" ou "interna" -- o que a cota mede.
  "ignorar": o vão não é abertura (ex.: interrupção por ruído); a parede segue contínua.

Faz: pixels -> milímetros (escala da cota, y invertido), arredonda à grade, monta um DXF em memória com as
camadas PAREDES/PORTAS/JANELAS e passa pelo MESMO conversor e validador do fluxo DXF. Escreve projeto.json e
script_sketchup.py. Sai com código 1, sem escrever nada, se algum vão não foi classificado ou se a validação falhar.
"""
import argparse
import json
import math
import sys
import tempfile
from pathlib import Path

import ezdxf
from ezdxf import units

from dxf_para_json import converter, validar
from gerar_script_sketchup import gerar_script

CONFIANCA_IMAGEM = 0.6


class ErroImagem(Exception):
    pass


def escala_mm_por_px(extracao, calibracao):
    paredes = {p["id"]: p for p in extracao["paredes"]}
    if calibracao["parede"] not in paredes:
        raise ErroImagem(f"calibração: parede {calibracao['parede']} não existe na extração")
    p = paredes[calibracao["parede"]]
    comp = math.hypot(p["fim_px"][0] - p["inicio_px"][0], p["fim_px"][1] - p["inicio_px"][1])
    delta = {"eixo": 0.0, "externa": extracao["espessura_px"], "interna": -extracao["espessura_px"]}.get(calibracao["referencia"])
    if delta is None:
        raise ErroImagem("calibração: referencia deve ser 'externa', 'eixo' ou 'interna'")
    px = comp + delta
    if px <= 0:
        raise ErroImagem("calibração: comprimento em pixels inválido")
    return calibracao["medida_mm"] / px, comp


def montar_dxf(extracao, classificacao, grade_mm, destino):
    """Escreve o DXF em mm. Retorna (espessura_mm, calibracao_para_converter, avisos)."""
    avisos = []
    escala, comp_ref_px = escala_mm_por_px(extracao, classificacao["calibracao"])
    xs = [v[0] for p in extracao["paredes"] for v in (p["inicio_px"], p["fim_px"])]
    ys = [v[1] for p in extracao["paredes"] for v in (p["inicio_px"], p["fim_px"])]
    x_min, y_max = min(xs), max(ys)

    def g(v):
        return round(v / grade_mm) * grade_mm

    def mm(pt):   # pixel -> mm, origem no canto inferior esquerdo, y para cima
        return (g((pt[0] - x_min) * escala), g((y_max - pt[1]) * escala))

    doc = ezdxf.new("R2010")
    doc.units = units.MM
    for nome in ("PAREDES", "PORTAS", "JANELAS"):
        doc.layers.add(nome)
    msp = doc.modelspace()
    for p in extracao["paredes"]:
        msp.add_line(mm(p["inicio_px"]), mm(p["fim_px"]), dxfattribs={"layer": "PAREDES"})

    tipos = classificacao.get("aberturas", {})
    for ab in extracao["aberturas"]:
        tipo = tipos.get(str(ab["id"]))
        if tipo is None:
            raise ErroImagem(f"vão {ab['id']} sem classificação (porta, janela ou ignorar)")
        if tipo == "ignorar":
            avisos.append(f"vão {ab['id']} marcado como 'ignorar': a parede segue contínua")
            continue
        if tipo not in ("porta", "janela"):
            raise ErroImagem(f"vão {ab['id']}: tipo '{tipo}' inválido (use porta, janela ou ignorar)")
        msp.add_line(mm(ab["inicio_px"]), mm(ab["fim_px"]), dxfattribs={"layer": "PORTAS" if tipo == "porta" else "JANELAS"})
    sobra = set(tipos) - {str(a["id"]) for a in extracao["aberturas"]}
    if sobra:
        avisos.append(f"classificação cita vãos que a extração não tem: {sorted(sobra)}")

    doc.saveas(destino)
    esp_mm = max(g(extracao["espessura_px"] * escala), grade_mm)
    ref = [p for p in extracao["paredes"] if p["id"] == classificacao["calibracao"]["parede"]][0]
    (xa, ya), (xb, yb) = mm(ref["inicio_px"]), mm(ref["fim_px"])
    medida_eixo = round(comp_ref_px * escala, 1)
    if escala >= 15:
        avisos.append(f"Resolução limitada: cada pixel vale {escala:.0f} mm, então posições e larguras têm erro de ±{escala:.0f} mm ou mais.")
    avisos.append(
        f"Escala {escala:.3f} mm/px ({1000 / escala:.0f} px/m) vinda da cota "
        f"({classificacao['calibracao'].get('origem', 'sem descrição')}); espessura {esp_mm:g} mm medida na imagem; "
        f"coordenadas arredondadas à grade de {grade_mm:g} mm."
    )
    return esp_mm, [xa, ya, xb, yb, medida_eixo], avisos


def converter_imagem(extracao, classificacao, grade_mm=10.0, pe_direito=None):
    """Retorna (projeto, avisos)."""
    with tempfile.TemporaryDirectory() as tmp:
        dxf = Path(tmp) / "da_imagem.dxf"
        esp_mm, cal, avisos = montar_dxf(extracao, classificacao, grade_mm, dxf)
        projeto, avisos_conv = converter(dxf, espessura=esp_mm, pe_direito=pe_direito, calibracao=cal)
    projeto["projeto"]["nome"] = classificacao.get("ambiente") or Path(extracao["imagem"]["arquivo"]).stem
    projeto["projeto"]["calibracao"]["origem"] = "inferida"
    projeto["fonte"] = {"tipo": "imagem", "arquivo": extracao["imagem"]["arquivo"], "confianca_global": CONFIANCA_IMAGEM}
    for p in projeto["pavimentos"][0]["paredes"]:
        p["origem"] = "medida"
        p["confianca"] = CONFIANCA_IMAGEM
    for a in projeto["pavimentos"][0]["aberturas"]:
        if a["origem"] == "medida":
            continue
        a["origem"] = "inferida"
    avisos += [w for w in avisos_conv if not w.startswith("Espessura das paredes assumida") and not w.startswith("Sem --calibracao")]
    avisos += extracao.get("avisos", [])
    if classificacao.get("incertos"):
        avisos.append(f"A classificação ficou em DÚVIDA nos vãos {classificacao['incertos']}: confirme porta/janela olhando o overlay.")
    avisos.append("Posições e larguras vêm de pixels (erro típico de ±1 px na escala da imagem); confira antes de produzir.")
    return projeto, avisos


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("extracao", type=Path)
    ap.add_argument("classificacao", type=Path)
    ap.add_argument("--saida-dir", type=Path, required=True)
    ap.add_argument("--grade-mm", type=float, default=10.0)
    ap.add_argument("--pe-direito", type=float, default=None)
    args = ap.parse_args()

    extracao = json.loads(args.extracao.read_text(encoding="utf-8"))
    classificacao = json.loads(args.classificacao.read_text(encoding="utf-8"))
    try:
        projeto, avisos = converter_imagem(extracao, classificacao, args.grade_mm, args.pe_direito)
    except ErroImagem as e:
        print(f"ERRO: {e}")
        return 1
    erros, avisos_geo = validar(projeto)
    for w in avisos + avisos_geo:
        print(f"AVISO: {w}")
    if erros:
        for e in erros:
            print(f"ERRO: {e}")
        return 1
    pav = projeto["pavimentos"][0]
    if not pav["ambientes"]:
        print("ERRO: as paredes extraídas não formam um contorno fechado.")
        return 1
    args.saida_dir.mkdir(parents=True, exist_ok=True)
    (args.saida_dir / "projeto.json").write_text(json.dumps(projeto, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    script = gerar_script(projeto)
    (args.saida_dir / "script_sketchup.py").write_text(script, encoding="utf-8")
    print(f"OK: {len(pav['paredes'])} paredes, {len(pav['aberturas'])} aberturas. Escrito em {args.saida_dir}/ "
          f"(projeto.json, script_sketchup.py: {len(script)} caracteres).")
    return 0


if __name__ == "__main__":
    sys.exit(main())
