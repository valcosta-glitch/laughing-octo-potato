# Helpers geométricos básicos para o conector Trimble SketchUp (build_model): unidade, material, orientação de
# faces e montagem de GeometryInput. Rodar PRIMEIRO. Sem import, unidade em polegadas.

MM = 1.0 / 25.4


def get_or_create_material(name, r, g, b, a=255):
    existing = {m.get_name(): m for m in model.get_materials()}
    if name in existing:
        return existing[name]
    mat = Material()
    mat.set_name(name)
    mat.set_color(SUColor(r, g, b, a))
    model.add_materials([mat])
    return mat


def newell(pts):
    nx = 0.0
    ny = 0.0
    nz = 0.0
    m = len(pts)
    for i in range(m):
        x1, y1, z1 = pts[i]
        x2, y2, z2 = pts[(i + 1) % m]
        nx += (y1 - y2) * (z1 + z2)
        ny += (z1 - z2) * (x1 + x2)
        nz += (x1 - x2) * (y1 + y2)
    return nx, ny, nz


def orient(pts, want):
    n = newell(pts)
    if n[0] * want[0] + n[1] * want[1] + n[2] * want[2] < 0:
        return list(reversed(pts))
    return pts


def to_geometry(faces):
    vidx = {}
    verts = []

    def vi(p):
        k = (round(p[0], 4), round(p[1], 4), round(p[2], 4))
        if k not in vidx:
            vidx[k] = len(verts)
            verts.append(SUPoint3D(p[0], p[1], p[2]))
        return vidx[k]

    for f in faces:
        for p in f["outer"]:
            vi(p)
        for hl in f["holes"]:
            for p in hl:
                vi(p)
    gi = GeometryInput()
    gi.set_vertices(verts)
    for f in faces:
        lp = LoopInput()
        for p in f["outer"]:
            lp.add_vertex_index(vi(p))
        fi, gi = gi.add_face(lp)
        for hl in f["holes"]:
            lh = LoopInput()
            for p in hl:
                lh.add_vertex_index(vi(p))
            gi = gi.face_add_inner_loop(fi, lh)
    return gi
