# SPDX-FileCopyrightText: 2026 Ricardo Lugaresi
# SPDX-License-Identifier: GPL-3.0-or-later

"""Textura → pocos colores por cara (para ver el color y poder separarlo con Color Splitter).

Los modelos de IA (Meshy, Tripo…) traen el color como una imagen pegada encima (textura con UV).
Una impresora sin AMS no puede imprimir una foto: aquí se lee el color medio de cada cara,
se reduce a unos pocos colores y cada color pasa a ser un material.

La parte de cálculo es numpy puro (se prueba sin Blender); `bake` y `apply` tocan Blender.
"""
import numpy as np

ATTR = 'ColorTextura'          # color medio de cada cara (sRGB 0..1), se guarda en el .blend
DEFAULT_COLORS = 6
MERGE_DE = 12.0               # dos colores más parecidos que esto (ΔE) no se distinguen impresos: se juntan
TEX_SIDE = 2048                # la textura se reduce a esto para leerla (sobra para el color medio de una cara)


# --------------------------------------------------------------------------- cálculo (sin Blender)
def sample_faces(uv, img, flip_v=False):
    """uv: (F, 3, 2) coordenadas de las 3 esquinas; img: (H, W, 3) 0..1 → (F, 3) color medio de cada cara.

    Se promedian 4 puntos por cara (centro y tres puntos a medio camino hacia las esquinas)
    para que una cara pequeña no recoja el color de la costura de al lado.
    """
    H, W = img.shape[:2]
    c = uv.mean(1)
    pts = [c] + [(2 * c + uv[:, i]) / 3 for i in range(3)]
    acc = np.zeros((len(uv), 3), np.float64)
    for p in pts:
        u = np.mod(p[:, 0], 1.0)
        v = np.mod(p[:, 1], 1.0)
        if flip_v:
            v = 1.0 - v
        x = np.clip((u * W).astype(np.int64), 0, W - 1)
        y = np.clip((v * H).astype(np.int64), 0, H - 1)
        acc += img[y, x, :3]
    return acc / len(pts)


def _srgb_to_lin(c):
    c = np.asarray(c, np.float64)
    return np.where(c <= 0.04045, c / 12.92, ((c + 0.055) / 1.055) ** 2.4)


def to_lab(rgb):
    """sRGB 0..1 → CIELAB (para agrupar por cómo se ven los colores, no por números)."""
    lin = _srgb_to_lin(rgb)
    M = np.array([[0.4124, 0.3576, 0.1805], [0.2126, 0.7152, 0.0722], [0.0193, 0.1192, 0.9505]])
    xyz = lin @ M.T / np.array([0.95047, 1.0, 1.08883])
    f = np.where(xyz > 0.008856, np.cbrt(xyz), 7.787 * xyz + 16 / 116)
    return np.stack([116 * f[:, 1] - 16, 500 * (f[:, 0] - f[:, 1]), 200 * (f[:, 1] - f[:, 2])], 1)


def quantize(rgb, weights, k, iters=25, seed=0, max_samples=120_000):
    """K-means ponderado por área en CIELAB. Devuelve (etiqueta por cara, paleta sRGB (k, 3))."""
    n = len(rgb)
    k = int(max(1, min(k, n)))
    lab = to_lab(rgb)
    w = np.maximum(np.asarray(weights, np.float64), 1e-12)
    rng = np.random.default_rng(seed)
    idx = rng.choice(n, size=min(n, max_samples), replace=False, p=w / w.sum()) if n > max_samples else np.arange(n)
    X, Wx = lab[idx], (np.ones(len(idx)) if n > max_samples else w[idx])
    # k-means++: el primero el más frecuente, los demás lejos de los que ya hay
    cent = [X[rng.choice(len(X), p=Wx / Wx.sum())]]
    for _ in range(1, k):
        d = np.min(((X[:, None, :] - np.array(cent)[None]) ** 2).sum(-1), 1) * Wx
        if d.sum() <= 0:
            break
        cent.append(X[rng.choice(len(X), p=d / d.sum())])
    C = np.array(cent)
    for _ in range(iters):
        lab_ = np.argmin(((X[:, None, :] - C[None]) ** 2).sum(-1), 1)
        newC = np.array([np.average(X[lab_ == j], 0, Wx[lab_ == j]) if (lab_ == j).any() else C[j] for j in range(len(C))])
        if np.allclose(newC, C, atol=1e-3):
            C = newC
            break
        C = newC
    labels = np.empty(n, np.int64)
    for s in range(0, n, 200_000):                 # a trozos para no llenar la memoria
        labels[s:s + 200_000] = np.argmin(((lab[s:s + 200_000, None, :] - C[None]) ** 2).sum(-1), 1)
    used = np.unique(labels)
    remap = -np.ones(len(C), np.int64); remap[used] = np.arange(len(used))
    labels = remap[labels]
    pal = np.array([np.average(rgb[labels == j], 0, w[labels == j]) for j in range(len(used))])
    # de más claro a más oscuro: así «Color 1» suele ser el fondo claro y el orden no salta entre pruebas
    order = np.argsort(-to_lab(pal)[:, 0])
    inv = np.empty_like(order); inv[order] = np.arange(len(order))
    return inv[labels], pal[order]


