"""Testes dos ajustes digitados: frase -> comandos -> projeto, desfazer exato, atomicidade e recusas (sem adivinhar)."""
import copy
import json
import sys
import tempfile
import unittest
from pathlib import Path

RAIZ = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(RAIZ / "tools"))

import ajustes as aj  # noqa: E402
import pdf_gerar_teste as ger  # noqa: E402
import pdf_para_json as conv  # noqa: E402
from gerar_script_sketchup import gerar_script  # noqa: E402
from validar import SCHEMA_PADRAO, checar_projeto  # noqa: E402
from jsonschema import Draft202012Validator  # noqa: E402

COR_PILAR = (1.0, 0.5, 0.0)


def projeto_base():
    with tempfile.TemporaryDirectory() as t:
        pdf = Path(t) / "planta.pdf"
        ger.gerar(2, pdf)
        projeto, _, _, _ = conv.converter_pdf(pdf, cor_pilar=COR_PILAR, pe_direito=2600,
                                              padroes_cli={"altura_porta_mm": 2100, "topo_janela_mm": 2100, "peitoril_janela_mm": 1000})
    return projeto


def canonico(p):
    """Projeto sem histórico e com listas ordenadas por id: igualdade que ignora a ordem de reinserção."""
    q = copy.deepcopy(p)
    q.pop("historico_ajustes", None)
    pav = q["pavimentos"][0]
    pav["paredes"].sort(key=lambda x: x["id"])
    pav["vaos"].sort(key=lambda x: x["id"])
    return q


