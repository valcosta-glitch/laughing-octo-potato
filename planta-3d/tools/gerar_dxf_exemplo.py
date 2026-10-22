#!/usr/bin/env python3
"""Gera exemplos/cozinha-planta.dxf: a mesma cozinha de exemplos/cozinha-simples.json, em mm."""
import sys
from pathlib import Path

import ezdxf
from ezdxf import units


def gerar(destino):
    doc = ezdxf.new("R2010")
    doc.units = units.MM
    for nome in ("PAREDES", "PORTAS", "JANELAS"):
        doc.layers.add(nome)
    msp = doc.modelspace()

    msp.add_lwpolyline([(0, 0), (4000, 0), (4000, 3000), (0, 3000)], close=True, dxfattribs={"layer": "PAREDES"})
    msp.add_line((500, 0), (1300, 0), dxfattribs={"layer": "PORTAS"})
    msp.add_line((4000, 900), (4000, 2100), dxfattribs={"layer": "JANELAS"})
    doc.saveas(destino)


if __name__ == "__main__":
    destino = Path(sys.argv[1]) if len(sys.argv) > 1 else Path(__file__).resolve().parent.parent / "exemplos" / "cozinha-planta.dxf"
    gerar(destino)
    print(f"OK: {destino}")