def face_neighbors(F):
    """Pares de caras que comparten arista (índices de vértice ya soldados)."""
    F = np.asarray(F, np.int64)
    e = np.concatenate([F[:, [0, 1]], F[:, [1, 2]], F[:, [2, 0]]])
    e.sort(1)
    fid = np.tile(np.arange(len(F)), 3)
    key = e[:, 0] * (int(F.max()) + 1) + e[:, 1]
    o = np.argsort(key, kind='stable')
    key, fid = key[o], fid[o]
    same = key[1:] == key[:-1]
    return np.stack([fid[:-1][same], fid[1:][same]], 1)


def smooth(labels, pairs, k, passes=2):
    """Quita motas: una cara cuyo color no comparte con ningún vecino toma el color mayoritario de sus vecinos."""
    lab = labels.copy()
    n = len(lab)
    if not len(pairs):
        return lab
    a, b = pairs[:, 0], pairs[:, 1]
    for _ in range(passes):
        votes = np.zeros((n, k), np.int32)
        np.add.at(votes, (a, lab[b]), 1)
        np.add.at(votes, (b, lab[a]), 1)
        own = votes[np.arange(n), lab]
        lonely = (own == 0) & (votes.sum(1) > 0)
        if not lonely.any():
            break
        lab[lonely] = votes[lonely].argmax(1)
    return lab


def merge_close(labels, pal, area, limit=MERGE_DE):
    """Junta colores que impresos serían el mismo filamento (ΔE < limit), quedándose con la media por área."""
    labels = labels.copy(); pal = [np.asarray(c, np.float64) for c in pal]
    w = [float(area[labels == i].sum()) for i in range(len(pal))]
    alive = list(range(len(pal)))
    while len(alive) > 1:
        L = to_lab(np.array([pal[i] for i in alive]))
        d = np.linalg.norm(L[:, None] - L[None], axis=-1) + np.eye(len(alive)) * 1e9
        a, b = np.unravel_index(np.argmin(d), d.shape)
        if d[a, b] >= limit:
            break
        ia, ib = alive[a], alive[b]
        if w[ib] > w[ia]:
            ia, ib = ib, ia
        tot = w[ia] + w[ib]
        pal[ia] = (pal[ia] * w[ia] + pal[ib] * w[ib]) / max(tot, 1e-12)
        w[ia] = tot
        labels[labels == ib] = ia
        alive.remove(ib)
    remap = -np.ones(len(pal), np.int64); remap[alive] = np.arange(len(alive))
    out = np.array([pal[i] for i in alive])
    order = np.argsort(-to_lab(out)[:, 0])
    inv = np.empty_like(order); inv[order] = np.arange(len(order))
    return inv[remap[labels]], out[order]


