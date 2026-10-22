"""Testes da leitura por imagem: plantas sintéticas com gabarito, limpas e com ruído (desfoque, ruído, JPEG).

A classificação dos vãos (porta/janela) e a leitura da cota vêm do gabarito: aqui o que se testa é a GEOMETRIA
(extração + conversão), não a I.A. que classificaria os vãos."""
import io
import json
import math
import random
import sys
import tempfile
import unittest
from pathlib import Path

RAIZ = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(RAIZ / "tools"))

import imagem_extrair as ext  # noqa: E402
import imagem_gerar_teste as ger  # noqa: E402
import imagem_classificar_claude as cla  # noqa: E402
import imagem_para_json as conv_img  # noqa: E402
from dxf_para_json import validar  # noqa: E402

TOL_PAREDE_MM = 20.0
TOL_ABERTURA_MM = 30.0
TOL_LARGURA_MM = 20.0


def gerar_planta(seed, forma, ruido, pasta, transformar=None):
    """`transformar`: função PIL.Image -> PIL.Image aplicada depois de desenhar (girar, reduzir, clarear...)."""
    rng = random.Random(seed)
    pts = ger.contorno(rng, forma)
    aberturas = ger.posicionar_aberturas(rng, pts)
    img, cota = ger.desenhar(pts, aberturas, rng, ruido)
    if transformar:
        img = transformar(img)
    caminho = Path(pasta) / ("planta.jpg" if ruido else "planta.png")
    if ruido:
        buf = io.BytesIO()
        img.save(buf, "JPEG", quality=70)
        caminho.write_bytes(buf.getvalue())
    else:
        img.save(caminho)
    return caminho, pts, aberturas, cota


def classificar_pelo_gabarito(extracao, aberturas_gab, cota, px_por_mm=ger.PX_POR_MM):
    """Faz o papel da I.A.: o tipo de cada vão pela largura (as larguras de porta e janela não se cruzam no gerador)."""
    tipos = {str(a["id"]): ("porta" if round(a["largura_px"] / px_por_mm / 50) * 50 in (800, 900) else "janela")
             for a in extracao["aberturas"]}
    base = max((p for p in extracao["paredes"] if p["direcao"] == "H"), key=lambda p: p["inicio_px"][1])
    medida = float(cota["texto"].split()[0].replace(",", ".")) * 1000
    return {"calibracao": {"parede": base["id"], "referencia": "externa", "medida_mm": round(medida), "origem": "cota " + cota["texto"]},
            "aberturas": tipos, "ambiente": "SALA"}


def segmentos_norm(pts_ou_paredes, fechado):
    """Segmentos (x0,y0,x1,y1) não orientados, deslocados para o canto mínimo em (0,0)."""
    if fechado:
        segs = [(pts_ou_paredes[i], pts_ou_paredes[(i + 1) % len(pts_ou_paredes)]) for i in range(len(pts_ou_paredes))]
    else:
        segs = [((p["inicio"]["x"], p["inicio"]["y"]), (p["fim"]["x"], p["fim"]["y"])) for p in pts_ou_paredes]
    xs = [v[0] for s in segs for v in s]
    ys = [v[1] for s in segs for v in s]
    x0, y0 = min(xs), min(ys)
    return {tuple(sorted(((a[0] - x0, a[1] - y0), (b[0] - x0, b[1] - y0)))) for a, b in segs}, (x0, y0)


def meios_das_aberturas(pav, deslocamento):
    out = []
    por_id = {p["id"]: p for p in pav["paredes"]}
    for a in pav["aberturas"]:
        w = por_id[a["parede_id"]]
        L = math.hypot(w["fim"]["x"] - w["inicio"]["x"], w["fim"]["y"] - w["inicio"]["y"])
        ux, uy = (w["fim"]["x"] - w["inicio"]["x"]) / L, (w["fim"]["y"] - w["inicio"]["y"]) / L
        s = a["posicao_mm"] + a["largura_mm"] / 2
        out.append((w["inicio"]["x"] + ux * s - deslocamento[0], w["inicio"]["y"] + uy * s - deslocamento[1], a["largura_mm"], a["tipo"]))
    return out


def ponto_mais_proximo(p, lista):
    return min(lista, key=lambda q: math.hypot(p[0] - q[0], p[1] - q[1]))