class Base(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.base = projeto_base()
        vaos = cls.base["pavimentos"][0]["vaos"]
        cls.porta = next(v for v in vaos if v["tipo"] == "porta")
        cls.janela = next(v for v in vaos if v["tipo"] == "janela")
        cls.paredes = cls.base["pavimentos"][0]["paredes"]

    def aplicar(self, *frases):
        return aj.aplicar_frases(self.base, list(frases))


class TestInterpretacao(Base):
    def test_numeros_com_unidade_e_sem(self):
        self.assertEqual(aj._para_mm("1,10", "m", "x"), 1100)
        self.assertEqual(aj._para_mm("110", "cm", "x"), 1100)
        self.assertEqual(aj._para_mm("2.10", None, "x"), 2100)      # < 10: metros
        self.assertEqual(aj._para_mm("1100", None, "x"), 1100)      # >= 100: mm
        with self.assertRaises(aj.ErroAjuste):
            aj._para_mm("90", None, "peitoril")                      # 10 a 99: ambíguo

    def test_peitoril_da_janela(self):
        c = aj.interpretar(f"janela {self.janela['id'][1:]}: peitoril 1,20 m", self.base)
        self.assertEqual(c, [aj._cmd("alterar_parametro", "vao", self.janela["id"], {"peitoril_mm": 1200})])

    def test_topo_vira_altura_com_peitoril_atual(self):
        c = aj.interpretar(f"topo da janela {self.janela['id']} 2,00 m", self.base)
        self.assertEqual(c[0]["parametros"], {"altura_mm": 2000 - self.janela["peitoril_mm"]})

    def test_acentos_e_variacoes(self):
        for frase in ("remover vão %s", "Remova o vão %s.", "apagar vão v%s", "REMOVER VÃO %s"):
            c = aj.interpretar(frase % self.porta["id"][1:], self.base)
            self.assertEqual(c, [aj._cmd("remover", "vao", self.porta["id"])])

    def test_pe_direito(self):
        for f in ("pé-direito 2,55 m", "pe direito para 255 cm", "Pé-direito 2550 mm"):
            self.assertEqual(aj.interpretar(f, self.base)[0]["parametros"], {"pe_direito_mm": 2550})

    def test_lote_janelas_so_gera_comando_para_quem_muda(self):
        c = aj.interpretar("todas as janelas: peitoril 1,10 m, topo 2,10 m", self.base)
        self.assertEqual({x["alvo_id"] for x in c}, {v["id"] for v in self.base["pavimentos"][0]["vaos"] if v["tipo"] == "janela"})
        for x in c:
            self.assertEqual(x["parametros"], {"peitoril_mm": 1100, "altura_mm": 1000})
        with self.assertRaises(aj.ErroAjuste):
            aj.interpretar("todas as janelas: peitoril 1 m, topo 2,10 m, largura 1 m", self.base)    # largura em lote: não

    def test_direcao(self):
        c = aj.interpretar(f"mover janela {self.janela['id'][1:]} 20 cm para leste", self.base)
        self.assertEqual(c[0]["parametros"], {"delta_mm": 200})
        c = aj.interpretar(f"mover janela {self.janela['id'][1:]} 20 cm para oeste", self.base)
        self.assertEqual(c[0]["parametros"], {"delta_mm": -200})


class TestRecusas(Base):
    def assertRecusa(self, frase, trecho=None):
        antes = copy.deepcopy(self.base)
        with self.assertRaises(aj.ErroAjuste) as cm:
            aj.aplicar_frases(self.base, [frase])
        self.assertEqual(self.base, antes, "o projeto original foi alterado")
        if trecho:
            self.assertIn(trecho, str(cm.exception))

    def test_nao_entendi(self):
        self.assertRecusa("deixa a casa mais bonita", "não entendi a frase")
        self.assertRecusa("")

    def test_numero_ambiguo(self):
        self.assertRecusa(f"janela {self.janela['id'][1:]}: peitoril 90", "ambíguo")

    def test_vao_inexistente(self):
        self.assertRecusa("remover vão 99", "não existe")

    def test_tipo_nao_confere(self):
        self.assertRecusa(f"remover janela {self.porta['id'][1:]}", "é porta, não janela")

    def test_direcao_impossivel_para_o_vao(self):
        eixo = self.janela["eixo"]
        errada = "norte" if eixo == "x" else "leste"
        self.assertRecusa(f"mover janela {self.janela['id'][1:]} 10 cm para {errada}", "só se move")

    def test_porta_com_peitoril(self):
        self.assertRecusa(f"porta {self.porta['id'][1:]}: peitoril 50 cm", "peitoril deve ser 0")

    def test_altura_e_topo_juntos(self):
        self.assertRecusa(f"janela {self.janela['id'][1:]}: altura 1 m, topo 2 m", "OU")

    def test_pe_direito_abaixo_da_porta_viola_validacao(self):
        self.assertRecusa("pé-direito 2 m", "ultrapassa o pé-direito")

    def test_remover_parede_com_vao(self):
        com_vao = None
        for p in self.paredes:
            if p.get("tipo") != "pilar":
                try:
                    aj.interpretar(f"remover parede {p['id']}", self.base)
                except aj.ErroAjuste as e:
                    if "tem vãos" in str(e):
                        com_vao = p["id"]
                        break
        # na planta sintética os vãos ficam entre peças (não 'na' peça): então remover é permitido; testa a recusa montando o caso
        if com_vao is None:
            proj = copy.deepcopy(self.base)
            v = proj["pavimentos"][0]["vaos"][0]
            p0 = next(p for p in proj["pavimentos"][0]["paredes"] if p.get("tipo") != "pilar")
            if v["eixo"] == "x":
                p0["inicio"]["y"] = p0["fim"]["y"] = v["centro"]["y"]
                p0["inicio"]["x"], p0["fim"]["x"] = v["centro"]["x"] - 500, v["centro"]["x"] + 500
            else:
                p0["inicio"]["x"] = p0["fim"]["x"] = v["centro"]["x"]
                p0["inicio"]["y"], p0["fim"]["y"] = v["centro"]["y"] - 500, v["centro"]["y"] + 500
            with self.assertRaises(aj.ErroAjuste) as cm:
                aj.interpretar(f"remover parede {p0['id']}", proj)
            self.assertIn("tem vãos", str(cm.exception))

    def test_lote_atomico_a_segunda_frase_invalida_nao_aplica_a_primeira(self):
        antes = copy.deepcopy(self.base)
        with self.assertRaises(aj.ErroAjuste):
            aj.aplicar_frases(self.base, [f"janela {self.janela['id'][1:]}: peitoril 1,05 m", "remover vão 99"])
        self.assertEqual(self.base, antes)

    def test_adicionar_vao_que_nao_cabe(self):
        p = max((p for p in self.paredes if p.get("tipo") != "pilar"), key=lambda p: aj._extremos(p)[3] - aj._extremos(p)[2])
        self.assertRecusa(f"adicionar janela de 1 m na parede {p['id']} a 99 m do início", "não cabe")


class TestSemEfeito(Base):
    def test_confirmar_o_mesmo_valor_marca_usuario_mas_repetir_nao_faz_nada(self):
        frase = f"todas as portas: altura {self.porta['altura_mm'] / 1000:g} m".replace(".", ",")
        inferida = copy.deepcopy(self.base)
        for v in inferida["pavimentos"][0]["vaos"]:
            v["origem"], v["confianca"] = "inferida", 0.3
        novo, por_frase, _ = aj.aplicar_frases(inferida, [frase])
        portas = [v for v in novo["pavimentos"][0]["vaos"] if v["tipo"] == "porta"]
        self.assertTrue(por_frase[0] and all(v["origem"] == "usuario" for v in portas))
        # já confirmado: repetir é sem efeito (aviso), e o resto do lote segue
        novo2, por_frase2, avisos = aj.aplicar_frases(novo, [frase, "pé-direito 2,70 m"])
        self.assertEqual(por_frase2[0], [])
        self.assertEqual(novo2["pavimentos"][0]["pe_direito_mm"], 2700)
        self.assertTrue(any("sem efeito" in a for a in avisos), avisos)


class TestAplicacao(Base):
    def test_peitoril_marca_usuario_e_historico_valido(self):
        novo, _, _ = self.aplicar(f"janela {self.janela['id'][1:]}: peitoril 1,15 m")
        v = next(x for x in novo["pavimentos"][0]["vaos"] if x["id"] == self.janela["id"])
        self.assertEqual(v["peitoril_mm"], 1150)
        self.assertEqual((v["origem"], v["confianca"]), ("usuario", 1.0))
        schema = json.loads(SCHEMA_PADRAO.read_text(encoding="utf-8"))
        self.assertEqual([e.message for e in Draft202012Validator(schema).iter_errors(novo)], [])
        h = novo["historico_ajustes"]
        self.assertEqual(len(h), 1)
        self.assertTrue(h[0]["aplicado"] and h[0]["texto_usuario"].startswith("janela"))
        self.assertIn("inverso", h[0]["comando"])

    def test_original_nao_muda(self):
        antes = copy.deepcopy(self.base)
        self.aplicar("pé-direito 2,70 m")
        self.assertEqual(self.base, antes)

    def test_transformar_janela_em_porta_mantem_o_topo(self):
        novo, _, _ = self.aplicar(f"transformar a janela {self.janela['id'][1:]} em porta")
        v = next(x for x in novo["pavimentos"][0]["vaos"] if x["id"] == self.janela["id"])
        self.assertEqual((v["tipo"], v["peitoril_mm"]), ("porta", 0))
        self.assertEqual(v["altura_mm"], self.janela["peitoril_mm"] + self.janela["altura_mm"])

    def test_transformar_em_janela_exige_peitoril_e_altura(self):
        with self.assertRaises(aj.ErroAjuste):
            self.aplicar(f"transformar vão {self.porta['id'][1:]} em janela")
        novo, _, _ = self.aplicar(f"transformar vão {self.porta['id'][1:]} em janela, peitoril 1 m, altura 1,1 m")
        v = next(x for x in novo["pavimentos"][0]["vaos"] if x["id"] == self.porta["id"])
        self.assertEqual((v["tipo"], v["peitoril_mm"], v["altura_mm"]), ("janela", 1000, 1100))

    def test_mover_vao_ao_longo_da_parede(self):
        direcao = "leste" if self.janela["eixo"] == "x" else "norte"
        novo, _, _ = self.aplicar(f"mover janela {self.janela['id'][1:]} 10 cm para {direcao}")
        v = next(x for x in novo["pavimentos"][0]["vaos"] if x["id"] == self.janela["id"])
        chave = self.janela["eixo"]
        self.assertEqual(v["centro"][chave], self.janela["centro"][chave] + 100)

    def test_largura_do_vao_centrada(self):
        novo, _, _ = self.aplicar(f"largura do vão {self.janela['id'][1:]}: 80 cm")
        v = next(x for x in novo["pavimentos"][0]["vaos"] if x["id"] == self.janela["id"])
        self.assertEqual(v["largura_mm"], 800)
        self.assertEqual(v["centro"], self.janela["centro"])

    def test_fechar_vao_cria_parede_que_cobre_o_vao(self):
        novo, _, avisos = self.aplicar(f"fechar vão {self.porta['id'][1:]}")
        pav = novo["pavimentos"][0]
        self.assertNotIn(self.porta["id"], [v["id"] for v in pav["vaos"]])
        nova = pav["paredes"][-1]
        eixo, c, a0, a1, esp = aj._extremos(nova)
        centro = self.porta["centro"]["x" if self.porta["eixo"] == "x" else "y"]
        self.assertAlmostEqual((a0 + a1) / 2, centro, delta=1)
        self.assertAlmostEqual(a1 - a0, self.porta["largura_mm"], delta=1)
        self.assertEqual(eixo, self.porta["eixo"])
        self.assertFalse(any("sobrepõe" in a for a in avisos), avisos)

    def test_adicionar_janela_divide_a_parede(self):
        p = max((p for p in self.paredes if p.get("tipo") != "pilar"), key=lambda p: aj._extremos(p)[3] - aj._extremos(p)[2])
        eixo, c, a0, a1, esp = aj._extremos(p)
        novo, _, avisos = self.aplicar(f"adicionar janela de 1,20 m na parede {p['id']} a 1 m do início, peitoril 1 m, altura 1,1 m")
        pav = novo["pavimentos"][0]
        self.assertNotIn(p["id"], [x["id"] for x in pav["paredes"]])
        pedacos = sorted((aj._extremos(x)[2], aj._extremos(x)[3]) for x in pav["paredes"]
                         if x["id"] not in {q["id"] for q in self.paredes} and aj._extremos(x)[1] == c and aj._eixo_parede(x) == eixo)
        self.assertEqual(pedacos[0], (a0, a0 + 1000))
        self.assertEqual(pedacos[1], (a0 + 2200, a1))
        nova = [v for v in pav["vaos"] if v["id"] not in {q["id"] for q in self.base["pavimentos"][0]["vaos"]}][0]
        self.assertEqual((nova["tipo"], nova["largura_mm"], nova["peitoril_mm"], nova["altura_mm"]), ("janela", 1200, 1000, 1100))
        self.assertFalse(any("sobrepõe" in a or "sobrepõem" in a for a in avisos), avisos)

    def test_script_do_sketchup_compila_apos_ajustes(self):
        novo, _, _ = self.aplicar("pé-direito 2,55 m", f"janela {self.janela['id'][1:]}: peitoril 1,10 m")
        compile(gerar_script(novo), "script.py", "exec")


class TestDesfazer(Base):
    FRASES = [
        lambda s: f"janela {s.janela['id'][1:]}: peitoril 1,15 m",
        lambda s: f"transformar a janela {s.janela['id'][1:]} em porta",
        lambda s: f"largura do vão {s.janela['id'][1:]}: 80 cm",
        lambda s: f"fechar vão {s.porta['id'][1:]}",
        lambda s: "pé-direito 2,70 m",
        lambda s: "todas as portas altura 2,00 m",
    ]

    def test_desfazer_restaura_exatamente(self):
        for f in self.FRASES:
            frase = f(self)
            with self.subTest(frase=frase):
                novo, _, _ = self.aplicar(frase)
                self.assertNotEqual(canonico(novo), canonico(self.base))
                volta, desfeita = aj.desfazer(novo)
                self.assertEqual(desfeita, frase)
                self.assertEqual(canonico(volta), canonico(self.base))
                self.assertEqual(volta.get("historico_ajustes", []), [])

    def test_desfazer_so_a_ultima_frase(self):
        novo, _, _ = self.aplicar("pé-direito 2,70 m", f"janela {self.janela['id'][1:]}: peitoril 1,15 m")
        meio, _ = aj.desfazer(novo)
        self.assertEqual(meio["pavimentos"][0]["pe_direito_mm"], 2700)
        v = next(x for x in meio["pavimentos"][0]["vaos"] if x["id"] == self.janela["id"])
        self.assertEqual(v["peitoril_mm"], self.janela["peitoril_mm"])
        self.assertEqual(len(meio["historico_ajustes"]), 1)
        inicio, _ = aj.desfazer(meio)
        self.assertEqual(canonico(inicio), canonico(self.base))

    def test_desfazer_sem_historico_e_erro(self):
        with self.assertRaises(aj.ErroAjuste):
            aj.desfazer(self.base)

    def test_origem_e_confianca_voltam_ao_original(self):
        novo, _, _ = self.aplicar(f"janela {self.janela['id'][1:]}: peitoril 1,15 m")
        volta, _ = aj.desfazer(novo)
        v = next(x for x in volta["pavimentos"][0]["vaos"] if x["id"] == self.janela["id"])
        self.assertEqual((v["origem"], v.get("evidencia")), (self.janela["origem"], self.janela.get("evidencia")))


class TestCLI(Base):
    def test_cli_ponta_a_ponta(self):
        with tempfile.TemporaryDirectory() as t:
            ent, sai, script = Path(t) / "p.json", Path(t) / "q.json", Path(t) / "s.py"
            ent.write_text(json.dumps(self.base), encoding="utf-8")
            sys_argv = sys.argv
            try:
                sys.argv = ["ajustes.py", str(ent), "pé-direito 2,55 m", "--saida", str(sai), "--script", str(script)]
                self.assertEqual(aj.main(), 0)
                sys.argv = ["ajustes.py", str(ent), "remover vão 99", "--saida", str(sai)]
                self.assertEqual(aj.main(), 1)
            finally:
                sys.argv = sys_argv
            q = json.loads(sai.read_text(encoding="utf-8")) if sai.exists() else None
            self.assertEqual(q["pavimentos"][0]["pe_direito_mm"], 2550)       # a execução com erro não sobrescreveu a saída
            self.assertTrue(script.exists())


if __name__ == "__main__":
    unittest.main()
