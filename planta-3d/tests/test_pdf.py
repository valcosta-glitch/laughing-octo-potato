"""Testes da leitura de PDF vetorial: plantas sintéticas com gabarito (escala 1:50, A3), com e sem giro de página.

A classificação porta/janela sai dos vetores (folha de porta, 3+ linhas de janela), sem I.A. Alturas não existem
na planta: os testes conferem que saem como padrão 'inferida'. O que se testa é a GEOMETRIA e a recusa clara
de estilos não suportados (linha dupla)."""
import json
import math
import sys
import tempfile
import unittest
from pathlib import Path

RAIZ = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(RAIZ / "tools"))

import pdf_extrair as ext  # noqa: E402
import pdf_gerar_teste as ger  # noqa: E402
import pdf_para_json as conv  # noqa: E402
from gerar_script_sketchup import gerar_script  # noqa: E402
from validar import SCHEMA_PADRAO, checar_projeto  # noqa: E402
from jsonschema import Draft202012Validator  # noqa: E402

COR_PILAR = (1.0, 0.5, 0.0)
TOL_MM = 10.0
SEMENTES = range(1, 9)


def extensao(pav):
    """Largura e profundidade da caixa envolvente de todas as caixas (faces, não eixos)."""
    caixas = [conv._caixa(w) for w in pav["paredes"]]
    return (max(c[1] for c in caixas) - min(c[0] for c in caixas), max(c[3] for c in caixas) - min(c[2] for c in caixas))


def converter(seed, rotacao=0, estilo="preenchido"):
    with tempfile.TemporaryDirectory() as t:
        pdf = Path(t) / "planta.pdf"
        gab = ger.gerar(seed, pdf, rotacao, estilo)
        projeto, avisos, _, _ = conv.converter_pdf(pdf, cor_pilar=COR_PILAR)
    return gab, projeto, avisos


class TestGeometria(unittest.TestCase):
    def test_aberturas_e_dimensoes_sem_giro(self):
        for estilo, seed in [("preenchido", s) for s in SEMENTES] + [("contorno", s) for s in range(1, 5)]:
            with self.subTest(estilo=estilo, seed=seed):
                gab, projeto, _ = converter(seed, estilo=estilo)
                pav = projeto["pavimentos"][0]
                W, D, xi = gab["largura_eixos_mm"], gab["profundidade_eixos_mm"], gab["parede_interna_x_mm"]
                # origem do JSON = canto inferior esquerdo dos pilares (100 mm além do eixo dos cantos)
                esperadas = []
                for a in gab["aberturas"]:
                    if a["linha"] == "sul":
                        esperadas.append((a["tipo"], "x", a["s0"] + a["largura"] / 2 + 100, 0 + 100, a["largura"]))
                    elif a["linha"] == "norte":
                        esperadas.append((a["tipo"], "x", a["s0"] + a["largura"] / 2 + 100, D + 100, a["largura"]))
                    else:
                        esperadas.append((a["tipo"], "y", xi + 100, a["s0"] + a["largura"] / 2 + 100, a["largura"]))
                achadas = [(v["tipo"], v["eixo"], v["centro"]["x"], v["centro"]["y"], v["largura_mm"]) for v in pav["vaos"]]
                self.assertEqual(len(achadas), len(esperadas), f"{achadas} x {esperadas}")
                for e in esperadas:
                    perto = [a for a in achadas if a[0] == e[0] and a[1] == e[1]
                             and abs(a[2] - e[2]) <= TOL_MM and abs(a[3] - e[3]) <= TOL_MM and abs(a[4] - e[4]) <= TOL_MM]
                    self.assertEqual(len(perto), 1, f"vão {e} não encontrado em {achadas}")
                dx, dy = extensao(pav)
                self.assertLessEqual(abs(dx - (W + gab["pilar_mm"])), TOL_MM)
                self.assertLessEqual(abs(dy - (D + gab["pilar_mm"])), TOL_MM)
                esp = {w["espessura_mm"] for w in pav["paredes"] if w["tipo"] == "parede"}
                self.assertTrue(all(abs(e - gab["espessura_mm"]) <= TOL_MM for e in esp), esp)
                self.assertEqual(sum(1 for w in pav["paredes"] if w["tipo"] == "pilar"), 4)

    def test_giro_de_pagina_troca_eixos_mas_preserva_medidas(self):
        for rot in (90, 180, 270):
            with self.subTest(rotacao=rot):
                gab, projeto, avisos = converter(3, rot)
                pav = projeto["pavimentos"][0]
                self.assertEqual(len(pav["vaos"]), 3)
                self.assertEqual(sorted(v["largura_mm"] for v in pav["vaos"]), sorted(a["largura"] for a in gab["aberturas"]))
                dx, dy = extensao(pav)
                W, D = gab["largura_eixos_mm"] + 200, gab["profundidade_eixos_mm"] + 200
                par = (W, D) if rot == 180 else (D, W)
                self.assertLessEqual(abs(dx - par[0]), TOL_MM)
                self.assertLessEqual(abs(dy - par[1]), TOL_MM)
                self.assertTrue(any("girada" in a for a in avisos))

    def test_tipos_vem_dos_vetores(self):
        for seed in SEMENTES:
            gab, projeto, _ = converter(seed)
            tipos = sorted(v["tipo"] for v in projeto["pavimentos"][0]["vaos"])
            self.assertEqual(tipos, sorted(a["tipo"] for a in gab["aberturas"]), f"seed {seed}")


