#!/usr/bin/env python3
"""Ajustes digitados: frase em português -> comandos estruturados -> projeto alterado, com histórico e desfazer.

Uso:
  python3 ajustes.py projeto.json "remover vão 9" "janela 3: peitoril 1,10 m" --saida projeto2.json [--script script.py]
  python3 ajustes.py projeto.json --desfazer --saida projeto3.json      # desfaz a última frase
  python3 ajustes.py projeto.json --historico

Princípios (da arquitetura do projeto):
  * Nunca código livre: a frase vira COMANDOS ESTRUTURADOS (acao, alvo, alvo_id, parametros) que este módulo valida e executa.
  * Nunca adivinha: frase que não casa com uma forma conhecida, número sem unidade ambíguo, vão que não existe, tipo que não
    confere ("janela 9" quando v9 é porta) ou direção impossível dão ERRO com a explicação; nada é alterado.
  * Atômico: se o projeto resultante não passar na validação (esquema + geometria), NADA é aplicado.
  * Auditável e reversível: cada frase vira um grupo no `historico_ajustes`, com o comando INVERSO guardado.

Formas aceitas (modo "livre", o do PDF vetorial; o modo "contorno" aceita só as de vão marcadas com [c]):
  remover vão 9 | remover janela 3 | apagar a porta v4        deixa o espaço ABERTO (sem esquadria)           [c]
  fechar vão 9                                                 troca o vão por um trecho de parede
  janela 3: peitoril 1,10 m | altura da porta 2 para 2,20 m | largura do vão 5: 0,90 m | topo da janela 3 2,10 m   [c: peitoril/altura]
  transformar vão 4 em janela (peitoril 1 m, altura 1,1 m) | transformar a janela 3 em porta
  mover janela 3 20 cm para leste | deslocar vão 5 10 cm para o sul   (só ao longo da parede)
  todas as janelas: peitoril 1 m, topo 2,10 m | todas as portas altura 2,10 m                                    [c]
  pé-direito 2,60 m                                                                                              [c]
  parede p5 espessura 15 cm | remover parede p5 | mover parede p5 10 cm para o norte (leva os vãos dela junto)
  adicionar janela de 1,20 m na parede p5 a 2 m do início [peitoril 1 m altura 1,1 m]   (início = ponta de menor coordenada)
Unidades: mm, cm ou m. Sem unidade: menor que 10 = metros; 100 ou mais = milímetros; entre 10 e 99 pede a unidade.
Direções: norte = +Y (cima na planta), sul = −Y, leste = +X, oeste = −X.
"""
import argparse
import copy
import json
import math
import re
import sys
import unicodedata
from pathlib import Path

from jsonschema import Draft202012Validator

from validar import SCHEMA_PADRAO, checar_projeto


class ErroAjuste(Exception):
    pass


class SemEfeito(ErroAjuste):
    """A frase é válida mas o projeto já está assim: vira aviso, não aborta o lote."""


# ----------------------------------------------------------------------------------------------------------------------
# acesso ao projeto
def _pav(projeto):
    return projeto["pavimentos"][0]


def _livre(projeto):
    return _pav(projeto).get("topologia") == "livre"


def _lista_vaos(projeto):
    pav = _pav(projeto)
    return pav["vaos"] if _livre(projeto) else pav.get("aberturas", [])


def _vao(projeto, vid):
    for v in _lista_vaos(projeto):
        if v["id"] == vid:
            return v
    existentes = ", ".join(v["id"] for v in _lista_vaos(projeto))
    raise ErroAjuste(f"vão '{vid}' não existe (existentes: {existentes})")


def _parede(projeto, pid):
    for p in _pav(projeto)["paredes"]:
        if p["id"] == pid:
            return p
    raise ErroAjuste(f"parede '{pid}' não existe")


def _eixo_parede(p):
    return "x" if abs(p["inicio"]["y"] - p["fim"]["y"]) < 1e-6 else "y"


def _extremos(p):
    """(eixo, coordenada_do_eixo, a0, a1, espessura) com a0 < a1 ao longo da parede."""
    e = _eixo_parede(p)
    if e == "x":
        a, b = sorted([p["inicio"]["x"], p["fim"]["x"]])
        return "x", p["inicio"]["y"], a, b, p["espessura_mm"]
    a, b = sorted([p["inicio"]["y"], p["fim"]["y"]])
    return "y", p["inicio"]["x"], a, b, p["espessura_mm"]


