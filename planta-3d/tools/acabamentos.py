#!/usr/bin/env python3
"""Catálogo de acabamentos (cores e texturas) v0: pinturas, madeiras, trama, granito, porcelanato.

Uso: python3 acabamentos.py            # lista o catálogo

Cada item tem um id estável (é o que o projeto grava em `textura.id` e em `parametros.frente`), nome, tipo e cores.
`rgb` é a cor média (reserva e prévia). Os tipos "madeira", "granito", "trama" e "porcelanato" viram textura PROCEDURAL
no SketchUp (o conector não lê arquivos de imagem): parecem o material, NÃO são a foto do fabricante. "liso" é cor sólida.
Os tons e as cores vieram das pranchas de detalhe a olho (marula, titânio trama, freijó, nogueira véneto, granito branco
itaúnas): confira contra a amostra física antes de aprovar com o cliente. Para trocar por foto real basta um item novo
com `imagem` quando o conector aceitar arquivos; os ids dos itens existentes não mudam.
"""
import sys
import unicodedata

CATALOGO_ID = "acabamentos"
VERSAO = 1

# id -> dados. c1/c2 são os dois tons da textura; escala_mm é o tamanho físico real da amostra repetida.
ACABAMENTOS = {
    # pinturas e lisos
    "branco": {"nome": "Branco", "tipo": "liso", "rgb": (240, 240, 235), "uso": ["parede", "movel"], "apelidos": ["branco neve", "branca"]},
    "areia": {"nome": "Areia", "tipo": "liso", "rgb": (222, 205, 175), "uso": ["parede", "movel"], "apelidos": []},
    "cinza_claro": {"nome": "Cinza claro", "tipo": "liso", "rgb": (200, 200, 198), "uso": ["parede", "movel"], "apelidos": ["cinza"]},
    "cinza_grafite": {"nome": "Cinza grafite", "tipo": "liso", "rgb": (85, 88, 92), "uso": ["parede", "movel"], "apelidos": ["grafite"]},
    "verde": {"nome": "Verde", "tipo": "liso", "rgb": (96, 140, 120), "uso": ["parede", "movel"], "apelidos": []},
    "verde_salvia": {"nome": "Verde sálvia", "tipo": "liso", "rgb": (156, 175, 150), "uso": ["parede", "movel"], "apelidos": ["salvia"]},
    "azul_petroleo": {"nome": "Azul petróleo", "tipo": "liso", "rgb": (40, 85, 100), "uso": ["parede", "movel"], "apelidos": ["petroleo"]},
    "terracota": {"nome": "Terracota", "tipo": "liso", "rgb": (190, 110, 80), "uso": ["parede", "movel"], "apelidos": []},
    "espelho": {"nome": "Espelho", "tipo": "liso", "rgb": (176, 200, 210), "uso": ["movel"], "apelidos": []},
    # madeiras e laminados (frentes das pranchas)
    "marula": {"nome": "Marula", "tipo": "madeira", "rgb": (205, 170, 125), "c1": (226, 190, 140), "c2": (176, 132, 84),
               "escala_mm": 300, "semente": 3, "aneis": 5, "uso": ["movel", "parede"], "apelidos": []},
    "freijo": {"nome": "Freijó", "tipo": "madeira", "rgb": (186, 148, 98), "c1": (206, 170, 118), "c2": (150, 112, 70),
               "escala_mm": 300, "semente": 5, "aneis": 6, "uso": ["movel", "parede"], "apelidos": []},
    "nogueira": {"nome": "Nogueira Véneto", "tipo": "madeira", "rgb": (92, 64, 48), "c1": (120, 84, 62), "c2": (64, 40, 30),
                 "escala_mm": 300, "semente": 7, "aneis": 7, "uso": ["movel", "parede"], "apelidos": ["nogueira veneto", "veneto"]},
    "carvalho": {"nome": "Carvalho", "tipo": "madeira", "rgb": (190, 160, 118), "c1": (208, 178, 134), "c2": (162, 130, 92),
                 "escala_mm": 300, "semente": 11, "aneis": 4, "uso": ["movel", "parede"], "apelidos": []},
    "titanio": {"nome": "Titânio Trama", "tipo": "trama", "rgb": (125, 128, 132), "c1": (150, 152, 156), "c2": (90, 92, 98),
                "escala_mm": 64, "semente": 2, "uso": ["movel", "parede"], "apelidos": ["titanio trama", "trama"]},
    # pedras e pisos
    "granito_itaunas": {"nome": "Granito Branco Itaúnas", "tipo": "granito", "rgb": (214, 214, 210), "c1": (226, 226, 222), "c2": (120, 120, 120),
                        "escala_mm": 200, "semente": 5, "uso": ["piso", "movel"], "apelidos": ["granito branco itaunas", "itaunas", "granito"]},
    "porcelanato_cinza": {"nome": "Porcelanato cinza 60x60", "tipo": "porcelanato", "rgb": (192, 188, 181), "c1": (205, 200, 192), "c2": (150, 146, 140),
                          "escala_mm": 600, "semente": 4, "uso": ["piso"], "apelidos": ["porcelanato", "porcelanato cinza"]},
    "porcelanato_areia": {"nome": "Porcelanato areia 60x60", "tipo": "porcelanato", "rgb": (216, 202, 178), "c1": (226, 213, 190), "c2": (170, 156, 134),
                          "escala_mm": 600, "semente": 6, "uso": ["piso"], "apelidos": ["porcelanato areia"]},
    "cimento_queimado": {"nome": "Cimento queimado", "tipo": "granito", "rgb": (170, 168, 162), "c1": (172, 170, 164), "c2": (140, 138, 132),
                         "escala_mm": 300, "semente": 9, "uso": ["piso", "parede"], "apelidos": ["cimento"]},
}


