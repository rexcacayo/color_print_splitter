bl_info = {'name': 'Color Print Splitter', 'author': 'Ricardo Lugaresi', 'version': (2, 1, 1),
           'blender': (4, 2, 0), 'location': 'Vista 3D > N > Color Splitter',
           'description': 'Separa un modelo pintado en una pieza por color, con el hueco hecho en la base para pegarlas. Todo en modo Objeto',
           'category': 'Object'}
import bpy
from . import color_split, common, exporting


class SplitterColor(bpy.types.PropertyGroup):
    index: bpy.props.IntProperty()
    label: bpy.props.StringProperty()
    rgba: bpy.props.FloatVectorProperty(size=4, subtype='COLOR', min=0, max=1)
    area: bpy.props.FloatProperty()
    zones: bpy.props.IntProperty()
    fine_zones: bpy.props.IntProperty()
    min_width: bpy.props.FloatProperty()
    use: bpy.props.BoolProperty(name='Pieza', description='Sacar este color como pieza aparte (si no, se queda en la base para pintarlo)', default=True)


class SplitterProperties(bpy.types.PropertyGroup):
    model_unit: bpy.props.EnumProperty(name='Unidades', items=common.UNIT_ITEMS, default='AUTO')
    colors: bpy.props.CollectionProperty(type=SplitterColor)
    analyzed: bpy.props.StringProperty(default='')
    base_color: bpy.props.IntProperty(default=-1)
    report: bpy.props.StringProperty(default='')
    depth: bpy.props.FloatProperty(name='Grosor de las piezas', description='Lo que entra cada pieza de color en la base, en mm', default=1.5, min=.4, max=10, precision=1)
    clearance: bpy.props.FloatProperty(name='Holgura', description='Juego entre la pieza de color y su hueco, en mm', default=.15, min=0, max=1, precision=2)
    min_width: bpy.props.FloatProperty(name='Ancho mínimo', description='Zonas más estrechas que esto no se imprimen aparte: se quedan en la base para pintarlas', default=2.0, min=.4, max=20, precision=1)
    min_area: bpy.props.FloatProperty(name='Motas hasta', description='Manchas de color más pequeñas que esto (mm²) pasan al color de alrededor', default=1.0, min=0, max=100, precision=1)
    show_fine: bpy.props.BoolProperty(name='Ajustes', default=False)
    show_extra: bpy.props.BoolProperty(name='Inserto a mano (modelo sin pintar)', default=False)
    cutter_shape: bpy.props.EnumProperty(name='Forma', items=common.SHAPE_ITEMS, default='CYLINDER')
    cutter_size: bpy.props.FloatVectorProperty(name='Tamaño (mm)', size=3, default=(6, 6, 3), min=.5, max=500)
    export_folder: bpy.props.StringProperty(name='Carpeta', default='//Piezas_color', subtype='DIR_PATH')
    export_mode: bpy.props.EnumProperty(name='Formato', items=[
        ('3MF', 'Un 3MF', 'Un solo archivo con todas las piezas, cada una con su nombre y su color (Orca, Bambu, Prusa)'),
        ('COLORS', 'Carpetas por color', 'Una carpeta por color y un STL por pieza: para imprimir por lotes de filamento'),
        ('STL', 'STL sueltos', 'Un STL por pieza en la misma carpeta')], default='3MF')
    export_scope: bpy.props.EnumProperty(name='Exportar', items=common.SCOPE_ITEMS, default='SELECTED')


def _model(context):
    try:
        return common.pick_model(context)
    except common.AddonError:
        return None


class OBJECT_OT_splitter_analyze(bpy.types.Operator):
    """Lee los colores del modelo, cierra la malla y limpia las motas sueltas"""
    bl_idname = 'object.splitter_analyze'; bl_label = 'Analizar colores'; bl_options = {'REGISTER'}

    @classmethod
    def poll(cls, context):
        return common.poll_object_mode(cls, context)

    def execute(self, context):
        p = context.scene.splitter_props
        try:
            obj = common.pick_model(context)
            summary, info = color_split.analyze(context, obj, p.min_area, p.min_width, p.model_unit)
        except common.AddonError as exc:
            self.report({'ERROR'}, str(exc)); return {'CANCELLED'}
        p.colors.clear()
        for idx, s in sorted(summary.items(), key=lambda kv: -kv[1]['area']):
            it = p.colors.add()
            it.index = idx
            it.label = color_split.color_name(obj, idx)
            it.rgba = color_split.color_rgba(obj, idx)
            it.area, it.zones, it.fine_zones = s['area'], s['zones'], s['fine_zones']
            it.min_width = min(s['min_width'], 9999.0)
            it.use = not s['base'] and s['fine_zones'] < s['zones']
        p.base_color = info['base']
        p.analyzed = obj.name
        p.report = f"{info['faces']:,} caras · {info['specks']:,} motas limpiadas".replace(',', '.')
        self.report({'INFO'}, 'Colores analizados: ' + p.report)
        return {'FINISHED'}