def _proximo_id(projeto, prefixo, extras=()):
    usados = [p["id"] for p in _pav(projeto)["paredes"]] + [v["id"] for v in _lista_vaos(projeto)] + list(extras)
    n = max([int(re.sub(r"\D", "", i) or 0) for i in usados if i.startswith(prefixo) and not (prefixo == "p" and i.startswith("pil"))] + [0])
    return f"{prefixo}{n + 1}"


# ----------------------------------------------------------------------------------------------------------------------
# números e texto
def _norm(txt):
    t = unicodedata.normalize("NFKD", txt.lower())
    t = "".join(c for c in t if not unicodedata.combining(c))
    return re.sub(r"\s+", " ", t).strip()


_NUM = r"(\d+(?:[.,]\d+)?)\s*(mm|cm|m|metros?|centimetros?|milimetros?)?(?![a-z0-9])"


def _para_mm(num, unidade, rotulo):
    v = float(num.replace(",", "."))
    if unidade:
        f = {"mm": 1, "milimetro": 1, "milimetros": 1, "cm": 10, "centimetro": 10, "centimetros": 10,
             "m": 1000, "metro": 1000, "metros": 1000}[unidade]
        return v * f
    if v < 10:
        return v * 1000.0
    if v >= 100:
        return v
    raise ErroAjuste(f"{rotulo}: '{num}' sem unidade é ambíguo (cm ou m?); escreva, por exemplo, '{num} cm'")


_REF_VAO = re.compile(r"\b(vao|janela|porta)\s*(?:n[o°º]?\s*)?v?(\d+)(?![.,]\d)\b|\bv(\d+)(?![.,]\d)\b")
_REF_PAREDE = re.compile(r"\bparede\s*(?:n[o°º]?\s*)?(pil\d+|p\d+|\d+)\b")


def _refs_vao(t):
    """Lista de (tipo_citado|None, id). Não remove nada do texto."""
    saida = []
    for m in _REF_VAO.finditer(t):
        if m.group(3):
            saida.append((None, f"v{m.group(3)}"))
        else:
            saida.append((None if m.group(1) == "vao" else m.group(1), f"v{m.group(2)}"))
    return saida


def _sem_refs(t):
    t = _REF_VAO.sub(" ", t)
    return _REF_PAREDE.sub(" ", t)


def _atributos(t):
    """Pares atributo -> mm de 'peitoril 1,10 m', 'altura 2,10 m', 'largura ...', 'topo ...', 'espessura ...'."""
    achados = {}
    for m in re.finditer(r"\b(peitoril|altura|largura|topo|espessura)\b[^0-9]{0,18}?" + _NUM, t):
        achados[m.group(1)] = _para_mm(m.group(2), m.group(3), m.group(1))
    return achados


_TIPO = {"janela": "janela", "porta": "porta"}


def _confere_tipo(projeto, citado, vid):
    v = _vao(projeto, vid)
    if citado and v.get("tipo") != citado:
        raise ErroAjuste(f"'{citado} {vid[1:]}': o vão {vid} é {v.get('tipo')}, não {citado}")
    return v


# ----------------------------------------------------------------------------------------------------------------------
# frase -> comandos primitivos
def _cmd(acao, alvo, alvo_id, parametros=None):
    return {"acao": acao, "alvo": alvo, "alvo_id": alvo_id, "parametros": parametros or {}}


_DIRECOES = {"norte": ("y", 1), "cima": ("y", 1), "sul": ("y", -1), "baixo": ("y", -1),
             "leste": ("x", 1), "direita": ("x", 1), "oeste": ("x", -1), "esquerda": ("x", -1)}


def _direcao(t):
    m = re.search(r"\b(norte|sul|leste|oeste|cima|baixo|direita|esquerda)\b", t)
    if not m:
        raise ErroAjuste("faltou a direção (norte, sul, leste ou oeste)")
    return _DIRECOES[m.group(1)]