def _norm(txt):
    t = unicodedata.normalize("NFKD", txt.lower())
    t = "".join(c for c in t if not unicodedata.combining(c))
    return " ".join(t.replace("-", " ").replace("_", " ").split())


def rgb(aid):
    return tuple(ACABAMENTOS[aid]["rgb"])


def achar(texto):
    """Id do acabamento citado em `texto` (já em minúsculas, sem acento) pelo maior nome/apelido que casa, ou None."""
    t = " " + _norm(texto) + " "
    melhor, tam = None, 0
    for aid, a in ACABAMENTOS.items():
        for nome in [aid, a["nome"]] + list(a.get("apelidos", [])):
            n = _norm(nome)
            if " " + n + " " in t and len(n) > tam:
                melhor, tam = aid, len(n)
    return melhor


def normalizar_id(txt):
    """Id exato a partir de um nome digitado ('Freijó', 'nogueira véneto'); None se não existe."""
    n = _norm(txt)
    for aid, a in ACABAMENTOS.items():
        if n in [_norm(aid), _norm(a["nome"])] + [_norm(x) for x in a.get("apelidos", [])]:
            return aid
    return None


def para_renderer(ids):
    """Dicionário compacto (tuplas viram listas) dos itens usados, para o script do SketchUp."""
    saida = {}
    for aid in sorted(set(ids)):
        a = ACABAMENTOS[aid]
        item = {"tipo": a["tipo"], "rgb": list(a["rgb"])}
        for k in ("c1", "c2"):
            if k in a:
                item[k] = list(a[k])
        for k in ("escala_mm", "semente", "aneis"):
            if k in a:
                item[k] = a[k]
        saida[aid] = item
    return saida


def ref_catalogo(aid):
    return {"catalogo": CATALOGO_ID, "id": aid, "versao": VERSAO}


def main():
    for aid, a in ACABAMENTOS.items():
        print(f"{aid:20s} {a['nome']:26s} {a['tipo']:12s} rgb={a['rgb']} uso={','.join(a['uso'])}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
