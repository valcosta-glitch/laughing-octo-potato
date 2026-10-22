"""Catálogo de blocos de marcenaria (v0): parâmetros, padrões e geometria em planta.

Fonte única para o validador, o gerador de script e as frases digitadas. O desenho 3D de cada bloco está em
renderer/sketchup_moveis.py (roda dentro do SketchUp e não pode importar este módulo).

PADRÕES: as medidas padrão vieram das pranchas de detalhe da casa de praia (lidas a olho, NÃO conferidas
por cota) e valem só quando a frase/JSON não informa a medida. Tudo o que for informado vence o padrão.
As frentes são acabamentos do catálogo (tools/acabamentos.py): textura procedural, não a foto do fabricante.
"""
import math

from acabamentos import ACABAMENTOS

# frentes e painéis: qualquer acabamento do catálogo marcado para móvel (id -> RGB médio); a caixaria é sempre branca
FRENTES = {aid: tuple(a["rgb"]) for aid, a in ACABAMENTOS.items() if "movel" in a["uso"]}

# o que cada bloco exige e os padrões; "elevacao_mm" e "afastamento_mm" ficam em apoio, não em parametros
BLOCOS = {
    # blocos do modo contorno (cozinha), também válidos no livre
    "balcao_2_portas": {"descricao": "balcão baixo com tampo", "exige": ["largura_mm", "altura_mm", "profundidade_mm", "espessura_chapa_mm"],
                        "padrao": {"espessura_chapa_mm": 15}, "elevacao_mm": 0},
    "aereo_2_portas": {"descricao": "armário aéreo", "exige": ["largura_mm", "altura_mm", "profundidade_mm", "espessura_chapa_mm"],
                       "padrao": {"espessura_chapa_mm": 15}, "elevacao_mm": 1400},
    "gaveteiro_3_gavetas": {"descricao": "gaveteiro com tampo", "exige": ["largura_mm", "altura_mm", "profundidade_mm", "espessura_chapa_mm"],
                            "padrao": {"espessura_chapa_mm": 15}, "elevacao_mm": 0},
    # marcenaria das pranchas de detalhe
    "roupeiro_piso_teto": {"descricao": "roupeiro do piso ao teto, portas de frente", "exige": ["largura_mm", "profundidade_mm", "espessura_chapa_mm"],
                           "padrao": {"profundidade_mm": 550, "espessura_chapa_mm": 15, "socalo_mm": 100, "frente": "branco", "ate_o_teto": True},
                           "elevacao_mm": 0},
    "gabinete_suspenso": {"descricao": "gabinete suspenso (banheiro/lavabo)", "exige": ["largura_mm", "altura_mm", "profundidade_mm", "espessura_chapa_mm"],
                          "padrao": {"altura_mm": 850, "profundidade_mm": 480, "espessura_chapa_mm": 15, "socalo_mm": 0, "frente": "branco"},
                          "elevacao_mm": 200},
    "rack_suspenso": {"descricao": "rack baixo suspenso (TV)", "exige": ["largura_mm", "altura_mm", "profundidade_mm", "espessura_chapa_mm"],
                      "padrao": {"altura_mm": 360, "profundidade_mm": 400, "espessura_chapa_mm": 15, "socalo_mm": 0, "frente": "branco"},
                      "elevacao_mm": 240},
    "painel_parede": {"descricao": "painel de parede (cabeceira, revestimento)", "exige": ["largura_mm", "altura_mm", "espessura_mm"],
                      "padrao": {"altura_mm": 1200, "espessura_mm": 18, "frente": "nogueira"}, "elevacao_mm": 800},
    "espelho_parede": {"descricao": "espelho de parede", "exige": ["largura_mm", "altura_mm", "espessura_mm"],
                       "padrao": {"altura_mm": 1000, "espessura_mm": 6, "frente": "espelho"}, "elevacao_mm": 1050},
}