class TestSaida(unittest.TestCase):
    def test_json_valido_e_script_compila(self):
        for seed in (1, 5):
            _, projeto, _ = converter(seed)
            schema = json.loads(SCHEMA_PADRAO.read_text(encoding="utf-8"))
            self.assertEqual([e.message for e in Draft202012Validator(schema).iter_errors(projeto)], [])
            erros, _ = checar_projeto(projeto)
            self.assertEqual(erros, [])
            script = gerar_script(projeto)
            compile(script, "script_sketchup.py", "exec")     # sintaxe; a execução é no conector
            self.assertIn("Verga_", script)

    def test_alturas_sao_padrao_inferida_e_avisadas(self):
        _, projeto, avisos = converter(2)
        for v in projeto["pavimentos"][0]["vaos"]:
            self.assertEqual(v["origem"], "inferida")
            self.assertLess(v["confianca"], 0.5)
        self.assertTrue(any("PADRÃO" in a for a in avisos))

    def test_ajustes_substituem_altura_padrao(self):
        with tempfile.TemporaryDirectory() as t:
            pdf = Path(t) / "planta.pdf"
            ger.gerar(2, pdf)
            projeto, _, _, _ = conv.converter_pdf(pdf, cor_pilar=COR_PILAR, ajustes={"vaos": {"1": {"altura_mm": 2200, "peitoril_mm": 0}, "2": {"remover": True}}})
        vaos = projeto["pavimentos"][0]["vaos"]
        self.assertEqual(len(vaos), 2)
        self.assertEqual(vaos[0]["altura_mm"], 2200)
        self.assertEqual(vaos[0]["origem"], "medida")


def dxf_corte(caminho, piso, teto, portas, janelas, unidade_mm=True):
    """Corte sintético 1:1 em mm: portas/janelas = lista de (largura, altura, peitoril)."""
    import ezdxf
    from ezdxf import units
    doc = ezdxf.new("R2010")
    doc.units = units.MM
    for n in ("CORTE_PISO", "CORTE_TETO", "CORTE_PORTAS", "CORTE_JANELAS"):
        doc.layers.add(n)
    msp = doc.modelspace()
    msp.add_line((0, piso), (9000, piso), dxfattribs={"layer": "CORTE_PISO"})
    msp.add_line((0, teto), (9000, teto), dxfattribs={"layer": "CORTE_TETO"})
    x = 500
    for camada, itens in (("CORTE_PORTAS", portas), ("CORTE_JANELAS", janelas)):
        for larg, alt, peit in itens:
            msp.add_lwpolyline([(x, piso + peit), (x + larg, piso + peit), (x + larg, piso + peit + alt), (x, piso + peit + alt)],
                               close=True, dxfattribs={"layer": camada})
            x += larg + 300
    doc.saveas(caminho)


