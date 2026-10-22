#!/usr/bin/env python3
"""Etapa de I.A.: o Claude olha o overlay da planta e classifica os vãos e lê a escala.

*** A chamada à API (função `chamar_claude`) NÃO FOI EXECUTADA por quem escreveu este arquivo: gastaria a chave
*** ANTHROPIC_API_KEY do ambiente, o que ninguém autorizou. O resto (montagem do prompt, interpretação da resposta
*** e validação) é puro e tem testes em tests/test_imagem.py. Rode uma vez com uma planta conhecida e confira.

Uso:
  pip install anthropic
  export ANTHROPIC_API_KEY=...            # a sua
  python3 imagem_classificar_claude.py extracao.json overlay.png --saida classificacao.json [--modelo ID]

O que se pede ao modelo (e só isso): para cada vão numerado no overlay, dizer se é porta, janela ou dúvida; ler a
cota escrita na imagem e dizer a que parede ela se refere e se mede face externa, eixo ou face interna; e o nome do
ambiente. O modelo NÃO estima coordenadas: a geometria vem da extração por visão computacional.

Sai com código 1 se a resposta for inválida (vão faltando, tipo inválido, parede inexistente...). Vãos marcados
como dúvida entram em "incertos" e viram aviso na conversão: peça confirmação humana.
"""
import argparse
import base64
import json
import os
import re
import sys
from pathlib import Path

MODELO_PADRAO = "claude-sonnet-5-5"
TIPOS_VALIDOS = {"porta", "janela", "ignorar"}
REFERENCIAS = {"externa", "eixo", "interna"}

PROMPT = """Você está lendo a planta baixa de um ambiente. A imagem é um overlay: as paredes aparecem com um fino traço azul no eixo e \
os vãos (interrupções nas paredes) estão em vermelho, cada um com um NÚMERO.

Tarefa (responda SOMENTE com um objeto JSON, sem texto antes ou depois):
1. Para cada vão numerado, diga o tipo:
   - "porta": símbolo de porta (folha em linha reta mais arco de giro) ou passagem com porta de correr;
   - "janela": símbolo de janela (uma ou mais linhas finas paralelas à parede atravessando o vão);
   - "ignorar": a interrupção NÃO é uma abertura (falha do desenho, mancha, trecho de parede apagado);
   Se o símbolo for ambíguo, escolha o mais provável E inclua o número do vão em "incertos".
2. Leia a cota escrita na imagem (ex.: "5,40 m") e diga qual parede ela mede, pelo id da lista de paredes abaixo, e
   se a linha de cota vai: "externa" (de uma face externa da parede à outra), "eixo" (entre eixos) ou "interna".
   Converta o valor para milímetros ("5,40 m" -> 5400).
3. Dê o nome do ambiente se estiver escrito (ex.: "SALA"); senão, null.

NÃO estime coordenadas nem medidas por conta própria: use só o que está escrito na imagem.

Formato exato:
{"calibracao": {"parede": <id>, "referencia": "externa|eixo|interna", "medida_mm": <numero>, "origem": "cota lida: <texto da cota>"},
 "aberturas": {"1": "porta|janela|ignorar", "2": "..."},
 "incertos": [<ids de vãos duvidosos>],
 "ambiente": "<nome ou null>"}

Paredes (id, direção, início e fim em pixels; y cresce para baixo):
{paredes}

Vãos (id, parede, largura em pixels): {vaos}
"""


class RespostaInvalida(Exception):
    pass


def montar_prompt(extracao):
    paredes = "\n".join(
        f"  {p['id']}: {p['direcao']}  de ({p['inicio_px'][0]:.0f}, {p['inicio_px'][1]:.0f}) a ({p['fim_px'][0]:.0f}, {p['fim_px'][1]:.0f})"
        for p in extracao["paredes"]
    )
    vaos = "; ".join(f"{a['id']} (parede {a['parede']}, {a['largura_px']:.0f} px)" for a in extracao["aberturas"])
    return PROMPT.replace("{paredes}", paredes).replace("{vaos}", vaos)


