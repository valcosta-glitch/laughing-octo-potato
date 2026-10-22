#!/usr/bin/env python3
"""Monta o script para colar no build_model do conector Trimble SketchUp.

Uso: python3 gerar_script_sketchup.py projeto.json [saida.py]

Lê o JSON intermediário (schema 0.1.0), valida, e escreve `projeto = {...}` e `moveis = [...]` (em mm)
seguidos dos módulos de renderer/. Sem saída informada, imprime no stdout.

Gera um script único (paredes, piso/porta/janela, móveis, seis cenas e validação final) para um
build_model com clean=true.

Dois modos, escolhidos por pavimento.topologia: "contorno" (padrão: um contorno fechado de paredes em ordem, com
mitra nos cantos, móveis e esquadrias por parede) e "livre" (várias salas: paredes são caixas, os vãos ficam em
`vaos` e os móveis se apoiam numa parede e num `lado` dela).

Limites desta versão: usa só o primeiro pavimento; as paredes precisam estar na ordem do contorno
(a ordem de paredes_ids do ambiente, que o conversor de DXF já entrega); os blocos com desenho estão em
tools/blocos.py (balcão, aéreo, gaveteiro, roupeiro piso-teto, gabinete e rack suspensos, painel, espelho); acabamentos (texturas) do JSON ainda não são aplicados
(as cores dos MDFs são fixas no renderizador).
"""
import json
import sys
from pathlib import Path

from jsonschema import Draft202012Validator

from blocos import BLOCOS, FRENTES, altura_do_movel, completar
from validar import SCHEMA_PADRAO, checar_projeto

RENDERER_DIR = Path(__file__).resolve().parent.parent / "renderer"
# ordem importa: base define os helpers; paredes grava o contexto; comum, esquadrias e móveis o usam; vistas e validação fecham.
MODULOS = ["sketchup_base.py", "sketchup_paredes.py", "sketchup_comum.py", "sketchup_esquadrias.py", "sketchup_moveis.py",
           "sketchup_vistas.py", "sketchup_validacao.py"]
# topologia "livre" (vários cômodos): paredes são caixas, vãos viram verga/peitoril + esquadria; os móveis (se houver) entram
# com sketchup_moveis.py antes das vistas
MODULOS_LIVRE = ["sketchup_base.py", "sketchup_livre_ctx.py", "sketchup_comum.py", "sketchup_livre.py",
                 "sketchup_esquadrias.py", "sketchup_vistas.py", "sketchup_validacao.py"]
BLOCOS_SUPORTADOS = set(BLOCOS)


def _dict_compacto(d):
    """JSON com uma linha por item das listas (o script vai colado no conector: quanto menor, melhor)."""
    linhas = ["{"]
    itens = list(d.items())
    for k, (chave, valor) in enumerate(itens):
        fim = "," if k < len(itens) - 1 else ""
        if isinstance(valor, list):
            linhas.append(f"  {json.dumps(chave)}: [")
            for i, it in enumerate(valor):
                linhas.append("    " + json.dumps(it, ensure_ascii=False) + ("," if i < len(valor) - 1 else ""))
            linhas.append("  ]" + fim)
        else:
            linhas.append(f"  {json.dumps(chave)}: {json.dumps(valor, ensure_ascii=False)}{fim}")
    linhas.append("}")
    return "\n".join(linhas)


def montar_dict_livre(dados):
    pav = dados["pavimentos"][0]
    return {
        "nome": dados["projeto"]["nome"],
        "pe_direito_mm": pav["pe_direito_mm"],
        "paredes": [
            {"id": p["id"], "inicio": [p["inicio"]["x"], p["inicio"]["y"]], "fim": [p["fim"]["x"], p["fim"]["y"]],
             "espessura_mm": p["espessura_mm"], "tipo": p.get("tipo", "parede")}
            for p in pav["paredes"]
        ],
        "vaos": [
            {"id": v["id"], "tipo": v["tipo"], "eixo": v["eixo"], "centro": [v["centro"]["x"], v["centro"]["y"]],
             "largura_mm": v["largura_mm"], "espessura_mm": v["espessura_mm"], "altura_mm": v["altura_mm"],
             "peitoril_mm": v.get("peitoril_mm", 0)}
            for v in pav.get("vaos", [])
        ],
    }


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
        par = completar(m["bloco"]["id"], m["parametros"])
        if par.get("ate_o_teto"):
            par["altura_mm"] = altura_do_movel(pav, m)          # acompanha o pé-direito
        if "frente" in par:
            par["frente_rgb"] = list(FRENTES[par["frente"]])
        item = {
            "id": m["id"],
            "bloco": m["bloco"]["id"],
            "parede_id": apoio["parede_id"],
            "distancia_do_inicio_mm": apoio["distancia_do_inicio_mm"],
            "afastamento_mm": apoio.get("afastamento_mm", 0),
            "elevacao_mm": apoio.get("elevacao_mm", 0),
            "parametros": par,
        }
        if pav.get("topologia") == "livre":
            item["lado"] = apoio["lado"]
        saida.append(item)
    return saida


def gerar_script(dados):
    """Script único para o build_model do conector a partir do JSON intermediário já validado."""
    pav = dados["pavimentos"][0]
    if pav.get("topologia") == "livre":
        moveis = montar_moveis(dados)
        partes = ["projeto = " + _dict_compacto(montar_dict_livre(dados)) + "\n"]
        modulos = list(MODULOS_LIVRE)
        if moveis:
            partes.append("moveis = [\n" + ",\n".join("  " + json.dumps(m, ensure_ascii=False) for m in moveis) + "\n]\n")
            modulos.insert(modulos.index("sketchup_esquadrias.py") + 1, "sketchup_moveis.py")
        for nome in modulos:
            partes.append("# " + "=" * 20 + " " + nome + " " + "=" * 20 + "\n" + (RENDERER_DIR / nome).read_text(encoding="utf-8"))
        return "\n".join(partes)
    partes = ["projeto = " + json.dumps(montar_dict(dados), ensure_ascii=False, indent=4) + "\n",
              "moveis = " + json.dumps(montar_moveis(dados), ensure_ascii=False, indent=4) + "\n"]
    for nome in MODULOS:
        partes.append("# " + "=" * 20 + " " + nome + " " + "=" * 20 + "\n" + (RENDERER_DIR / nome).read_text(encoding="utf-8"))
    return "\n".join(partes)


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

    script = gerar_script(dados)
    if len(sys.argv) > 2:
        Path(sys.argv[2]).write_text(script, encoding="utf-8")
        print(f"OK: {sys.argv[2]} ({len(script)} caracteres)")
    else:
        sys.stdout.write(script)
    return 0


if __name__ == "__main__":
    sys.exit(main())