def _um_vao(projeto, t):
    refs = _refs_vao(t)
    ids = {r[1] for r in refs}
    if len(ids) != 1:
        raise ErroAjuste("cite exatamente um vão (ex.: 'vão 9', 'janela 3' ou 'v9')")
    citado, vid = refs[0]
    return _confere_tipo(projeto, citado, vid), vid


def interpretar(texto, projeto):
    """Frase -> lista de comandos primitivos. Levanta ErroAjuste se não entender; nunca adivinha."""
    t = _norm(texto.strip().rstrip(".!"))
    if not t:
        raise ErroAjuste("frase vazia")
    livre = _livre(projeto)
    pav = _pav(projeto)

    # pé-direito
    if re.search(r"\bpe[- ]?direito\b", t):
        m = re.search(_NUM, re.sub(r"\bpe[- ]?direito\b", " ", t))
        if not m:
            raise ErroAjuste("pé-direito: faltou o valor (ex.: 'pé-direito 2,60 m')")
        return [_cmd("alterar_parametro", "pavimento", pav["id"], {"pe_direito_mm": _para_mm(m.group(1), m.group(2), "pé-direito")})]

    # em lote: todas as janelas / portas / vãos
    m = re.match(r"^(?:em )?(?:todas as|todos os|todas|todos) (janelas|portas|vaos)\b(.*)$", t)
    if m:
        quais = {"janelas": "janela", "portas": "porta", "vaos": None}[m.group(1)]
        attrs = _atributos(m.group(2))
        if not attrs or set(attrs) - {"peitoril", "altura", "topo"}:
            raise ErroAjuste("em lote só aceito peitoril, altura e topo (ex.: 'todas as janelas: peitoril 1 m, topo 2,10 m')")
        if "altura" in attrs and "topo" in attrs:
            raise ErroAjuste("informe altura OU topo, não os dois")
        alvos = [v for v in _lista_vaos(projeto) if quais is None or v["tipo"] == quais]
        if not alvos:
            raise ErroAjuste(f"o projeto não tem {m.group(1)}")
        cmds = []
        for v in alvos:
            peit = attrs.get("peitoril", v.get("peitoril_mm", 0))
            if "topo" in attrs:
                alt = attrs["topo"] - peit
                if alt <= 0:
                    raise ErroAjuste(f"topo {attrs['topo']:g} mm não fica acima do peitoril {peit:g} mm ({v['id']})")
            else:
                alt = attrs.get("altura", v["altura_mm"])
            params = {}
            if abs(peit - v.get("peitoril_mm", 0)) > 1e-9:
                params["peitoril_mm"] = peit
            if abs(alt - v["altura_mm"]) > 1e-9:
                params["altura_mm"] = alt
            if not params and v.get("origem") != "usuario":
                params = {"altura_mm": alt}            # o valor já é esse, mas dizê-lo é confirmar: passa a 'usuario'
            if params:
                cmds.append(_cmd("alterar_parametro", "vao", v["id"], params))
        if not cmds:
            raise SemEfeito("nada a alterar: os vãos já têm esses valores")
        return cmds

    # parede
    mp = _REF_PAREDE.search(t)
    if re.match(r"^adicion\w* (janela|porta)\b", t):
        return _adicionar_vao(projeto, t)
    if mp:
        pid = mp.group(1) if not mp.group(1).isdigit() else f"p{mp.group(1)}"
        if not livre:
            raise ErroAjuste("ajuste de paredes só existe no modo 'livre' (planta com vários cômodos)")
        p = _parede(projeto, pid)
        resto = _REF_PAREDE.sub(" ", t)
        if re.match(r"^(remov|apag|tir|delet|exclu)\w*", t):
            return _remover_parede(projeto, p)
        if re.match(r"^(mov|desloc|empurr)\w*", t):
            eixo_mov, sinal = _direcao(resto)
            m2 = re.search(_NUM, re.sub(r"\b(norte|sul|leste|oeste|cima|baixo|direita|esquerda)\b", " ", resto))
            if not m2:
                raise ErroAjuste("faltou a distância (ex.: 'mover parede p5 10 cm para o norte')")
            d = _para_mm(m2.group(1), m2.group(2), "distância")
            eixo_p, c, a0, a1, esp = _extremos(p)
            if eixo_mov == eixo_p:
                raise ErroAjuste(f"a parede {pid} corre ao longo de {'X' if eixo_p == 'x' else 'Y'}: só se move na perpendicular "
                                 f"({'norte/sul' if eixo_p == 'x' else 'leste/oeste'})")
            delta = sinal * d
            cmds = [_cmd("mover", "parede", pid, {"delta_mm": delta})]
            for v in pav["vaos"]:                                   # os vãos que estão nesta parede vão junto
                if v["eixo"] == eixo_p and abs((v["centro"]["y"] if eixo_p == "x" else v["centro"]["x"]) - c) <= esp / 2 + 1 \
                        and a0 - 1 <= (v["centro"]["x"] if eixo_p == "x" else v["centro"]["y"]) <= a1 + 1:
                    cmds.append(_cmd("mover", "vao", v["id"], {"delta_mm": delta, "perpendicular": True}))
            return cmds
        atr = _atributos(resto)
        if set(atr) == {"espessura"}:
            return [_cmd("alterar_parametro", "parede", pid, {"espessura_mm": atr["espessura"]})]
        raise ErroAjuste(f"parede {pid}: não entendi o que fazer (use 'espessura 15 cm', 'remover' ou 'mover ... para o norte')")

    # vão
    if _REF_VAO.search(t):
        refs = _refs_vao(t)
        if re.match(r"^(remov|apag|tir|delet|exclu)\w*", t):
            v, vid = _um_vao(projeto, t)
            return [_cmd("remover", "vao", vid)]
        if re.match(r"^(fech|tamp|vedar)\w*", t):
            if not livre:
                raise ErroAjuste("'fechar vão' só existe no modo 'livre'")
            v, vid = _um_vao(projeto, t)
            return [_cmd("remover", "vao", vid), _cmd("adicionar", "parede", _proximo_id(projeto, "p"), _parede_do_vao(v))]
        if re.match(r"^(mov|desloc|empurr)\w*", t):
            if not livre:
                raise ErroAjuste("'mover vão' só existe no modo 'livre'")
            v, vid = _um_vao(projeto, t)
            eixo_mov, sinal = _direcao(t)
            if eixo_mov != v["eixo"]:
                raise ErroAjuste(f"o vão {vid} fica numa parede que corre ao longo de {'X' if v['eixo'] == 'x' else 'Y'}: só se move "
                                 f"{'para leste/oeste' if v['eixo'] == 'x' else 'para norte/sul'}")
            m2 = re.search(_NUM, re.sub(r"\b(norte|sul|leste|oeste|cima|baixo|direita|esquerda)\b", " ", _sem_refs(t)))
            if not m2:
                raise ErroAjuste("faltou a distância (ex.: 'mover janela 3 20 cm para leste')")
            return [_cmd("mover", "vao", vid, {"delta_mm": sinal * _para_mm(m2.group(1), m2.group(2), "distância")})]
        mt = re.match(r"^(transform\w*|troc\w*|mud\w*|convert\w*)\b.*\b(?:em|para)\s+(janela|porta)\b(.*)$", t)
        if mt:
            v, vid = _um_vao(projeto, t[: mt.start(2)])
            novo = mt.group(2)
            if v["tipo"] == novo:
                raise ErroAjuste(f"o vão {vid} já é {novo}")
            attrs = _atributos(mt.group(3))
            if novo == "janela":
                if "peitoril" not in attrs or not ({"altura", "topo"} & set(attrs)):
                    raise ErroAjuste("para virar janela informe peitoril e altura (ou topo), ex.: 'transformar vão 4 em janela, peitoril 1 m, altura 1,1 m'")
                alt = attrs["altura"] if "altura" in attrs else attrs["topo"] - attrs["peitoril"]
                return [_cmd("alterar_parametro", "vao", vid, {"tipo": "janela", "peitoril_mm": attrs["peitoril"], "altura_mm": alt})]
            topo = v.get("peitoril_mm", 0) + v["altura_mm"]
            return [_cmd("alterar_parametro", "vao", vid, {"tipo": "porta", "peitoril_mm": 0,
                                                            "altura_mm": attrs.get("altura", topo)})]
        # alterar atributos de um vão
        v, vid = _um_vao(projeto, t)
        attrs = _atributos(_sem_refs(t))
        extra = set(attrs) - {"peitoril", "altura", "largura", "topo"}
        if not attrs or extra:
            raise ErroAjuste(f"vão {vid}: não entendi o que alterar (aceito peitoril, altura, topo e largura)")
        if "altura" in attrs and "topo" in attrs:
            raise ErroAjuste("informe altura OU topo, não os dois")
        peit = attrs.get("peitoril", v.get("peitoril_mm", 0))
        if v["tipo"] == "porta" and "peitoril" in attrs and attrs["peitoril"] != 0:
            raise ErroAjuste("porta vai até o piso: peitoril deve ser 0 (para outro peitoril, transforme em janela)")
        cmds = []
        params = {}
        if "peitoril" in attrs:
            params["peitoril_mm"] = attrs["peitoril"]
        if "topo" in attrs:
            if attrs["topo"] <= peit:
                raise ErroAjuste(f"topo {attrs['topo']:g} mm não fica acima do peitoril {peit:g} mm")
            params["altura_mm"] = attrs["topo"] - peit
        elif "altura" in attrs:
            params["altura_mm"] = attrs["altura"]
        elif "peitoril" in attrs and v["tipo"] == "janela" and "topo" not in attrs:
            pass            # só o peitoril: a altura fica
        if params:
            cmds.append(_cmd("alterar_parametro", "vao", vid, params))
        if "largura" in attrs:
            if not livre:
                raise ErroAjuste("alterar largura só existe no modo 'livre'")
            cmds.append(_cmd("redimensionar", "vao", vid, {"largura_mm": attrs["largura"]}))
        return cmds

    raise ErroAjuste("não entendi a frase. Formas aceitas: " + "; ".join(
        ["remover vão 9", "fechar vão 9", "janela 3: peitoril 1,10 m", "mover janela 3 20 cm para leste", "transformar vão 4 em janela, peitoril 1 m, altura 1,1 m",
         "todas as janelas: peitoril 1 m, topo 2,10 m", "pé-direito 2,60 m", "parede p5 espessura 15 cm", "remover parede p5",
         "mover parede p5 10 cm para o norte", "adicionar janela de 1,20 m na parede p5 a 2 m do início"]))


