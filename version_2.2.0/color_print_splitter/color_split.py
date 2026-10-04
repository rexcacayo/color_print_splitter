"""Parte de Blender de «Separar por colores»: leer la malla, crear objetos, booleana."""
import time

import bpy
import numpy as np
from mathutils.bvhtree import BVHTree

from . import color_core as cc
from . import common

_CACHE = {}


def _arrays(context, obj, mm):
    graph = context.evaluated_depsgraph_get()
    ev = obj.evaluated_get(graph)
    me = ev.to_mesh()
    try:
        me.calc_loop_triangles()
        nt = len(me.loop_triangles)
        tri = np.empty(nt * 3, np.int64); me.loop_triangles.foreach_get('vertices', tri)
        pidx = np.empty(nt, np.int64); me.loop_triangles.foreach_get('polygon_index', pidx)
        pmat = np.empty(len(me.polygons), np.int64); me.polygons.foreach_get('material_index', pmat)
        co = np.empty(len(me.vertices) * 3); me.vertices.foreach_get('co', co)
    finally:
        ev.to_mesh_clear()
    M = np.array(obj.matrix_world)
    V = (co.reshape(-1, 3) @ M[:3, :3].T + M[:3, 3]) * mm
    F = tri.reshape(-1, 3)
    if np.linalg.det(M[:3, :3]) < 0:
        F = F[:, ::-1]
    return V, F, pmat[pidx]


def color_name(obj, index):
    if index < len(obj.material_slots) and obj.material_slots[index].material is not None:
        name = obj.material_slots[index].material.name
        return name.replace('Color ', '').strip() or f'color {index + 1}'
    return f'color {index + 1}'


def color_rgba(obj, index):
    if index < len(obj.material_slots) and obj.material_slots[index].material is not None:
        return tuple(obj.material_slots[index].material.diffuse_color)
    return (.8, .8, .8, 1)


def analyze(context, obj, min_area=1.0, min_width=2.0, unit='AUTO'):
    """Suelda, limpia motas y mide las zonas. Devuelve (resumen por color, informe)."""
    t0 = time.time()
    _code, mm = common.resolve_unit(context.scene, unit, obj)
    V, F, mat = _arrays(context, obj, mm)
    if len(obj.material_slots) < 2 or len(np.unique(mat)) < 2:
        raise common.AddonError('Este modelo no tiene colores por caras (materiales). Píntalo o impórtalo como 3MF/OBJ con colores.')
    raw = (V, F, mat)
    V, F, keep = cc.weld(V, F)
    mat = mat[keep]
    table = cc.edge_table(F)
    stitched = 0
    for _ in range(4):                       # uniones en T de los 3MF pintados
        if cc.is_closed(table):
            break
        V, F, mat, n = cc.fix_t_junctions(V, F, mat)
        if not n:
            break
        stitched += n
        table = cc.edge_table(F)
    if not cc.is_closed(table):
        # ¿modelo que ya viene en piezas de un color? (sin quitar caras repetidas: dos
        # piezas que se tocan comparten caras y cada una las necesita para ir cerrada)
        Vp, Fp, kp = cc.weld(raw[0], raw[1], dedupe=False)
        if _closed_by_color(Fp, raw[2][kp]):
            return _analyze_pieces(obj, Vp, Fp, raw[2][kp], mm, t0)
        bad = int((table['cnt'] != 2).sum())
        raise common.AddonError(f'Después de soldar quedan {bad} aristas abiertas: la malla no es cerrada. '
                                'Repárala antes con Mesh Doctor y vuelve a analizar.')
    mat, specks = cc.clean_specks(V, F, mat, table, min_area=min_area)
    # modelos con pocas caras: refinar junto a las fronteras para poder cortar limpio
    V, F, mat, refined = cc.subdivide_borders(V, F, mat, target=0.3)
    if refined:
        table = cc.edge_table(F)
        if not cc.is_closed(table):
            raise common.AddonError('No se pudo refinar la malla junto a los colores sin abrirla.')
    lab = cc.regions(F, mat, table)
    stats = cc.region_stats(V, F, mat, table, lab)
    _n, farea = cc.face_normals_areas(V, F)
    base = int(np.argmax(np.bincount(mat, weights=farea)))
    summary = cc.color_summary(stats, base, min_width)
    _CACHE[obj.name] = {'V': V, 'F': F, 'mat': mat, 'table': table, 'lab': lab, 'stats': stats,
                        'mm': mm, 'base': base, 'min_width': min_width}
    return summary, {'refined': refined, 'stitched': stitched, 'specks': specks, 'faces': len(F), 'seconds': time.time() - t0, 'base': base}


