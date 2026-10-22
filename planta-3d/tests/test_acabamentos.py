"""Catálogo de acabamentos: itens, frases (parede, lado, piso), validação, script e os módulos do renderer com conector de mentira."""
import copy
import json
import sys
import unittest
from pathlib import Path

RAIZ = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(RAIZ / "tools"))
sys.path.insert(0, str(RAIZ / "tests"))

import acabamentos as cat  # noqa: E402
import ajustes as aj  # noqa: E402
from gerar_script_sketchup import gerar_script, montar_acabamentos, montar_moveis  # noqa: E402
from test_ajustes import canonico, projeto_base  # noqa: E402
from validar import checar_projeto  # noqa: E402

FRASE_ARMARIO = "adicionar armário de 1,58 m na parede p4 lado norte a 1,2 m do início"
BANNER = lambda n: "= " + n + " ="                  # o nome do módulo também aparece em comentários de outros módulos


class Base(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.base = projeto_base()

    def aplicar(self, *frases, projeto=None):
        return aj.aplicar_frases(projeto or self.base, list(frases))

    def acab(self, projeto):
        return projeto["pavimentos"][0].get("acabamentos", [])


class TestCatalogo(unittest.TestCase):
    def test_itens_completos(self):
        for aid, a in cat.ACABAMENTOS.items():
            self.assertIn(a["tipo"], ("liso", "madeira", "granito", "trama", "porcelanato"), aid)
            self.assertEqual(len(a["rgb"]), 3, aid)
            self.assertTrue(all(0 <= v <= 255 for v in a["rgb"]), aid)
            self.assertTrue(a["uso"], aid)
            if a["tipo"] != "liso":
                self.assertTrue(all(0 <= v <= 255 for v in a["c1"] + a["c2"]), aid)
                self.assertGreater(a["escala_mm"], 0, aid)

    def test_nomes_e_apelidos_nao_colidem(self):
        vistos = {}
        for aid, a in cat.ACABAMENTOS.items():
            for n in [aid, a["nome"]] + a["apelidos"]:
                k = cat._norm(n)
                self.assertIn(vistos.setdefault(k, aid), (aid,), f"'{n}' de {aid} já é de {vistos.get(k)}")

    def test_achar_pega_o_nome_mais_longo(self):
        self.assertEqual(cat.achar("de verde salvia"), "verde_salvia")
        self.assertEqual(cat.achar("de verde"), "verde")
        self.assertEqual(cat.achar("cinza grafite"), "cinza_grafite")
        self.assertEqual(cat.achar("porcelanato cinza"), "porcelanato_cinza")
        self.assertIsNone(cat.achar("rosa choque"))

    def test_normalizar_id(self):
        self.assertEqual(cat.normalizar_id("Freijó"), "freijo")
        self.assertEqual(cat.normalizar_id("nogueira véneto"), "nogueira")
        self.assertEqual(cat.normalizar_id("Titânio Trama"), "titanio")
        self.assertIsNone(cat.normalizar_id("rosa"))

    def test_para_renderer_so_leva_o_pedido(self):
        r = cat.para_renderer(["marula", "branco"])
        self.assertEqual(sorted(r), ["branco", "marula"])
        self.assertEqual(r["marula"]["tipo"], "madeira")
        self.assertNotIn("c1", r["branco"])


class TestFrases(Base):
    def test_pintar_parede(self):
        novo, por_frase, _ = self.aplicar("pintar parede p4 de verde sálvia")
        a = self.acab(novo)[0]
        self.assertEqual(a["alvo"], {"tipo": "parede", "id": "p4"})
        self.assertEqual(a["textura"], {"catalogo": "acabamentos", "id": "verde_salvia", "versao": 1})
        self.assertEqual(por_frase[0][0]["alvo_id"], "a1")
        self.assertEqual(checar_projeto(novo)[0], [])

    def test_lado_e_outros_verbos(self):
        novo, _, _ = self.aplicar("pintar parede p4 lado norte de terracota", "revestir parede p5 lado leste com marula",
                                  "acabamento da parede p1: nogueira véneto")
        alvos = {a["alvo"]["id"]: a for a in self.acab(novo)}
        self.assertEqual(alvos["p4"]["alvo"]["lado"], "norte")
        self.assertEqual(alvos["p5"]["textura"]["id"], "marula")
        self.assertEqual(alvos["p1"]["textura"]["id"], "nogueira")
        self.assertEqual({a["id"] for a in self.acab(novo)}, {"a1", "a2", "a3"})

    def test_piso(self):
        novo, _, _ = self.aplicar("piso porcelanato cinza")
        self.assertEqual(self.acab(novo)[0]["alvo"], {"tipo": "piso", "id": "pav1"})
        novo2, _, _ = self.aplicar("acabamento do piso: cimento queimado", projeto=novo)
        self.assertEqual(len(self.acab(novo2)), 1)                      # troca, não acumula
        self.assertEqual(self.acab(novo2)[0]["textura"]["id"], "cimento_queimado")

    def test_trocar_mantem_o_id_e_desfaz(self):
        a, _, _ = self.aplicar("pintar parede p4 de verde")
        b, por_frase, _ = self.aplicar("pintar parede p4 de terracota", projeto=a)
        self.assertEqual([c["acao"] for c in por_frase[0]], ["remover", "adicionar"])
        self.assertEqual(self.acab(b)[0]["id"], "a1")
        c, _ = aj.desfazer(b)
        self.assertEqual(canonico(c), canonico(a))

    def test_remover(self):
        a, _, _ = self.aplicar("pintar parede p4 de verde", "piso porcelanato cinza")
        b, _, _ = self.aplicar("remover acabamento a1", projeto=a)
        self.assertEqual([x["id"] for x in self.acab(b)], ["a2"])
        c, _, _ = self.aplicar("remover acabamento do piso", projeto=b)
        self.assertNotIn("acabamentos", c["pavimentos"][0])
        d, _, _ = self.aplicar("remover acabamento da parede p4", projeto=a)
        self.assertEqual([x["id"] for x in self.acab(d)], ["a2"])

    def test_desfazer_devolve_o_projeto_exato(self):
        novo, _, _ = self.aplicar("pintar parede p4 lado norte de verde sálvia", "piso porcelanato areia")
        novo, _ = aj.desfazer(novo)
        novo, _ = aj.desfazer(novo)
        self.assertEqual(canonico(novo), canonico(self.base))

    def test_sem_efeito_vira_aviso(self):
        a, _, _ = self.aplicar("pintar parede p4 de verde")
        _, _, avisos = self.aplicar("pintar parede p4 de verde", "piso porcelanato cinza", projeto=a)
        self.assertTrue(any("sem efeito" in x for x in avisos), avisos)

    def test_recusas_sem_adivinhar(self):
        for frase, trecho in (("pintar parede p4 de rosa choque", "não reconhecido"),
                              ("pintar parede p4 lado leste de verde", "norte ou sul"),
                              ("pintar parede p4 de porcelanato cinza", "não é acabamento de parede"),
                              ("piso verde", "não é acabamento de piso"),
                              ("pintar parede p4 de verde brilhante", "não entendi: 'brilhante'"),
                              ("pintar parede p99 de verde", "não existe"),
                              ("pintar parede pil1 de verde", "pilar"),
                              ("pintar de verde", "alvo"),
                              ("remover acabamento a7", "não existe"),
                              ("piso lado norte porcelanato cinza", "piso não tem lado")):
            with self.assertRaisesRegex(aj.ErroAjuste, trecho, msg=frase):
                self.aplicar(frase)

    def test_frente_do_movel_com_nome_do_catalogo(self):
        novo, _, _ = self.aplicar(FRASE_ARMARIO + ", frente titânio trama, portas 3")
        self.assertEqual(novo["pavimentos"][0]["mobiliario"][0]["parametros"]["frente"], "titanio")
        novo, _, _ = self.aplicar(FRASE_ARMARIO + ", frente granito branco itaúnas")
        self.assertEqual(novo["pavimentos"][0]["mobiliario"][0]["parametros"]["frente"], "granito_itaunas")
        novo, _, _ = self.aplicar("móvel m1: frente carvalho", projeto=novo)
        self.assertEqual(novo["pavimentos"][0]["mobiliario"][0]["parametros"]["frente"], "carvalho")

    def test_nao_confunde_com_outras_frases(self):
        a, _, _ = self.aplicar("pintar parede p4 de verde")
        b, _, _ = self.aplicar("remover parede p5", "pé-direito 2,5 m", projeto=a)        # frases de parede continuam valendo
        self.assertEqual(len(self.acab(b)), 1)


class TestValidacao(Base):
    def projeto_com(self, *acabs):
        p = copy.deepcopy(self.base)
        p["pavimentos"][0]["acabamentos"] = list(acabs)
        return p

    def ac(self, i, tipo, alvo_id, tex, **alvo):
        return {"id": i, "alvo": {"tipo": tipo, "id": alvo_id, **alvo}, "textura": {"catalogo": "acabamentos", "id": tex, "versao": 1}}

    def test_ok(self):
        p = self.projeto_com(self.ac("a1", "parede", "p4", "verde"), self.ac("a2", "piso", "pav1", "porcelanato_cinza"))
        self.assertEqual(checar_projeto(p)[0], [])

    def test_erros(self):
        for acs, trecho in (([self.ac("a1", "parede", "p4", "inexistente")], "não existe no catálogo"),
                            ([self.ac("a1", "parede", "p99", "verde")], "parede 'p99' não existe"),
                            ([self.ac("a1", "parede", "pil1", "verde")], "pilar"),
                            ([self.ac("a1", "parede", "p4", "verde"), self.ac("a2", "parede", "p4", "areia")], "mesmo alvo"),
                            ([self.ac("a1", "parede", "p4", "verde", lado="leste")], "o lado é"),
                            ([self.ac("a1", "ambiente", "x", "verde")], "ainda não é suportado")):
            erros, _ = checar_projeto(self.projeto_com(*acs))
            self.assertTrue(any(trecho in e for e in erros), (trecho, erros))

    def test_lados_diferentes_da_mesma_parede_convivem(self):
        p = self.projeto_com(self.ac("a1", "parede", "p4", "verde", lado="norte"), self.ac("a2", "parede", "p4", "areia", lado="sul"))
        self.assertEqual(checar_projeto(p)[0], [])


class TestScript(Base):
    def test_resolve_normais_e_grupos(self):
        novo, _, _ = self.aplicar("pintar parede p4 lado norte de verde", "pintar parede p5 de areia", "piso porcelanato cinza")
        cat_, ap = montar_acabamentos(novo, [])
        self.assertEqual(sorted(cat_), ["areia", "porcelanato_cinza", "verde"])
        self.assertEqual(ap, [{"grupo": "Parede_p4", "acab": "verde", "normal": [0, 1, 0]},
                              {"grupo": "Parede_p5", "acab": "areia", "normal": None},
                              {"grupo": "Piso", "acab": "porcelanato_cinza", "normal": [0, 0, 1]}])

    def test_script_inclui_modulos_na_ordem(self):
        novo, _, _ = self.aplicar(FRASE_ARMARIO + ", frente nogueira", "pintar parede p4 de verde")
        script = gerar_script(novo)
        compile(script, "script.py", "exec")
        ordem = [script.index(BANNER(n)) for n in ("sketchup_livre_ctx.py", "sketchup_texturas.py", "sketchup_comum.py", "sketchup_livre.py",
                                                    "sketchup_esquadrias.py", "sketchup_moveis.py", "sketchup_acabamentos.py", "sketchup_vistas.py")]
        self.assertEqual(ordem, sorted(ordem))
        self.assertIn('"nogueira": {"tipo": "madeira"', script)
        self.assertIn('"grupo": "Parede_p4"', script)

    def test_sem_acabamento_nao_ha_textura(self):
        script = gerar_script(self.base)
        self.assertNotIn(BANNER("sketchup_texturas.py"), script)
        self.assertNotIn(BANNER("sketchup_acabamentos.py"), script)

    def test_so_frente_traz_textura_mas_nao_o_aplicador(self):
        novo, _, _ = self.aplicar(FRASE_ARMARIO + ", frente marula")
        script = gerar_script(novo)
        self.assertIn(BANNER("sketchup_texturas.py"), script)
        self.assertNotIn(BANNER("sketchup_acabamentos.py"), script)
        self.assertNotIn('"branco": {', script.split("acabamentos_cat")[1].split("# ====")[0])     # só o que foi usado

    def test_contorno_continua_gerando(self):
        dados = json.loads((RAIZ / "exemplos" / "cozinha-simples.json").read_text(encoding="utf-8"))
        script = gerar_script(dados)
        compile(script, "script.py", "exec")
        self.assertNotIn(BANNER("sketchup_texturas.py"), script)


# ---- módulos do renderer com conector de mentira ----------------------------------------------------------------------
class _Mat:
    def __init__(self):
        self.nome = None
        self.tex = None

    def set_name(self, n):
        self.nome = n

    def get_name(self):
        return self.nome

    def set_texture(self, t):
        self.tex = t


class _Tex:
    def __init__(self, ir):
        self.ir = ir
        self.dim = None

    @staticmethod
    def from_image_rep(ir):
        return _Tex(ir)

    def set_dimensions(self, a, b):
        self.dim = (a, b)


class _IR:
    def set_data(self, dados, w, h, bpp, pad):
        self.dados, self.w, self.h, self.bpp, self.pad = dados, w, h, bpp, pad


class _Model:
    def __init__(self):
        self.mats = []
        self.grupos = []

    def get_materials(self):
        return self.mats

    def add_materials(self, ms):
        self.mats += ms

    def get_entities(self):
        return self


def rodar_texturas(cat_, falhar=False):
    modelo = _Model()
    solido = []

    def goc(nome, r, g, b, a=255):
        m = _Mat()
        m.set_name(nome)
        solido.append((nome, (r, g, b)))
        modelo.mats.append(m)
        return m

    class Tex(_Tex):
        @staticmethod
        def from_image_rep(ir):
            if falhar:
                raise Exception("sem textura")
            return _Tex(ir)

    env = {"session_state": {"ctx": {"MM": 1.0 / 25.4}}, "model": modelo, "Material": _Mat, "ImageRep": _IR, "Texture": Tex,
           "get_or_create_material": goc, "acabamentos_cat": cat_, "math": __import__("math")}
    exec((RAIZ / "renderer" / "sketchup_texturas.py").read_text(encoding="utf-8"), env)
    return env, modelo, solido


class TestRendererTexturas(unittest.TestCase):
    def test_textura_procedural(self):
        env, modelo, _ = rodar_texturas(cat.para_renderer(["marula", "titanio", "granito_itaunas", "porcelanato_cinza"]))
        for aid, esc in (("marula", 300), ("titanio", 64), ("granito_itaunas", 200), ("porcelanato_cinza", 600)):
            m = env["session_state"]["ctx"]["material_acab"](aid)
            self.assertEqual(m.nome, "Acab_" + aid)
            ir = m.tex.ir
            self.assertEqual((ir.w, ir.h, ir.bpp, ir.pad, len(ir.dados)), (64, 64, 24, 0, 64 * 64 * 3))
            self.assertAlmostEqual(m.tex.dim[0], 64 / (esc / 25.4), places=6)           # pixels por polegada
            self.assertGreater(len(set(ir.dados)), 3, aid)                              # tem variação, não é cor chapada
        self.assertEqual(len(modelo.mats), 4)

    def test_liso_e_cache(self):
        env, modelo, solido = rodar_texturas(cat.para_renderer(["verde"]))
        f = env["session_state"]["ctx"]["material_acab"]
        self.assertIs(f("verde"), f("verde"))
        self.assertEqual(solido, [("Acab_verde", (96, 140, 120))])
        self.assertEqual(len(modelo.mats), 1)

    def test_cai_na_cor_se_a_textura_falha(self):
        env, _, solido = rodar_texturas(cat.para_renderer(["marula"]), falhar=True)
        m = env["session_state"]["ctx"]["material_acab"]("marula")
        self.assertEqual(m.nome, "Acab_marula_cor")
        self.assertEqual(solido[0][1], (205, 170, 125))

    def test_pixels_deterministicos_e_no_intervalo(self):
        a = rodar_texturas(cat.para_renderer(["nogueira"]))[0]["session_state"]["ctx"]["material_acab"]("nogueira").tex.ir.dados
        b = rodar_texturas(cat.para_renderer(["nogueira"]))[0]["session_state"]["ctx"]["material_acab"]("nogueira").tex.ir.dados
        self.assertEqual(a, b)
        self.assertTrue(all(0 <= v <= 255 for v in a))


class _Normal:
    def __init__(self, x, y, z):
        self.x, self.y, self.z = x, y, z


class _Face:
    def __init__(self, n):
        self.n, self.frente, self.verso = _Normal(*n), None, None

    def get_normal(self):
        return self.n

    def set_front_material(self, m):
        self.frente = m

    def set_back_material(self, m):
        self.verso = m


class _G:
    def __init__(self, nome, faces=()):
        self.nome, self.faces = nome, list(faces)

    def get_name(self):
        return self.nome

    def get_entities(self):
        return self

    def get_faces(self):
        return self.faces

    def get_groups(self):
        return [self]


class TestRendererAcabamentos(unittest.TestCase):
    def test_normal_seleciona_faces(self):
        parede = _G("Parede_p4", [_Face(n) for n in ((0, 1, 0), (0, -1, 0), (1, 0, 0), (-1, 0, 0), (0, 0, 1), (0, 0, -1))])
        piso = _G("Piso", [_Face((0, 0, 1)), _Face((0, 0, -1)), _Face((1, 0, 0))])
        outra = _G("Parede_p5", [_Face((0, 1, 0))])
        raiz = _G("proj")
        raiz.get_groups = lambda: [raiz]
        raiz.get_entities = lambda: type("E", (), {"get_groups": lambda s: [parede, piso, outra]})()
        modelo = type("M", (), {"get_entities": lambda s: type("E", (), {"get_groups": lambda s2: [raiz]})()})()

        mats = {}

        def mat(aid):
            mats.setdefault(aid, object())
            return mats[aid]

        env = {"session_state": {"ctx": {"material_acab": mat, "nome": "proj"}}, "model": modelo,
               "acabamentos": [{"grupo": "Parede_p4", "acab": "verde", "normal": [0, 1, 0]},
                               {"grupo": "Piso", "acab": "areia", "normal": [0, 0, 1]},
                               {"grupo": "Parede_p5", "acab": "terracota", "normal": None}]}
        exec((RAIZ / "renderer" / "sketchup_acabamentos.py").read_text(encoding="utf-8"), env)
        self.assertEqual([f.frente is mats["verde"] for f in parede.faces], [True, False, False, False, False, False])
        self.assertEqual([f.frente is mats["areia"] for f in piso.faces], [True, False, False])
        self.assertTrue(outra.faces[0].frente is mats["terracota"] and outra.faces[0].verso is mats["terracota"])
        self.assertEqual([r["faces"] for r in env["result"]["acabamentos_aplicados"]], [1, 1, 1])


if __name__ == "__main__":
    unittest.main()