def _parede_do_vao(v):
    c, w, e = v["centro"], v["largura_mm"], v["espessura_mm"]
    if v["eixo"] == "x":
        ini, fim = {"x": c["x"] - w / 2, "y": c["y"]}, {"x": c["x"] + w / 2, "y": c["y"]}
    else:
        ini, fim = {"x": c["x"], "y": c["y"] - w / 2}, {"x": c["x"], "y": c["y"] + w / 2}
    return {"inicio": ini, "fim": fim, "espessura_mm": e, "eixo": "centro", "tipo": "parede", "origem": "usuario", "confianca": 1.0}


def _remover_parede(projeto, p):
    pav = _pav(projeto)
    eixo, c, a0, a1, esp = _extremos(p)
    presos = [v["id"] for v in pav["vaos"] if v["eixo"] == eixo and
              abs((v["centro"]["y"] if eixo == "x" else v["centro"]["x"]) - c) <= esp / 2 + 1 and
              a0 - 1 <= (v["centro"]["x"] if eixo == "x" else v["centro"]["y"]) <= a1 + 1]
    if presos:
        raise ErroAjuste(f"a parede {p['id']} tem vãos na linha dela ({', '.join(presos)}): remova-os antes")
    return [_cmd("remover", "parede", p["id"])]


def _adicionar_vao(projeto, t):
    if not _livre(projeto):
        raise ErroAjuste("adicionar vão só existe no modo 'livre'")
    pav = _pav(projeto)
    tipo = re.match(r"^adicion\w* (janela|porta)", t).group(1)
    mp = _REF_PAREDE.search(t)
    if not mp:
        raise ErroAjuste("diga a parede (ex.: 'na parede p5')")
    pid = mp.group(1) if not mp.group(1).isdigit() else f"p{mp.group(1)}"
    p = _parede(projeto, pid)
    if p.get("tipo") == "pilar":
        raise ErroAjuste("não dá para abrir vão num pilar")
    resto = _REF_PAREDE.sub(" ", t)
    mlarg = re.search(r"\bde\s+" + _NUM, resto)
    mpos = re.search(r"\ba\s+" + _NUM + r"\s+do\s+inicio\b", resto)
    if not mlarg or not mpos:
        raise ErroAjuste("faltam largura e posição: 'adicionar janela de 1,20 m na parede p5 a 2 m do início'")
    larg = _para_mm(mlarg.group(1), mlarg.group(2), "largura")
    s0 = _para_mm(mpos.group(1), mpos.group(2), "posição")
    sem = resto.replace(mlarg.group(0), " ").replace(mpos.group(0), " ")
    attrs = _atributos(sem)
    eixo, c, a0, a1, esp = _extremos(p)
    if s0 < 0 or s0 + larg > (a1 - a0) + 1e-6:
        raise ErroAjuste(f"o vão ({s0:g} a {s0 + larg:g} mm) não cabe na parede {pid} ({a1 - a0:g} mm)")
    # padrão por precedente: o que os outros vãos do mesmo tipo têm
    iguais = [v for v in pav["vaos"] if v["tipo"] == tipo]
    if tipo == "porta":
        peit = 0.0
        alt = attrs.get("altura", (iguais[0]["altura_mm"] if iguais else 2100.0))
    else:
        peit = attrs.get("peitoril", (iguais[0]["peitoril_mm"] if iguais else 1000.0))
        if "topo" in attrs:
            alt = attrs["topo"] - peit
        else:
            alt = attrs.get("altura", (iguais[0]["altura_mm"] if iguais else 1100.0))
    if alt <= 0:
        raise ErroAjuste("topo não fica acima do peitoril")
    cmds = [_cmd("remover", "parede", pid)]
    novos = []
    vid = _proximo_id(projeto, "v")
    contador = int(re.sub(r"\D", "", _proximo_id(projeto, "p")))
    base = {k: copy.deepcopy(p[k]) for k in p if k not in ("id", "inicio", "fim")}
    for ini, fim in ((a0, a0 + s0), (a0 + s0 + larg, a1)):
        if fim - ini > 1e-6:
            nid = f"p{contador}"
            contador += 1
            if eixo == "x":
                seg = {"inicio": {"x": ini, "y": c}, "fim": {"x": fim, "y": c}}
            else:
                seg = {"inicio": {"x": c, "y": ini}, "fim": {"x": c, "y": fim}}
            novos.append(_cmd("adicionar", "parede", nid, {**seg, **base}))
    centro = {"x": a0 + s0 + larg / 2, "y": c} if eixo == "x" else {"x": c, "y": a0 + s0 + larg / 2}
    novos.append(_cmd("adicionar", "vao", vid, {"tipo": tipo, "eixo": eixo, "centro": centro, "largura_mm": larg, "espessura_mm": esp,
                                                 "altura_mm": alt, "peitoril_mm": peit, "origem": "usuario", "confianca": 1.0,
                                                 "evidencia": "adicionado por ajuste digitado"}))
    return cmds + novos