def _n_parts(n, f):
    """Número de trozos sueltos de una malla."""
    a = np.concatenate([f[:, 0], f[:, 1]]); b = np.concatenate([f[:, 1], f[:, 2]])
    return len(np.unique(cc.components(n, a, b)[np.unique(f)]))


def _closed_by_color(F, mat):
    """True si cada color, por separado, es un sólido sin bordes abiertos (el modelo viene
    en piezas que se tocan o se meten unas en otras). Si no, None."""
    for m in np.unique(mat):
        t = cc.edge_table(F[mat == m])
        if int((t['cnt'] == 1).sum()):
            return None
    return True


def _analyze_pieces(obj, V, F, mat, mm, t0):
    _n, farea = cc.face_normals_areas(V, F)
    area = np.bincount(mat, weights=farea, minlength=int(mat.max()) + 1)
    base = int(np.argmax(area))
    summary = {}
    for m in np.unique(mat):
        f = F[mat == m]
        nz = _n_parts(len(V), f)
        summary[int(m)] = {'zones': nz, 'area': float(area[m]), 'fine_zones': 0, 'fine_area': 0.0,
                           'min_width': float('inf'), 'base': int(m) == base}
    _CACHE[obj.name] = {'mode': 'pieces', 'V': V, 'F': F, 'mat': mat, 'mm': mm, 'base': base}
    return summary, {'refined': 0, 'stitched': 0, 'specks': 0, 'faces': len(F),
                     'seconds': time.time() - t0, 'base': base, 'pieces': True}


def _split_pieces(context, obj, data, piece_colors, base_color, clearance):
    """Modelo en piezas: un objeto por color; a la base se le resta cada pieza elegida
    (crecida la holgura) para que quede su hueco y encaje al pegarla."""
    t0 = time.time()
    V, F, mat, mm = data['V'], data['F'], data['mat'], data['mm']
    col = obj.users_collection[0] if obj.users_collection else context.scene.collection
    mats = [s.material for s in obj.material_slots]

    def sub(m):
        f = F[mat == m]
        used = np.unique(f)
        remap = -np.ones(len(V), np.int64); remap[used] = np.arange(len(used))
        return V[used], remap[f]
    created, report = [], {'zones': 0, 'painted': 0, 'pieces': 0, 'not_cut': 0}
    try:
        bv, bf = sub(base_color)
        base = _new_mesh_object(f'{obj.name}_base', bv / mm, bf, col,
                                [mats[base_color]] if base_color < len(mats) and mats[base_color] else None)
        created.append(base)
        outputs = [base]
        for c in piece_colors:
            if c == base_color:
                continue
            pv, pf = sub(c)
            m = mats[c] if c < len(mats) else None
            o = _new_mesh_object(f'{obj.name}_{color_name(obj, c)}', pv / mm, pf, col, [m] if m else None)
            created.append(o); outputs.append(o)
            report['pieces'] += 1
            report['zones'] += _n_parts(len(pv), pf)
            grown = pv + cc.vertex_normals_full(pv, pf) * clearance
            cut = _new_mesh_object('Cortador_color_temporal', grown / mm, pf, col)
            created.append(cut)
            try:
                _subtract(context, base, cut)
            except common.AddonError:
                report['not_cut'] += 1          # la pieza solo apoya: no hace falta hueco
            created.remove(cut); common.remove_objects([cut])
        code, _mm = common.resolve_unit(context.scene, 'AUTO', obj)
        for o in outputs:
            o[common.UNIT_PROP] = code
            o['taller_origen'] = obj.name
        obj.hide_set(True); obj.hide_render = True
        for o in context.selected_objects:
            o.select_set(False)
        for o in outputs:
            o.select_set(True)
        context.view_layer.objects.active = base
    except Exception:
        common.remove_objects(created)
        raise
    report['seconds'] = time.time() - t0
    return outputs, report


def _new_mesh_object(name, V, F, collection, materials=None, mat_index=None):
    me = bpy.data.meshes.new(name)
    me.vertices.add(len(V))
    me.vertices.foreach_set('co', V.astype(np.float32).ravel())
    me.loops.add(len(F) * 3)
    me.loops.foreach_set('vertex_index', F.astype(np.int32).ravel())
    me.polygons.add(len(F))
    me.polygons.foreach_set('loop_start', np.arange(0, len(F) * 3, 3, dtype=np.int32))
    if materials:
        for m in materials:
            me.materials.append(m)
        if mat_index is not None:
            me.polygons.foreach_set('material_index', mat_index.astype(np.int32))
    me.update(calc_edges=True)
    obj = bpy.data.objects.new(name, me)
    collection.objects.link(obj)
    return obj


