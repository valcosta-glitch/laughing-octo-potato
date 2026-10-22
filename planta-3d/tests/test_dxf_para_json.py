"""Testes do conversor DXF -> JSON. Rodar: python3 -m unittest discover -s tests (dentro de planta-3d/)."""
import json
import sys
import tempfile
import unittest
from pathlib import Path

RAIZ = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(RAIZ / "tools"))

import ezdxf  # noqa: E402
from ezdxf import units  # noqa: E402

import dxf_para_json as conv  # noqa: E402


def novo_doc(unidade=units.MM):
    doc = ezdxf.new("R2010")
    # ezdxf grava metros por padrão; 0 = "sem unidade" precisa ser pedido explicitamente.
    doc.header["$INSUNITS"] = 0 if unidade is None else unidade
    for nome in ("PAREDES", "PORTAS", "JANELAS"):
        doc.layers.add(nome)
    return doc


def retangulo(msp, pts, layer="PAREDES"):
    for a, b in zip(pts, pts[1:] + pts[:1]):
        msp.add_line(a, b, dxfattribs={"layer": layer})


class TestConversao(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)

    def salvar(self, doc, nome="t.dxf"):
        caminho = Path(self.tmp.name) / nome
        doc.saveas(caminho)
        return caminho

    def test_exemplo_bate_com_json_de_referencia(self):
        projeto, _ = conv.converter(RAIZ / "exemplos" / "cozinha-planta.dxf", calibracao=[0, 0, 4000, 0, 4000])
        ref = json.loads((RAIZ / "exemplos" / "cozinha-simples.json").read_text(encoding="utf-8"))
        pav, pref = projeto["pavimentos"][0], ref["pavimentos"][0]
        self.assertEqual(
            [(p["inicio"], p["fim"]) for p in pav["paredes"]],
            [(p["inicio"], p["fim"]) for p in pref["paredes"]],
        )
        for ab, rf in zip(pav["aberturas"], pref["aberturas"]):
            self.assertEqual((ab["tipo"], ab["posicao_mm"], ab["largura_mm"]), (rf["tipo"], rf["posicao_mm"], rf["largura_mm"]))
        erros, _ = conv.validar(projeto)
        self.assertEqual(erros, [])

    def test_contorno_horario_vira_antihorario(self):
        doc = novo_doc()
        retangulo(doc.modelspace(), [(0, 0), (0, 3000), (4000, 3000), (4000, 0)])  # horário
        projeto, _ = conv.converter(self.salvar(doc))
        paredes = projeto["pavimentos"][0]["paredes"]
        area = sum(p["inicio"]["x"] * p["fim"]["y"] - p["fim"]["x"] * p["inicio"]["y"] for p in paredes) / 2
        self.assertGreater(area, 0)

    def test_unidade_do_cabecalho_em_metros(self):
        doc = novo_doc(units.M)
        retangulo(doc.modelspace(), [(0, 0), (4, 0), (4, 3), (0, 3)])
        projeto, _ = conv.converter(self.salvar(doc))
        xs = {p["fim"]["x"] for p in projeto["pavimentos"][0]["paredes"]}
        self.assertIn(4000.0, xs)

    def test_unidade_ausente_exige_argumento(self):
        doc = novo_doc(None)
        retangulo(doc.modelspace(), [(0, 0), (4, 0), (4, 3), (0, 3)])
        caminho = self.salvar(doc)
        with self.assertRaises(conv.ErroConversao):
            conv.converter(caminho)
        projeto, _ = conv.converter(caminho, unidade="m")
        self.assertIn(4000.0, {p["fim"]["x"] for p in projeto["pavimentos"][0]["paredes"]})

    def test_abertura_fora_de_parede_e_ignorada_com_aviso(self):
        doc = novo_doc()
        msp = doc.modelspace()
        retangulo(msp, [(0, 0), (4000, 0), (4000, 3000), (0, 3000)])
        msp.add_line((500, 1500), (1300, 1500), dxfattribs={"layer": "PORTAS"})  # no meio do ambiente
        projeto, avisos = conv.converter(self.salvar(doc))
        self.assertEqual(projeto["pavimentos"][0]["aberturas"], [])
        self.assertTrue(any("não está sobre nenhuma parede" in a for a in avisos))

    def test_sem_paredes_da_erro(self):
        doc = novo_doc()
        with self.assertRaises(conv.ErroConversao):
            conv.converter(self.salvar(doc))

    def test_contorno_aberto_avisa_e_nao_cria_ambiente(self):
        doc = novo_doc()
        msp = doc.modelspace()
        for a, b in [((0, 0), (4000, 0)), ((4000, 0), (4000, 3000)), ((4000, 3000), (0, 3000))]:
            msp.add_line(a, b, dxfattribs={"layer": "PAREDES"})
        projeto, avisos = conv.converter(self.salvar(doc))
        self.assertEqual(projeto["pavimentos"][0]["ambientes"], [])
        self.assertTrue(any("contorno fechado" in a for a in avisos))

    def test_polilinha_com_arco_e_recusada(self):
        doc = novo_doc()
        doc.modelspace().add_lwpolyline([(0, 0, 0, 0, 0.5), (4000, 0, 0, 0, 0), (4000, 3000, 0, 0, 0)], format="xyseb", dxfattribs={"layer": "PAREDES"})
        with self.assertRaises(conv.ErroConversao):
            conv.converter(self.salvar(doc))

    def test_calibracao_do_usuario_e_registrada(self):
        projeto, avisos = conv.converter(RAIZ / "exemplos" / "cozinha-planta.dxf", calibracao=[0, 0, 4000, 0, 4000])
        self.assertEqual(projeto["projeto"]["calibracao"]["origem"], "usuario")
        self.assertFalse(any("Sem --calibracao" in a for a in avisos))
        _, avisos = conv.converter(RAIZ / "exemplos" / "cozinha-planta.dxf")
        self.assertTrue(any("Sem --calibracao" in a for a in avisos))