class TestCorte(unittest.TestCase):
    def _converter_com_corte(self, seed, **kw):
        with tempfile.TemporaryDirectory() as t:
            pdf, dxf = Path(t) / "planta.pdf", Path(t) / "corte.dxf"
            gab = ger.gerar(seed, pdf)
            larg_portas = sorted({a["largura"] for a in gab["aberturas"] if a["tipo"] == "porta"})
            larg_janelas = sorted({a["largura"] for a in gab["aberturas"] if a["tipo"] == "janela"})
            dxf_corte(dxf, 0, 2800, [(w, 2200, 0) for w in larg_portas], [(w, 1100, 900) for w in larg_janelas])
            projeto, avisos, _, _ = conv.converter_pdf(pdf, cor_pilar=COR_PILAR, corte=dxf, **kw)
        return gab, projeto, avisos

    def test_corte_preenche_pe_direito_altura_e_peitoril(self):
        for seed in (1, 2, 3):
            with self.subTest(seed=seed):
                _, projeto, avisos = self._converter_com_corte(seed)
                pav = projeto["pavimentos"][0]
                self.assertEqual(pav["pe_direito_mm"], 2800)
                for v in pav["vaos"]:
                    self.assertEqual(v["origem"], "medida")
                    if v["tipo"] == "porta":
                        self.assertEqual((v["altura_mm"], v["peitoril_mm"]), (2200, 0))
                    else:
                        self.assertEqual((v["altura_mm"], v["peitoril_mm"]), (1100, 900))
                self.assertFalse(any("PADRÃO" in a and "altura" in a for a in avisos), avisos)
                self.assertTrue(any("Pé-direito de 2800" in a for a in avisos))

    def test_ajuste_manual_vence_o_corte(self):
        with tempfile.TemporaryDirectory() as t:
            pdf, dxf = Path(t) / "planta.pdf", Path(t) / "corte.dxf"
            gab = ger.gerar(2, pdf)
            dxf_corte(dxf, 0, 2800, [(a["largura"], 2200, 0) for a in gab["aberturas"] if a["tipo"] == "porta"],
                      [(a["largura"], 1100, 900) for a in gab["aberturas"] if a["tipo"] == "janela"])
            projeto, _, _, _ = conv.converter_pdf(pdf, cor_pilar=COR_PILAR, corte=dxf, ajustes={"vaos": {"1": {"altura_mm": 2000, "peitoril_mm": 0}}})
        self.assertEqual(projeto["pavimentos"][0]["vaos"][0]["altura_mm"], 2000)

    def test_largura_sem_correspondencia_fica_padrao_e_avisa(self):
        with tempfile.TemporaryDirectory() as t:
            pdf, dxf = Path(t) / "planta.pdf", Path(t) / "corte.dxf"
            ger.gerar(2, pdf)
            dxf_corte(dxf, 0, 2800, [(555, 2200, 0)], [(777, 1100, 900)])     # larguras que a planta não tem
            projeto, avisos, _, _ = conv.converter_pdf(pdf, cor_pilar=COR_PILAR, corte=dxf)
        self.assertTrue(all(v["origem"] == "inferida" for v in projeto["pavimentos"][0]["vaos"]))
        self.assertTrue(any("sem retângulo de mesma largura" in a for a in avisos), avisos)

    def test_tolerancia_de_largura_permite_batente(self):
        """Vão de alvenaria = folha + batente: com --tolerancia-largura o retângulo de 800 casa com o vão de 880."""
        with tempfile.TemporaryDirectory() as t:
            pdf, dxf = Path(t) / "planta.pdf", Path(t) / "corte.dxf"
            gab = ger.gerar(2, pdf)
            dxf_corte(dxf, 0, 2800, [(a["largura"] - 80, 2200, 0) for a in gab["aberturas"] if a["tipo"] == "porta"],
                      [(a["largura"] - 80, 1100, 900) for a in gab["aberturas"] if a["tipo"] == "janela"])
            sem, _, _, _ = conv.converter_pdf(pdf, cor_pilar=COR_PILAR, corte=dxf)
            com, _, _, _ = conv.converter_pdf(pdf, cor_pilar=COR_PILAR, corte=dxf, tol_largura_mm=85)
        self.assertTrue(all(v["origem"] == "inferida" for v in sem["pavimentos"][0]["vaos"]))
        self.assertTrue(all(v["origem"] == "medida" for v in com["pavimentos"][0]["vaos"]))


class TestRecusas(unittest.TestCase):
    def test_modo_contorno_e_detectado_sozinho_e_avisa(self):
        _, projeto, avisos = converter(2, estilo="contorno")
        self.assertTrue(any("CONTORNOS" in a for a in avisos), avisos)
        self.assertEqual(len(projeto["pavimentos"][0]["vaos"]), 3)

    def test_linha_dupla_solta_e_recusada_com_erro_claro(self):
        with self.assertRaises(ext.ErroPDF) as cm:
            converter(4, estilo="linha_dupla")
        self.assertIn("linha dupla", str(cm.exception))

    def test_escala_errada_com_cor_forcada_avisa_pela_espessura(self):
        with tempfile.TemporaryDirectory() as t:
            pdf = Path(t) / "planta.pdf"
            ger.gerar(4, pdf)
            _, avisos, _, _ = conv.converter_pdf(pdf, escala=200, cor_parede=(0.5, 0.5, 0.5), cor_pilar=COR_PILAR)
        self.assertTrue(any("confira a escala" in a for a in avisos), avisos)

    def test_sem_escala_no_texto_pede_escala(self):
        import pymupdf
        with tempfile.TemporaryDirectory() as t:
            pdf = Path(t) / "sem_texto.pdf"
            doc = pymupdf.open()
            pg = doc.new_page(width=842, height=1191)
            pg.draw_rect(pymupdf.Rect(100, 100, 400, 108.5), color=(0.5, 0.5, 0.5), fill=(0.5, 0.5, 0.5))
            doc.save(pdf)
            with self.assertRaises(ext.ErroPDF) as cm:
                conv.converter_pdf(pdf)
        self.assertIn("--escala", str(cm.exception))


class TestRobustezMecanica(unittest.TestCase):
    def test_pecas_cobrem_a_mascara(self):
        with tempfile.TemporaryDirectory() as t:
            pdf = Path(t) / "planta.pdf"
            ger.gerar(6, pdf)
            r = ext.montar(pdf, cor_pilar=COR_PILAR)
        self.assertGreater(r["cobertura"], 0.97)

    def test_mutacao_deslocar_gabarito_1pct_seria_detectado(self):
        """Prova que o teste de dimensões não é frouxo: 1% na largura estoura a tolerância de 10 mm."""
        gab, projeto, _ = converter(3)
        largura = extensao(projeto["pavimentos"][0])[0]
        self.assertGreater(abs(largura * 1.01 - (gab["largura_eixos_mm"] + 200)), TOL_MM)


if __name__ == "__main__":
    unittest.main()