def drop_blends(labels, pal, area, rgb, max_pct=2.0, limit=0.08):
    """Quita los colores «de transición»: poca superficie y a medio camino entre otros dos
    (las caras del borde entre rojo y blanco salen rosas). Sus caras van al más cercano de esos dos.
    Se mide en sRGB, que es donde se mezclan las muestras de una cara a caballo entre dos zonas."""
    labels = labels.copy()
    tot = float(area.sum()) or 1.0
    L = np.asarray(pal, np.float64)
    pct = np.array([area[labels == i].sum() / tot * 100 for i in range(len(pal))])
    keep = np.ones(len(pal), bool)
    for c in np.argsort(pct):
        if pct[c] >= max_pct:
            break
        others = [i for i in range(len(pal)) if i != c and keep[i]]
        best = None
        for ai, a in enumerate(others):
            for b in others[ai + 1:]:
                ab = L[b] - L[a]
                t = float(np.clip(np.dot(L[c] - L[a], ab) / max(np.dot(ab, ab), 1e-9), 0, 1))
                if not 0.1 < t < 0.9:
                    continue
                d = float(np.linalg.norm(L[a] + t * ab - L[c]))
                if d < limit and (best is None or d < best[0]):
                    best = (d, a, b)
        if best is None:
            continue
        _d, a, b = best
        m = labels == c
        fl = rgb[m]
        labels[m] = np.where(np.linalg.norm(fl - L[a], axis=1) <= np.linalg.norm(fl - L[b], axis=1), a, b)
        keep[c] = False
    remap = -np.ones(len(pal), np.int64); remap[keep] = np.arange(keep.sum())
    return remap[labels], pal[keep]


def reduce(rgb, area, F, k):
    """Color medio por cara → (etiqueta por cara, paleta sRGB) con como mucho k colores distinguibles.

    Si al juntar los casi iguales sobran huecos, se prueba a repartir en más grupos para aprovecharlos.
    """
    k = max(1, int(k))
    pairs = face_neighbors(F)
    best = None
    for kk in range(k, k + 5):
        labels, pal = quantize(rgb, area, kk)
        labels, pal = merge_close(labels, pal, area)
        labels, pal = drop_blends(labels, pal, area, rgb)
        if len(pal) > k:
            break
        if best is None or len(pal) > len(best[1]):
            best = (labels, pal)
        if len(pal) == k or kk >= len(rgb):
            break
    labels, pal = best
    labels = smooth(labels, pairs, len(pal))
    used = np.unique(labels)
    if len(used) < len(pal):
        remap = -np.ones(len(pal), np.int64); remap[used] = np.arange(len(used))
        labels, pal = remap[labels], pal[used]
    return labels, pal


def hex_color(c):
    return '#' + ''.join(f'{int(round(float(x) * 255)):02X}' for x in np.clip(c[:3], 0, 1))


# --------------------------------------------------------------------------- Blender
def _texture_image(ob):
    """La imagen conectada al color base de algún material del objeto (o None)."""
    for slot in ob.material_slots:
        mat = slot.material
        nt = getattr(mat, 'node_tree', None) if mat else None
        if nt is None:
            continue
        for node in nt.nodes:
            if node.type == 'BSDF_PRINCIPLED':
                inp = node.inputs.get('Base Color')
                if inp is not None and inp.is_linked:
                    stack = [inp.links[0].from_node]
                    seen = set()
                    while stack:
                        nd = stack.pop()
                        if nd.name in seen:
                            continue
                        seen.add(nd.name)
                        if nd.type == 'TEX_IMAGE' and nd.image is not None:
                            return nd.image
                        for i in nd.inputs:
                            stack += [l.from_node for l in i.links]
        for node in nt.nodes:                      # texturas sueltas sin conectar al BSDF
            if node.type == 'TEX_IMAGE' and node.image is not None:
                return node.image
    return None


def has_texture(ob):
    return ob.type == 'MESH' and ob.data.uv_layers.active is not None and _texture_image(ob) is not None


def _pixels(image, side=TEX_SIDE):
    import bpy
    img = image
    tmp = None
    w, h = image.size
    if not w or not h:
        raise ValueError(f'No se pudo leer la textura {image.name} (¿falta la imagen junto al modelo?).')
    if max(w, h) > side:
        tmp = image.copy()
        s = side / max(w, h)
        tmp.scale(max(1, int(w * s)), max(1, int(h * s)))
        img = tmp
    try:
        w, h = img.size
        px = np.empty(w * h * img.channels, np.float32)
        img.pixels.foreach_get(px)
        px = px.reshape(h, w, img.channels)[:, :, :3]
        # pixels ya viene en el espacio de la imagen: sRGB para PNG/JPG normales, lineal para HDR/EXR
        if image.colorspace_settings.name.lower() in ('linear', 'linear rec.709', 'non-color', 'linear srgb') or image.is_float:
            px = np.where(px <= 0.0031308, px * 12.92, 1.055 * np.power(np.clip(px, 0, None), 1 / 2.4) - 0.055)
        return np.clip(px, 0, 1)
    finally:
        if tmp is not None:
            bpy.data.images.remove(tmp)


