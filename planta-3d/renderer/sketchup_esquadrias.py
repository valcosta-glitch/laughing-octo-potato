# Piso, porta (batente + folha fechada) e janela (caixilho + vidro) para o conector Trimble SketchUp.
#
# Rodar DEPOIS de sketchup_paredes.py e sketchup_comum.py (usa session_state["ctx"]).
# Sem import, unidade em polegadas. Medidas das peças (batente 40 mm, caixilho 40 mm, folha 35 mm,
# vidro 6 mm, piso 100 mm) são padrões do renderizador, NÃO vêm do projeto: confira com o detalhamento.

ctx = session_state["ctx"]
MM = ctx["MM"]
get_or_create_material = ctx["get_or_create_material"]
extrude_faces = ctx["extrude_faces"]
prism_faces = ctx["prism_faces"]
leaf_group = ctx["leaf_group"]
relatar = ctx["relatar"]
paredes = ctx["paredes"]
cantos_out = ctx["cantos_out"]

BATENTE = 40 * MM
CAIXILHO = 40 * MM
FOLHA_ESP = 35 * MM
VIDRO_ESP = 6 * MM
PISO_ESP = 100 * MM
FOLGA = 3 * MM
FOLGA_BASE = 8 * MM

mat_piso = get_or_create_material("Piso_Cinza", 200, 195, 185)
mat_madeira = get_or_create_material("Madeira_Porta", 160, 120, 80)
mat_aluminio = get_or_create_material("Aluminio", 190, 192, 195)
mat_vidro = get_or_create_material("Vidro", 160, 200, 220, 90)

projeto_grp = None
for g in model.get_entities().get_groups():
    if g.get_name() == ctx["nome"]:
        projeto_grp = g

# piso: laje sob o contorno externo das paredes (as paredes assentam sobre ela, em z = 0)
piso_poly = ctx.get("piso_poly") or [(p[0], p[1]) for p in cantos_out]
leaf_group(projeto_grp, "Piso", prism_faces(piso_poly, -PISO_ESP, 0.0), mat_piso)

for w in paredes:
    o0 = w["off_out"]
    o1 = w["off_in"]
    mid = (o0 + o1) / 2
    for a in ctx["abs"].get(w["id"], []):
        s0, s1, z0, z1 = a["s0"], a["s1"], a["z0"], a["z1"]
        asm = Group()
        projeto_grp.get_entities().add_group(asm)
        if a["tipo"] == "porta":
            asm.set_name("Porta_" + a["id"])
            j = BATENTE
            u_shape = [(s0, 0.0), (s0 + j, 0.0), (s0 + j, z1 - j), (s1 - j, z1 - j), (s1 - j, 0.0), (s1, 0.0), (s1, z1), (s0, z1)]
            leaf_group(asm, "Batente", extrude_faces(w, [u_shape], o0, o1), mat_madeira)
            folha = [(s0 + j + FOLGA, FOLGA_BASE), (s1 - j - FOLGA, FOLGA_BASE), (s1 - j - FOLGA, z1 - j - FOLGA), (s0 + j + FOLGA, z1 - j - FOLGA)]
            leaf_group(asm, "Folha", extrude_faces(w, [folha], mid - FOLHA_ESP / 2, mid + FOLHA_ESP / 2), mat_madeira)
        else:
            asm.set_name("Janela_" + a["id"])
            c = CAIXILHO
            ring = [(s0, z0), (s1, z0), (s1, z1), (s0, z1)]
            furo = [(s0 + c, z0 + c), (s1 - c, z0 + c), (s1 - c, z1 - c), (s0 + c, z1 - c)]
            prof = 70 * MM
            leaf_group(asm, "Caixilho", extrude_faces(w, [ring, furo], mid - prof / 2, mid + prof / 2), mat_aluminio)
            leaf_group(asm, "Vidro", extrude_faces(w, [furo], mid - VIDRO_ESP / 2, mid + VIDRO_ESP / 2), mat_vidro)


# ---- valida as peças ----
rel = []
for g in projeto_grp.get_entities().get_groups():
    if g.get_name().startswith("Parede_"):
        continue
    filhos = g.get_entities().get_groups()
    if len(filhos) > 0:
        for f in filhos:
            relatar(f, g.get_name() + "/" + f.get_name(), rel)
    else:
        relatar(g, g.get_name(), rel)
result = {"esquadrias": rel}
