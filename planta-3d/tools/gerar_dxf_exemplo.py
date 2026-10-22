#!/usr/bin/env python3
"""Gera os DXFs de exemplo em exemplos/.

  cozinha-planta.dxf   a cozinha de exemplos/cozinha-simples.json (mm), com os três móveis
  sala-L-planta.dxf    planta em L desenhada no sentido horário e em CENTÍMETROS, com porta, duas janelas
                       e móveis em três paredes (inclusive uma parede de canto reentrante)

Uso: python3 gerar_dxf_exemplo.py [pasta_destino]
"""
import sys
from pathlib import Path

import ezdxf
from ezdxf import units


def _doc(unidade):
    doc = ezdxf.new("R2010")
    doc.units = unidade
    for nome in ("PAREDES", "PORTAS", "JANELAS", "MOVEIS_BALCAO_2_PORTAS", "MOVEIS_AEREO_2_PORTAS", "MOVEIS_GAVETEIRO_3_GAVETAS"):
        doc.layers.add(nome)
    return doc


def _ret(msp, x0, y0, x1, y1, camada):
    msp.add_lwpolyline([(x0, y0), (x1, y0), (x1, y1), (x0, y1)], close=True, dxfattribs={"layer": camada})


def cozinha(destino):
    doc = _doc(units.MM)
    msp = doc.modelspace()
    msp.add_lwpolyline([(0, 0), (4000, 0), (4000, 3000), (0, 3000)], close=True, dxfattribs={"layer": "PAREDES"})
    msp.add_line((500, 0), (1300, 0), dxfattribs={"layer": "PORTAS"})
    msp.add_line((4000, 900), (4000, 2100), dxfattribs={"layer": "JANELAS"})
    # parede norte: face interna em y = 3000 - 75 = 2925
    _ret(msp, 2200, 2325, 3400, 2925, "MOVEIS_BALCAO_2_PORTAS")
    _ret(msp, 1600, 2325, 2200, 2925, "MOVEIS_GAVETEIRO_3_GAVETAS")
    _ret(msp, 2200, 2595, 3400, 2925, "MOVEIS_AEREO_2_PORTAS")
    doc.saveas(destino)


def sala_L(destino):
    """Contorno em L, em cm, desenhado no sentido horário (o conversor reorienta)."""
    doc = _doc(units.CM)
    msp = doc.modelspace()
    contorno = [(0, 0), (600, 0), (600, 300), (350, 300), (350, 500), (0, 500)]   # anti-horário
    contorno = list(reversed(contorno))                                          # horário
    msp.add_lwpolyline(contorno, close=True, dxfattribs={"layer": "PAREDES"})
    msp.add_line((100, 0), (190, 0), dxfattribs={"layer": "PORTAS"})             # porta, parede sul
    msp.add_line((600, 100), (600, 220), dxfattribs={"layer": "JANELAS"})        # janela, parede leste
    msp.add_line((100, 500), (250, 500), dxfattribs={"layer": "JANELAS"})        # janela, parede norte
    # parede oeste (x = 0): face interna em x = 7,5
    _ret(msp, 7.5, 100, 67.5, 220, "MOVEIS_BALCAO_2_PORTAS")
    _ret(msp, 7.5, 220, 67.5, 280, "MOVEIS_GAVETEIRO_3_GAVETAS")
    _ret(msp, 7.5, 100, 40.5, 220, "MOVEIS_AEREO_2_PORTAS")
    # parede norte (y = 500): face interna em y = 492,5
    _ret(msp, 100, 432.5, 220, 492.5, "MOVEIS_BALCAO_2_PORTAS")
    # parede do degrau do L (x = 350, interior a oeste): face interna em x = 342,5
    _ret(msp, 282.5, 330, 342.5, 450, "MOVEIS_BALCAO_2_PORTAS")
    doc.saveas(destino)


if __name__ == "__main__":
    pasta = Path(sys.argv[1]) if len(sys.argv) > 1 else Path(__file__).resolve().parent.parent / "exemplos"
    pasta.mkdir(parents=True, exist_ok=True)
    cozinha(pasta / "cozinha-planta.dxf")
    sala_L(pasta / "sala-L-planta.dxf")
    print(f"OK: {pasta}/cozinha-planta.dxf, {pasta}/sala-L-planta.dxf")