def bake(ob):
    """Lee la textura y guarda el color medio de cada cara en el atributo ColorTextura. Devuelve nº de caras."""
    me = ob.data
    image = _texture_image(ob)
    uvl = me.uv_layers.active
    if image is None or uvl is None:
        return 0
    img = _pixels(image)
    nl = len(me.loops)
    uv = np.empty(nl * 2, np.float32); uvl.data.foreach_get('uv', uv); uv = uv.reshape(-1, 2)
    me.calc_loop_triangles()
    nt = len(me.loop_triangles)
    tl = np.empty(nt * 3, np.int64); me.loop_triangles.foreach_get('loops', tl)
    tp = np.empty(nt, np.int64); me.loop_triangles.foreach_get('polygon_index', tp)
    ta = np.empty(nt, np.float64); me.loop_triangles.foreach_get('area', ta)
    tri_rgb = sample_faces(uv[tl.reshape(-1, 3)], img)          # Blender: v = 0 abajo, fila 0 abajo
    npoly = len(me.polygons)
    acc = np.zeros((npoly, 3)); wsum = np.zeros(npoly)
    np.add.at(acc, tp, tri_rgb * np.maximum(ta, 1e-12)[:, None]); np.add.at(wsum, tp, np.maximum(ta, 1e-12))
    rgb = acc / np.maximum(wsum, 1e-12)[:, None]
    if ATTR in me.attributes:
        me.attributes.remove(me.attributes[ATTR])
    at = me.attributes.new(ATTR, 'FLOAT_COLOR', 'FACE')
    at.data.foreach_set('color', np.hstack([rgb, np.ones((npoly, 1))]).astype(np.float32).ravel())
    return npoly


def has_baked(ob):
    return ob.type == 'MESH' and ATTR in ob.data.attributes


def _material(hexc, rgb):
    import bpy
    name = f'Color {hexc}'
    mat = bpy.data.materials.get(name) or bpy.data.materials.new(name)
    lin = tuple(float(x) for x in _srgb_to_lin(rgb[:3])) + (1.0,)
    mat.diffuse_color = lin
    try:
        mat.use_nodes = True
    except Exception:
        pass
    nt = getattr(mat, 'node_tree', None)
    if nt is not None:
        for node in nt.nodes:
            if node.type == 'BSDF_PRINCIPLED':
                node.inputs['Base Color'].default_value = lin
    return mat


def apply(ob, k=DEFAULT_COLORS):
    """Reduce ColorTextura a k colores y deja un material por color. Devuelve la lista de colores (hex, % área)."""
    me = ob.data
    npoly = len(me.polygons)
    col = np.empty(npoly * 4, np.float32); me.attributes[ATTR].data.foreach_get('color', col)
    rgb = col.reshape(-1, 4)[:, :3].astype(np.float64)
    area = np.empty(npoly, np.float64); me.polygons.foreach_get('area', area)
    # vecinos por vértices reales (ya soldados en la malla de Blender), con polígonos triangulados en abanico
    me.calc_loop_triangles()
    nt = len(me.loop_triangles)
    tv = np.empty(nt * 3, np.int64); me.loop_triangles.foreach_get('vertices', tv)
    tp = np.empty(nt, np.int64); me.loop_triangles.foreach_get('polygon_index', tp)
    labels_t, pal = reduce(rgb[tp], area[tp], tv.reshape(-1, 3), k)
    # vuelta a polígonos: el color mayoritario de sus triángulos (casi siempre ya es un triángulo)
    votes = np.zeros((npoly, len(pal)), np.float64)
    np.add.at(votes, (tp, labels_t), 1)
    labels = votes.argmax(1)
    me.materials.clear()
    hexes = [hex_color(c) for c in pal]
    for hx, c in zip(hexes, pal):
        me.materials.append(_material(hx, c))
    me.polygons.foreach_set('material_index', labels.astype(np.int32))
    me.update()
    tot = area.sum() or 1.0
    return [(hx, float(area[labels == i].sum() / tot * 100)) for i, hx in enumerate(hexes)]
