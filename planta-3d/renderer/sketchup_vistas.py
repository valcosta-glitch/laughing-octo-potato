# Estilo técnico + seis cenas (cinco ortográficas + interior de cima) para o conector Trimble SketchUp (build_model).
#
# Rodar DEPOIS de sketchup_paredes.py (precisa de geometria no modelo; o contexto em session_state["ctx"]
# é opcional: sem ele a parede da frente não é ocultada). Sem import, unidade em polegadas.
# A caixa envolvente vem do próprio modelo. Cenas: Planta, Frontal, Fundos, Lateral esquerda e
# Lateral direita e Interior de cima (perspectiva). O arquivo abre em Interior de cima, que oculta a parede da frente.
#
# Convenção (Y+ = fundos do projeto): frontal olha de Y- para Y+, lateral direita olha de X+ para X-.
# Limite: a "Planta" é vista de cima, sem plano de corte (o conector não expõe SectionPlane).

CONSTRUCTION_DOC = {
    "rendering_options": {
        "EDGE_DISPLAY_MODE": TypedValue(int_value=1),
        "EDGE_COLOR_MODE": TypedValue(int_value=0),
        "RENDER_MODE": TypedValue(int_value=2),
        "MODEL_TRANSPARENCY": TypedValue(bool_value=False),
        "MATERIAL_TRANSPARENCY": TypedValue(bool_value=True),
        "DRAW_DEPTH_QUE": TypedValue(bool_value=False),
        "DEPTH_QUE_WIDTH": TypedValue(int_value=2),
        "DRAW_SILHOUETTES": TypedValue(bool_value=True),
        "SILHOUETTE_WIDTH": TypedValue(int_value=3),
        "DRAW_HORIZON": TypedValue(bool_value=False),
        "DRAW_GROUND": TypedValue(bool_value=False),
        "DISPLAY_SKETCH_AXES": TypedValue(bool_value=False),
        "HIGHLIGHT_COLOR": TypedValue(color_value=SUColor(0, 1, 255, 255)),
        "LOCKED_COLOR": TypedValue(color_value=SUColor(255, 0, 0, 255)),
        "BACKGROUND_COLOR": TypedValue(color_value=SUColor(255, 255, 255, 255)),
        "FACE_FRONT_COLOR": TypedValue(color_value=SUColor(255, 255, 255, 255)),
        "FACE_BACK_COLOR": TypedValue(color_value=SUColor(200, 200, 220, 255)),
        "FOREGROUND_COLOR": TypedValue(color_value=SUColor(0, 0, 0, 255)),
        "AMBIENT_OCCLUSION": TypedValue(bool_value=False),
    },
    "shadow_info": {"DISPLAY_SHADOWS": TypedValue(bool_value=False)},
}
apply_preset(model, CONSTRUCTION_DOC)

# caixa envolvente do modelo (união dos grupos de topo)
xmin = ymin = zmin = 1e18
xmax = ymax = zmax = -1e18
for g in model.get_entities().get_groups():
    bb = g.get_bounding_box()
    xmin = min(xmin, bb.min_point[0])
    ymin = min(ymin, bb.min_point[1])
    zmin = min(zmin, bb.min_point[2])
    xmax = max(xmax, bb.max_point[0])
    ymax = max(ymax, bb.max_point[1])
    zmax = max(zmax, bb.max_point[2])

cx, cy, cz = (xmin + xmax) / 2, (ymin + ymax) / 2, (zmin + zmax) / 2
w, d, h = xmax - xmin, ymax - ymin, zmax - zmin
ASPECT = 1.6
DIST = 4.0 * max(w, d, h)
UP_Z = SUVector3D(0, 0, 1)
AZ_INTERNA = 10.0
EL_INTERNA = 40.0


def cam_orto(eye, target, up, altura_visivel):
    c = Camera()
    c.set_orientation(eye, target, up)
    c.enable_perspective(False)
    c.set_orthographic_frustum_height(altura_visivel)
    return c


def altura_para(largura_necessaria, altura_necessaria):
    return max(altura_necessaria, largura_necessaria / ASPECT) * 1.25


def distancia_para(dx, dy, dz, fov):
    """Distância do olho ao centro da caixa para enquadrar a caixa inteira, olhando na direção -(dx, dy, dz)."""
    rl = math.hypot(dx, dy)
    rx, ry = -dy / rl, dx / rl
    ux, uy, uz = -dz * ry, dz * rx, dx * ry - dy * rx
    hext = abs(rx) * w + abs(ry) * d
    vext = abs(ux) * w + abs(uy) * d + abs(uz) * h
    vh = math.radians(fov / 2)
    hh = math.atan(ASPECT * math.tan(vh))
    return max((vext / 2) / math.tan(vh), (hext / 2) / math.tan(hh)) * 1.25


