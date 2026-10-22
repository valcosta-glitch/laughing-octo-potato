# Blocos de marcenaria, peça por peça, para o conector Trimble SketchUp: balcão e aéreo de 2 portas, gaveteiro de N gavetas
# (modo contorno e livre) e, das pranchas de detalhe, roupeiro piso-teto, gabinete e rack suspensos, painel e espelho.
#
# Rodar DEPOIS de sketchup_paredes.py (ou sketchup_livre.py) e sketchup_comum.py. Espera uma variável global `moveis`:
#   [{"id", "bloco": <ver BLOCOS abaixo>, "parede_id", "distancia_do_inicio_mm", "afastamento_mm", "elevacao_mm",
#     "lado": "norte"|"sul"|"leste"|"oeste"   (SÓ no modo livre: face da parede onde encosta; distância da ponta de menor coordenada),
#     "parametros": {...}}]   (tudo em mm)
# No modo contorno a parede vem do contexto (ctx["paredes"]); no livre o quadro da face é montado aqui a partir de `projeto`.
#
# Cada móvel é um grupo com uma peça (chapa) por subgrupo, nomeada para virar lista de corte.
# Convenção da peça: espessura = menor dimensão; comprimento = maior; largura = a do meio.
# Padrões do bloco (NÃO vêm do projeto, confira): fundo 6 mm, zócalo recuado 50 mm, folga de porta 3 mm,
# tampo do balcão na mesma chapa do corpo (na prática costuma ser outro material/espessura).
# Gaveteiro: caixa de gaveta com laterais/traseira/frente interna de 15 mm e fundo de 6 mm, folga de 13 mm de
# cada lado para a corrediça, comprimento da caixa em múltiplos de 50 mm (até 550); frentes na cor das portas do balcão.

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
GAVETA_ESP = 15.0          # laterais, traseira e frente interna da caixa
GAVETA_FUNDO = 6.0
FOLGA_CORREDICA = 13.0     # de cada lado, entre a lateral do corpo e a lateral da caixa

mat_corpo = get_or_create_material("MDF_Branco", 240, 240, 235)
mat_verde = get_or_create_material("MDF_Verde", 96, 140, 120)


def quadro_lado(par, lado):
    """Quadro (A, u, nrm) de UMA face de uma parede ortogonal do modo livre. nrm aponta para dentro do cômodo (lado pedido)."""
    ax, ay, bx, by = par["inicio"][0], par["inicio"][1], par["fim"][0], par["fim"][1]
    t = par["espessura_mm"] * MM
    if abs(ay - by) < 1e-6:
        c, lo, hi = ay * MM, min(ax, bx) * MM, max(ax, bx) * MM
        A, u = ((lo, c), (1.0, 0.0)) if lado == "norte" else ((hi, c), (-1.0, 0.0))
    else:
        c, lo, hi = ax * MM, min(ay, by) * MM, max(ay, by) * MM
        A, u = ((c, hi), (0.0, -1.0)) if lado == "leste" else ((c, lo), (0.0, 1.0))
    return {"id": par["id"], "A": A, "u": u, "nrm": (-u[1], u[0]), "L": hi - lo, "t": t, "off_in": t / 2,
            "invertido": u[0] < 0 or u[1] < 0}

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


