bl_info = {'name': 'Color Print Splitter (MultiColor Kit)', 'author': 'Ricardo Lugaresi', 'version': (1, 2, 0),
           'blender': (4, 2, 0), 'location': 'Vista 3D > N > Color Splitter',
           'description': 'Separa zonas para imprimir en otro color (espigas e insertos). Todo en modo Objeto', 'category': 'Object'}
import math
import bpy
from . import common


class SplitterProperties(bpy.types.PropertyGroup):
    model_unit: bpy.props.EnumProperty(name='Unidades de entrada', items=common.UNIT_ITEMS, default='SCENE')
    tolerance: bpy.props.FloatProperty(name='Holgura (mm)', description='Juego entre pieza y alojamiento', default=.2, min=.01, max=2)
    minimum_wall: bpy.props.FloatProperty(name='Pared mínima (mm)', default=1, min=.1, max=20)
    region: bpy.props.EnumProperty(name='Separar por', items=common.REGION_ITEMS, default='PLANE')
    plane_axis: bpy.props.EnumProperty(name='Orientación inicial', items=[('Z', 'Horizontal', ''), ('X', 'Vertical X', ''), ('Y', 'Vertical Y', '')], default='Z')
    dowel_radius: bpy.props.FloatProperty(name='Radio de espiga (mm)', default=2, min=.1, max=30)
    dowel_length: bpy.props.FloatProperty(name='Longitud de espiga (mm)', default=6, min=.5, max=100)
    inlay_source: bpy.props.EnumProperty(name='Inserto desde', items=[('CUTTER', 'Cortador', 'Una forma que colocas sobre la zona'), ('MARKED', 'Caras marcadas', 'Caras que dejaste seleccionadas')], default='CUTTER')
    cutter_shape: bpy.props.EnumProperty(name='Forma', items=common.SHAPE_ITEMS, default='CYLINDER')
    cutter_size: bpy.props.FloatVectorProperty(name='Tamaño (mm)', size=3, default=(10, 10, 6), min=.5, max=500)
    inlay_depth: bpy.props.FloatProperty(name='Profundidad de inserto (mm)', default=1.5, min=.1, max=30)
    show_advanced: bpy.props.BoolProperty(name='Colocar a mano / caras marcadas', default=False)


def _run(op, fn, message):
    try:
        fn()
    except common.AddonError as exc:
        op.report({'ERROR'}, str(exc)); return {'CANCELLED'}
    op.report({'INFO'}, message); return {'FINISHED'}


class OBJECT_OT_splitter_add_plane(bpy.types.Operator):
    """Añade un plano de corte en el centro del modelo. Muévelo y gíralo en modo Objeto"""
    bl_idname = 'object.splitter_add_plane'; bl_label = 'Añadir plano de corte'; bl_options = {'REGISTER', 'UNDO'}

    @classmethod
    def poll(cls, context):
        return common.poll_object_mode(cls, context)

    def execute(self, context):
        return _run(self, lambda: common.add_cut_plane(context, common.pick_model(context), context.scene.splitter_props.plane_axis),
                    'Plano añadido: colócalo (G / R) y pulsa «Separar con espiga».')


class OBJECT_OT_split_dowel(bpy.types.Operator):
    """Separa el modelo en dos piezas con agujeros enfrentados y una espiga suelta"""
    bl_idname = 'object.split_dowel'; bl_label = 'Separar con espiga'; bl_options = {'REGISTER', 'UNDO'}

    @classmethod
    def poll(cls, context):
        return common.poll_object_mode(cls, context)

    def execute(self, context):
        p = context.scene.splitter_props
        fn = common.split_with_plane if p.region == 'PLANE' else common.split_marked
        return _run(self, lambda: fn(context, 'DOWEL', p.dowel_radius, p.dowel_length, p.tolerance, p.minimum_wall, 'ONE', p.model_unit),
                    'Dos piezas y espiga creadas. Original conservado y oculto.')


class OBJECT_OT_splitter_add_cutter(bpy.types.Operator):
    """Añade un cortador. Colócalo sobre la zona y húndelo lo que quieras de profundidad"""
    bl_idname = 'object.splitter_add_cutter'; bl_label = 'Añadir cortador'; bl_options = {'REGISTER', 'UNDO'}

    @classmethod
    def poll(cls, context):
        return common.poll_object_mode(cls, context)

    def execute(self, context):
        p = context.scene.splitter_props
        return _run(self, lambda: common.add_cutter(context, common.pick_model(context), p.cutter_shape, tuple(p.cutter_size), p.model_unit),
                    'Cortador añadido: colócalo sobre la zona (G / R / S) y pulsa «Crear inserto».')


class OBJECT_OT_create_inlay(bpy.types.Operator):
    """Saca la zona como pieza aparte (inserto) y deja su alojamiento en el modelo"""
    bl_idname = 'object.create_inlay'; bl_label = 'Crear inserto y alojamiento'; bl_options = {'REGISTER', 'UNDO'}

    @classmethod
    def poll(cls, context):
        return common.poll_object_mode(cls, context)

    def execute(self, context):
        p = context.scene.splitter_props
        if p.inlay_source == 'CUTTER':
            fn = lambda: common.inlay_from_cutter(context, p.tolerance, p.model_unit)
        else:
            fn = lambda: common.inlay_marked(context, p.inlay_depth, p.tolerance, p.minimum_wall, p.model_unit)
        return _run(self, fn, 'Inserto y base creados. Original conservado y oculto.')