def cam_persp(azimute, elevacao, fov, alvo_z):
    """Perspectiva olhando para o centro da caixa. azimute: 0 = vindo de Y- (frente); positivo vai para X+."""
    az, el = math.radians(azimute), math.radians(elevacao)
    dx, dy, dz = math.sin(az) * math.cos(el), -math.cos(az) * math.cos(el), math.sin(el)
    dist = distancia_para(dx, dy, dz, fov)
    c = Camera()
    c.set_orientation(SUPoint3D(cx + dist * dx, cy + dist * dy, cz + dist * dz), SUPoint3D(cx, cy, alvo_z), UP_Z)
    c.enable_perspective()
    c.set_perspective_frustum_fov(fov)
    return c


vistas = [
    ("Planta", cam_orto(SUPoint3D(cx, cy, zmax + DIST), SUPoint3D(cx, cy, 0), SUVector3D(0, 1, 0), altura_para(w, d))),
    ("Frontal", cam_orto(SUPoint3D(cx, ymin - DIST, cz), SUPoint3D(cx, cy, cz), UP_Z, altura_para(w, h))),
    ("Fundos", cam_orto(SUPoint3D(cx, ymax + DIST, cz), SUPoint3D(cx, cy, cz), UP_Z, altura_para(w, h))),
    ("Lateral esquerda", cam_orto(SUPoint3D(xmin - DIST, cy, cz), SUPoint3D(cx, cy, cz), UP_Z, altura_para(d, h))),
    ("Lateral direita", cam_orto(SUPoint3D(xmax + DIST, cy, cz), SUPoint3D(cx, cy, cz), UP_Z, altura_para(d, h))),
    # a parede da frente é ocultada só nesta cena; 10 graus de azimute e 40 de altura mantêm o olho
    # dentro da parede leste (azimute maior com altura menor o colocaria atrás dela)
    ("Interior de cima", cam_persp(AZ_INTERNA, EL_INTERNA, 35.0, zmin + h * 0.25)),
]

cenas = []
for nome, _ in vistas:
    s = Scene()
    s.set_name(nome)
    cenas.append(s)
model.add_scenes(cenas)  # antes de configurar

for s, (nome, cam) in zip(cenas, vistas):
    s.set_use_camera(True)
    s.set_camera(cam)

# parede da frente = a que fica entre a câmera interna e o ambiente (maior produto escalar entre a
# normal externa da parede e a direção horizontal do olho). Some com as esquadrias dela, só na cena interna.
ctx_vistas = session_state.get("ctx")
oculta = None
nomes_ocultos = []
if ctx_vistas is not None and ctx_vistas.get("ocultar_nomes") is not None:
    nomes_ocultos = list(ctx_vistas["ocultar_nomes"])      # modo livre: o próprio renderer já decidiu
elif ctx_vistas is not None:
    olho_x, olho_y = math.sin(math.radians(AZ_INTERNA)), -math.cos(math.radians(AZ_INTERNA))
    frente = None
    melhor = -2.0
    for wv in ctx_vistas["paredes"]:
        dot = -wv["nrm"][0] * olho_x - wv["nrm"][1] * olho_y   # normal externa = -nrm
        if dot > melhor:
            melhor = dot
            frente = wv
    nomes_ocultos = ["Parede_" + frente["id"]]
    for ab in ctx_vistas["abs"].get(frente["id"], []):
        nomes_ocultos.append(("Porta_" if ab["tipo"] == "porta" else "Janela_") + ab["id"])
if nomes_ocultos:
    oculta = Layer()
    oculta.set_name("Parede_da_frente")
    model.add_layers([oculta])
    pai = None
    for g in model.get_entities().get_groups():
        if g.get_name() == ctx_vistas["nome"]:
            pai = g
    for g in pai.get_entities().get_groups():
        if g.get_name() in nomes_ocultos:
            g.set_layer(oculta)

# toda cena grava a visibilidade das etiquetas; senão herdaria o estado da cena anterior
for s in cenas:
    s.set_use_hidden_layers(True)
if oculta is not None:
    cenas[-1].add_layer(oculta)   # add_layer = OCULTAR nesta cena

# o arquivo abre na vista interna de cima (câmera do modelo = câmera da última cena)
model.set_camera(vistas[-1][1])
model.set_active_scene(cenas[-1])

leitura = []
for s in cenas:
    c = s.get_camera()
    o = c.get_orientation()
    h_ort = c.get_orthographic_frustum_height()   # None em cena em perspectiva
    leitura.append({
        "cena": s.get_name(),
        "olho": [round(o[0].x, 1), round(o[0].y, 1), round(o[0].z, 1)],
        "perspectiva": c.is_perspective(),
        "altura_ortho": round(h_ort, 1) if h_ort is not None else None,
        "usa_camera": s.get_use_camera(),
    })
mc = model.get_camera()
result = {"bbox": [round(v, 2) for v in (xmin, ymin, zmin, xmax, ymax, zmax)], "cenas": leitura,
          "model_persp": mc.is_perspective(), "model_fov": mc.get_perspective_frustum_fov()}
