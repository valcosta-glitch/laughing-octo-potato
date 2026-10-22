# Funções geométricas compartilhadas entre as etapas (esquadrias, móveis) para o conector Trimble SketchUp.
#
# Rodar DEPOIS de sketchup_paredes.py: lê e completa session_state["ctx"]. Sem import, unidade em polegadas.

ctx = session_state["ctx"]
orient = ctx["orient"]
to_geometry = ctx["to_geometry"]


def PO(w, s, off, z):
    return (w["A"][0] + w["u"][0] * s + w["nrm"][0] * off,
            w["A"][1] + w["u"][1] * s + w["nrm"][1] * off, z)


def area2d(loop):
    a = 0.0
    m = len(loop)
    for i in range(m):
        a += loop[i][0] * loop[(i + 1) % m][1] - loop[(i + 1) % m][0] * loop[i][1]
    return a / 2


def extrude_faces(w, loops, o0, o1):
    """Extrude um contorno (s, z) com furos entre as profundidades o0 < o1 (deslocamento sobre a normal)."""
    ls = []
    for k, lp in enumerate(loops):
        if (area2d(lp) > 0) != (k == 0):   # externo anti-horário, furos horários
            lp = list(reversed(lp))
        ls.append(lp)
    u = w["u"]
    n = w["nrm"]
    faces = []
    for off, nv in ((o1, (n[0], n[1], 0)), (o0, (-n[0], -n[1], 0))):
        outer = [PO(w, s, off, z) for (s, z) in ls[0]]
        holes = [orient([PO(w, s, off, z) for (s, z) in hl], (-nv[0], -nv[1], 0)) for hl in ls[1:]]
        faces.append({"outer": orient(outer, nv), "holes": holes})
    for lp in ls:
        m = len(lp)
        for i in range(m):
            sa, za = lp[i]
            sb, zb = lp[(i + 1) % m]
            ns, nz = zb - za, -(sb - sa)   # normal à direita da aresta = para fora do sólido
            quad = [PO(w, sa, o0, za), PO(w, sb, o0, zb), PO(w, sb, o1, zb), PO(w, sa, o1, za)]
            faces.append({"outer": orient(quad, (u[0] * ns, u[1] * ns, nz)), "holes": []})
    return faces


def prism_faces(poly, z0, z1):
    """Prisma vertical a partir de um polígono (x, y) convexo ou não, z0 < z1."""
    a = 0.0
    m = len(poly)
    for i in range(m):
        a += poly[i][0] * poly[(i + 1) % m][1] - poly[(i + 1) % m][0] * poly[i][1]
    if a < 0:
        poly = list(reversed(poly))
    faces = [{"outer": orient([(x, y, z1) for (x, y) in poly], (0, 0, 1)), "holes": []},
             {"outer": orient([(x, y, z0) for (x, y) in poly], (0, 0, -1)), "holes": []}]
    for i in range(m):
        (xa, ya), (xb, yb) = poly[i], poly[(i + 1) % m]
        quad = [(xa, ya, z0), (xb, yb, z0), (xb, yb, z1), (xa, ya, z1)]
        faces.append({"outer": orient(quad, (yb - ya, -(xb - xa), 0)), "holes": []})
    return faces


def leaf_group(parent, nome, faces, mat):
    g = Group()
    parent.get_entities().add_group(g)
    g.get_entities().fill(to_geometry(faces), weld_vertices=True)
    g.set_name(nome)
    for f in g.get_entities().get_faces():
        f.set_front_material(mat)
        f.set_back_material(mat)
    return g


# ---- valida as peças ----
def orient_ok(group):
    for e in group.get_entities().get_edges():
        fs = e.get_faces()
        if len(fs) == 2:
            if e.is_reversed_in_face(fs[0]) == e.is_reversed_in_face(fs[1]):
                return False
    return True


def relatar(g, nome, saida):
    bordas = 0
    soltas = 0
    for e in g.get_entities().get_edges():
        nf = e.get_num_faces()
        if nf == 1:
            bordas += 1
        elif nf == 0:
            soltas += 1
    saida.append({"peca": nome, "faces": len(g.get_entities().get_faces()), "volume_in3": g.compute_volume(),
                  "bordas": bordas, "soltas": soltas, "orient_ok": orient_ok(g)})


ctx["PO"] = PO
ctx["extrude_faces"] = extrude_faces
ctx["prism_faces"] = prism_faces
ctx["leaf_group"] = leaf_group
ctx["relatar"] = relatar
ctx["orient_ok"] = orient_ok