# ----------------------------------------------------------------------------------------------------------------------
# execução dos comandos primitivos (cada um devolve o seu inverso)
def _marcar_usuario(v, txt):
    v["origem"], v["confianca"] = "usuario", 1.0
    v["evidencia"] = (v.get("evidencia", "") + "; " if v.get("evidencia") else "") + txt


def _executar(projeto, c):
    pav = _pav(projeto)
    acao, alvo, aid, par = c["acao"], c["alvo"], c["alvo_id"], c.get("parametros", {})
    if alvo == "pavimento":
        antigo = pav["pe_direito_mm"]
        pav["pe_direito_mm"] = par["pe_direito_mm"]
        return _cmd("alterar_parametro", "pavimento", aid, {"pe_direito_mm": antigo})
    if alvo == "parede":
        lista = pav["paredes"]
        if acao == "remover":
            p = _parede(projeto, aid)
            lista.remove(p)
            return _cmd("adicionar", "parede", aid, {k: v for k, v in p.items() if k != "id"})
        if acao == "adicionar":
            if any(p["id"] == aid for p in lista):
                raise ErroAjuste(f"já existe a parede '{aid}'")
            lista.append({"id": aid, **copy.deepcopy(par)})
            return _cmd("remover", "parede", aid)
        p = _parede(projeto, aid)
        if acao == "mover":
            d = par["delta_mm"]
            eixo = _eixo_parede(p)
            chave = "y" if eixo == "x" else "x"
            p["inicio"][chave] += d
            p["fim"][chave] += d
            return _cmd("mover", "parede", aid, {"delta_mm": -d})
        if acao == "alterar_parametro":
            antigo = p["espessura_mm"]
            p["espessura_mm"] = par["espessura_mm"]
            return _cmd("alterar_parametro", "parede", aid, {"espessura_mm": antigo})
    if alvo == "vao":
        lista = _lista_vaos(projeto)
        if acao == "remover":
            v = _vao(projeto, aid)
            lista.remove(v)
            return _cmd("adicionar", "vao", aid, {k: val for k, val in v.items() if k != "id"})
        if acao == "adicionar":
            if any(v["id"] == aid for v in lista):
                raise ErroAjuste(f"já existe o vão '{aid}'")
            lista.append({"id": aid, **copy.deepcopy(par)})
            return _cmd("remover", "vao", aid)
        v = _vao(projeto, aid)
        if acao == "mover":
            d = par["delta_mm"]
            chave = ("y" if v["eixo"] == "x" else "x") if par.get("perpendicular") else v["eixo"]
            v["centro"][chave] += d
            return _cmd("mover", "vao", aid, {**{k: x for k, x in par.items() if k != "delta_mm"}, "delta_mm": -d})
        if acao in ("alterar_parametro", "redimensionar"):
            chaves = ("tipo", "altura_mm", "peitoril_mm", "largura_mm")
            meta = ("origem", "confianca", "evidencia")
            restaurando = "_meta" in par
            for k in par:
                if k not in chaves and k != "_meta":
                    raise ErroAjuste(f"parâmetro '{k}' desconhecido")
            antigo = {k: (v.get(k, 0) if k == "peitoril_mm" else v.get(k)) for k in par if k in chaves}
            antigo["_meta"] = {k: v.get(k) for k in meta}           # None = o campo não existia
            for k, val in par.items():
                if k in chaves:
                    v[k] = val
            if restaurando:
                for k, val in par["_meta"].items():
                    if val is None:
                        v.pop(k, None)
                    else:
                        v[k] = val
            else:
                _marcar_usuario(v, "ajuste digitado")
            return _cmd(acao, "vao", aid, antigo)
    raise ErroAjuste(f"comando não suportado: {acao} {alvo}")