def gaveteiro(asm, w, base, p):
    W, H, D = p["largura_mm"], p["altura_mm"], p["profundidade_mm"]
    e = p["espessura_chapa_mm"]
    soc = p.get("socalo_mm", 100.0)
    n = p.get("gavetas", 3)
    Dc = D - e
    peca(asm, w, base, "Lateral_Esq", 0, e, 0, Dc, 0, H - e, mat_corpo)
    peca(asm, w, base, "Lateral_Dir", W - e, W, 0, Dc, 0, H - e, mat_corpo)
    peca(asm, w, base, "Base", e, W - e, FUNDO_ESP, Dc, soc, soc + e, mat_corpo)
    peca(asm, w, base, "Fundo", e, W - e, 0, FUNDO_ESP, soc, H - e, mat_corpo)
    peca(asm, w, base, "Zocalo", e, W - e, Dc - RECUO_ZOCALO, Dc - RECUO_ZOCALO + e, 0, soc, mat_corpo)
    peca(asm, w, base, "Tampo", 0, W, 0, D + TAMPO_AVANCO, H - e, H, mat_corpo)

    util = (H - e - FOLGA_PORTA) - (soc + FOLGA_PORTA)            # altura disponível para as frentes
    fh = (util - (n - 1) * FOLGA_PORTA) / n                      # altura de cada frente
    comp = min(550.0, ((Dc - FUNDO_ESP - 10.0) // 50.0) * 50.0)  # comprimento da caixa (corrediça padrão)
    hc = fh - 40.0                                               # a caixa é mais baixa que a frente
    a0 = e + FOLGA_CORREDICA
    a1 = W - e - FOLGA_CORREDICA
    d1 = Dc
    d0 = Dc - comp
    for i in range(n):
        g = "Gaveta" + str(i + 1) + "_"
        zf = soc + FOLGA_PORTA + i * (fh + FOLGA_PORTA)
        peca(asm, w, base, g + "Frente", FOLGA_PORTA, W - FOLGA_PORTA, Dc, D, zf, zf + fh, mat_verde)
        zc = zf + 12.0
        if i == 0:
            zc = max(zc, soc + e + 2.0)   # a primeira caixa assenta 2 mm acima da base do corpo
        peca(asm, w, base, g + "Lateral_Esq", a0, a0 + GAVETA_ESP, d0, d1, zc, zc + hc, mat_corpo)
        peca(asm, w, base, g + "Lateral_Dir", a1 - GAVETA_ESP, a1, d0, d1, zc, zc + hc, mat_corpo)
        peca(asm, w, base, g + "Traseira", a0 + GAVETA_ESP, a1 - GAVETA_ESP, d0, d0 + GAVETA_ESP, zc, zc + hc, mat_corpo)
        peca(asm, w, base, g + "Frente_Caixa", a0 + GAVETA_ESP, a1 - GAVETA_ESP, d1 - GAVETA_ESP, d1, zc, zc + hc, mat_corpo)
        peca(asm, w, base, g + "Fundo", a0 + GAVETA_ESP, a1 - GAVETA_ESP, d0 + GAVETA_ESP, d1 - GAVETA_ESP, zc, zc + GAVETA_FUNDO, mat_corpo)


def caixa_portas(asm, w, base, p):
    """Roupeiro piso-teto, gabinete e rack suspensos: caixa branca + frentes na cor `frente_rgb`. socalo 0 = suspenso."""
    W, H, D = p["largura_mm"], p["altura_mm"], p["profundidade_mm"]
    e = p["espessura_chapa_mm"]
    soc = p.get("socalo_mm", 0.0)
    Dc = D - e
    mat_f = get_or_create_material("Frente_" + p.get("frente", "branco"), p["frente_rgb"][0], p["frente_rgb"][1], p["frente_rgb"][2])
    peca(asm, w, base, "Lateral_Esq", 0, e, 0, Dc, 0, H, mat_corpo)
    peca(asm, w, base, "Lateral_Dir", W - e, W, 0, Dc, 0, H, mat_corpo)
    peca(asm, w, base, "Base", e, W - e, FUNDO_ESP, Dc, soc, soc + e, mat_corpo)
    peca(asm, w, base, "Topo", e, W - e, FUNDO_ESP, Dc, H - e, H, mat_corpo)
    peca(asm, w, base, "Fundo", e, W - e, 0, FUNDO_ESP, soc + e, H - e, mat_corpo)
    if soc > 0:
        peca(asm, w, base, "Zocalo", e, W - e, Dc - RECUO_ZOCALO, Dc - RECUO_ZOCALO + e, 0, soc, mat_corpo)
    nd = p.get("divisorias", 0)
    if nd > 0:
        vao = ((W - 2 * e) - nd * e) / (nd + 1)
        for i in range(nd):
            a0 = e + (i + 1) * vao + i * e
            peca(asm, w, base, "Divisoria_" + str(i + 1), a0, a0 + e, FUNDO_ESP, Dc, soc + e, H - e, mat_corpo)
    n = p.get("portas", 2)
    larg = (W - (n + 1) * FOLGA_PORTA) / n
    for i in range(n):
        a0 = FOLGA_PORTA + i * (larg + FOLGA_PORTA)
        peca(asm, w, base, "Porta_" + str(i + 1), a0, a0 + larg, Dc, D, soc + FOLGA_PORTA, H - FOLGA_PORTA, mat_f)


def painel(asm, w, base, p):
    """Painel ou espelho: uma chapa na parede."""
    mat_p = get_or_create_material("Frente_" + p.get("frente", "nogueira"), p["frente_rgb"][0], p["frente_rgb"][1], p["frente_rgb"][2])
    peca(asm, w, base, "Painel", 0, p["largura_mm"], 0, p["espessura_mm"], 0, p["altura_mm"], mat_p)


BLOCOS = {"balcao_2_portas": balcao, "aereo_2_portas": aereo, "gaveteiro_3_gavetas": gaveteiro,
          "roupeiro_piso_teto": caixa_portas, "gabinete_suspenso": caixa_portas, "rack_suspenso": caixa_portas,
          "painel_parede": painel, "espelho_parede": painel}

projeto_grp = None
for g in model.get_entities().get_groups():
    if g.get_name() == ctx["nome"]:
        projeto_grp = g

paredes_livre = {}
for q in projeto["paredes"]:
    paredes_livre[q["id"]] = q

for m in moveis:
    if "lado" in m:
        w = quadro_lado(paredes_livre[m["parede_id"]], m["lado"])
        s_mm = m["distancia_do_inicio_mm"]
        if w["invertido"]:                  # o quadro corre ao contrário: s = comprimento - (distância + largura)
            s_mm = w["L"] / MM - (s_mm + m["parametros"]["largura_mm"])
    else:
        w = paredes_por_id[m["parede_id"]]
        s_mm = m["distancia_do_inicio_mm"]
    base = {"id": m["id"], "s": s_mm * MM, "afast": m.get("afastamento_mm", 0) * MM,
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