class OBJECT_OT_splitter_click_dowel(common.ClickPlacer, bpy.types.Operator):
    """Clic en el modelo donde quieres separar: se corta ahí con espiga"""
    bl_idname = 'object.splitter_click_dowel'; bl_label = 'Clic para separar con espiga'; bl_options = {'REGISTER', 'UNDO'}
    hint = 'Clic: separar aquí · X / Y / Z: orientación del corte · Rueda: girar 5° · Esc: cancelar'

    @classmethod
    def poll(cls, context):
        return common.poll_object_mode(cls, context)

    def create_helper(self, context, model):
        self.axis = context.scene.splitter_props.plane_axis
        self.tilt = 0.0
        return common.add_cut_plane(context, model, self.axis)

    def key(self, context, helper, key):
        if key in {'X', 'Y', 'Z'}:
            self.axis = key; self.tilt = 0.0; return True
        return False

    def wheel(self, context, helper, up):
        self.tilt += math.radians(5 if up else -5)

    def place(self, context, helper, loc, normal):
        common.place_plane(helper, loc, self.axis)
        helper.rotation_euler.rotate_axis('X', self.tilt)

    def commit(self, context, model, helper):
        p = context.scene.splitter_props
        common.commit_split(context, model, helper, 'DOWEL', p.dowel_radius, p.dowel_length, p.tolerance, p.minimum_wall, 'ONE', p.model_unit)
        return 'Separado con espiga. Ctrl+Z si quieres probar en otro sitio.'


class OBJECT_OT_splitter_click_inlay(common.ClickPlacer, bpy.types.Operator):
    """Clic sobre la zona (ojo, botón, logo): sale como inserto y deja su hueco"""
    bl_idname = 'object.splitter_click_inlay'; bl_label = 'Clic en la zona para sacar inserto'; bl_options = {'REGISTER', 'UNDO'}
    hint = 'Clic: sacar esta zona · Rueda: tamaño · Esc: cancelar'

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
        common.commit_inlay(context, model, helper, p.tolerance, p.model_unit)
        return 'Inserto y hueco creados. Ctrl+Z si quieres probar en otro sitio.'


class VIEW3D_PT_splitter_ui(bpy.types.Panel):
    bl_label = 'MultiColor Splitter'; bl_idname = 'VIEW3D_PT_splitter_ui'; bl_space_type = 'VIEW_3D'; bl_region_type = 'UI'; bl_category = 'Color Splitter'

    def draw(self, context):
        layout = self.layout; p = context.scene.splitter_props
        common.draw_mode_warning(layout, context)
        layout.prop(p, 'model_unit'); layout.prop(p, 'tolerance'); layout.prop(p, 'minimum_wall')
        box = layout.box(); box.label(text='Inserto de color (ojo, botón, logo)', icon='MOD_SOLIDIFY')
        row = box.row(align=True); row.prop(p, 'cutter_shape', expand=True)
        box.prop(p, 'cutter_size')
        col = box.column(); col.scale_y = 1.6; col.operator('object.splitter_click_inlay', icon='RESTRICT_SELECT_OFF')
        box.label(text='Rueda: tamaño. La mitad del alto entra en la pieza.')
        box = layout.box(); box.label(text='Separar con espiga', icon='MOD_BOOLEAN')
        box.prop(p, 'dowel_radius'); box.prop(p, 'dowel_length')
        col = box.column(); col.scale_y = 1.6; col.operator('object.splitter_click_dowel', icon='RESTRICT_SELECT_OFF')
        box.label(text='X / Y / Z: orientación; rueda: inclinar.')
        adv = layout.box(); adv.prop(p, 'show_advanced', icon='TRIA_DOWN' if p.show_advanced else 'TRIA_RIGHT', emboss=False)
        if p.show_advanced:
            adv.label(text='Espiga:'); adv.prop(p, 'region', expand=True)
            if p.region == 'PLANE':
                row = adv.row(align=True); row.prop(p, 'plane_axis', text=''); row.operator('object.splitter_add_plane', icon='MESH_PLANE')
            adv.operator('object.split_dowel', icon='MOD_BOOLEAN')
            adv.separator(); adv.label(text='Inserto:'); adv.prop(p, 'inlay_source', expand=True)
            if p.inlay_source == 'CUTTER':
                adv.operator('object.splitter_add_cutter', icon='MESH_CYLINDER')
            else:
                adv.prop(p, 'inlay_depth')
            adv.operator('object.create_inlay', icon='MOD_SOLIDIFY')
        layout.label(text='El original se conserva oculto.', icon='INFO')


classes = (SplitterProperties, OBJECT_OT_splitter_click_dowel, OBJECT_OT_splitter_click_inlay, OBJECT_OT_splitter_add_plane, OBJECT_OT_split_dowel, OBJECT_OT_splitter_add_cutter, OBJECT_OT_create_inlay, VIEW3D_PT_splitter_ui)


def register():
    common.register_classes(classes, 'splitter_props', SplitterProperties)


def unregister():
    common.unregister_classes(classes, 'splitter_props')
