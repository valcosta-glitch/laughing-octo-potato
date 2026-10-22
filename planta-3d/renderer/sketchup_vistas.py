# Estilo técnico + cinco cenas em projeção ortográfica para o conector Trimble SketchUp (build_model).
#
# Rodar DEPOIS de sketchup_paredes.py (precisa de geometria no modelo). Sem import, unidade em polegadas.
# A caixa envolvente vem do próprio modelo. Cenas: Planta, Frontal, Fundos, Lateral esquerda e
# Lateral direita; câmera de abertura em perspectiva 3/4.
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


def cam_orto(eye, target, up, altura_visivel):
    c = Camera()
    c.set_orientation(eye, target, up)
    c.enable_perspective(False)
    c.set_orthographic_frustum_height(altura_visivel)
    return c


def altura_para(largura_necessaria, altura_necessaria):
    return max(altura_necessaria, largura_necessaria / ASPECT) * 1.25


vistas = [
    ("Planta", cam_orto(SUPoint3D(cx, cy, zmax + DIST), SUPoint3D(cx, cy, 0), SUVector3D(0, 1, 0), altura_para(w, d))),
    ("Frontal", cam_orto(SUPoint3D(cx, ymin - DIST, cz), SUPoint3D(cx, cy, cz), UP_Z, altura_para(w, h))),
    ("Fundos", cam_orto(SUPoint3D(cx, ymax + DIST, cz), SUPoint3D(cx, cy, cz), UP_Z, altura_para(w, h))),
    ("Lateral esquerda", cam_orto(SUPoint3D(xmin - DIST, cy, cz), SUPoint3D(cx, cy, cz), UP_Z, altura_para(d, h))),
    ("Lateral direita", cam_orto(SUPoint3D(xmax + DIST, cy, cz), SUPoint3D(cx, cy, cz), UP_Z, altura_para(d, h))),
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

# câmera de abertura: perspectiva 3/4, enquadrando a caixa inteira
fov = 35.0
az, el = math.radians(45), math.radians(30)
dx, dy, dz = math.cos(az) * math.cos(el), -math.sin(az) * math.cos(el), math.sin(el)
rl = math.hypot(dx, dy)
rx, ry = -dy / rl, dx / rl
ux, uy, uz = -dz * ry, dz * rx, dx * ry - dy * rx
hext = abs(rx) * w + abs(ry) * d
vext = abs(ux) * w + abs(uy) * d + abs(uz) * h
vh = math.radians(fov / 2)
hh = math.atan(ASPECT * math.tan(vh))
dist = max((vext / 2) / math.tan(vh), (hext / 2) / math.tan(hh)) * 1.25
hero = Camera()
hero.set_orientation(SUPoint3D(cx + dist * dx, cy + dist * dy, cz + dist * dz), SUPoint3D(cx, cy, zmin + h * 0.4), UP_Z)
hero.enable_perspective()
hero.set_perspective_frustum_fov(fov)
model.set_camera(hero)
model.set_active_scene(cenas[0])

leitura = []
for s in cenas:
    c = s.get_camera()
    o = c.get_orientation()
    leitura.append({
        "cena": s.get_name(),
        "olho": [round(o[0].x, 1), round(o[0].y, 1), round(o[0].z, 1)],
        "perspectiva": c.is_perspective(),
        "altura_ortho": round(c.get_orthographic_frustum_height(), 1),
        "usa_camera": s.get_use_camera(),
    })
mc = model.get_camera()
result = {"bbox": [round(v, 2) for v in (xmin, ymin, zmin, xmax, ymax, zmax)], "cenas": leitura,
          "model_persp": mc.is_perspective(), "model_fov": mc.get_perspective_frustum_fov()}
