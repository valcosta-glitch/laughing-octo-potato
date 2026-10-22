# Aplica acabamentos do catálogo a paredes e piso (topologia livre) para o conector Trimble SketchUp.
#
# Rodar DEPOIS de sketchup_livre.py e sketchup_esquadrias.py (e de sketchup_moveis.py), com sketchup_texturas.py já carregado.
# Espera a global `acabamentos`, já resolvida pelo gerador:
#   [{"grupo": "Parede_p5" | "Piso", "acab": "<id do catálogo>", "normal": [x, y, z] | None}]
# Com "normal", só as faces voltadas para esse lado (produto escalar > 0,9) recebem o material; sem ela, todas.
# Limite: a verga e o peitoril dos vãos vizinhos à parede NÃO mudam de cor (são peças à parte).

ctx = session_state["ctx"]
material_acab = ctx["material_acab"]

projeto_grp = None
for g in model.get_entities().get_groups():
    if g.get_name() == ctx["nome"]:
        projeto_grp = g

aplicados = []
for ac in acabamentos:
    mat = material_acab(ac["acab"])
    n_faces = 0
    for g in projeto_grp.get_entities().get_groups():
        if g.get_name() != ac["grupo"]:
            continue
        for f in g.get_entities().get_faces():
            if ac["normal"] is not None:
                nv = f.get_normal()
                if nv.x * ac["normal"][0] + nv.y * ac["normal"][1] + nv.z * ac["normal"][2] < 0.9:
                    continue
            f.set_front_material(mat)
            f.set_back_material(mat)
            n_faces += 1
    aplicados.append({"grupo": ac["grupo"], "acabamento": ac["acab"], "faces": n_faces})
result = {"acabamentos_aplicados": aplicados}
