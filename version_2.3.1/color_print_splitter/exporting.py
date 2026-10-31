# SPDX-FileCopyrightText: 2026 Ricardo Lugaresi
# SPDX-License-Identifier: GPL-3.0-or-later

"""Exportar las piezas: un 3MF con colores, o STL agrupados por color en carpetas."""
import io
import zipfile
from pathlib import Path

import bpy
import numpy as np

from . import common


def _dominant_material(obj, graph):
    """Material que ocupa más superficie: es el color de la pieza (en la base, el color base,
    aunque conserve marcadas las líneas finas para pintar)."""
    ev = obj.evaluated_get(graph)
    me = ev.to_mesh()
    try:
        n = len(me.polygons)
        if not n or not obj.material_slots:
            return None
        mi = np.empty(n, np.int32); me.polygons.foreach_get('material_index', mi)
        ar = np.empty(n); me.polygons.foreach_get('area', ar)
    finally:
        ev.to_mesh_clear()
    idx = int(np.argmax(np.bincount(mi, weights=ar)))
    slots = obj.material_slots
    return slots[idx].material if idx < len(slots) else None


def _hex(mat):
    """Color de la pieza en sRGB. Si el material se llama «Color #RRGGBB» (3MF pintados)
    se usa ese valor tal cual; si no, se convierte el color del material (lineal)."""
    import re
    if mat is None:
        return '#CCCCCC'
    m = re.search(r'#([0-9A-Fa-f]{6})', mat.name)
    if m:
        return '#' + m.group(1).upper()

    def srgb(c):
        c = max(0.0, min(1.0, c))
        return 12.92 * c if c <= 0.0031308 else 1.055 * c ** (1 / 2.4) - 0.055
    r, g, b = (round(srgb(c) * 255) for c in mat.diffuse_color[:3])
    return f'#{r:02X}{g:02X}{b:02X}'


def _color_label(mat):
    if mat is None:
        return 'Sin_color'
    return mat.name.replace('Color ', '').replace('#', '') or 'color'


def _mesh_mm(obj, graph, scale):
    """Vértices (mm, mundo) y triángulos de la malla evaluada."""
    ev = obj.evaluated_get(graph)
    me = ev.to_mesh()
    try:
        me.calc_loop_triangles()
        tri = np.empty(len(me.loop_triangles) * 3, np.int64); me.loop_triangles.foreach_get('vertices', tri)
        co = np.empty(len(me.vertices) * 3); me.vertices.foreach_get('co', co)
    finally:
        ev.to_mesh_clear()
    m = np.array(obj.matrix_world)
    V = (co.reshape(-1, 3) @ m[:3, :3].T + m[:3, 3]) * scale
    F = tri.reshape(-1, 3)
    if np.linalg.det(m[:3, :3]) < 0:
        F = F[:, [0, 2, 1]]
    used, inv = np.unique(F, return_inverse=True)
    return V[used], inv.reshape(-1, 3)


def _objects(context, scope):
    cands = context.selected_objects if scope == 'SELECTED' else context.visible_objects
    objs = sorted((o for o in cands if o.type == 'MESH' and not common.is_helper(o)), key=lambda o: o.name)
    if not objs:
        raise common.AddonError('No hay piezas seleccionadas para exportar.')
    return objs


