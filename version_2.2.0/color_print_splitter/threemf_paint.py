"""Lector propio de 3MF pintados (Bambu Studio, Orca Slicer, PrusaSlicer).

El importador de Blender no siempre trae los colores del pincel: los 3MF guardan la
pintura por triángulo en el atributo `paint_color` (Bambu/Orca) o
`slic3rpe:mmu_segmentation` (PrusaSlicer) como un árbol codificado en hexadecimal, y los
triángulos sin pintar usan el filamento del objeto. Aquí se lee todo eso y se crea un
objeto con un material por filamento usado (con su color real), listo para separar.

Cuando un triángulo está subdividido por la pintura (frontera fina), se le asigna el
color que más ocupa dentro de él; la frontera se alisa después al separar.
"""
import json
import re
import zipfile

import bpy
import numpy as np

_VERT = re.compile(rb'<(?:\w+:)?vertex\s+x="([^"]+)"\s+y="([^"]+)"\s+z="([^"]+)"')
_TRI = re.compile(rb'<(?:\w+:)?triangle\s+([^>]*?)/?>')
_ATTR = re.compile(rb'(\w+(?::\w+)?)="([^"]*)"')
_OBJ = re.compile(rb'<(?:\w+:)?object\s+([^>]*)>(.*?)</(?:\w+:)?object>', re.S)
_COMP = re.compile(rb'<(?:\w+:)?component\s+([^>]*?)/?>')
_ITEM = re.compile(rb'<(?:\w+:)?item\s+([^>]*?)/?>')
_FAST_TRI = re.compile(rb'<(?:\w+:)?triangle\s+v1="(\d+)"\s+v2="(\d+)"\s+v3="(\d+)"'
                       rb'(?:\s+(?:paint_color|slic3rpe:mmu_segmentation)="([0-9A-Fa-f]*)")?')


def decode_paint(code):
    """Estado dominante de un triángulo pintado. 0 = sin pintar (filamento del objeto)."""
    if not code:
        return 0
    nibbles = [int(c, 16) for c in reversed(code)]
    bits = []
    for n in nibbles:
        bits.extend(((n >> i) & 1) for i in range(4))
    pos = [0]

    def read(k):
        v = 0
        for i in range(k):
            if pos[0] < len(bits):
                v |= bits[pos[0]] << i
            pos[0] += 1
        return v
    weights = {}

    def node(w):
        split = read(2)
        if split == 0:
            st = read(2)
            if st == 3:
                st = 3 + read(4)
            weights[st] = weights.get(st, 0.0) + w
            return
        read(2)                           # lado especial
        n = split + 1
        for _ in range(n):
            if pos[0] >= len(bits):
                return
            node(w / n)
    try:
        node(1.0)
    except RecursionError:
        pass
    return max(weights, key=weights.get) if weights else 0


def _attrs(blob):
    return {k.decode().split(':')[-1] if k.decode() not in ('slic3rpe:mmu_segmentation',) else 'mmu': v.decode()
            for k, v in _ATTR.findall(blob)}


def _matrix(txt):
    if not txt:
        return np.eye(4)
    v = [float(x) for x in txt.split()]
    m = np.eye(4)
    m[:3, :3] = np.array(v[:9]).reshape(3, 3)          # 3MF: filas = ejes, vector fila
    m[:3, 3] = v[9:12]
    return m


def _apply(m, V):
    return V @ m[:3, :3] + m[:3, 3]


def _triangles(body):
    """Triángulos y estado de pintura. Vía rápida con una sola regex; si el archivo
    ordena los atributos de otra forma, se usa la lectura genérica."""
    n_all = len(_TRI.findall(body))
    fast = _FAST_TRI.findall(body)
    cache = {b'': 0}
    if len(fast) == n_all:
        F = np.array([(int(a), int(b), int(c)) for a, b, c, _ in fast], np.int64).reshape(-1, 3)
        S = np.empty(len(fast), np.int64)
        for i, (_, _, _, p) in enumerate(fast):
            st = cache.get(p)
            if st is None:
                st = cache[p] = decode_paint(p.decode())
            S[i] = st
        return F, S
    tris, states = [], []
    for t in _TRI.findall(body):
        ta = _attrs(t)
        tris.append((int(ta['v1']), int(ta['v2']), int(ta['v3'])))
        p = (ta.get('paint_color') or ta.get('mmu') or '').encode()
        st = cache.get(p)
        if st is None:
            st = cache[p] = decode_paint(p.decode())
        states.append(st)
    return np.array(tris, np.int64).reshape(-1, 3), np.array(states, np.int64)