def _validar(projeto):
    schema = json.loads(SCHEMA_PADRAO.read_text(encoding="utf-8"))
    erros = [e.message for e in Draft202012Validator(schema).iter_errors(projeto)]
    if erros:
        raise ErroAjuste("o projeto resultante viola o esquema: " + "; ".join(erros[:3]))
    erros, avisos = checar_projeto(projeto)
    if erros:
        raise ErroAjuste("o projeto resultante é inválido: " + "; ".join(erros))
    return avisos


_OCULTOS = ("inicio", "fim", "centro", "origem", "confianca", "evidencia", "eixo", "_meta", "perpendicular", "tipo_alvo")


def descrever(c):
    """Uma linha legível do comando (o que o usuário vê antes de confirmar)."""
    p = {k: v for k, v in c.get("parametros", {}).items() if k not in _OCULTOS}
    extra = ""
    if c["acao"] == "adicionar" and c.get("parametros"):
        q = c["parametros"]
        if "inicio" in q:
            extra = f" ({q['inicio']['x']:g},{q['inicio']['y']:g})→({q['fim']['x']:g},{q['fim']['y']:g})"
        elif "centro" in q:
            extra = f" {q.get('tipo', '')} em ({q['centro']['x']:g},{q['centro']['y']:g})"
    det = ", ".join(f"{k}={('%g' % v) if isinstance(v, (int, float)) else v}" for k, v in p.items())
    return f"{c['acao']} {c['alvo']} {c['alvo_id']}{extra}" + (f": {det}" if det else "")