def _tri_arrays(me):
    me.calc_loop_triangles()
    tri = np.empty(len(me.loop_triangles) * 3, np.int64); me.loop_triangles.foreach_get('vertices', tri)
    co = np.empty(len(me.vertices) * 3); me.vertices.foreach_get('co', co)
    return co.reshape(-1, 3), tri.reshape(-1, 3)


def _subtract(context, base, cutter):
    """Resta rápida con el solver Manifold. Se acepta si no deja bordes abiertos y el volumen
    baja; los cascarones pueden rozarse consigo mismos en pliegues finos y dejar alguna
    arista compartida por más de dos caras, que los laminadores toleran sin problema."""
    solvers = set(bpy.types.BooleanModifier.bl_rna.properties['solver'].enum_items.keys())
    solver = 'MANIFOLD' if 'MANIFOLD' in solvers else 'EXACT'
    V0, F0 = _tri_arrays(base.data)
    before = cc.signed_volume(V0, F0)
    mod = base.modifiers.new('Color_resta', 'BOOLEAN')
    mod.operation = 'DIFFERENCE'; mod.solver = solver; mod.object = cutter
    try:
        context.view_layer.update()
        graph = context.evaluated_depsgraph_get()
        new = bpy.data.meshes.new_from_object(base.evaluated_get(graph), preserve_all_data_layers=True, depsgraph=graph)
    finally:
        base.modifiers.remove(mod)
    V1, F1 = _tri_arrays(new)
    table = cc.edge_table(F1) if len(F1) else None
    after = cc.signed_volume(V1, F1) if len(F1) else 0.0
    if table is None or int((table['cnt'] == 1).sum()) or not (0 < after < before):
        bpy.data.meshes.remove(new)
        raise common.AddonError('No se pudo abrir el hueco en la base (la resta no dio un sólido). '
                                'Prueba con menos grosor o sube «Motas hasta» y vuelve a analizar.')
    old = base.data
    base.data = new
    new.name = old.name
    if old.users == 0:
        bpy.data.meshes.remove(old)
    return int((table['cnt'] > 2).sum())


def _drop_crumbs(obj, mm, min_mm3=3.0, rel=0.002):
    """Quita los trocitos sueltos que deja la resta (por ejemplo, el alma finísima de un
    lazo pintado por las dos caras). Devuelve cuántos se han quitado."""
    import bmesh
    me = obj.data
    me.calc_loop_triangles()
    nt = len(me.loop_triangles)
    tri = np.empty(nt * 3, np.int64); me.loop_triangles.foreach_get('vertices', tri)
    pidx = np.empty(nt, np.int64); me.loop_triangles.foreach_get('polygon_index', pidx)
    co = np.empty(len(me.vertices) * 3); me.vertices.foreach_get('co', co)
    V = co.reshape(-1, 3) * mm
    F = tri.reshape(-1, 3)
    # componentes por vértices compartidos
    a = np.concatenate([F[:, 0], F[:, 1]]); b = np.concatenate([F[:, 1], F[:, 2]])
    vlab = cc.components(len(V), a, b)
    flab = vlab[F[:, 0]]
    vols = np.bincount(flab, weights=np.einsum('ij,ij->i', V[F[:, 0]], np.cross(V[F[:, 1]], V[F[:, 2]])) / 6.0)
    total = vols.sum()
    small = np.nonzero(np.abs(vols) < max(min_mm3, rel * abs(total)))[0]
    if not len(small):
        return 0
    bad_polys = np.unique(pidx[np.isin(flab, small)])
    bm = bmesh.new()
    bm.from_mesh(me)
    bm.faces.ensure_lookup_table()
    bmesh.ops.delete(bm, geom=[bm.faces[int(i)] for i in bad_polys], context='FACES')
    loose = [v for v in bm.verts if not v.link_faces]
    if loose:
        bmesh.ops.delete(bm, geom=loose, context='VERTS')
    bm.to_mesh(me)
    bm.free()
    me.update()
    return int(len(small))