def interpretar_resposta(texto):
    """Extrai o primeiro objeto JSON da resposta (tolera cercas ```json e texto em volta)."""
    m = re.search(r"```(?:json)?\s*(\{.*?\})\s*```", texto, re.S)
    bruto = m.group(1) if m else texto[texto.find("{"): texto.rfind("}") + 1]
    if not bruto or not bruto.startswith("{"):
        raise RespostaInvalida("a resposta não contém um objeto JSON")
    try:
        return json.loads(bruto)
    except json.JSONDecodeError as e:
        raise RespostaInvalida(f"JSON inválido na resposta: {e}")


def validar_classificacao(classif, extracao):
    """Confere a resposta contra a extração. Levanta RespostaInvalida; devolve a classificação normalizada."""
    erros = []
    cal = classif.get("calibracao")
    ids_paredes = {p["id"] for p in extracao["paredes"]}
    if not isinstance(cal, dict):
        erros.append("falta 'calibracao'")
    else:
        if cal.get("parede") not in ids_paredes:
            erros.append(f"calibracao.parede {cal.get('parede')!r} não existe (ids: {sorted(ids_paredes)})")
        if cal.get("referencia") not in REFERENCIAS:
            erros.append(f"calibracao.referencia deve ser um de {sorted(REFERENCIAS)}")
        try:
            if not float(cal.get("medida_mm")) > 0:
                erros.append("calibracao.medida_mm deve ser positiva")
        except (TypeError, ValueError):
            erros.append("calibracao.medida_mm deve ser um número")
    ab = classif.get("aberturas")
    if not isinstance(ab, dict):
        erros.append("falta 'aberturas'")
    else:
        esperados = {str(a["id"]) for a in extracao["aberturas"]}
        faltam = esperados - {str(k) for k in ab}
        sobram = {str(k) for k in ab} - esperados
        if faltam:
            erros.append(f"vãos sem classificação: {sorted(faltam, key=int)}")
        if sobram:
            erros.append(f"vãos que não existem na extração: {sorted(sobram)}")
        for k, v in ab.items():
            if v not in TIPOS_VALIDOS:
                erros.append(f"vão {k}: tipo {v!r} inválido (use porta, janela ou ignorar)")
    if erros:
        raise RespostaInvalida("; ".join(erros))
    incertos = [str(i) for i in classif.get("incertos", [])]
    return {
        "calibracao": {"parede": cal["parede"], "referencia": cal["referencia"], "medida_mm": float(cal["medida_mm"]),
                       "origem": cal.get("origem", "lida pela I.A.")},
        "aberturas": {str(k): v for k, v in ab.items()},
        "incertos": incertos,
        "ambiente": classif.get("ambiente"),
    }


def chamar_claude(extracao, caminho_overlay, modelo):
    """NÃO EXECUTADO por quem escreveu: usa a API da Anthropic (ANTHROPIC_API_KEY)."""
    import anthropic

    dados = base64.standard_b64encode(Path(caminho_overlay).read_bytes()).decode("ascii")
    cliente = anthropic.Anthropic()
    resposta = cliente.messages.create(
        model=modelo,
        max_tokens=1500,
        messages=[{"role": "user", "content": [
            {"type": "image", "source": {"type": "base64", "media_type": "image/png", "data": dados}},
            {"type": "text", "text": montar_prompt(extracao)},
        ]}],
    )
    return "".join(b.text for b in resposta.content if getattr(b, "type", "") == "text")


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("extracao", type=Path)
    ap.add_argument("overlay", type=Path)
    ap.add_argument("--saida", type=Path, required=True)
    ap.add_argument("--modelo", default=os.environ.get("CLAUDE_MODEL", MODELO_PADRAO))
    args = ap.parse_args()

    if not os.environ.get("ANTHROPIC_API_KEY"):
        print("ERRO: defina ANTHROPIC_API_KEY.")
        return 1
    extracao = json.loads(args.extracao.read_text(encoding="utf-8"))
    try:
        classif = validar_classificacao(interpretar_resposta(chamar_claude(extracao, args.overlay, args.modelo)), extracao)
    except RespostaInvalida as e:
        print(f"ERRO: resposta inválida do modelo: {e}")
        return 1
    args.saida.write_text(json.dumps(classif, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(f"OK: {args.saida}")
    if classif["incertos"]:
        print(f"ATENÇÃO: o modelo ficou em dúvida nos vãos {classif['incertos']}: confira no overlay antes de produzir.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
