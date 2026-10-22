"""Porta de vidro de correr: leitura no PDF (entre tocos de parede, painéis escalonados), esquema, frases e geometria do renderer."""
import copy
import sys
import tempfile
import unittest
from pathlib import Path

RAIZ = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(RAIZ / "tools"))
sys.path.insert(0, str(RAIZ / "tests"))

import ajustes as aj  # noqa: E402
import pdf_gerar_teste as ger  # noqa: E402
import pdf_para_json as conv  # noqa: E402
from gerar_script_sketchup import gerar_script  # noqa: E402
from test_ajustes import canonico, projeto_base  # noqa: E402
from test_marcenaria import _Ents, _Grp, _Mat  # noqa: E402
from validar import checar_projeto  # noqa: E402

PADROES = {"altura_porta_mm": 2100, "topo_janela_mm": 2100, "peitoril_janela_mm": 1000}


def projeto_correr(n_folhas=3, largura=3000, rotacao=0):
    with tempfile.TemporaryDirectory() as t:
        pdf = Path(t) / "planta.pdf"
        gab = ger.gerar_correr(pdf, n_folhas=n_folhas, largura=largura, rotacao=rotacao)
        projeto, avisos, _, _ = conv.converter_pdf(pdf, pe_direito=2600, padroes_cli=PADROES)
    return projeto, gab, avisos


class TestLeituraPDF(unittest.TestCase):
    def test_porta_de_correr_entre_tocos(self):
        projeto, gab, _ = projeto_correr()
        vaos = projeto["pavimentos"][0]["vaos"]
        self.assertEqual([v["tipo"] for v in vaos], ["porta_correr"])
        v = vaos[0]
        self.assertAlmostEqual(v["largura_mm"], gab["largura_mm"], delta=15)
        self.assertAlmostEqual(v["centro"]["x"], gab["centro_x_mm"] + 75, delta=15)             # origem = face externa da parede oeste
        self.assertEqual((v["folhas"], v["peitoril_mm"], v["altura_mm"], v["eixo"]), (3, 0, 2100, "x"))
        self.assertIn("painéis escalonados", v["evidencia"])
        self.assertEqual(checar_projeto(projeto)[0], [])

    def test_numero_de_folhas_vem_do_desenho(self):
        projeto, _, _ = projeto_correr(n_folhas=4, largura=3600)
        self.assertEqual(projeto["pavimentos"][0]["vaos"][0]["folhas"], 4)

    def test_rotacao_da_pagina(self):
        for rot in (90, 270):
            projeto, gab, _ = projeto_correr(rotacao=rot)
            vaos = projeto["pavimentos"][0]["vaos"]
            self.assertEqual([v["tipo"] for v in vaos], ["porta_correr"], rot)
            self.assertAlmostEqual(vaos[0]["largura_mm"], gab["largura_mm"], delta=15)

    def test_vao_entre_tocos_sem_paineis_continua_aberto(self):
        with tempfile.TemporaryDirectory() as t:
            pdf = Path(t) / "p.pdf"
            ger.gerar_correr(pdf, com_paineis=False)                   # só os dois tocos, sem painéis nem trilhos
            projeto, _, _, _ = conv.converter_pdf(pdf, pe_direito=2600, padroes_cli=PADROES)
        self.assertEqual(projeto["pavimentos"][0]["vaos"], [])

    def test_janelas_de_2_folhas_nao_viram_porta_de_correr(self):
        base = projeto_base()
        self.assertNotIn("porta_correr", {v["tipo"] for v in base["pavimentos"][0]["vaos"]})


class TestEsquema(unittest.TestCase):
    def test_folhas_so_em_porta_de_correr(self):
        projeto, _, _ = projeto_correr()
        p = copy.deepcopy(projeto)
        p["pavimentos"][0]["vaos"][0]["folhas"] = 9
        self.assertTrue(any("2 a 6" in e for e in checar_projeto(p)[0]))
        p = copy.deepcopy(projeto)
        p["pavimentos"][0]["vaos"][0]["tipo"] = "porta"
        self.assertTrue(any("só vale para porta de correr" in e for e in checar_projeto(p)[0]))


