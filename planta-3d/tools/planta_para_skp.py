#!/usr/bin/env python3
"""Da planta DXF ao script do SketchUp, num comando só.

Uso:
  python3 planta_para_skp.py planta.dxf --saida-dir saida [--unidade mm|cm|m]
      [--espessura 150] [--pe-direito 2700] [--corte corte.dxf] [--calibracao x1,y1,x2,y2,medida_mm]

Faz: lê o DXF (camadas PAREDES, PORTAS, JANELAS, MOVEIS_<BLOCO> e CORTE_*), monta o JSON intermediário, valida,
e escreve em --saida-dir:
  projeto.json          o JSON intermediário (confira os valores marcados 'inferida')
  script_sketchup.py    para colar em build_model (clean=true) do conector Trimble SketchUp
Sai com código 1 se a conversão ou a validação falhar; nada é escrito nesse caso.
"""
import argparse
import json
import sys
from pathlib import Path

from dxf_para_json import UNIDADE_PARA_MM, ErroConversao, converter, validar
from gerar_script_sketchup import gerar_script


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("dxf", type=Path)
    ap.add_argument("--saida-dir", type=Path, required=True)
    ap.add_argument("--unidade", choices=sorted(UNIDADE_PARA_MM))
    ap.add_argument("--espessura", type=float, default=150.0)
    ap.add_argument("--pe-direito", type=float, default=None, help="padrão 2700; o corte, se houver, tem prioridade")
    ap.add_argument("--corte", type=Path, help="DXF do corte (camadas CORTE_*); sem ele lê as camadas CORTE_* do próprio DXF")
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
        projeto, avisos = converter(args.dxf, args.unidade, args.espessura, args.pe_direito, calibracao, args.corte)
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

    pav = projeto["pavimentos"][0]
    if not pav["ambientes"]:
        print("ERRO: sem um contorno fechado de paredes não há ambiente para desenhar.")
        return 1

    args.saida_dir.mkdir(parents=True, exist_ok=True)
    (args.saida_dir / "projeto.json").write_text(json.dumps(projeto, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    script = gerar_script(projeto)
    (args.saida_dir / "script_sketchup.py").write_text(script, encoding="utf-8")

    print(
        f"OK: {len(pav['paredes'])} paredes, {len(pav['aberturas'])} aberturas, {len(pav['mobiliario'])} móveis. "
        f"Escrito em {args.saida_dir}/ (projeto.json, script_sketchup.py: {len(script)} caracteres)."
    )
    print("Próximo passo: colar script_sketchup.py em build_model com clean=true e depois salvar o modelo.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