class TestMoveis(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)

    def doc_cozinha(self):
        doc = novo_doc()
        for nome in ("MOVEIS_BALCAO_2_PORTAS", "MOVEIS_AEREO_2_PORTAS", "MOVEIS_GAVETEIRO_3_GAVETAS", "MOVEIS_SOFA"):
            doc.layers.add(nome)
        retangulo(doc.modelspace(), [(0, 0), (4000, 0), (4000, 3000), (0, 3000)])
        return doc

    def ret(self, doc, camada, x0, y0, x1, y1):
        doc.modelspace().add_lwpolyline([(x0, y0), (x1, y0), (x1, y1), (x0, y1)], close=True, dxfattribs={"layer": camada})

    def converte(self, doc):
        caminho = Path(self.tmp.name) / "m.dxf"
        doc.saveas(caminho)
        return conv.converter(caminho)

    def test_moveis_do_exemplo_batem_com_json_de_referencia(self):
        projeto, _ = conv.converter(RAIZ / "exemplos" / "cozinha-planta.dxf", calibracao=[0, 0, 4000, 0, 4000])
        ref = json.loads((RAIZ / "exemplos" / "cozinha-simples.json").read_text(encoding="utf-8"))

        def chave(m):
            return (m["bloco"]["id"], m["apoio"]["distancia_do_inicio_mm"], m["parametros"]["largura_mm"],
                    m["parametros"]["profundidade_mm"], m["apoio"]["elevacao_mm"], m["parametros"]["altura_mm"])
        self.assertEqual(sorted(chave(m) for m in projeto["pavimentos"][0]["mobiliario"]),
                         sorted(chave(m) for m in ref["pavimentos"][0]["mobiliario"]))
        self.assertEqual(conv.validar(projeto)[0], [])

    def test_movel_longe_da_parede_e_ignorado_com_aviso(self):
        doc = self.doc_cozinha()
        self.ret(doc, "MOVEIS_BALCAO_2_PORTAS", 1000, 1000, 2200, 1600)   # no meio da sala
        projeto, avisos = self.converte(doc)
        self.assertEqual(projeto["pavimentos"][0]["mobiliario"], [])
        self.assertTrue(any("não está encostado" in a for a in avisos))

    def test_bloco_desconhecido_e_ignorado_com_aviso(self):
        doc = self.doc_cozinha()
        self.ret(doc, "MOVEIS_SOFA", 1000, 2325, 2200, 2925)
        projeto, avisos = self.converte(doc)
        self.assertEqual(projeto["pavimentos"][0]["mobiliario"], [])
        self.assertTrue(any("não existe na biblioteca" in a for a in avisos))

    def test_entidade_que_nao_e_retangulo_e_ignorada(self):
        doc = self.doc_cozinha()
        doc.modelspace().add_line((1000, 2925), (2200, 2925), dxfattribs={"layer": "MOVEIS_BALCAO_2_PORTAS"})
        projeto, avisos = self.converte(doc)
        self.assertEqual(projeto["pavimentos"][0]["mobiliario"], [])
        self.assertTrue(any("não é um retângulo" in a for a in avisos))

    def test_retangulo_girado_em_relacao_a_parede_e_ignorado(self):
        doc = self.doc_cozinha()
        doc.modelspace().add_lwpolyline([(1000, 2925), (2000, 2700), (2150, 2850), (1150, 3075)], close=True,
                                        dxfattribs={"layer": "MOVEIS_BALCAO_2_PORTAS"})
        projeto, _ = self.converte(doc)
        self.assertEqual(projeto["pavimentos"][0]["mobiliario"], [])

    def test_validador_acusa_moveis_sobrepostos(self):
        doc = self.doc_cozinha()
        self.ret(doc, "MOVEIS_BALCAO_2_PORTAS", 1000, 2325, 2200, 2925)
        self.ret(doc, "MOVEIS_GAVETEIRO_3_GAVETAS", 1800, 2325, 2400, 2925)   # invade o balcão em 400 mm
        projeto, _ = self.converte(doc)
        erros, _ = conv.validar(projeto)
        self.assertTrue(any("se sobrepõem" in e for e in erros))

    def test_aereo_sobre_balcao_nao_e_sobreposicao(self):
        doc = self.doc_cozinha()
        self.ret(doc, "MOVEIS_BALCAO_2_PORTAS", 1000, 2325, 2200, 2925)
        self.ret(doc, "MOVEIS_AEREO_2_PORTAS", 1000, 2595, 2200, 2925)
        projeto, _ = self.converte(doc)
        self.assertEqual(conv.validar(projeto)[0], [])


