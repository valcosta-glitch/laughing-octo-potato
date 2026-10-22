# Renderizador de paredes para o conector Trimble SketchUp (build_model).
#
# Roda DENTRO do sandbox do conector: sem import, sem arquivos, unidade em polegadas.
# Depende de sketchup_base.py (MM, get_or_create_material, orient, to_geometry), que roda antes.
# Espera uma variável global `projeto` definida ANTES deste texto (tools/gerar_script_sketchup.py
# monta o script completo a partir do JSON do projeto). Formato de `projeto`, em milímetros:
#   {"pe_direito_mm": 2700,
#    "paredes":   [{"id", "inicio": [x, y], "fim": [x, y], "espessura_mm", "eixo"}],   # contorno anti-horário
#    "aberturas": [{"id", "tipo", "parede_id", "posicao_mm", "largura_mm", "altura_mm", "peitoril_mm"}]}
#
# Portas viram entalhe no contorno da face; janelas viram furo (laço interno). Os cantos são
# em esquadro (interseção das linhas de offset), então as paredes se encostam sem sobrepor.

def intersect(l1, l2):
    (p1, d1), (p2, d2) = l1, l2
    cross = d1[0] * d2[1] - d1[1] * d2[0]
    if abs(cross) < 1e-9:
        return None
    s = ((p2[0] - p1[0]) * d2[1] - (p2[1] - p1[1]) * d2[0]) / cross
    return (p1[0] + d1[0] * s, p1[1] + d1[1] * s)


def prep_parede(p, pe_direito):
    ax, ay = p["inicio"][0] * MM, p["inicio"][1] * MM
    bx, by = p["fim"][0] * MM, p["fim"][1] * MM
    L = math.hypot(bx - ax, by - ay)
    u = ((bx - ax) / L, (by - ay) / L)
    nrm = (-u[1], u[0])  # esquerda = lado interno
    t = p["espessura_mm"] * MM
    if p["eixo"] == "centro":
        off_in, off_out = t / 2, -t / 2
    elif p["eixo"] == "face_interna":
        off_in, off_out = 0.0, -t
    else:
        off_in, off_out = t, 0.0
    return {"id": p["id"], "A": (ax, ay), "u": u, "nrm": nrm, "L": L, "t": t,
            "off_in": off_in, "off_out": off_out, "h": pe_direito * MM}


def line_of(w, side):
    off = w["off_in"] if side == "in" else w["off_out"]
    return ((w["A"][0] + w["nrm"][0] * off, w["A"][1] + w["nrm"][1] * off), w["u"])


def P(w, s, z, side):
    off = w["off_in"] if side == "in" else w["off_out"]
    return (w["A"][0] + w["u"][0] * s + w["nrm"][0] * off,
            w["A"][1] + w["u"][1] * s + w["nrm"][1] * off, z)


def wall_faces(w, aberturas, c_si, c_so, c_ei, c_eo):
    """Faces (contorno + furos) de uma parede."""
    h = w["h"]
    portas = sorted([a for a in aberturas if a["tipo"] == "porta"], key=lambda a: a["s0"])
    janelas = [a for a in aberturas if a["tipo"] != "porta"]
    faces = []
    for side, sc, ec, want in (("in", c_si, c_ei, (w["nrm"][0], w["nrm"][1], 0)),
                               ("out", c_so, c_eo, (-w["nrm"][0], -w["nrm"][1], 0))):
        outline = [(sc[0], sc[1], 0.0)]
        for a in portas:
            outline += [P(w, a["s0"], 0.0, side), P(w, a["s0"], a["z1"], side),
                        P(w, a["s1"], a["z1"], side), P(w, a["s1"], 0.0, side)]
        outline += [(ec[0], ec[1], 0.0), (ec[0], ec[1], h), (sc[0], sc[1], h)]
        holes = []
        for a in janelas:
            hole = [P(w, a["s0"], a["z0"], side), P(w, a["s1"], a["z0"], side),
                    P(w, a["s1"], a["z1"], side), P(w, a["s0"], a["z1"], side)]
            holes.append(orient(hole, (-want[0], -want[1], 0)))
        faces.append({"outer": orient(outline, want), "holes": holes})

    # topo
    faces.append({"outer": orient([(c_si[0], c_si[1], h), (c_ei[0], c_ei[1], h), (c_eo[0], c_eo[1], h), (c_so[0], c_so[1], h)], (0, 0, 1)), "holes": []})
    # base: segmentos entre portas
    marcos = [0.0]
    for a in portas:
        marcos += [a["s0"], a["s1"]]
    marcos.append(w["L"])
    for i in range(0, len(marcos), 2):
        sa, sb = marcos[i], marcos[i + 1]
        ia = (c_si[0], c_si[1], 0.0) if i == 0 else P(w, sa, 0.0, "in")
        oa = (c_so[0], c_so[1], 0.0) if i == 0 else P(w, sa, 0.0, "out")
        ib = (c_ei[0], c_ei[1], 0.0) if i + 2 >= len(marcos) else P(w, sb, 0.0, "in")
        ob = (c_eo[0], c_eo[1], 0.0) if i + 2 >= len(marcos) else P(w, sb, 0.0, "out")
        faces.append({"outer": orient([ia, ib, ob, oa], (0, 0, -1)), "holes": []})
    # extremidades
    faces.append({"outer": orient([(c_si[0], c_si[1], 0.0), (c_si[0], c_si[1], h), (c_so[0], c_so[1], h), (c_so[0], c_so[1], 0.0)], (-w["u"][0], -w["u"][1], 0)), "holes": []})
    faces.append({"outer": orient([(c_ei[0], c_ei[1], 0.0), (c_ei[0], c_ei[1], h), (c_eo[0], c_eo[1], h), (c_eo[0], c_eo[1], 0.0)], (w["u"][0], w["u"][1], 0)), "holes": []})
    # túneis das aberturas
    for a in portas + janelas:
        z0 = 0.0 if a["tipo"] == "porta" else a["z0"]
        z1 = a["z1"]
        ux, uy = w["u"]
        faces.append({"outer": orient([P(w, a["s0"], z0, "in"), P(w, a["s0"], z1, "in"), P(w, a["s0"], z1, "out"), P(w, a["s0"], z0, "out")], (ux, uy, 0)), "holes": []})
        faces.append({"outer": orient([P(w, a["s1"], z0, "in"), P(w, a["s1"], z1, "in"), P(w, a["s1"], z1, "out"), P(w, a["s1"], z0, "out")], (-ux, -uy, 0)), "holes": []})
        faces.append({"outer": orient([P(w, a["s0"], z1, "in"), P(w, a["s1"], z1, "in"), P(w, a["s1"], z1, "out"), P(w, a["s0"], z1, "out")], (0, 0, -1)), "holes": []})
        if a["tipo"] != "porta":
            faces.append({"outer": orient([P(w, a["s0"], z0, "in"), P(w, a["s1"], z0, "in"), P(w, a["s1"], z0, "out"), P(w, a["s0"], z0, "out")], (0, 0, 1)), "holes": []})
    return faces