class OBJECT_OT_splitter_set_base(bpy.types.Operator):
    """Usar este color como pieza base (la que lleva los huecos)"""
    bl_idname = 'object.splitter_set_base'; bl_label = 'Base'; bl_options = {'REGISTER', 'UNDO'}
    index: bpy.props.IntProperty()

    def execute(self, context):
        p = context.scene.splitter_props
        p.base_color = self.index
        for it in p.colors:
            if it.index == self.index:
                it.use = False
        return {'FINISHED'}


class OBJECT_OT_splitter_split_colors(bpy.types.Operator):
    """Crea la base con los huecos y una pieza por cada color marcado"""
    bl_idname = 'object.splitter_split_colors'; bl_label = 'Separar por colores'; bl_options = {'REGISTER', 'UNDO'}

    @classmethod
    def poll(cls, context):
        p = context.scene.splitter_props
        return common.poll_object_mode(cls, context) and bool(p.analyzed) and bpy.data.objects.get(p.analyzed) is not None

    def execute(self, context):
        p = context.scene.splitter_props
        obj = bpy.data.objects[p.analyzed]
        chosen = [it.index for it in p.colors if it.use and it.index != p.base_color]
        if not chosen:
            self.report({'ERROR'}, 'Marca al menos un color como «pieza».'); return {'CANCELLED'}
        wm = context.window_manager
        wm.progress_begin(0, 100)
        step = [0]

        def tick():
            step[0] += 1
            wm.progress_update(min(99, step[0]))
        try:
            outputs, rep = color_split.split(context, obj, chosen, p.base_color, p.depth, p.clearance, tick)
        except common.AddonError as exc:
            wm.progress_end()
            self.report({'ERROR'}, str(exc)); return {'CANCELLED'}
        wm.progress_end()
        txt = f"Base + {rep['pieces']} color(es) en {rep['zones']} zona(s)"
        if rep['painted']:
            txt += f" · {rep['painted']} zona(s) finas quedan para pintar"
        p.report = txt + f" · {rep['seconds']:.0f} s"
        p.analyzed = ''
        self.report({'INFO'}, p.report + '. Original conservado y oculto.')
        return {'FINISHED'}


class OBJECT_OT_splitter_click_inlay(common.ClickPlacer, bpy.types.Operator):
    """Clic sobre una zona (ojo, botón, logo): sale como inserto y deja su hueco"""
    bl_idname = 'object.splitter_click_inlay'; bl_label = 'Clic en la zona para sacar inserto'; bl_options = {'REGISTER', 'UNDO'}
    hint = 'Clic: sacar esta zona · Shift + rueda: tamaño · Esc: cancelar'

    @classmethod
    def poll(cls, context):
        return common.poll_object_mode(cls, context)

    def create_helper(self, context, model):
        p = context.scene.splitter_props
        return common.add_cutter(context, model, p.cutter_shape, tuple(p.cutter_size), p.model_unit)

    def wheel(self, context, helper, up):
        k = 1.1 if up else 1 / 1.1
        helper.scale = (helper.scale[0] * k, helper.scale[1] * k, helper.scale[2] * k)

    def place(self, context, helper, loc, normal):
        common.place_cutter(helper, loc, normal)

    def commit(self, context, model, helper):
        p = context.scene.splitter_props
        common.commit_inlay(context, model, helper, p.clearance, p.model_unit)
        return 'Inserto y hueco creados. Ctrl+Z si quieres probar en otro sitio.'


class OBJECT_OT_splitter_export(bpy.types.Operator):
    """Exporta las piezas en milímetros: un 3MF con colores, carpetas por color o STL sueltos"""
    bl_idname = 'object.splitter_export'; bl_label = 'Exportar'

    @classmethod
    def poll(cls, context):
        return common.poll_object_mode(cls, context)

    def execute(self, context):
        p = context.scene.splitter_props
        try:
            if p.export_mode == '3MF':
                files = exporting.export_3mf(context, p.export_folder, p.export_scope, p.model_unit)
            elif p.export_mode == 'COLORS':
                files = exporting.export_by_color(context, p.export_folder, p.export_scope, p.model_unit)
            else:
                files = common.export_meshes(context, p.export_folder, p.export_scope, p.model_unit)
        except (common.AddonError, OSError) as exc:
            self.report({'ERROR'}, str(exc)); return {'CANCELLED'}
        where = files[0].parent if files else common.export_folder(p.export_folder)
        kind = '3MF' if p.export_mode == '3MF' else 'STL'
        self.report({'INFO'}, f'{len(files)} {kind} exportado(s) en mm en {where}'); return {'FINISHED'}