def aplicar_frases(projeto, frases):
    """Interpreta e aplica as frases, em ordem, ATOMICAMENTE. Retorna (novo_projeto, comandos_por_frase, avisos)."""
    novo = copy.deepcopy(projeto)
    hist = novo.setdefault("historico_ajustes", [])
    por_frase = []
    sem_efeito = []
    for k, frase in enumerate(frases):
        try:
            cmds = interpretar(frase, novo)             # interpreta sobre o estado já alterado pelas frases anteriores
        except SemEfeito as e:
            sem_efeito.append(f'"{frase}": {e}')
            por_frase.append([])
            continue
        n_grupo = max([int(re.sub(r"\D", "", h.get("grupo", "g0")) or 0) for h in hist] + [0]) + 1
        grupo = "g%d" % n_grupo
        proximo = max([int(re.sub(r"\D", "", h["id"]) or 0) for h in hist] + [0])
        for c in cmds:
            inverso = _executar(novo, c)
            proximo += 1
            hist.append({"id": f"aj{proximo}", "grupo": grupo, "texto_usuario": frase,
                         "comando": {**c, "inverso": inverso}, "aplicado": True})
        por_frase.append(cmds)
    avisos = _validar(novo)
    avisos += [f"frase sem efeito, ignorada: {m}" for m in sem_efeito]
    if any(c["acao"] == "mover" and c["alvo"] == "parede" for cmds in por_frase for c in cmds):
        avisos.append("parede movida: as paredes que se encontram com ela NÃO foram esticadas ou encurtadas; confira as junções no overlay/3D")
    return novo, por_frase, avisos


