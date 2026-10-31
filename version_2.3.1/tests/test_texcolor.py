# SPDX-FileCopyrightText: 2026 Ricardo Lugaresi
# SPDX-License-Identifier: GPL-3.0-or-later

"""Pruebas de textura → colores por cara (sin Blender):  python -m unittest tests.test_texcolor  (desde version_2.3.0)"""
import sys
import unittest
from pathlib import Path

import numpy as np

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

sys.path.insert(0, str(ROOT / "color_print_splitter"))
import texcolor as T  # noqa: E402


def plane(n=40):
    """Rejilla n×n en el plano con UV = posición (0..1). Devuelve V, F, UV por cara (F, 3, 2)."""
    xs = np.linspace(0, 1, n + 1)
    V = np.array([(x, y, 0.0) for y in xs for x in xs])
    F = []
    for j in range(n):
        for i in range(n):
            a = j * (n + 1) + i
            F += [(a, a + 1, a + n + 2), (a, a + n + 2, a + n + 1)]
    F = np.array(F)
    return V, F, V[F][:, :, :2]


def area(V, F):
    t = V[F]
    return np.linalg.norm(np.cross(t[:, 1] - t[:, 0], t[:, 2] - t[:, 0]), axis=1) / 2


class Textura(unittest.TestCase):
    def setUp(self):
        rng = np.random.default_rng(1)
        img = np.zeros((256, 256, 3))
        img[:, :128] = (0.85, 0.15, 0.15)         # izquierda roja
        img[:, 128:] = (0.15, 0.25, 0.85)         # derecha azul
        img[200:, 200:] = (0.95, 0.85, 0.2)       # esquina amarilla (arriba a la derecha con v = 0 abajo)
        self.img = np.clip(img + rng.normal(0, 0.02, img.shape), 0, 1)   # textura de IA: nunca es un color plano
        self.V, self.F, self.UV = plane()

    def test_lee_el_color_de_cada_cara(self):
        rgb = T.sample_faces(self.UV, self.img)
        c = self.UV.mean(1)
        izq = c[:, 0] < 0.45
        self.assertTrue((rgb[izq, 0] > 0.7).all())
        self.assertTrue((rgb[(c[:, 0] > 0.55) & (c[:, 1] < 0.7), 2] > 0.7).all())

    def test_casi_iguales_se_juntan(self):
        rgb = T.sample_faces(self.UV, self.img)
        labels, pal = T.reduce(rgb, area(self.V, self.F), self.F, 6)
        self.assertEqual(len(pal), 3)              # rojo, azul y amarillo; el ruido no inventa colores
        hexes = {T.hex_color(c) for c in pal}
        self.assertEqual(len(hexes), 3)
        self.assertEqual(len(np.unique(labels)), 3)

    def test_respeta_el_maximo(self):
        rgb = T.sample_faces(self.UV, self.img)
        _l, pal = T.reduce(rgb, area(self.V, self.F), self.F, 2)
        self.assertLessEqual(len(pal), 2)

    def test_quita_motas(self):
        rgb = T.sample_faces(self.UV, self.img)
        rgb[500] = (0.1, 0.9, 0.1)                 # una cara suelta verde en medio del rojo
        labels, pal = T.reduce(rgb, area(self.V, self.F), self.F, 6)
        nb = T.face_neighbors(self.F)
        vec = np.concatenate([nb[nb[:, 0] == 500, 1], nb[nb[:, 1] == 500, 0]])
        self.assertIn(labels[500], set(labels[vec]))

    def test_vecinos(self):
        nb = T.face_neighbors(self.F)
        self.assertEqual(len(nb), 3 * 40 * 40 - 2 * 40)      # aristas interiores de la rejilla

    def test_lab(self):
        L = T.to_lab(np.array([[1.0, 1.0, 1.0], [0.0, 0.0, 0.0]]))
        self.assertAlmostEqual(L[0, 0], 100, delta=0.5)
        self.assertAlmostEqual(L[1, 0], 0, delta=0.5)


if __name__ == '__main__':
    unittest.main()