# ---- monta ----
paredes = [prep_parede(p, projeto["pe_direito_mm"]) for p in projeto["paredes"]]
n = len(paredes)

abs_por_parede = {}
for a in projeto["aberturas"]:
    abs_por_parede.setdefault(a["parede_id"], []).append({
        "id": a["id"],
        "tipo": a["tipo"],
        "s0": a["posicao_mm"] * MM,
        "s1": (a["posicao_mm"] + a["largura_mm"]) * MM,
        "z0": a["peitoril_mm"] * MM,
        "z1": (a["peitoril_mm"] + a["altura_mm"]) * MM,
    })


def canto(i, side):
    a, b = paredes[i], paredes[(i + 1) % n]
    pt = intersect(line_of(a, side), line_of(b, side))
    if pt is None:
        off = a["off_in"] if side == "in" else a["off_out"]
        pt = (a["A"][0] + a["u"][0] * a["L"] + a["nrm"][0] * off, a["A"][1] + a["u"][1] * a["L"] + a["nrm"][1] * off)
    return pt


cantos_in = [canto(i, "in") for i in range(n)]    # canto no FIM da parede i
cantos_out = [canto(i, "out") for i in range(n)]

mat = get_or_create_material("Parede_Branco", 235, 232, 225)

projeto_grp = Group()
model.get_entities().add_group(projeto_grp)
projeto_grp.set_name(projeto.get("nome", "Projeto"))

for i, w in enumerate(paredes):
    faces = wall_faces(w, abs_por_parede.get(w["id"], []),
                       cantos_in[(i - 1) % n], cantos_out[(i - 1) % n], cantos_in[i], cantos_out[i])
    g = Group()
    projeto_grp.get_entities().add_group(g)
    g.get_entities().fill(to_geometry(faces), weld_vertices=True)
    g.set_name("Parede_" + w["id"])
    for f in g.get_entities().get_faces():
        f.set_front_material(mat)
        f.set_back_material(mat)


# ---- valida cada parede ----
def orient_ok(group):
    for e in group.get_entities().get_edges():
        fs = e.get_faces()
        if len(fs) == 2:
            if e.is_reversed_in_face(fs[0]) == e.is_reversed_in_face(fs[1]):
                return False
    return True


rel = []
for g in projeto_grp.get_entities().get_groups():
    ents = g.get_entities()
    bordas = 0
    soltas = 0
    for e in ents.get_edges():
        nf = e.get_num_faces()
        if nf == 1:
            bordas += 1
        elif nf == 0:
            soltas += 1
    rel.append({"nome": g.get_name(), "faces": len(ents.get_faces()), "volume_in3": g.compute_volume(),
                "bordas_abertas": bordas, "soltas": soltas, "orient_consistente": orient_ok(g)})
result = {"paredes": rel}

# contexto para as etapas seguintes (esquadrias, móveis), que rodam em chamadas separadas
session_state["ctx"] = {
    "MM": MM, "nome": projeto.get("nome", "Projeto"), "pe_direito": projeto["pe_direito_mm"],
    "paredes": paredes, "abs": abs_por_parede, "cantos_in": cantos_in, "cantos_out": cantos_out,
    "orient": orient, "to_geometry": to_geometry, "get_or_create_material": get_or_create_material,
}