def read_3mf(path):
    """Devuelve (V mm, F, estado por triángulo, colores de filamento, extrusor por objeto)."""
    z = zipfile.ZipFile(path)
    names = z.namelist()
    colors = []
    for n in names:
        if n.endswith('project_settings.config'):
            try:
                colors = json.loads(z.read(n).decode('utf-8', 'ignore')).get('filament_colour', []) or []
            except ValueError:
                pass
        elif n.endswith('Slic3r_PE.config') and not colors:
            m = re.search(rb'extruder_colour\s*=\s*(.+)', z.read(n))
            if m:
                colors = [c.strip() for c in m.group(1).decode().split(';')]
    default_ext = {}     # objeto -> extrusor
    part_ext = {}        # (objeto, pieza) -> extrusor (Bambu/Orca: cada pieza puede tener el suyo)
    for n in names:
        if n.endswith('model_settings.config'):
            txt = z.read(n).decode('utf-8', 'ignore')
            for oid, body in re.findall(r'<object id="(\d+)">(.*?)</object>', txt, re.S):
                head = re.split(r'<part\b', body, 1)[0]
                m = re.search(r'key="extruder" value="(\d+)"', head)
                if m and int(m.group(1)) > 0:
                    default_ext[oid] = int(m.group(1))
                for pid, pbody in re.findall(r'<part id="(\d+)"[^>]*>(.*?)</part>', body, re.S):
                    m = re.search(r'key="extruder" value="(\d+)"', pbody)
                    if m and int(m.group(1)) > 0:
                        part_ext[(oid, pid)] = int(m.group(1))
    meshes = {}          # (archivo, id) -> (V, F, estados)
    comps = {}           # id de objeto del modelo principal -> [(archivo, id, matriz)]
    items = []
    for n in names:
        if not n.endswith('.model'):
            continue
        data = z.read(n)
        for head, body in _OBJ.findall(data):
            a = _attrs(head)
            oid = a.get('id')
            if b'<mesh' in body or b':mesh' in body:
                vs = np.array(_VERT.findall(body), dtype=float) if body else np.zeros((0, 3))
                meshes[(n, oid)] = (vs.reshape(-1, 3),) + _triangles(body)
            for c in _COMP.findall(body):
                ca = _attrs(c)
                path_attr = ca.get('path', '').lstrip('/') or n
                comps.setdefault((n, oid), []).append((path_attr, ca.get('objectid'), _matrix(ca.get('transform'))))
        for it in _ITEM.findall(data):
            ia = _attrs(it)
            items.append((n, ia.get('objectid'), _matrix(ia.get('transform'))))
    Vs, Fs, Ss = [], [], []
    off = 0

    def add(key, m, ext, top):
        nonlocal off
        if key in meshes:
            V, F, S = meshes[key]
            S = np.where(S == 0, ext, S)
            Vs.append(_apply(m, V)); Fs.append(F + off); Ss.append(S); off += len(V)
        for (p, cid, cm) in comps.get(key, []):
            add((p, cid), _compose(cm, m), part_ext.get((top, cid), ext), top)

    def _compose(child, parent):
        # vectores fila: primero el del hijo y luego el del padre
        out = np.eye(4)
        out[:3, :3] = child[:3, :3] @ parent[:3, :3]
        out[:3, 3] = child[:3, 3] @ parent[:3, :3] + parent[:3, 3]
        return out
    for (n, oid, m) in items or [(k[0], k[1], np.eye(4)) for k in meshes]:
        add((n, oid), m, default_ext.get(oid, 1), oid)
    if not Vs:
        raise ValueError('El 3MF no tiene mallas que leer.')
    return np.vstack(Vs), np.vstack(Fs), np.concatenate(Ss), colors


def _srgb_to_linear(c):
    return c / 12.92 if c <= 0.04045 else ((c + 0.055) / 1.055) ** 2.4


def import_painted(context, path):
    V, F, S, colors = read_3mf(path)
    used = sorted(set(int(s) for s in np.unique(S)))
    mats = []
    for ext in used:
        hx = colors[ext - 1] if 0 < ext <= len(colors) else '#CCCCCC'
        hx = '#' + hx.lstrip('#')[:6].upper()
        name = f'Color {hx}'
        mat = bpy.data.materials.get(name) or bpy.data.materials.new(name)
        r, g, b = (int(hx[i:i + 2], 16) / 255 for i in (1, 3, 5))
        mat.diffuse_color = (_srgb_to_linear(r), _srgb_to_linear(g), _srgb_to_linear(b), 1.0)
        mats.append(mat)
    index = {e: i for i, e in enumerate(used)}
    mi = np.array([index[int(s)] for s in S], np.int32)
    name = bpy.path.display_name_from_filepath(path)
    me = bpy.data.meshes.new(name)
    me.vertices.add(len(V)); me.vertices.foreach_set('co', (V * 0.001).astype(np.float32).ravel())
    me.loops.add(len(F) * 3); me.loops.foreach_set('vertex_index', F.astype(np.int32).ravel())
    me.polygons.add(len(F)); me.polygons.foreach_set('loop_start', np.arange(0, len(F) * 3, 3, dtype=np.int32))
    for m in mats:
        me.materials.append(m)
    me.polygons.foreach_set('material_index', mi)
    me.update(calc_edges=True)
    obj = bpy.data.objects.new(name, me)
    context.collection.objects.link(obj)
    obj['taller_unidad'] = 'M'
    for o in context.selected_objects:
        o.select_set(False)
    obj.select_set(True)
    context.view_layer.objects.active = obj
    counts = {colors[e - 1] if 0 < e <= len(colors) else f'filamento {e}': int((S == e).sum()) for e in used}
    return obj, counts
