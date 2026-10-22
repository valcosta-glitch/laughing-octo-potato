# Validação final: percorre todas as peças-folha do modelo e confere que cada uma é um sólido fechado.
#
# Rodar por último. Usa relatar() de sketchup_comum.py. Sem import, unidade em polegadas.
# Folha = grupo sem subgrupos. Problema = borda aberta, aresta solta, orientação inconsistente
# ou volume indefinido (compute_volume() == None).

ctx = session_state["ctx"]
relatar = ctx["relatar"]

folhas_rel = []


def varrer(grupo, caminho):
    filhos = grupo.get_entities().get_groups()
    if len(filhos) == 0:
        relatar(grupo, caminho, folhas_rel)
    else:
        for f in filhos:
            varrer(f, caminho + "/" + f.get_name())


for g in model.get_entities().get_groups():
    varrer(g, g.get_name())

problemas = [r for r in folhas_rel
             if r["bordas"] != 0 or r["soltas"] != 0 or not r["orient_ok"] or r["volume_in3"] is None]
try:
    lista_de_corte = corte   # definida por sketchup_moveis.py quando o script roda inteiro
except Exception:
    lista_de_corte = []
pecas_por_movel = {}
for c in lista_de_corte:
    pecas_por_movel[c["movel"]] = pecas_por_movel.get(c["movel"], 0) + 1
result = {"pecas_verificadas": len(folhas_rel), "pecas_com_problema": problemas,
          "cenas": [s.get_name() for s in model.get_scenes()],
          "pecas_por_movel": pecas_por_movel, "lista_de_corte": lista_de_corte}
