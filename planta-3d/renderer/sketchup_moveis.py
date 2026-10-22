# Blocos de marcenaria (balcão e aéreo de 2 portas), peça por peça, para o conector Trimble SketchUp.
#
# Rodar DEPOIS de sketchup_paredes.py e sketchup_comum.py. Espera uma variável global `moveis`:
#   [{"id", "bloco": "balcao_2_portas" | "aereo_2_portas", "parede_id", "distancia_do_inicio_mm",
#     "afastamento_mm", "elevacao_mm", "parametros": {...}}]   (tudo em mm)
#
# Cada móvel é um grupo com uma peça (chapa) por subgrupo, nomeada para virar lista de corte.
# Convenção da peça: espessura = menor dimensão; comprimento = maior; largura = a do meio.
# Padrões do bloco (NÃO vêm do projeto, confira): fundo 6 mm, zócalo recuado 50 mm, folga de porta 3 mm,
# tampo do balcão na mesma chapa do corpo (na prática costuma ser outro material/espessura).

ctx = session_state["ctx"]
MM = ctx["MM"]
get_or_create_material = ctx["get_or_create_material"]
extrude_faces = ctx["extrude_faces"]
leaf_group = ctx["leaf_group"]
relatar = ctx["relatar"]
paredes_por_id = {}
for w in ctx["paredes"]:
    paredes_por_id[w["id"]] = w

FUNDO_ESP = 6.0
RECUO_ZOCALO = 50.0
FOLGA_PORTA = 3.0
TAMPO_AVANCO = 20.0

mat_corpo = get_or_create_material("MDF_Branco", 240, 240, 235)
mat_verde = get_or_create_material("MDF_Verde", 96, 140, 120)

corte = []   # lista de corte (mm)


def peca(asm, w, base, nome, a0, a1, d0, d1, z0, z1, mat):
    """Chapa em coordenadas locais do móvel (mm): a = ao longo da parede, d = para dentro do ambiente, z = altura."""
    s0 = base["s"] + a0 * MM
    s1 = base["s"] + a1 * MM
    o0 = w["off_in"] + base["afast"] + d0 * MM
    o1 = w["off_in"] + base["afast"] + d1 * MM
    zz0 = base["z"] + z0 * MM
    zz1 = base["z"] + z1 * MM
    rect = [(s0, zz0), (s1, zz0), (s1, zz1), (s0, zz1)]
    leaf_group(asm, nome, extrude_faces(w, [rect], o0, o1), mat)
    dims = sorted([a1 - a0, d1 - d0, z1 - z0], reverse=True)
    corte.append({"movel": base["id"], "peca": nome, "comprimento_mm": round(dims[0], 1),
                  "largura_mm": round(dims[1], 1), "espessura_mm": round(dims[2], 1),
                  "material": mat.get_name()})


def balcao(asm, w, base, p):
    W, H, D = p["largura_mm"], p["altura_mm"], p["profundidade_mm"]
    e = p["espessura_chapa_mm"]
    soc = p.get("socalo_mm", 100.0)
    Dc = D - e   # profundidade do corpo; a porta ocupa a espessura restante na frente
    peca(asm, w, base, "Lateral_Esq", 0, e, 0, Dc, 0, H - e, mat_corpo)
    peca(asm, w, base, "Lateral_Dir", W - e, W, 0, Dc, 0, H - e, mat_corpo)
    peca(asm, w, base, "Base", e, W - e, FUNDO_ESP, Dc, soc, soc + e, mat_corpo)
    peca(asm, w, base, "Fundo", e, W - e, 0, FUNDO_ESP, soc, H - e, mat_corpo)
    peca(asm, w, base, "Zocalo", e, W - e, Dc - RECUO_ZOCALO, Dc - RECUO_ZOCALO + e, 0, soc, mat_corpo)
    peca(asm, w, base, "Tampo", 0, W, 0, D + TAMPO_AVANCO, H - e, H, mat_corpo)
    n = p.get("portas", 2)
    larg = (W - (n + 1) * FOLGA_PORTA) / n
    for i in range(n):
        a0 = FOLGA_PORTA + i * (larg + FOLGA_PORTA)
        peca(asm, w, base, "Porta_" + str(i + 1), a0, a0 + larg, Dc, D, soc + FOLGA_PORTA, H - e - FOLGA_PORTA, mat_verde)


def aereo(asm, w, base, p):
    W, H, D = p["largura_mm"], p["altura_mm"], p["profundidade_mm"]
    e = p["espessura_chapa_mm"]
    Dc = D - e
    peca(asm, w, base, "Lateral_Esq", 0, e, 0, Dc, 0, H, mat_corpo)
    peca(asm, w, base, "Lateral_Dir", W - e, W, 0, Dc, 0, H, mat_corpo)
    peca(asm, w, base, "Base", e, W - e, FUNDO_ESP, Dc, 0, e, mat_corpo)
    peca(asm, w, base, "Topo", e, W - e, FUNDO_ESP, Dc, H - e, H, mat_corpo)
    peca(asm, w, base, "Fundo", e, W - e, 0, FUNDO_ESP, e, H - e, mat_corpo)
    n = p.get("portas", 2)
    larg = (W - (n + 1) * FOLGA_PORTA) / n
    for i in range(n):
        a0 = FOLGA_PORTA + i * (larg + FOLGA_PORTA)
        peca(asm, w, base, "Porta_" + str(i + 1), a0, a0 + larg, Dc, D, FOLGA_PORTA, H - FOLGA_PORTA, mat_corpo)


BLOCOS = {"balcao_2_portas": balcao, "aereo_2_portas": aereo}

projeto_grp = None
for g in model.get_entities().get_groups():
    if g.get_name() == ctx["nome"]:
        projeto_grp = g

for m in moveis:
    w = paredes_por_id[m["parede_id"]]
    base = {"id": m["id"], "s": m["distancia_do_inicio_mm"] * MM, "afast": m.get("afastamento_mm", 0) * MM,
            "z": m.get("elevacao_mm", 0) * MM}
    asm = Group()
    projeto_grp.get_entities().add_group(asm)
    asm.set_name("Movel_" + m["id"])
    BLOCOS[m["bloco"]](asm, w, base, m["parametros"])

rel = []
for g in projeto_grp.get_entities().get_groups():
    if g.get_name().startswith("Movel_"):
        for f in g.get_entities().get_groups():
            relatar(f, g.get_name() + "/" + f.get_name(), rel)
result = {"moveis": rel, "lista_de_corte": corte}
