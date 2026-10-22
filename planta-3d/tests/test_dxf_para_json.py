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


if __name__ == "__main__":
    unittest.main()