class TestCorte(unittest.TestCase):
    """Leitura do corte: pé-direito pela distância piso-teto; altura e peitoril por retângulo de mesma largura."""

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)

    def doc_planta(self, aberturas):
        """Sala 4000x3000 com as aberturas dadas: lista de (camada, x0, x1) sobre a parede sul."""
        doc = novo_doc()
        for nome in ("CORTE_PISO", "CORTE_TETO", "CORTE_PORTAS", "CORTE_JANELAS"):
            doc.layers.add(nome)
        retangulo(doc.modelspace(), [(0, 0), (4000, 0), (4000, 3000), (0, 3000)])
        for camada, x0, x1 in aberturas:
            doc.modelspace().add_line((x0, 0), (x1, 0), dxfattribs={"layer": camada})
        return doc

    def corte(self, doc, teto=2800, caixas=(), piso=True):
        msp = doc.modelspace()
        if piso:
            msp.add_line((0, -5000), (4000, -5000), dxfattribs={"layer": "CORTE_PISO"})
        msp.add_line((0, -5000 + teto), (4000, -5000 + teto), dxfattribs={"layer": "CORTE_TETO"})
        for camada, x0, x1, y0, y1 in caixas:   # y relativo ao piso
            msp.add_lwpolyline([(x0, -5000 + y0), (x1, -5000 + y0), (x1, -5000 + y1), (x0, -5000 + y1)], close=True,
                               dxfattribs={"layer": camada})

    def converte(self, doc):
        caminho = Path(self.tmp.name) / "c.dxf"
        doc.saveas(caminho)
        return conv.converter(caminho)

    def test_exemplo_com_corte_separado(self):
        projeto, avisos = conv.converter(RAIZ / "exemplos" / "cozinha-planta.dxf", corte=RAIZ / "exemplos" / "cozinha-corte.dxf",
                                         calibracao=[0, 0, 4000, 0, 4000])
        pav = projeto["pavimentos"][0]
        self.assertEqual(pav["pe_direito_mm"], 2800.0)
        porta = [a for a in pav["aberturas"] if a["tipo"] == "porta"][0]
        janela = [a for a in pav["aberturas"] if a["tipo"] == "janela"][0]
        self.assertEqual((porta["altura_mm"], porta["peitoril_mm"], porta["origem"]), (2200, 0, "medida"))
        self.assertEqual((janela["altura_mm"], janela["peitoril_mm"], janela["origem"]), (1200, 1000, "medida"))
        self.assertEqual(projeto["fonte"]["arquivo_corte"], "cozinha-corte.dxf")
        self.assertEqual(conv.validar(projeto)[0], [])

    def test_corte_no_mesmo_dxf_com_unidade_em_cm(self):
        projeto, _ = conv.converter(RAIZ / "exemplos" / "sala-L-planta.dxf", calibracao=[0, 0, 600, 0, 6000])
        pav = projeto["pavimentos"][0]
        self.assertEqual(pav["pe_direito_mm"], 2600.0)
        por_id = {a["id"]: a for a in pav["aberturas"]}
        self.assertEqual((por_id["janela_1"]["altura_mm"], por_id["janela_1"]["peitoril_mm"]), (1200, 900))
        self.assertEqual((por_id["janela_2"]["altura_mm"], por_id["janela_2"]["peitoril_mm"]), (1000, 1100))

    def test_sem_corte_usa_padrao_e_avisa(self):
        projeto, avisos = self.converte(self.doc_planta([("JANELAS", 1000, 2200)]))
        pav = projeto["pavimentos"][0]
        self.assertEqual(pav["pe_direito_mm"], 2700.0)
        self.assertEqual(pav["aberturas"][0]["origem"], "inferida")
        self.assertTrue(any("padrão" in a and "janela_1" in a for a in avisos))

    def test_corte_tem_prioridade_sobre_pe_direito_informado(self):
        doc = self.doc_planta([("JANELAS", 1000, 2200)])
        self.corte(doc, teto=2900, caixas=[("CORTE_JANELAS", 1000, 2200, 1000, 2100)])
        caminho = Path(self.tmp.name) / "p.dxf"
        doc.saveas(caminho)
        projeto, avisos = conv.converter(caminho, pe_direito=2500)
        self.assertEqual(projeto["pavimentos"][0]["pe_direito_mm"], 2900.0)
        self.assertTrue(any("difere do corte" in a for a in avisos))

    def test_largura_repetida_com_alturas_diferentes_nao_e_chutada(self):
        doc = self.doc_planta([("JANELAS", 500, 1700), ("JANELAS", 2000, 3200)])   # duas janelas de 1200
        self.corte(doc, caixas=[("CORTE_JANELAS", 0, 1200, 1000, 2100), ("CORTE_JANELAS", 2000, 3200, 900, 2000)])
        projeto, avisos = self.converte(doc)
        for a in projeto["pavimentos"][0]["aberturas"]:
            self.assertEqual((a["altura_mm"], a["peitoril_mm"], a["origem"]), (1000, 1100, "inferida"))
        self.assertTrue(any("ambíguo" in a for a in avisos))

    def test_largura_repetida_com_mesma_altura_vale_para_as_duas(self):
        doc = self.doc_planta([("JANELAS", 500, 1700), ("JANELAS", 2000, 3200)])
        self.corte(doc, caixas=[("CORTE_JANELAS", 0, 1200, 1000, 2100)])
        projeto, _ = self.converte(doc)
        for a in projeto["pavimentos"][0]["aberturas"]:
            self.assertEqual((a["altura_mm"], a["peitoril_mm"], a["origem"]), (1100, 1000, "medida"))

    def test_retangulo_sem_abertura_correspondente_avisa_escala(self):
        doc = self.doc_planta([("JANELAS", 1000, 2200)])
        self.corte(doc, caixas=[("CORTE_JANELAS", 0, 120, 1000, 2100)])   # 120 mm: corte em outra escala/unidade
        projeto, avisos = self.converte(doc)
        self.assertEqual(projeto["pavimentos"][0]["aberturas"][0]["origem"], "inferida")
        self.assertTrue(any("escala ou unidade" in a for a in avisos))
        self.assertTrue(any("sem retângulo de mesma largura" in a for a in avisos))

    def test_sem_linha_de_piso_nao_calcula_peitoril(self):
        doc = self.doc_planta([("JANELAS", 1000, 2200)])
        self.corte(doc, piso=False, caixas=[("CORTE_JANELAS", 1000, 2200, 1000, 2100)])
        projeto, avisos = self.converte(doc)
        self.assertEqual(projeto["pavimentos"][0]["aberturas"][0]["origem"], "inferida")
        self.assertEqual(projeto["pavimentos"][0]["pe_direito_mm"], 2700.0)
        self.assertTrue(any("Falta CORTE_PISO" in a for a in avisos))

    def test_porta_com_peitoril_no_corte_vai_para_zero(self):
        doc = self.doc_planta([("PORTAS", 500, 1300)])
        self.corte(doc, caixas=[("CORTE_PORTAS", 0, 800, 200, 2300)])
        projeto, avisos = self.converte(doc)
        porta = projeto["pavimentos"][0]["aberturas"][0]
        self.assertEqual((porta["altura_mm"], porta["peitoril_mm"]), (2100, 0))
        self.assertTrue(any("peitoril" in a and "não é suportado" in a for a in avisos))

    def test_abertura_mais_alta_que_o_pe_direito_e_erro_de_validacao(self):
        doc = self.doc_planta([("JANELAS", 1000, 2200)])
        self.corte(doc, teto=2000, caixas=[("CORTE_JANELAS", 1000, 2200, 1000, 2500)])
        projeto, _ = self.converte(doc)
        erros, _ = conv.validar(projeto)
        self.assertTrue(any("ultrapassa a altura" in e for e in erros))


