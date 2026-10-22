# Acabamentos (cores e texturas) para o conector Trimble SketchUp.
#
# Rodar DEPOIS de sketchup_base.py e de quem cria session_state["ctx"] (sketchup_paredes.py ou sketchup_livre_ctx.py),
# ANTES de sketchup_moveis.py. Espera a global `acabamentos_cat` (gerada por tools/gerar_script_sketchup.py a partir de
# tools/acabamentos.py), só com os itens usados:
#   {"marula": {"tipo": "liso"|"madeira"|"granito"|"trama"|"porcelanato", "rgb": [r, g, b] (cor média, também o reserva),
#               "c1": [r, g, b], "c2": [r, g, b] (tons da textura), "escala_mm": 300, "semente": 3, "aneis": 6}}
#
# O sandbox do conector não lê arquivos: as texturas são PROCEDURAIS (uma amostra de 64 x 64 pixels que se repete),
# parecidas com o material mas NÃO são a foto do fabricante. "liso" é cor sólida. Se a textura falhar, cai na cor sólida.
# Sem import, unidade em polegadas. Oferece ctx["material_acab"](id) -> Material.

ctx = session_state["ctx"]
LADO = 64
_cache = {}


def _ruido(ix, iy, sem):
    v = math.sin(ix * 127.1 + iy * 311.7 + sem * 74.7) * 43758.5453
    return v - math.floor(v)


def _suave(x, y, sem):
    """Ruído de valor periódico (8 x 8 células no tile de LADO pixels), bilinear com suavização."""
    fx = x / 8.0
    fy = y / 8.0
    i0 = int(math.floor(fx))
    j0 = int(math.floor(fy))
    tx = fx - i0
    ty = fy - j0
    tx = tx * tx * (3 - 2 * tx)
    ty = ty * ty * (3 - 2 * ty)
    a = _ruido(i0 % 8, j0 % 8, sem)
    b = _ruido((i0 + 1) % 8, j0 % 8, sem)
    c = _ruido(i0 % 8, (j0 + 1) % 8, sem)
    d = _ruido((i0 + 1) % 8, (j0 + 1) % 8, sem)
    return (a * (1 - tx) + b * tx) * (1 - ty) + (c * (1 - tx) + d * tx) * ty


def _mistura(c1, c2, t):
    t = max(0.0, min(1.0, t))
    return (c1[0] + (c2[0] - c1[0]) * t, c1[1] + (c2[1] - c1[1]) * t, c1[2] + (c2[2] - c1[2]) * t)


def _pixel(a, x, y):
    tipo = a["tipo"]
    c1 = a.get("c1", a["rgb"])
    c2 = a.get("c2", a["rgb"])
    sem = a.get("semente", 1)
    if tipo == "madeira":
        aneis = a.get("aneis", 6)
        warp = _suave(x, y, sem)
        v = 0.5 + 0.5 * math.sin(2 * math.pi * (aneis * y / LADO + 0.9 * warp))
        fibra = _ruido(0, y, sem)
        return _mistura(c1, c2, 0.55 * v + 0.25 * fibra + 0.2 * warp)
    if tipo == "granito":
        r = _ruido(x, y, sem)
        if r > 0.93:
            return c2
        if r < 0.04:
            return _mistura(c1, c2, 0.5)
        return c1
    if tipo == "trama":
        horizontal = ((x // 4) + (y // 4)) % 2 == 0
        k = (x % 4) if horizontal else (y % 4)
        brilho = 0.5 + 0.5 * math.sin(math.pi * (k + 0.5) / 4.0)
        return _mistura(c2, c1, brilho * (0.8 + 0.2 * _ruido(x, y, sem)))
    if tipo == "porcelanato":
        if x < 2 or y < 2:
            return c2
        return _mistura(c1, c2, 0.12 * _ruido(x, y, sem))
    return c1


def _textura(aid, a):
    dados = []
    for y in range(LADO):
        for x in range(LADO):
            p = _pixel(a, x, y)
            dados.append(int(max(0, min(255, p[0]))))
            dados.append(int(max(0, min(255, p[1]))))
            dados.append(int(max(0, min(255, p[2]))))
    ir = ImageRep()
    ir.set_data(bytes(dados), LADO, LADO, 24, 0)
    tex = Texture.from_image_rep(ir)
    # set_dimensions recebe PIXELS POR POLEGADA (medido no conector: o inverso deixa a amostra gigante e a textura lisa)
    ppp = LADO / (a.get("escala_mm", 300) * ctx["MM"])
    tex.set_dimensions(ppp, ppp)
    return tex


def material_acab(aid):
    if aid in _cache:
        return _cache[aid]
    a = acabamentos_cat[aid]
    nome = "Acab_" + aid
    mat = None
    for m in model.get_materials():
        if m.get_name() == nome:
            mat = m
    if mat is None:
        if a["tipo"] == "liso":
            mat = get_or_create_material(nome, a["rgb"][0], a["rgb"][1], a["rgb"][2])
        else:
            try:
                mat = Material()
                mat.set_name(nome)
                mat.set_texture(_textura(aid, a))
                model.add_materials([mat])
            except Exception:
                mat = get_or_create_material(nome + "_cor", a["rgb"][0], a["rgb"][1], a["rgb"][2])
    _cache[aid] = mat
    return mat


ctx["material_acab"] = material_acab