def split(context, obj, piece_colors, base_color, depth=1.5, clearance=0.15, progress=None):
    """Crea la base con huecos y una pieza por color elegido. Devuelve (objetos, informe)."""
    data = _CACHE.get(obj.name)
    if data is None:
        raise common.AddonError('Analiza los colores primero.')
    if data.get('mode') == 'pieces':
        return _split_pieces(context, obj, data, piece_colors, base_color, clearance)
    t0 = time.time()
    V, F, mat, table, lab, stats, mm = (data[k] for k in ('V', 'F', 'mat', 'table', 'lab', 'stats', 'mm'))
    min_width = data['min_width']
    tree = BVHTree.FromPolygons(V.tolist(), F.tolist(), all_triangles=True)
    vn_full = cc.vertex_normals_full(V, F)
    col = obj.users_collection[0] if obj.users_collection else context.scene.collection
    mats = [s.material for s in obj.material_slots]

    pieces, cutters, report = {}, {}, {'zones': 0, 'painted': 0, 'thin_spots': 0}
    closed_faces = []
    for c in piece_colors:
        if c == base_color:
            continue
        pv, pf, cv, cf = [], [], [], []
        np_, nc_ = 0, 0
        for r in np.nonzero(stats['mat'] == c)[0]:
            if stats['width'][r] < min_width:
                report['painted'] += 1
                continue
            faces = np.nonzero(lab == r)[0]
            if stats['perimeter'][r] == 0:          # pieza entera de un color: sale tal cual
                closed_faces.append(faces)
                used, Fl, _b = cc._region_geometry(V, F, faces)
                pv.append(V[used]); pf.append(Fl + np_); np_ += len(used)
                report['zones'] += 1
                continue
            used, Fl, border = cc._region_geometry(V, F, faces)
            Vr = cc.relax_patch(V[used], Fl, border, tree)
            vn = cc.region_normals(vn_full, used, Fl)
            th = cc.thickness(Vr, vn, tree, range(len(Vr)), depth * 3 + 1)
            d = np.clip(0.45 * th, min(0.5, depth), depth)    # más fino donde el modelo es fino
            report['thin_spots'] += int((d < depth - 1e-6).sum())
            d = cc._smooth_scalar(d, Fl)
            vn, d = cc.smooth_offsets(vn, d, Fl, border)
            # Zonas finas pintadas (p. ej. un lazo de color por las dos caras): si entre el
            # hueco y la otra cara quedaría menos de 0,6 mm de base, el hueco se pasa de la
            # mitad y la base se abre limpia ahí; la pieza llega casi a la mitad. Así no
            # quedan almas finísimas ni paredes de grosor cero (aristas no-manifold).
            thin = (th - 2 * (d + clearance)) < 0.6
            d_cut = np.where(thin, 0.5 * th + 0.1, d + clearance)
            d = np.where(thin, np.clip(0.5 * th - clearance / 2 - 0.05, 0.25, depth), d)
            sv, sf = cc.shell(Vr, Fl, border, vn, d, 0.0, clearance)
            pv.append(sv); pf.append(sf + np_); np_ += len(sv)
            # el hueco sobresale un pelo por fuera y por los lados: así la resta no
            # trabaja con caras coincidentes
            kv, kf = cc.shell(Vr, Fl, border, vn, d_cut, 0.05, -0.03)
            cv.append(kv); cf.append(kf + nc_); nc_ += len(kv)
            report['zones'] += 1
            if progress:
                progress()
        if pv:
            pieces[c] = (np.vstack(pv), np.vstack(pf))
        if cv:
            cutters[c] = (np.vstack(cv), np.vstack(cf))

    if not pieces:
        raise common.AddonError('Ninguna zona es lo bastante ancha para imprimirla aparte: todas quedan para pintar.')

    keep = np.ones(len(F), bool)
    for fc in closed_faces:
        keep[fc] = False
    base_faces = np.nonzero(keep)[0]
    used = np.unique(F[base_faces])
    remap = -np.ones(len(V), np.int64); remap[used] = np.arange(len(used))
    base = _new_mesh_object(f'{obj.name}_base', V[used] / mm, remap[F[base_faces]], col, mats, mat[base_faces])
    created = [base]
    try:
        for c, (kv, kf) in cutters.items():
            cut = _new_mesh_object('Cortador_color_temporal', kv / mm, kf, col)
            created.append(cut)
            report['touching'] = report.get('touching', 0) + _subtract(context, base, cut)
            created.remove(cut); common.remove_objects([cut])
        report['crumbs'] = _drop_crumbs(base, mm)
        outputs = [base]
        for c, (pv, pf) in pieces.items():
            m = mats[c] if c < len(mats) else None
            o = _new_mesh_object(f'{obj.name}_{color_name(obj, c)}', pv / mm, pf, col, [m] if m else None)
            created.append(o); outputs.append(o)
        code, _mm = common.resolve_unit(context.scene, 'AUTO', obj)
        for o in outputs:
            o[common.UNIT_PROP] = code
            o['taller_origen'] = obj.name
        obj.hide_set(True); obj.hide_render = True
        for o in context.selected_objects:
            o.select_set(False)
        for o in outputs:
            o.select_set(True)
        context.view_layer.objects.active = base
    except Exception:
        common.remove_objects(created)
        raise
    report['seconds'] = time.time() - t0
    report['pieces'] = len(pieces)
    return outputs, report