def export_3mf(context, folder, scope='SELECTED', unit='AUTO', name=None):
    """Un solo .3mf con todas las piezas, cada una con su nombre y su color, en mm."""
    objs = _objects(context, scope)
    graph = context.evaluated_depsgraph_get()
    dest = Path(bpy.path.abspath(common.export_folder(folder))).resolve()
    dest.mkdir(parents=True, exist_ok=True)
    base = name or objs[0].get('taller_origen') or objs[0].name
    used = {p.stem.casefold() for p in dest.iterdir()}
    target = dest / (common.unique_name(common.safe_name(base), used) + '.3mf')

    mats, colors, objects_xml, items = [], {}, [], []
    for i, obj in enumerate(objs, start=1):
        mat = _dominant_material(obj, graph)
        hx = _hex(mat)
        if hx not in colors:
            colors[hx] = len(mats)
            mats.append(f'<base name="{_color_label(mat)}" displaycolor="{hx}FF"/>')
        V, F = _mesh_mm(obj, graph, common.factor(context.scene, unit, obj))
        vb = io.StringIO(); np.savetxt(vb, V, fmt='<vertex x="%.4f" y="%.4f" z="%.4f"/>')
        tb = io.StringIO(); np.savetxt(tb, F, fmt='<triangle v1="%d" v2="%d" v3="%d"/>')
        oname = common.safe_name(obj.name).replace('"', "'").replace('&', 'y')
        objects_xml.append(
            f'<object id="{i + 1}" type="model" name="{oname}" pid="1" pindex="{colors[hx]}">'
            f'<mesh><vertices>\n{vb.getvalue()}</vertices><triangles>\n{tb.getvalue()}</triangles></mesh></object>')
        items.append(f'<item objectid="{i + 1}"/>')
    model = ('<?xml version="1.0" encoding="UTF-8"?>\n'
             '<model unit="millimeter" xml:lang="es-ES" xmlns="http://schemas.microsoft.com/3dmanufacturing/core/2015/02">'
             '<resources><basematerials id="1">' + ''.join(mats) + '</basematerials>'
             + ''.join(objects_xml) + '</resources><build>' + ''.join(items) + '</build></model>')
    ctypes = ('<?xml version="1.0" encoding="UTF-8"?>\n'
              '<Types xmlns="http://schemas.openxmlformats.org/package/2006/content-types">'
              '<Default Extension="rels" ContentType="application/vnd.openxmlformats-package.relationships+xml"/>'
              '<Default Extension="model" ContentType="application/vnd.ms-package.3dmanufacturing-3dmodel+xml"/></Types>')
    rels = ('<?xml version="1.0" encoding="UTF-8"?>\n'
            '<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">'
            '<Relationship Target="/3D/3dmodel.model" Id="rel0" '
            'Type="http://schemas.microsoft.com/3dmanufacturing/2013/01/3dmodel"/></Relationships>')
    with zipfile.ZipFile(target, 'x', zipfile.ZIP_DEFLATED) as z:
        z.writestr('[Content_Types].xml', ctypes)
        z.writestr('_rels/.rels', rels)
        z.writestr('3D/3dmodel.model', model)
    return [target]


def export_by_color(context, folder, scope='SELECTED', unit='AUTO'):
    """Una carpeta por color y un STL por pieza: para imprimir por lotes de filamento.
    Cada pieza va entera a la carpeta de su color principal."""
    objs = _objects(context, scope)
    graph = context.evaluated_depsgraph_get()
    dest = Path(bpy.path.abspath(common.export_folder(folder))).resolve()
    planned = []
    for obj in objs:
        mat = _dominant_material(obj, graph)
        v, n, _m = common._world_triangles(obj, graph, common.factor(context.scene, unit, obj))
        if not len(v):
            raise common.AddonError(f'{obj.name}: la malla no tiene triángulos válidos.')
        planned.append((dest / common.safe_name(_color_label(mat)), obj.name, v, n))
    created = []
    try:
        for sub, name, v, n in planned:
            sub.mkdir(parents=True, exist_ok=True)
            used = {p.stem.casefold() for p in sub.iterdir()}
            target = sub / (common.unique_name(name, used) + '.stl')
            common._write_stl(target, v, n)
            created.append(target)
    except Exception:
        for f in created:
            if f.is_file():
                f.unlink()
        raise
    return created


def _mesh_mm_mat(obj, graph, scale):
    """Como _mesh_mm, con el material de cada triángulo."""
    ev = obj.evaluated_get(graph)
    me = ev.to_mesh()
    try:
        me.calc_loop_triangles()
        nt = len(me.loop_triangles)
        tri = np.empty(nt * 3, np.int64); me.loop_triangles.foreach_get('vertices', tri)
        mi = np.empty(nt, np.int64); me.loop_triangles.foreach_get('material_index', mi)
        co = np.empty(len(me.vertices) * 3); me.vertices.foreach_get('co', co)
    finally:
        ev.to_mesh_clear()
    m = np.array(obj.matrix_world)
    V = (co.reshape(-1, 3) @ m[:3, :3].T + m[:3, 3]) * scale
    F = tri.reshape(-1, 3)
    if np.linalg.det(m[:3, :3]) < 0:
        F = F[:, [0, 2, 1]]
    used, inv = np.unique(F, return_inverse=True)
    return V[used], inv.reshape(-1, 3), mi


