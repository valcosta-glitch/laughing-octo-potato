"""Marcenaria na topologia livre: catálogo, validação (cabe, bate, sobrepõe), frases digitadas, desfazer e geometria do renderer."""
import copy
import json
import sys
import unittest
from pathlib import Path

RAIZ = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(RAIZ / "tools"))
sys.path.insert(0, str(RAIZ / "tests"))

import ajustes as aj  # noqa: E402
import blocos  # noqa: E402
from gerar_script_sketchup import gerar_script, montar_moveis  # noqa: E402
from test_ajustes import canonico, projeto_base  # noqa: E402
from validar import checar_projeto  # noqa: E402

# planta sintética (seed 2, 1:50): p4 horizontal y=105 (x 1900..6145), p1 y=4205 (x 205..4400), p5 vertical x=100 (y 205..4100),
# p6 vertical x=2950 (y 2305..4130), pé-direito 2600
FRASE_ARMARIO = "adicionar armário de 1,58 m na parede p4 lado norte a 1,2 m do início"   # p7 sobe do x=2950: começa depois dela


class Base(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.base = projeto_base()

    def aplicar(self, *frases, projeto=None):
        return aj.aplicar_frases(projeto or self.base, list(frases))

    def movel(self, projeto, mid="m1"):
        return next(m for m in projeto["pavimentos"][0]["mobiliario"] if m["id"] == mid)


class TestCatalogo(unittest.TestCase):
    def test_padroes_e_portas(self):
        p = blocos.completar("roupeiro_piso_teto", {"largura_mm": 1580})
        self.assertEqual((p["profundidade_mm"], p["espessura_chapa_mm"], p["portas"], p["divisorias"]), (550, 15, 3, 1))
        self.assertTrue(p["ate_o_teto"])
        g = blocos.completar("gabinete_suspenso", {"largura_mm": 1200, "profundidade_mm": 550})
        self.assertEqual((g["profundidade_mm"], g["altura_mm"], g["portas"], g["divisorias"]), (550, 850, 2, 0))

    def test_informado_vence_o_padrao(self):
        p = blocos.completar("roupeiro_piso_teto", {"largura_mm": 4180, "profundidade_mm": 600, "portas": 6, "ate_o_teto": False, "altura_mm": 2400})
        self.assertEqual((p["profundidade_mm"], p["portas"], p["ate_o_teto"], p["altura_mm"]), (600, 6, False, 2400))

    def test_faltando(self):
        self.assertEqual(blocos.faltando("balcao_2_portas", blocos.completar("balcao_2_portas", {"largura_mm": 800})), ["altura_mm", "profundidade_mm"])
        self.assertEqual(blocos.faltando("roupeiro_piso_teto", blocos.completar("roupeiro_piso_teto", {"largura_mm": 800})), [])


class TestFrases(Base):
    def test_adicionar_armario(self):
        novo, por_frase, avisos = self.aplicar(FRASE_ARMARIO)
        c = por_frase[0][0]
        self.assertEqual((c["acao"], c["alvo"], c["alvo_id"]), ("adicionar", "movel", "m1"))
        m = self.movel(novo)
        self.assertEqual(m["bloco"]["id"], "roupeiro_piso_teto")
        self.assertEqual((m["apoio"]["parede_id"], m["apoio"]["lado"], m["apoio"]["distancia_do_inicio_mm"]), ("p4", "norte", 1200))
        self.assertEqual(m["parametros"]["largura_mm"], 1580)
        self.assertEqual(checar_projeto(novo)[0], [])
        self.assertTrue(any("PADRÃO" in a for a in avisos), avisos)        # profundidade/espessura vieram do padrão: avisa

    def test_informado_nao_vira_aviso_de_padrao(self):
        _, _, avisos = self.aplicar("adicionar roupeiro de 1,58 m na parede p4 lado norte a 1,2 m do início, profundidade 55 cm, "
                                    "espessura 15 mm, frente freijó, piso ao teto")
        self.assertFalse(any("PADRÃO" in a for a in avisos), avisos)

    def test_lado_errado_para_o_eixo(self):
        with self.assertRaisesRegex(aj.ErroAjuste, "norte ou sul"):
            self.aplicar("adicionar armário de 1 m na parede p4 lado leste a 1 m do início")

    def test_faltas_nao_adivinham(self):
        for frase, trecho in (("adicionar armário de 1 m na parede p4 a 1 m do início", "lado"),
                              ("adicionar armário na parede p4 lado norte a 1 m do início", "largura"),
                              ("adicionar armário de 1 m na parede p4 lado norte", "posição"),
                              ("adicionar armário de 1 m lado norte a 1 m do início", "parede"),
                              ("adicionar balcão de 1 m na parede p4 lado norte a 1 m do início", "altura"),
                              ("adicionar armário de 1 m na parede pil1 lado norte a 0 m do início", "pilar")):
            with self.assertRaisesRegex(aj.ErroAjuste, trecho, msg=frase):
                self.aplicar(frase)

    def test_palavra_sobrando_recusa(self):
        with self.assertRaisesRegex(aj.ErroAjuste, "não entendi: 'colorido'"):
            self.aplicar("adicionar armário de 1 m na parede p4 lado norte a 1 m do início colorido")

    def test_frente_desconhecida(self):
        with self.assertRaisesRegex(aj.ErroAjuste, "frente 'rosa' desconhecida"):
            self.aplicar(FRASE_ARMARIO + ", frente rosa")

    def test_nao_cabe_na_parede(self):
        with self.assertRaisesRegex(aj.ErroAjuste, "passa do fim"):
            self.aplicar("adicionar armário de 5 m na parede p4 lado norte a 1 m do início")

    def test_bate_em_outra_parede(self):
        with self.assertRaisesRegex(aj.ErroAjuste, "bate na parede 'p6'"):
            self.aplicar("adicionar armário de 1 m na parede p1 lado sul a 2 m do início")

    def test_sobrepoe_outro_movel(self):
        with self.assertRaisesRegex(aj.ErroAjuste, "se sobrepõem"):
            self.aplicar(FRASE_ARMARIO, "adicionar gabinete de 1 m na parede p4 lado norte a 2 m do início, elevação 20 cm")

    def test_lados_opostos_nao_se_sobrepoem(self):
        novo, _, _ = self.aplicar(FRASE_ARMARIO, "adicionar armário de 1,58 m na parede p4 lado sul a 1,2 m do início")
        self.assertEqual(len(novo["pavimentos"][0]["mobiliario"]), 2)

    def test_acima_do_pe_direito(self):
        with self.assertRaisesRegex(aj.ErroAjuste, "pé-direito"):
            self.aplicar("adicionar painel de 2,44 m na parede p4 lado norte a 1,2 m do início, altura 3 m")

    def test_encostado_no_fim_respeita_a_parede_que_fecha_o_canto(self):
        novo, _, _ = self.aplicar("adicionar armário de 1 m na parede p5 lado leste encostado no fim")
        m = self.movel(novo)
        self.assertEqual(m["apoio"]["distancia_do_inicio_mm"], 2895)      # p5 tem 3895 mm: termina na ponta, não passa
        self.assertEqual(checar_projeto(novo)[0], [])

    def test_a_distancia_do_fim(self):
        novo, _, _ = self.aplicar("adicionar armário de 1 m na parede p4 lado norte a 0,5 m do fim")
        self.assertEqual(self.movel(novo)["apoio"]["distancia_do_inicio_mm"], 4245 - 500 - 1000)

    def test_gabinete_e_rack_usam_elevacao_do_bloco(self):
        novo, _, _ = self.aplicar("adicionar gabinete de 1,2 m na parede p4 lado norte a 3 m do início",
                                  "adicionar rack de 2,2 m na parede p1 lado norte a 0,5 m do início")
        self.assertEqual(self.movel(novo, "m1")["apoio"]["elevacao_mm"], 200)
        self.assertEqual(self.movel(novo, "m2")["apoio"]["elevacao_mm"], 240)

    def test_mover_so_ao_longo_da_parede(self):
        base, _, _ = self.aplicar(FRASE_ARMARIO)
        novo, _, _ = self.aplicar("mover móvel m1 20 cm para leste", projeto=base)
        self.assertEqual(self.movel(novo)["apoio"]["distancia_do_inicio_mm"], 1400)
        with self.assertRaisesRegex(aj.ErroAjuste, "só se move"):
            self.aplicar("mover armário m1 20 cm para o norte", projeto=base)

    def test_alterar_altura_e_piso_teto(self):
        base, _, _ = self.aplicar(FRASE_ARMARIO)
        a, _, _ = self.aplicar("móvel m1: altura 2,40 m, frente nogueira", projeto=base)
        p = self.movel(a)["parametros"]
        self.assertEqual((p["altura_mm"], p["ate_o_teto"], p["frente"]), (2400, False, "nogueira"))
        b, _, _ = self.aplicar("móvel m1: piso ao teto", projeto=a)
        p = self.movel(b)["parametros"]
        self.assertTrue(p["ate_o_teto"])
        self.assertNotIn("altura_mm", p)

    def test_movel_inexistente_e_remover(self):
        with self.assertRaisesRegex(aj.ErroAjuste, "não existe"):
            self.aplicar("remover móvel m7")
        base, _, _ = self.aplicar(FRASE_ARMARIO)
        novo, _, _ = self.aplicar("remover armário m1", projeto=base)
        self.assertNotIn("mobiliario", novo["pavimentos"][0])

    def test_desfazer_devolve_o_projeto_exato(self):
        for frases in ([FRASE_ARMARIO], [FRASE_ARMARIO, "mover móvel m1 20 cm para leste"],
                       [FRASE_ARMARIO, "móvel m1: altura 2,40 m, profundidade 60 cm"], [FRASE_ARMARIO, "remover móvel m1"]):
            novo, _, _ = self.aplicar(*frases)
            for _ in frases:
                novo, _ = aj.desfazer(novo)
            self.assertEqual(canonico(novo), canonico(self.base), frases)

    def test_nao_altera_o_projeto_de_entrada(self):
        antes = copy.deepcopy(self.base)
        self.aplicar(FRASE_ARMARIO)
        self.assertEqual(antes, self.base)

    def test_ate_o_teto_acompanha_o_pe_direito(self):
        novo, _, _ = self.aplicar(FRASE_ARMARIO + ", piso ao teto", "pé-direito 2,50 m")
        self.assertEqual(montar_moveis(novo)[0]["parametros"]["altura_mm"], 2500)
        with self.assertRaisesRegex(aj.ErroAjuste, "pé-direito"):
            self.aplicar("adicionar armário de 1 m na parede p4 lado norte a 1,2 m do início, altura 2,5 m", "pé-direito 2,40 m")


class TestScript(Base):
    def test_script_compila_e_traz_os_moveis(self):
        novo, _, _ = self.aplicar(FRASE_ARMARIO + ", frente nogueira, portas 3",
                                  "adicionar gabinete de 1,2 m na parede p4 lado norte a 3 m do início, profundidade 55 cm")
        script = gerar_script(novo)
        compile(script, "script.py", "exec")
        self.assertIn("moveis = [", script)
        self.assertIn('"lado": "norte"', script)
        self.assertIn('"frente_rgb": [92, 64, 48]', script)
        self.assertLess(script.index("sketchup_esquadrias.py"), script.index("sketchup_moveis.py"))
        self.assertLess(script.index("sketchup_moveis.py"), script.index("sketchup_vistas.py"))

    def test_sem_moveis_o_script_nao_inclui_o_modulo(self):
        script = gerar_script(self.base)
        self.assertNotIn("moveis = [", script)
        self.assertNotIn("def caixa_portas", script)


# ---- geometria do renderer, executando o módulo com um conector de mentira --------------------------------------------
class _Mat:
    def __init__(self, nome):
        self.nome = nome

    def get_name(self):
        return self.nome


class _Ents:
    def __init__(self):
        self.g = []

    def add_group(self, g):
        self.g.append(g)

    def get_groups(self):
        return self.g


class _Grp:
    def __init__(self):
        self.e = _Ents()
        self.nome = ""
        self.caixa = None

    def get_entities(self):
        return self.e

    def set_name(self, n):
        self.nome = n

    def get_name(self):
        return self.nome


def rodar_moveis(projeto_dados):
    """Executa renderer/sketchup_moveis.py (modo livre) com MM=1 e devolve {id_do_móvel: (x0, x1, y0, y1, z0, z1)} das peças reunidas."""
    from gerar_script_sketchup import montar_dict_livre
    proj = montar_dict_livre(projeto_dados)
    moveis = montar_moveis(projeto_dados)
    raiz = _Grp()
    raiz.set_name(proj["nome"])

    class _Model:
        def get_entities(self):
            e = _Ents()
            e.g = [raiz]
            return e

    def PO(w, s, off, z):
        return (w["A"][0] + w["u"][0] * s + w["nrm"][0] * off, w["A"][1] + w["u"][1] * s + w["nrm"][1] * off, z)

    def extrude_faces(w, loops, o0, o1):
        pts = [PO(w, s, off, z) for (s, z) in loops[0] for off in (o0, o1)]
        return [(min(p[0] for p in pts), max(p[0] for p in pts), min(p[1] for p in pts), max(p[1] for p in pts),
                 min(p[2] for p in pts), max(p[2] for p in pts))]

    def leaf_group(pai, nome, faces, mat):
        g = _Grp()
        g.set_name(nome)
        g.caixa = faces[0]
        pai.get_entities().add_group(g)
        return g

    ctx = {"MM": 1.0, "nome": proj["nome"], "get_or_create_material": lambda n, r, g, b: _Mat(n), "extrude_faces": extrude_faces,
           "leaf_group": leaf_group, "relatar": lambda *a: None, "paredes": []}
    env = {"session_state": {"ctx": ctx}, "projeto": proj, "moveis": moveis, "model": _Model(), "Group": _Grp}
    exec((RAIZ / "renderer" / "sketchup_moveis.py").read_text(encoding="utf-8"), env)
    saida = {}
    for g in raiz.get_entities().get_groups():
        cs = [f.caixa for f in g.get_entities().get_groups()]
        saida[g.get_name()[len("Movel_"):]] = (min(c[0] for c in cs), max(c[1] for c in cs), min(c[2] for c in cs), max(c[3] for c in cs),
                                              min(c[4] for c in cs), max(c[5] for c in cs))
    return saida, env["corte"]


class TestRenderer(Base):
    def test_quatro_lados_ocupam_o_retangulo_previsto(self):
        dados = copy.deepcopy(self.base)
        pav = dados["pavimentos"][0]
        casos = [("p4", "norte", 1200), ("p4", "sul", 1200), ("p5", "leste", 600), ("p5", "oeste", 600)]
        pav["mobiliario"] = []
        for i, (pid, lado, dist) in enumerate(casos):
            pav["mobiliario"].append({"id": f"m{i + 1}", "bloco": {"catalogo": "marcenaria", "id": "roupeiro_piso_teto", "versao": 1},
                                      "apoio": {"parede_id": pid, "lado": lado, "distancia_do_inicio_mm": dist, "afastamento_mm": 0},
                                      "parametros": {"largura_mm": 1580}})
        achado, corte = rodar_moveis(dados)
        paredes = {p["id"]: p for p in pav["paredes"]}
        for i, (pid, lado, dist) in enumerate(casos):
            m = pav["mobiliario"][i]
            esperado = blocos.retangulo_movel(paredes[pid], m, 1580, 550)
            x0, x1, y0, y1, z0, z1 = achado[m["id"]]
            for a, b in zip((x0, x1, y0, y1), esperado):
                self.assertAlmostEqual(a, b, places=6, msg=(pid, lado))
            self.assertAlmostEqual(z0, 0)
            self.assertAlmostEqual(z1, 2600)                     # piso-teto: acompanha o pé-direito
        # 3 portas (1580/600), 1 divisória, 2 laterais, base, topo, fundo, zócalo
        pecas = [c["peca"] for c in corte if c["movel"] == "m1"]
        self.assertEqual(sum(p.startswith("Porta_") for p in pecas), 3)
        self.assertEqual(sum(p.startswith("Divisoria_") for p in pecas), 1)

    def test_suspensos_e_painel(self):
        dados = copy.deepcopy(self.base)
        pav = dados["pavimentos"][0]
        pav["mobiliario"] = [
            {"id": "m1", "bloco": {"catalogo": "marcenaria", "id": "gabinete_suspenso", "versao": 1},
             "apoio": {"parede_id": "p4", "lado": "norte", "distancia_do_inicio_mm": 2000, "afastamento_mm": 0, "elevacao_mm": 200},
             "parametros": {"largura_mm": 1200}},
            {"id": "m2", "bloco": {"catalogo": "marcenaria", "id": "espelho_parede", "versao": 1},
             "apoio": {"parede_id": "p4", "lado": "norte", "distancia_do_inicio_mm": 2000, "afastamento_mm": 0, "elevacao_mm": 1050},
             "parametros": {"largura_mm": 1200}}]
        achado, _ = rodar_moveis(dados)
        self.assertAlmostEqual(achado["m1"][4], 200)
        self.assertAlmostEqual(achado["m1"][5], 1050)            # topo do gabinete a 1,05 m do piso
        self.assertAlmostEqual(achado["m2"][4], 1050)
        self.assertAlmostEqual(achado["m2"][5], 2050)
        self.assertAlmostEqual(achado["m2"][3] - achado["m2"][2], 6)       # espelho de 6 mm


if __name__ == "__main__":
    unittest.main()
