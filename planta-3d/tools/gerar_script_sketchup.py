#!/usr/bin/env python3
"""Monta o script para colar no build_model do conector Trimble SketchUp.

Uso: python3 gerar_script_sketchup.py projeto.json [saida.py]

Lê o JSON intermediário (schema 0.1.0), valida, e escreve `projeto = {...}` e `moveis = [...]` (em mm)
seguidos dos módulos de renderer/. Sem saída informada, imprime no stdout.

Gera um script único (paredes, piso/porta/janela, móveis, seis cenas e validação final) para um
build_model com clean=true.

Limites desta versão: usa só o primeiro pavimento; as paredes precisam estar na ordem do contorno
(a ordem de paredes_ids do ambiente, que o conversor de DXF já entrega); só os blocos
balcao_2_portas e aereo_2_portas têm desenho; acabamentos (texturas) do JSON ainda não são aplicados
(as cores dos MDFs são fixas no renderizador).
"""
import json
import sys
from pathlib import Path

from jsonschema import Draft202012Validator

from validar import SCHEMA_PADRAO, checar_projeto

RENDERER_DIR = Path(__file__).resolve().parent.parent / "renderer"
# ordem importa: paredes grava o contexto; comum, esquadrias e móveis o usam; vistas e validação fecham.
MODULOS = ["sketchup_paredes.py", "sketchup_comum.py", "sketchup_esquadrias.py", "sketchup_moveis.py",
           "sketchup_vistas.py", "sketchup_validacao.py"]
BLOCOS_SUPORTADOS = {"balcao_2_portas", "aereo_2_portas"}


def montar_dict(dados):
    pav = dados["pavimentos"][0]
    por_id = {p["id"]: p for p in pav["paredes"]}
    ordem = pav["paredes"]
    if pav.get("ambientes"):
        ordem = [por_id[i] for i in pav["ambientes"][0]["paredes_ids"]]
    return {
        "nome": dados["projeto"]["nome"],
        "pe_direito_mm": pav["pe_direito_mm"],
        "paredes": [
            {
                "id": p["id"],
                "inicio": [p["inicio"]["x"], p["inicio"]["y"]],
                "fim": [p["fim"]["x"], p["fim"]["y"]],
                "espessura_mm": p["espessura_mm"],
                "eixo": p["eixo"],
            }
            for p in ordem
        ],
        "aberturas": [
            {
                "id": a["id"],
                "tipo": a["tipo"],
                "parede_id": a["parede_id"],
                "posicao_mm": a["posicao_mm"],
                "largura_mm": a["largura_mm"],
                "altura_mm": a["altura_mm"],
                "peitoril_mm": a.get("peitoril_mm", 0),
            }
            for a in pav.get("aberturas", [])
        ],
    }


def montar_moveis(dados):
    pav = dados["pavimentos"][0]
    saida = []
    for m in pav.get("mobiliario", []):
        if m["bloco"]["id"] not in BLOCOS_SUPORTADOS:
            raise SystemExit(f"ERRO: bloco '{m['bloco']['id']}' sem desenho implementado (suportados: {sorted(BLOCOS_SUPORTADOS)})")
        apoio = m["apoio"]
        saida.append({
            "id": m["id"],
            "bloco": m["bloco"]["id"],
            "parede_id": apoio["parede_id"],
            "distancia_do_inicio_mm": apoio["distancia_do_inicio_mm"],
            "afastamento_mm": apoio.get("afastamento_mm", 0),
            "elevacao_mm": apoio.get("elevacao_mm", 0),
            "parametros": m["parametros"],
        })
    return saida


def main():
    if len(sys.argv) < 2:
        print(__doc__)
        return 2
    dados = json.loads(Path(sys.argv[1]).read_text(encoding="utf-8"))
    schema = json.loads(SCHEMA_PADRAO.read_text(encoding="utf-8"))
    problemas = [e.message for e in Draft202012Validator(schema).iter_errors(dados)]
    if not problemas:
        problemas, _ = checar_projeto(dados)
    if problemas:
        for p in problemas:
            print(f"ERRO: {p}", file=sys.stderr)
        return 1

    partes = ["projeto = " + json.dumps(montar_dict(dados), ensure_ascii=False, indent=4) + "\n",
              "moveis = " + json.dumps(montar_moveis(dados), ensure_ascii=False, indent=4) + "\n"]
    for nome in MODULOS:
        partes.append("# " + "=" * 20 + " " + nome + " " + "=" * 20 + "\n" + (RENDERER_DIR / nome).read_text(encoding="utf-8"))
    script = "\n".join(partes)
    if len(sys.argv) > 2:
        Path(sys.argv[2]).write_text(script, encoding="utf-8")
        print(f"OK: {sys.argv[2]} ({len(script)} caracteres)")
    else:
        sys.stdout.write(script)
    return 0


if __name__ == "__main__":
    sys.exit(main())