# apelidos digitáveis -> bloco (o texto já vem sem acentos e em minúsculas)
APELIDOS = {
    "roupeiro": "roupeiro_piso_teto", "armario": "roupeiro_piso_teto", "guarda-roupa": "roupeiro_piso_teto",
    "gabinete": "gabinete_suspenso", "rack": "rack_suspenso", "painel": "painel_parede", "espelho": "espelho_parede",
    "balcao": "balcao_2_portas", "aereo": "aereo_2_portas", "gaveteiro": "gaveteiro_3_gavetas",
}


def altura_do_movel(pav, m):
    """Altura efetiva em mm: com 'ate_o_teto' acompanha o pé-direito (menos a elevação)."""
    p = completar(m["bloco"]["id"], m["parametros"])
    if p.get("ate_o_teto"):
        return pav["pe_direito_mm"] - m["apoio"].get("elevacao_mm", 0)
    return p.get("altura_mm", 0)


def completar(bloco_id, parametros):
    """Parâmetros com os padrões do bloco nos campos que faltam (não sobrescreve nada). Calcula portas/divisórias."""
    if bloco_id not in BLOCOS:
        raise KeyError(bloco_id)
    p = dict(BLOCOS[bloco_id]["padrao"])
    p.update(parametros)
    if bloco_id in ("roupeiro_piso_teto", "gabinete_suspenso", "rack_suspenso") and "largura_mm" in p:
        p.setdefault("portas", max(1, math.ceil(p["largura_mm"] / 600.0)))
        if bloco_id == "roupeiro_piso_teto":
            p.setdefault("divisorias", max(0, math.ceil(p["largura_mm"] / 900.0) - 1))
        else:
            p.setdefault("divisorias", 0)
    return p


def faltando(bloco_id, parametros):
    return [k for k in BLOCOS[bloco_id]["exige"] if k not in parametros and not (k == "altura_mm" and parametros.get("ate_o_teto"))]


# ---------------------------------------------------------------------------------------------------------------
# geometria em planta (topologia livre)
LADOS = {"x": ("norte", "sul"), "y": ("leste", "oeste")}   # eixo da parede -> lados possíveis


def eixo_parede(p):
    return "x" if abs(p["inicio"]["y"] - p["fim"]["y"]) < 1e-6 else "y"


def extremos(p):
    """(eixo, coordenada do eixo, a0, a1): a0 < a1 ao longo da parede."""
    e = eixo_parede(p)
    if e == "x":
        a, b = sorted([p["inicio"]["x"], p["fim"]["x"]])
        return "x", p["inicio"]["y"], a, b
    a, b = sorted([p["inicio"]["y"], p["fim"]["y"]])
    return "y", p["inicio"]["x"], a, b


def retangulo_movel(p, m, largura, profundidade):
    """(x0, x1, y0, y1) do móvel em planta, apoiado na face `lado` da parede p (distância medida da ponta de menor coordenada)."""
    eixo, c, a0, a1 = extremos(p)
    t = p["espessura_mm"]
    s0 = a0 + m["apoio"]["distancia_do_inicio_mm"]
    s1 = s0 + largura
    af = m["apoio"].get("afastamento_mm", 0)
    lado = m["apoio"]["lado"]
    if eixo == "x":
        if lado == "norte":
            return s0, s1, c + t / 2 + af, c + t / 2 + af + profundidade
        return s0, s1, c - t / 2 - af - profundidade, c - t / 2 - af
    if lado == "leste":
        return c + t / 2 + af, c + t / 2 + af + profundidade, s0, s1
    return c - t / 2 - af - profundidade, c - t / 2 - af, s0, s1


def caixa_parede(p):
    eixo, c, a0, a1 = extremos(p)
    t = p["espessura_mm"]
    return (a0, a1, c - t / 2, c + t / 2) if eixo == "x" else (c - t / 2, c + t / 2, a0, a1)