def export_3mf_painted(context, folder, scope='SELECTED', unit='AUTO', name=None):
    """Un 3MF «pintado» como los de Bambu Studio / Orca: cada pieza entera, con el color de
    cada cara en `paint_color` y un filamento por color. Orca lo abre con la pintura hecha y
    3D LAB y «Importar 3MF pintado» lo leen con todos sus colores. Sin separar nada."""
    from . import threemf_paint
    objs = _objects(context, scope)
    graph = context.evaluated_depsgraph_get()
    dest = Path(bpy.path.abspath(common.export_folder(folder))).resolve()
    dest.mkdir(parents=True, exist_ok=True)
    base = name or objs[0].get('taller_origen') or objs[0].name
    used = {p.stem.casefold() for p in dest.iterdir()}
    target = dest / (common.unique_name(common.safe_name(base) + '_pintado', used) + '.3mf')

    filaments = []                                   # colores hex en orden de filamento (1, 2, …)
    objects_xml, items, settings = [], [], []
    for i, obj in enumerate(objs, start=1):
        V, F, mi = _mesh_mm_mat(obj, graph, common.factor(context.scene, unit, obj))
        slots = obj.material_slots
        ext_of_slot = []
        for k in range(max(1, len(slots))):
            hx = _hex(slots[k].material if k < len(slots) else None)
            if hx not in filaments:
                filaments.append(hx)
            ext_of_slot.append(filaments.index(hx) + 1)
        ext = np.array(ext_of_slot)[np.clip(mi, 0, len(ext_of_slot) - 1)]
        main = int(np.bincount(ext).argmax())            # el filamento de la pieza: el que más caras tiene
        codes = {e: threemf_paint.encode_paint(e) for e in np.unique(ext)}
        vb = io.StringIO(); np.savetxt(vb, V, fmt='<vertex x="%.4f" y="%.4f" z="%.4f"/>')
        tris = []
        for (a, b, c), e in zip(F.tolist(), ext.tolist()):
            if e == main:
                tris.append(f'<triangle v1="{a}" v2="{b}" v3="{c}"/>')
            else:
                tris.append(f'<triangle v1="{a}" v2="{b}" v3="{c}" paint_color="{codes[e]}"/>')
        oname = common.safe_name(obj.name).replace('"', "'").replace('&', 'y')
        objects_xml.append(f'<object id="{i}" type="model"><mesh><vertices>\n{vb.getvalue()}</vertices>'
                           f'<triangles>\n' + '\n'.join(tris) + '</triangles></mesh></object>')
        items.append(f'<item objectid="{i}" printable="1"/>')
        settings.append(f'<object id="{i}"><metadata key="name" value="{oname}"/><metadata key="extruder" value="{main}"/>'
                        f'<part id="1" subtype="normal_part"><metadata key="name" value="{oname}"/>'
                        f'<metadata key="extruder" value="{main}"/></part></object>')
    model = ('<?xml version="1.0" encoding="UTF-8"?>\n'
             '<model unit="millimeter" xml:lang="es-ES" xmlns="http://schemas.microsoft.com/3dmanufacturing/core/2015/02" '
             'xmlns:BambuStudio="http://schemas.bambulab.com/package/2021">'
             '<metadata name="Application">BambuStudio-02.03.01.00</metadata>'
             '<metadata name="BambuStudio:3mfVersion">1</metadata>'
             '<metadata name="BambuStudio:MmPaintingVersion">1</metadata>'
             '<resources>' + ''.join(objects_xml) + '</resources><build>' + ''.join(items) + '</build></model>')
    import json
    project = json.dumps({'filament_colour': filaments, 'filament_type': ['PLA'] * len(filaments)}, indent=4)
    config = ('<?xml version="1.0" encoding="UTF-8"?>\n<config>' + ''.join(settings) + '</config>')
    ctypes = ('<?xml version="1.0" encoding="UTF-8"?>\n'
              '<Types xmlns="http://schemas.openxmlformats.org/package/2006/content-types">'
              '<Default Extension="rels" ContentType="application/vnd.openxmlformats-package.relationships+xml"/>'
              '<Default Extension="model" ContentType="application/vnd.ms-package.3dmanufacturing-3dmodel+xml"/>'
              '<Default Extension="config" ContentType="text/xml"/></Types>')
    rels = ('<?xml version="1.0" encoding="UTF-8"?>\n'
            '<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">'
            '<Relationship Target="/3D/3dmodel.model" Id="rel0" '
            'Type="http://schemas.microsoft.com/3dmanufacturing/2013/01/3dmodel"/></Relationships>')
    with zipfile.ZipFile(target, 'x', zipfile.ZIP_DEFLATED) as z:
        z.writestr('[Content_Types].xml', ctypes)
        z.writestr('_rels/.rels', rels)
        z.writestr('3D/3dmodel.model', model)
        z.writestr('Metadata/model_settings.config', config)
        z.writestr('Metadata/project_settings.config', project)
    return [target], filaments