class VIEW3D_PT_splitter_ui(bpy.types.Panel):
    bl_label = 'Color Splitter'; bl_idname = 'VIEW3D_PT_splitter_ui'; bl_space_type = 'VIEW_3D'; bl_region_type = 'UI'; bl_category = 'Color Splitter'

    def draw(self, context):
        layout = self.layout; p = context.scene.splitter_props
        if common.draw_mode_warning(layout, context):
            return
        model = _model(context)

        box = layout.box()
        box.label(text='1 · Modelo pintado', icon='MESH_DATA')
        if model is None:
            row = box.row(); row.alert = True
            row.label(text='Selecciona el modelo', icon='ERROR')
        else:
            code, mm = common.resolve_unit(context.scene, p.model_unit, model)
            d = [x * mm for x in model.dimensions]
            box.label(text=model.name, icon='OBJECT_DATA')
            box.label(text=f'{d[0]:.0f} × {d[1]:.0f} × {d[2]:.0f} mm · {len(model.material_slots)} colores')
        col = box.column(); col.scale_y = 1.4
        col.operator('object.splitter_analyze', icon='VIEWZOOM')

        if p.analyzed and p.colors:
            box = layout.box()
            box.label(text='2 · Colores', icon='COLOR')
            if p.report:
                box.label(text=p.report)
            for it in p.colors:
                row = box.row(align=True)
                sw = row.row(); sw.ui_units_x = 1.2; sw.enabled = False
                sw.prop(it, 'rgba', text='')
                info = f'{it.label} · {it.area / 100:.1f} cm²'
                if it.index == p.base_color:
                    row.label(text=info + ' · BASE', icon='HOME')
                    continue
                row.label(text=info)
                if it.fine_zones and it.fine_zones == it.zones:
                    row.label(text='pintar', icon='BRUSH_DATA')
                else:
                    row.prop(it, 'use', text='Pieza', toggle=True)
                op = row.operator('object.splitter_set_base', text='', icon='HOME'); op.index = it.index
                if it.fine_zones and it.fine_zones < it.zones and it.use:
                    sub = box.row(); sub.scale_y = .8
                    sub.label(text=f'   {it.fine_zones} de {it.zones} zonas muy finas: se pintan', icon='BRUSH_DATA')

            fine = box.column()
            fine.prop(p, 'show_fine', icon='TRIA_DOWN' if p.show_fine else 'TRIA_RIGHT', emboss=False)
            if p.show_fine:
                fine.prop(p, 'depth'); fine.prop(p, 'clearance'); fine.prop(p, 'min_width'); fine.prop(p, 'min_area')
                fine.label(text='Ancho y motas: vuelve a analizar', icon='INFO')
            col = box.column(); col.scale_y = 1.6
            col.operator('object.splitter_split_colors', icon='MOD_BOOLEAN')
        elif p.report:
            layout.label(text=p.report, icon='CHECKMARK')

        box = layout.box()
        box.label(text='3 · Exportar', icon='EXPORT')
        box.prop(p, 'export_mode', text='')
        row = box.row(); row.prop(p, 'export_scope', expand=True)
        box.prop(p, 'export_folder')
        if p.export_folder.startswith('//') and not bpy.data.filepath:
            note = box.column(align=True); note.scale_y = .8
            note.label(text='.blend sin guardar: irá a', icon='INFO')
            note.label(text=common.export_folder(p.export_folder))
        col = box.column(); col.scale_y = 1.3
        col.operator('object.splitter_export', icon='EXPORT')

        box = layout.box()
        box.prop(p, 'show_extra', icon='TRIA_DOWN' if p.show_extra else 'TRIA_RIGHT', emboss=False)
        if p.show_extra:
            box.label(text='Inserto a mano (modelo de un color)')
            row = box.row(); row.prop(p, 'cutter_shape', expand=True)
            box.prop(p, 'cutter_size')
            box.operator('object.splitter_click_inlay', icon='RESTRICT_SELECT_OFF')


classes = (SplitterColor, SplitterProperties, OBJECT_OT_splitter_analyze, OBJECT_OT_splitter_set_base,
           OBJECT_OT_splitter_split_colors, OBJECT_OT_splitter_click_inlay, OBJECT_OT_splitter_export, VIEW3D_PT_splitter_ui)


def register():
    for c in classes[:1]:
        bpy.utils.register_class(c)
    common.register_classes(classes[1:], 'splitter_props', SplitterProperties)


def unregister():
    common.unregister_classes(classes[1:], 'splitter_props')
    bpy.utils.unregister_class(classes[0])