class TestLeituraPorImagem(unittest.TestCase):
    def conferir(self, seed, forma, ruido, transformar=None, px_por_mm=ger.PX_POR_MM, tol_parede=TOL_PAREDE_MM,
                 tol_abertura=TOL_ABERTURA_MM, tol_largura=TOL_LARGURA_MM):
        with tempfile.TemporaryDirectory() as tmp:
            caminho, pts, aberturas_gab, cota = gerar_planta(seed, forma, ruido, tmp, transformar)
            extracao = ext.extrair(caminho)
            classif = classificar_pelo_gabarito(extracao, aberturas_gab, cota, px_por_mm)
            projeto, _ = conv_img.converter_imagem(extracao, classif)
        rotulo = f"seed={seed} forma={forma} ruido={ruido}"
        self.assertEqual(validar(projeto)[0], [], rotulo)
        pav = projeto["pavimentos"][0]

        # paredes: o contorno extraído, deslocado, bate com o do gabarito
        gab_segs, gab_desl = segmentos_norm([tuple(p) for p in pts], True)
        ext_segs, ext_desl = segmentos_norm(pav["paredes"], False)
        self.assertEqual(len(ext_segs), len(gab_segs), f"{rotulo}: número de paredes")
        for s in gab_segs:
            erro = min(max(abs(s[0][0] - t[0][0]), abs(s[0][1] - t[0][1]), abs(s[1][0] - t[1][0]), abs(s[1][1] - t[1][1])) for t in ext_segs)
            self.assertLessEqual(erro, tol_parede, f"{rotulo}: parede {s} a {erro:.0f} mm")
        self.assertLessEqual(abs(pav["paredes"][0]["espessura_mm"] - ger.ESPESSURA_MM), max(tol_parede, 10), rotulo)

        # aberturas: posição do meio, largura e tipo
        # (o gabarito usa o deslocamento do contorno de eixo; o extraído, o do seu próprio canto mínimo)
        gab_meios = []
        n = len(pts)
        for a in aberturas_gab:
            p0, p1 = pts[a["parede"]], pts[(a["parede"] + 1) % n]
            L = math.hypot(p1[0] - p0[0], p1[1] - p0[1])
            ux, uy = (p1[0] - p0[0]) / L, (p1[1] - p0[1]) / L
            s = a["s0_mm"] + a["largura_mm"] / 2
            gab_meios.append((p0[0] + ux * s - gab_desl[0], p0[1] + uy * s - gab_desl[1], a["largura_mm"], a["tipo"]))
        ext_meios = meios_das_aberturas(pav, ext_desl)
        self.assertEqual(len(ext_meios), len(gab_meios), f"{rotulo}: número de aberturas")
        for g in gab_meios:
            m = ponto_mais_proximo(g, ext_meios)
            self.assertLessEqual(math.hypot(g[0] - m[0], g[1] - m[1]), tol_abertura, f"{rotulo}: posição da abertura {g}")
            self.assertLessEqual(abs(g[2] - m[2]), tol_largura, f"{rotulo}: largura da abertura {g}")
            self.assertEqual(g[3], m[3], f"{rotulo}: tipo da abertura {g}")

    def test_retangulos_limpos(self):
        for seed in (1, 2, 3, 4, 5):
            with self.subTest(seed=seed):
                self.conferir(seed, "retangulo", False)

    def test_plantas_em_L_limpas(self):
        for seed in (11, 12, 13, 14):
            with self.subTest(seed=seed):
                self.conferir(seed, "L", False)

    def test_com_ruido_desfoque_e_jpeg(self):
        for seed, forma in ((21, "retangulo"), (22, "retangulo"), (23, "L"), (24, "L")):
            with self.subTest(seed=seed, forma=forma):
                self.conferir(seed, forma, True)


