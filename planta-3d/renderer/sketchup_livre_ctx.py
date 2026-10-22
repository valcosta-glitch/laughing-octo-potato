# Contexto inicial do modo "topologia livre" (plantas com vários cômodos, sem contorno único).
#
# Rodar logo depois de sketchup_base.py e ANTES de sketchup_comum.py: o comum lê session_state["ctx"].
# Espera `projeto` definido antes (ver sketchup_livre.py). Sem import, unidade em polegadas.

session_state["ctx"] = {
    "MM": MM, "nome": projeto.get("nome", "Projeto"), "pe_direito": projeto["pe_direito_mm"],
    "paredes": [], "abs": {}, "cantos_in": [], "cantos_out": [],
    "orient": orient, "to_geometry": to_geometry, "get_or_create_material": get_or_create_material,
}