def desfazer(projeto):
    """Desfaz o último grupo (a última frase). Retorna (novo_projeto, frase_desfeita)."""
    novo = copy.deepcopy(projeto)
    hist = novo.get("historico_ajustes", [])
    ativos = [h for h in hist if h.get("aplicado")]
    if not ativos:
        raise ErroAjuste("não há ajuste para desfazer")
    grupo = ativos[-1]["grupo"]
    do_grupo = [h for h in ativos if h["grupo"] == grupo]
    for h in reversed(do_grupo):
        _executar(novo, h["comando"]["inverso"])
        hist.remove(h)
    _validar(novo)
    return novo, do_grupo[0]["texto_usuario"]


# ----------------------------------------------------------------------------------------------------------------------
def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("projeto", type=Path)
    ap.add_argument("frases", nargs="*")
    ap.add_argument("--arquivo", type=Path, help="arquivo com uma frase por linha")
    ap.add_argument("--saida", type=Path)
    ap.add_argument("--script", type=Path, help="também escreve o script do SketchUp do projeto ajustado")
    ap.add_argument("--desfazer", action="store_true")
    ap.add_argument("--historico", action="store_true")
    args = ap.parse_args()

    projeto = json.loads(args.projeto.read_text(encoding="utf-8"))
    if args.historico:
        for h in projeto.get("historico_ajustes", []):
            print(f"{h['id']} [{h.get('grupo', '-')}] \"{h['texto_usuario']}\" -> {descrever(h['comando'])}")
        return 0
    frases = list(args.frases)
    if args.arquivo:
        frases += [l.strip() for l in args.arquivo.read_text(encoding="utf-8").splitlines() if l.strip() and not l.startswith("#")]
    try:
        if args.desfazer:
            novo, frase = desfazer(projeto)
            print(f'Desfeito: "{frase}"')
        else:
            if not frases:
                ap.error("nenhuma frase")
            novo, por_frase, avisos = aplicar_frases(projeto, frases)
            for f, cmds in zip(frases, por_frase):
                print(f'"{f}" ->')
                for c in cmds:
                    print("   ", descrever(c))
            for w in avisos:
                print(f"AVISO: {w}")
    except ErroAjuste as e:
        print(f"ERRO: {e}\nNada foi alterado.")
        return 1
    if args.saida:
        args.saida.write_text(json.dumps(novo, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        print(f"Escrito {args.saida}")
        if args.script:
            from gerar_script_sketchup import gerar_script
            args.script.write_text(gerar_script(novo), encoding="utf-8")
            print(f"Escrito {args.script}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