class TestImagemDegradada(unittest.TestCase):
    conferir = TestLeituraPorImagem.conferir
    assertLessEqual = unittest.TestCase.assertLessEqual
    """Mesma conferência com a imagem estragada. As tolerâncias crescem com a perda de resolução (1 px = 10 mm / escala)."""

    def test_girada_1_5_grau(self):
        from PIL import Image
        for seed, forma in ((31, "retangulo"), (32, "L")):
            with self.subTest(seed=seed, forma=forma):
                self.conferir(seed, forma, False, lambda im: im.rotate(1.5, expand=True, fillcolor=255, resample=Image.BICUBIC),
                              tol_parede=30, tol_abertura=40, tol_largura=30)

    def test_girada_com_ruido_e_jpeg(self):
        from PIL import Image
        with self.subTest():
            self.conferir(33, "L", True, lambda im: im.rotate(-2.0, expand=True, fillcolor=255, resample=Image.BICUBIC),
                          tol_parede=30, tol_abertura=40, tol_largura=30)

    def test_meia_resolucao(self):
        from PIL import Image
        for seed, forma in ((34, "retangulo"), (35, "L")):
            with self.subTest(seed=seed, forma=forma):
                self.conferir(seed, forma, False, lambda im: im.resize((im.width // 2, im.height // 2), Image.LANCZOS),
                              px_por_mm=ger.PX_POR_MM / 2, tol_parede=40, tol_abertura=50, tol_largura=40)

    def test_paredes_em_cinza_claro(self):
        import numpy as np
        from PIL import Image
        with self.subTest():
            self.conferir(36, "retangulo", False, lambda im: Image.fromarray(np.where(np.asarray(im) < 128, 150, 255).astype("uint8")))

    def test_paredes_ocas_ou_hachuradas_dao_erro_claro_e_nao_resultado_errado(self):
        import numpy as np
        from PIL import Image
        with tempfile.TemporaryDirectory() as tmp:
            caminho, *_ = gerar_planta(37, "retangulo", False, tmp)
            a = np.asarray(Image.open(caminho).convert("L")) < 128
            borda = a & ~(np.roll(a, 1, 0) & np.roll(a, -1, 0) & np.roll(a, 1, 1) & np.roll(a, -1, 1))
            oca = Path(tmp) / "oca.png"
            Image.fromarray(np.where(borda, 0, 255).astype("uint8")).save(oca)
            with self.assertRaises(ext.ErroExtracao):
                ext.extrair(oca)


class TestAvisosDeResolucao(unittest.TestCase):
    def avisos(self, fator):
        from PIL import Image
        with tempfile.TemporaryDirectory() as tmp:
            caminho, pts, ab, cota = gerar_planta(2, "retangulo", False, tmp,
                                                  (lambda im: im.resize((im.width // fator, im.height // fator), Image.LANCZOS)) if fator > 1 else None)
            e = ext.extrair(caminho)
            try:
                cl = classificar_pelo_gabarito(e, ab, cota, ger.PX_POR_MM / fator)
                _, av = conv_img.converter_imagem(e, cl)
            except Exception:
                av = []
            return e["avisos"] + av

    def test_resolucao_normal_nao_avisa(self):
        self.assertFalse([a for a in self.avisos(1) if "RESOLUÇÃO" in a or "Resolução" in a])

    def test_meia_resolucao_avisa(self):
        self.assertTrue([a for a in self.avisos(2) if "Resolução baixa" in a or "RESOLUÇÃO" in a])

    def test_um_terco_avisa_forte_sobre_perda_silenciosa(self):
        self.assertTrue([a for a in self.avisos(3) if "RESOLUÇÃO MUITO BAIXA" in a and "PERDIDOS" in a])


class TestRespostaDaIA(unittest.TestCase):
    """Parte offline da etapa de I.A.: interpretar e validar a resposta. A chamada à API não é testada aqui."""

    EXTRACAO = {"paredes": [{"id": 0, "direcao": "H", "inicio_px": [10, 10], "fim_px": [110, 10]},
                            {"id": 1, "direcao": "H", "inicio_px": [10, 90], "fim_px": [110, 90]}],
                "aberturas": [{"id": 1, "parede": 0, "largura_px": 80.0}, {"id": 2, "parede": 1, "largura_px": 100.0}]}
    BOA = {"calibracao": {"parede": 1, "referencia": "externa", "medida_mm": 5400, "origem": "cota lida: 5,40 m"},
           "aberturas": {"1": "porta", "2": "janela"}, "incertos": [2], "ambiente": "SALA"}

    def test_prompt_traz_paredes_e_vaos_da_extracao(self):
        p = cla.montar_prompt(self.EXTRACAO)
        self.assertIn("0: H  de (10, 10) a (110, 10)", p)
        self.assertIn("2 (parede 1, 100 px)", p)
        self.assertIn("NÃO estime coordenadas", p)

    def test_interpreta_json_puro_cercado_e_com_texto_em_volta(self):
        for texto in (json.dumps(self.BOA), "```json\n" + json.dumps(self.BOA) + "\n```", "Claro! Aqui está:\n" + json.dumps(self.BOA) + "\nEspero ter ajudado."):
            self.assertEqual(cla.interpretar_resposta(texto)["ambiente"], "SALA")

    def test_resposta_sem_json_ou_quebrada_e_invalida(self):
        for texto in ("não consegui ler a imagem", '{"calibracao": ', ""):
            with self.assertRaises(cla.RespostaInvalida):
                cla.interpretar_resposta(texto)

    def test_validacao_aceita_a_resposta_boa_e_normaliza(self):
        c = cla.validar_classificacao(json.loads(json.dumps(self.BOA)), self.EXTRACAO)
        self.assertEqual(c["incertos"], ["2"])
        self.assertEqual(c["calibracao"]["medida_mm"], 5400.0)

    def test_validacao_recusa_problemas(self):
        def com(**mud):
            r = json.loads(json.dumps(self.BOA))
            for k, f in mud.items():
                f(r)
            return r
        casos = {
            "vão faltando": com(a=lambda r: r["aberturas"].pop("2")),
            "vão inexistente": com(a=lambda r: r["aberturas"].update({"9": "porta"})),
            "tipo inválido": com(a=lambda r: r["aberturas"].update({"1": "portão"})),
            "parede de calibração inexistente": com(a=lambda r: r["calibracao"].update({"parede": 7})),
            "referência inválida": com(a=lambda r: r["calibracao"].update({"referencia": "meio"})),
            "medida negativa": com(a=lambda r: r["calibracao"].update({"medida_mm": -3})),
            "medida não numérica": com(a=lambda r: r["calibracao"].update({"medida_mm": "cinco"})),
            "sem calibração": com(a=lambda r: r.pop("calibracao")),
        }
        for nome, resp in casos.items():
            with self.subTest(nome), self.assertRaises(cla.RespostaInvalida):
                cla.validar_classificacao(resp, self.EXTRACAO)

    def test_incertos_viram_aviso_na_conversao(self):
        with tempfile.TemporaryDirectory() as tmp:
            caminho, pts, ab, cota = gerar_planta(2, "retangulo", False, tmp)
            e = ext.extrair(caminho)
            c = classificar_pelo_gabarito(e, ab, cota)
            c["incertos"] = ["1"]
            _, avisos = conv_img.converter_imagem(e, c)
            self.assertTrue(any("DÚVIDA" in a for a in avisos))


class TestFalhasDaLeitura(unittest.TestCase):
    def test_imagem_sem_paredes_da_erro(self):
        from PIL import Image, ImageDraw
        with tempfile.TemporaryDirectory() as tmp:
            img = Image.new("L", (300, 200), 255)
            ImageDraw.Draw(img).line([(10, 10), (290, 190)], fill=0, width=1)
            caminho = Path(tmp) / "vazia.png"
            img.save(caminho)
            with self.assertRaises(ext.ErroExtracao):
                ext.extrair(caminho)

    def test_vao_sem_classificacao_e_erro(self):
        with tempfile.TemporaryDirectory() as tmp:
            caminho, pts, ab, cota = gerar_planta(2, "retangulo", False, tmp)
            extracao = ext.extrair(caminho)
            classif = classificar_pelo_gabarito(extracao, ab, cota)
            classif["aberturas"].pop(next(iter(classif["aberturas"])))
            with self.assertRaises(conv_img.ErroImagem):
                conv_img.converter_imagem(extracao, classif)

    def test_vao_ignorado_deixa_a_parede_continua(self):
        with tempfile.TemporaryDirectory() as tmp:
            caminho, pts, ab, cota = gerar_planta(2, "retangulo", False, tmp)
            extracao = ext.extrair(caminho)
            classif = classificar_pelo_gabarito(extracao, ab, cota)
            primeiro = next(iter(classif["aberturas"]))
            classif["aberturas"][primeiro] = "ignorar"
            projeto, avisos = conv_img.converter_imagem(extracao, classif)
            self.assertEqual(len(projeto["pavimentos"][0]["aberturas"]), len(ab) - 1)
            self.assertTrue(any("ignorar" in a for a in avisos))

    def test_escala_errada_da_cota_muda_tudo_proporcionalmente(self):
        with tempfile.TemporaryDirectory() as tmp:
            caminho, pts, ab, cota = gerar_planta(2, "retangulo", False, tmp)
            extracao = ext.extrair(caminho)
            c1 = classificar_pelo_gabarito(extracao, ab, cota)
            c2 = json.loads(json.dumps(c1))
            c2["calibracao"]["medida_mm"] = c1["calibracao"]["medida_mm"] * 2
            p1, _ = conv_img.converter_imagem(extracao, c1)
            p2, _ = conv_img.converter_imagem(extracao, c2)
            w1 = p1["pavimentos"][0]["paredes"]
            w2 = p2["pavimentos"][0]["paredes"]
            self.assertAlmostEqual(max(p["fim"]["x"] for p in w2) / max(p["fim"]["x"] for p in w1), 2.0, delta=0.01)


if __name__ == "__main__":
    unittest.main()