class TestFrases(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.base = projeto_base()
        vaos = cls.base["pavimentos"][0]["vaos"]
        cls.janela = next(v for v in vaos if v["tipo"] == "janela")["id"]
        cls.porta = next(v for v in vaos if v["tipo"] == "porta")["id"]

    def aplicar(self, *frases, projeto=None):
        return aj.aplicar_frases(projeto or self.base, list(frases))

    def vao(self, projeto, vid):
        return next(v for v in projeto["pavimentos"][0]["vaos"] if v["id"] == vid)

    def test_transformar_em_porta_de_correr(self):
        novo, _, _ = self.aplicar(f"transformar janela {self.janela[1:]} em porta de correr, 4 folhas")
        v = self.vao(novo, self.janela)
        self.assertEqual((v["tipo"], v["folhas"], v["peitoril_mm"]), ("porta_correr", 4, 0))
        self.assertEqual(v["altura_mm"], 1000 + self.vao(self.base, self.janela)["altura_mm"])      # a porta vai até o topo da janela
        novo, _, _ = self.aplicar(f"trocar vão {self.janela[1:]} para porta de correr")
        self.assertEqual(self.vao(novo, self.janela)["folhas"], 3)

    def test_mudar_folhas_e_referencia_por_tipo(self):
        a, _, _ = self.aplicar(f"transformar janela {self.janela[1:]} em porta de correr")
        n = self.janela[1:]
        b, _, _ = self.aplicar(f"porta de correr {n}: 4 folhas", projeto=a)
        self.assertEqual(self.vao(b, self.janela)["folhas"], 4)
        c, _, _ = self.aplicar(f"porta {n}: altura 2,20 m", projeto=a)                 # "porta N" vale para a de correr também
        self.assertEqual(self.vao(c, self.janela)["altura_mm"], 2200)
        with self.assertRaisesRegex(aj.ErroAjuste, "é porta, não porta de correr"):
            self.aplicar(f"porta de correr {self.porta[1:]}: 4 folhas")
        with self.assertRaisesRegex(aj.ErroAjuste, "janela"):
            self.aplicar(f"janela {n}: 4 folhas", projeto=a)

    def test_folhas_fora_do_intervalo_e_em_vao_comum(self):
        with self.assertRaisesRegex(aj.ErroAjuste, "só vale para porta de correr"):
            self.aplicar(f"janela {self.janela[1:]}: 3 folhas")
        a, _, _ = self.aplicar(f"transformar janela {self.janela[1:]} em porta de correr")
        with self.assertRaisesRegex(aj.ErroAjuste, "de 2 a 6"):
            self.aplicar(f"porta de correr {self.janela[1:]}: 8 folhas", projeto=a)

    def test_voltar_a_porta_tira_as_folhas_e_desfaz(self):
        a, _, _ = self.aplicar(f"transformar janela {self.janela[1:]} em porta de correr, 4 folhas")
        b, _, _ = self.aplicar(f"transformar vão {self.janela[1:]} em porta", projeto=a)
        self.assertNotIn("folhas", self.vao(b, self.janela))
        self.assertEqual(self.vao(b, self.janela)["tipo"], "porta")
        c, _ = aj.desfazer(b)
        self.assertEqual(canonico(c), canonico(a))
        self.assertEqual(self.vao(c, self.janela)["folhas"], 4)

    def test_adicionar_porta_de_correr(self):
        base = self.base["pavimentos"][0]
        p4 = next(p for p in base["paredes"] if p["inicio"]["y"] == p["fim"]["y"] and abs(p["inicio"]["x"] - p["fim"]["x"]) > 3500)
        novo, _, _ = self.aplicar(f"adicionar porta de correr de 2,4 m na parede {p4['id']} a 0,8 m do início, 2 folhas")
        v = next(v for v in novo["pavimentos"][0]["vaos"] if v["tipo"] == "porta_correr")
        self.assertEqual((v["largura_mm"], v["folhas"], v["peitoril_mm"], v["altura_mm"]), (2400, 2, 0, 2100))
        self.assertEqual(checar_projeto(novo)[0], [])
        novo, _ = aj.desfazer(novo)
        self.assertEqual(canonico(novo), canonico(self.base))

    def test_em_lote_inclui_a_de_correr(self):
        a, _, _ = self.aplicar(f"transformar janela {self.janela[1:]} em porta de correr")
        b, _, _ = self.aplicar("todas as portas: altura 2,20 m", projeto=a)
        self.assertEqual(self.vao(b, self.janela)["altura_mm"], 2200)


class TestScriptERenderer(unittest.TestCase):
    def test_script_leva_folhas_so_na_de_correr(self):
        projeto, _, _ = projeto_correr()
        script = gerar_script(projeto)
        compile(script, "s.py", "exec")
        self.assertIn('"tipo": "porta_correr"', script)
        self.assertIn('"folhas": 3', script)
        base = gerar_script(projeto_base())
        self.assertNotIn('"folhas"', base.split("# ====")[0])

    def test_geometria_dos_paineis(self):
        mm = 1.0
        w = {"id": "v1", "A": (0.0, 0.0), "u": (1.0, 0.0), "nrm": (0.0, 1.0), "L": 3000.0, "t": 190.0, "off_in": 95.0, "off_out": -95.0, "h": 2600.0}
        raiz = _Grp()
        raiz.set_name("proj")
        caixas = {}

        def PO(w_, s, off, z):
            return (w_["A"][0] + w_["u"][0] * s, w_["A"][1] + w_["u"][1] * s + off, z)

        def extrude_faces(w_, loops, o0, o1):
            ss = [p[0] for lp in loops for p in lp]
            zs = [p[1] for lp in loops for p in lp]
            return (min(ss), max(ss), o0, o1, min(zs), max(zs))

        def leaf_group(pai, nome, faces, mat):
            g = _Grp()
            g.set_name(nome)
            g.caixa = faces
            pai.get_entities().add_group(g)
            return g

        class _Model:
            def get_entities(self):
                e = _Ents()
                e.g = [raiz]
                return e

        ctx = {"MM": mm, "nome": "proj", "get_or_create_material": lambda n, *a: _Mat(n), "extrude_faces": extrude_faces,
               "prism_faces": lambda *a: None, "leaf_group": leaf_group, "relatar": lambda *a: None, "paredes": [w],
               "abs": {"v1": [{"id": "v1", "tipo": "porta_correr", "s0": 0.0, "s1": 3000.0, "z0": 0.0, "z1": 2100.0, "folhas": 3}]},
               "cantos_out": [], "piso_poly": [(0, 0), (1, 0), (1, 1)]}
        env = {"session_state": {"ctx": ctx}, "model": _Model(), "Group": _Grp}
        exec((RAIZ / "renderer" / "sketchup_esquadrias.py").read_text(encoding="utf-8"), env)
        asm = next(g for g in raiz.get_entities().get_groups() if g.get_name() == "Porta_v1")
        filhos = {g.get_name(): g.caixa for g in asm.get_entities().get_groups()}
        self.assertEqual(sorted(filhos), ["Batente", "Folha1_Moldura", "Folha1_Vidro", "Folha2_Moldura", "Folha2_Vidro",
                                          "Folha3_Moldura", "Folha3_Vidro", "Trilho"])
        mold = [filhos[f"Folha{i}_Moldura"] for i in (1, 2, 3)]
        self.assertAlmostEqual(mold[0][0], 40.0)                         # começa no montante
        self.assertAlmostEqual(mold[2][1], 2960.0)                       # termina no outro montante
        for a, b in zip(mold, mold[1:]):
            self.assertAlmostEqual(a[1] - b[0], 50.0)                    # sobreposição de 50 mm
        offs = [(m[2] + m[3]) / 2 for m in mold]
        self.assertEqual([round(o) for o in offs], [-25, 25, -25])       # trilhos alternados
        for m in mold:
            self.assertAlmostEqual(m[3] - m[2], 40.0)
            self.assertAlmostEqual(m[4], 20.0)                           # assenta sobre o trilho
            self.assertLess(m[5], 2100.0)                                # e fica abaixo do cabeçalho
        vid = filhos["Folha2_Vidro"]
        self.assertAlmostEqual(vid[3] - vid[2], 6.0)


if __name__ == "__main__":
    unittest.main()
