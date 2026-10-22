# Paredes em "topologia livre" para o conector Trimble SketchUp (build_model).
#
# Cada parede é uma CAIXA (segmento de eixo + espessura, extremidades retas, sem mitra); cada vão (porta ou janela)
# vira verga acima dele e, nas janelas, peitoril abaixo; as esquadrias (batente/folha, caixilho/vidro) são feitas
# por sketchup_esquadrias.py a partir de um "quadro" de parede fictício por vão. Isso dispensa contorno fechado:
# serve para casa com vários cômodos, T e vão na ponta de parede.
#
# Roda DENTRO do sandbox (sem import, polegadas), depois de sketchup_base, sketchup_livre_ctx e sketchup_comum.
# Espera `projeto` global, em milímetros:
#   {"nome", "pe_direito_mm",
#    "paredes": [{"id", "inicio": [x, y], "fim": [x, y], "espessura_mm", "tipo": "parede"|"pilar"}],
#    "vaos":    [{"id", "tipo": "porta"|"janela"|"porta_correr" (com "folhas"), "eixo": "x"|"y", "centro": [x, y], "largura_mm", "espessura_mm",
#                 "altura_mm", "peitoril_mm"}]}
# Limites: paredes e vãos ortogonais; os móveis (se houver) vêm de sketchup_moveis.py; o piso é uma laje retangular sob a caixa envolvente.

ctx = session_state["ctx"]
prism_faces = ctx["prism_faces"]
leaf_group = ctx["leaf_group"]

H = projeto["pe_direito_mm"] * MM
mat_parede = get_or_create_material("Parede_Branco", 235, 232, 225)
mat_pilar = get_or_create_material("Pilar_Concreto", 170, 170, 168)

projeto_grp = Group()
model.get_entities().add_group(projeto_grp)
projeto_grp.set_name(projeto.get("nome", "Projeto"))


def retangulo(ax, ay, bx, by, t):
    """Retângulo de eixo A-B e espessura t (extremidades retas)."""
    L = math.hypot(bx - ax, by - ay)
    ux, uy = (bx - ax) / L, (by - ay) / L
    nx, ny = -uy, ux
    return [(ax + nx * t / 2, ay + ny * t / 2), (bx + nx * t / 2, by + ny * t / 2),
            (bx - nx * t / 2, by - ny * t / 2), (ax - nx * t / 2, ay - ny * t / 2)]


xs, ys = [], []
y_min_eixo = 1e18
for p in projeto["paredes"]:
    ax, ay = p["inicio"][0] * MM, p["inicio"][1] * MM
    bx, by = p["fim"][0] * MM, p["fim"][1] * MM
    poly = retangulo(ax, ay, bx, by, p["espessura_mm"] * MM)
    xs += [q[0] for q in poly]
    ys += [q[1] for q in poly]
    pilar = p.get("tipo") == "pilar"
    leaf_group(projeto_grp, ("Pilar_" if pilar else "Parede_") + p["id"], prism_faces(poly, 0.0, H),
               mat_pilar if pilar else mat_parede)

paredes_vao = []
abs_vao = {}
nomes_por_vao = {}
for v in projeto["vaos"]:
    w_ = v["largura_mm"] * MM
    t = v["espessura_mm"] * MM
    cx, cy = v["centro"][0] * MM, v["centro"][1] * MM
    u = (1.0, 0.0) if v["eixo"] == "x" else (0.0, 1.0)
    A = (cx - u[0] * w_ / 2, cy - u[1] * w_ / 2)
    B = (cx + u[0] * w_ / 2, cy + u[1] * w_ / 2)
    z0 = v.get("peitoril_mm", 0) * MM
    z1 = z0 + v["altura_mm"] * MM
    quadro = {"id": v["id"], "A": A, "u": u, "nrm": (-u[1], u[0]), "L": w_, "t": t,
              "off_in": t / 2, "off_out": -t / 2, "h": H}
    paredes_vao.append(quadro)
    abs_vao[v["id"]] = [{"id": v["id"], "tipo": v["tipo"], "s0": 0.0, "s1": w_, "z0": z0, "z1": z1, "folhas": v.get("folhas", 3)}]
    poly = retangulo(A[0], A[1], B[0], B[1], t)
    nomes = []
    if z1 < H - 1e-6:
        leaf_group(projeto_grp, "Verga_" + v["id"], prism_faces(poly, z1, H), mat_parede)
        nomes.append("Verga_" + v["id"])
    if v["tipo"] == "janela" and z0 > 1e-6:
        leaf_group(projeto_grp, "Peitoril_" + v["id"], prism_faces(poly, 0.0, z0), mat_parede)
        nomes.append("Peitoril_" + v["id"])
    nomes.append(("Janela_" if v["tipo"] == "janela" else "Porta_") + v["id"])
    nomes_por_vao[v["id"]] = nomes
    xs += [q[0] for q in poly]
    ys += [q[1] for q in poly]

x_min, x_max, y_min, y_max = min(xs), max(xs), min(ys), max(ys)

# parede da frente (Y mínimo) = caixas horizontais cuja linha de eixo está na faixa mais ao sul da planta;
# somem na cena interna junto com vergas, peitoris e esquadrias dos vãos dessa faixa
faixa = max(p["espessura_mm"] for p in projeto["paredes"]) * MM * 1.5
ocultar = []
for p in projeto["paredes"]:
    ay, by = p["inicio"][1] * MM, p["fim"][1] * MM
    if abs(ay - by) < 1e-6 and ay <= y_min + faixa and p.get("tipo") != "pilar":
        ocultar.append("Parede_" + p["id"])
for v in projeto["vaos"]:
    if v["eixo"] == "x" and v["centro"][1] * MM <= y_min + faixa:
        ocultar += nomes_por_vao[v["id"]]

ctx["paredes"] = paredes_vao
ctx["abs"] = abs_vao
ctx["piso_poly"] = [(x_min, y_min), (x_max, y_min), (x_max, y_max), (x_min, y_max)]
ctx["ocultar_nomes"] = ocultar

rel = []
for g in projeto_grp.get_entities().get_groups():
    ctx["relatar"](g, g.get_name(), rel)
result = {"caixas": len(rel), "com_problema": [r for r in rel if r["bordas"] or r["soltas"] or not r["orient_ok"] or r["volume_in3"] is None]}