class TestPlantaEmL(unittest.TestCase):
    """Planta em L, em centímetros, desenhada no sentido horário: exercita reorientação, unidade e parede reentrante."""

    @classmethod
    def setUpClass(cls):
        cls.projeto, cls.avisos = conv.converter(RAIZ / "exemplos" / "sala-L-planta.dxf", calibracao=[0, 0, 600, 0, 6000])

    def test_contorno_e_anti_horario_e_em_mm(self):
        paredes = self.projeto["pavimentos"][0]["paredes"]
        self.assertEqual(len(paredes), 6)
        area = sum(p["inicio"]["x"] * p["fim"]["y"] - p["fim"]["x"] * p["inicio"]["y"] for p in paredes) / 2
        self.assertAlmostEqual(area / 1e6, 25.0, places=3)   # 600x300 + 350x200 cm

    def test_aberturas_e_moveis(self):
        pav = self.projeto["pavimentos"][0]
        self.assertEqual(len(pav["aberturas"]), 3)
        self.assertEqual(len(pav["mobiliario"]), 5)
        degrau = [m for m in pav["mobiliario"] if m["apoio"]["distancia_do_inicio_mm"] == 300.0]
        self.assertEqual(len(degrau), 1)                      # o balcão da parede do degrau do L
        self.assertEqual(degrau[0]["parametros"]["largura_mm"], 1200.0)

    def test_valida_sem_erros(self):
        self.assertEqual(conv.validar(self.projeto)[0], [])

    def test_script_do_sketchup_compila_e_leva_os_dados(self):
        import gerar_script_sketchup as gen
        script = gen.gerar_script(self.projeto)
        compile(script, "script_sketchup.py", "exec")         # só sintaxe; os nomes do conector não existem aqui
        self.assertIn('"sala-L-planta"', script)
        self.assertIn("gaveteiro_3_gavetas", script)


if __name__ == "__main__":
    unittest.main()
