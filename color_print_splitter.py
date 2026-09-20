bl_info = {
    "name": "Color Print Splitter (MultiColor Kit)",
    "author": "Asistente 3D",
    "version": (1, 0, 0),
    "blender": (3, 0, 0),
    "location": "View3D > Sidebar (N) > Color Splitter",
    "description": "Prepara cualquier modelo STL para impresion multicolor por piezas y pegado",
    "category": "Mesh",
}

import bpy
import bmesh
from mathutils import Vector

# Parametros configurables desde el panel
class SplitterProperties(bpy.types.PropertyGroup):
    tolerance: bpy.props.FloatProperty(
        name="Tolerancia FDM (mm)",
        description="Holgura para que las piezas encajen suavemente con pegamento",
        default=0.2,
        min=0.05,
        max=0.8,
        unit='LENGTH'
    )
    dowel_radius: bpy.props.FloatProperty(
        name="Radio Espiga (mm)",
        description="Grosor de la espiga cilindrica",
        default=2.0,
        min=0.5,
        max=10.0,
        unit='LENGTH'
    )
    dowel_length: bpy.props.FloatProperty(
        name="Largo Espiga (mm)",
        description="Longitud total del cilindro conector",
        default=6.0,
        min=2.0,
        max=25.0,
        unit='LENGTH'
    )
    inlay_depth: bpy.props.FloatProperty(
        name="Profundidad Cajeado (mm)",
        description="Profundidad del hueco para lunares o parches curvos",
        default=1.5,
        min=0.5,
        max=6.0,
        unit='LENGTH'
    )

# 1. HERRAMIENTA: SEPARAR EXTREMIDADES CON DOWEL (Estilo Lincoln)
class MESH_OT_split_dowel(bpy.types.Operator):
    bl_idname = "mesh.split_dowel"
    bl_label = "Separar con Conector Dowel"
    bl_options = {'REGISTER', 'UNDO'}

    def execute(self, context):
        props = context.scene.splitter_props
        base_obj = context.active_object

        if not base_obj or base_obj.mode != 'EDIT':
            self.report({'ERROR'}, "Debes estar en Edit Mode y tener seleccionada la extremidad")
            return {'CANCELLED'}

        # Calcular centro de la costura antes de separar
        bm = bmesh.from_edit_mesh(base_obj.data)
        boundary_verts = [v for v in bm.verts if v.select and any(not e.other_face(f) or not e.other_face(f).select for f in v.link_faces for e in f.edges)]
        
        if boundary_verts:
            avg_center = sum((v.co for v in boundary_verts), Vector()) / len(boundary_verts)
            world_center = base_obj.matrix_world @ avg_center
        else:
            selected_verts = [v.co for v in bm.verts if v.select]
            if not selected_verts:
                self.report({'ERROR'}, "No hay caras seleccionadas")
                return {'CANCELLED'}
            world_center = base_obj.matrix_world @ (sum(selected_verts, Vector()) / len(selected_verts))

        # Separar la pieza seleccionada
        bpy.ops.mesh.separate(type='SELECTED')
        bpy.ops.object.mode_set(mode='OBJECT')

        part_b = [o for o in context.selected_objects if o != base_obj][0]
        part_b.name = f"{base_obj.name}_Extremidad"

        # Sellar tapas en ambas mallas
        for ob in [base_obj, part_b]:
            context.view_layer.objects.active = ob
            bpy.ops.object.mode_set(mode='EDIT')
            bpy.ops.mesh.select_all(action='SELECT')
            bpy.ops.mesh.fill_holes(sides=0)
            bpy.ops.object.mode_set(mode='OBJECT')

        # Cortador de hueco con tolerancia
        cutter_radius = props.dowel_radius + props.tolerance
        cutter_length = props.dowel_length + (props.tolerance * 2)

        bpy.ops.mesh.primitive_cylinder_add(
            radius=cutter_radius,
            depth=cutter_length,
            location=world_center
        )
        cutter = context.active_object
        cutter.name = "Temp_Cutter"

        # Cavar caja en Base
        mod_a = base_obj.modifiers.new(name="Dowel_Hole", type='BOOLEAN')
        mod_a.operation = 'DIFFERENCE'
        mod_a.object = cutter
        mod_a.solver = 'FAST'
        context.view_layer.objects.active = base_obj
        bpy.ops.object.modifier_apply(modifier="Dowel_Hole")

        # Cavar caja en Extremidad
        mod_b = part_b.modifiers.new(name="Dowel_Hole", type='BOOLEAN')
        mod_b.operation = 'DIFFERENCE'
        mod_b.object = cutter
        mod_b.solver = 'FAST'
        context.view_layer.objects.active = part_b
        bpy.ops.object.modifier_apply(modifier="Dowel_Hole")

        bpy.data.objects.remove(cutter, do_unlink=True)

        # Generar el Dowel independiente para imprimir
        bpy.ops.mesh.primitive_cylinder_add(
            radius=props.dowel_radius,
            depth=props.dowel_length,
            location=world_center + Vector((props.dowel_radius * 4, 0, 0))
        )
        dowel = context.active_object
        dowel.name = f"Dowel_{base_obj.name}"

        self.report({'INFO'}, "Piezas separadas y espiga con tolerancia generada")
        return {'FINISHED'}

# 2. HERRAMIENTA: INSERTO CURVO CAJEADO (Estilo Pikachu)
class MESH_OT_create_inlay(bpy.types.Operator):
    bl_idname = "mesh.create_inlay"
    bl_label = "Crear Inserto / Cajeado"
    bl_options = {'REGISTER', 'UNDO'}

    def execute(self, context):
        props = context.scene.splitter_props
        base_obj = context.active_object

        if not base_obj or base_obj.mode != 'EDIT':
            self.report({'ERROR'}, "Debes estar en Edit Mode y pintar las caras del detalle")
            return {'CANCELLED'}

        # Duplicar y separar
        bpy.ops.mesh.duplicate()
        bpy.ops.mesh.separate(type='SELECTED')
        bpy.ops.object.mode_set(mode='OBJECT')

        inlay_obj = [o for o in context.selected_objects if o != base_obj][0]
        inlay_obj.name = f"{base_obj.name}_Boton_Color"

        # Dar grosor hacia adentro (Solidify)
        mod_sol = inlay_obj.modifiers.new(name="Solidify", type='SOLIDIFY')
        mod_sol.thickness = -props.inlay_depth
        mod_sol.use_even_offset = True
        context.view_layer.objects.active = inlay_obj
        bpy.ops.object.modifier_apply(modifier="Solidify")

        # Cortador del lecho con tolerancia perimetral
        cutter = inlay_obj.copy()
        cutter.data = inlay_obj.data.copy()
        cutter.name = "Temp_Cutter"
        context.collection.objects.link(cutter)

        mod_disp = cutter.modifiers.new(name="Tolerance", type='DISPLACE')
        mod_disp.strength = props.tolerance
        context.view_layer.objects.active = cutter
        bpy.ops.object.modifier_apply(modifier="Tolerance")

        # Cavar lecho en la base
        mod_bool = base_obj.modifiers.new(name="Pocket_Bed", type='BOOLEAN')
        mod_bool.operation = 'DIFFERENCE'
        mod_bool.object = cutter
        mod_bool.solver = 'FAST'
        context.view_layer.objects.active = base_obj
        bpy.ops.object.modifier_apply(modifier="Pocket_Bed")

        bpy.data.objects.remove(cutter, do_unlink=True)

        self.report({'INFO'}, "Boton curvo y cajeado hembra listos")
        return {'FINISHED'}

# Panel en la barra lateral
class VIEW3D_PT_splitter_ui(bpy.types.Panel):
    bl_label = "MultiColor Splitter"
    bl_idname = "VIEW3D_PT_splitter_ui"
    bl_space_type = 'VIEW_3D'
    bl_region_type = 'UI'
    bl_category = 'Color Splitter'

    def draw(self, context):
        layout = self.layout
        props = context.scene.splitter_props

        col = layout.column(align=True)
        col.label(text="Holgura General:")
        col.prop(props, "tolerance")

        layout.separator()

        box1 = layout.box()
        box1.label(text="1. Extremidades (Lincoln):")
        box1.prop(props, "dowel_radius")
        box1.prop(props, "dowel_length")
        box1.operator("mesh.split_dowel", icon='CON_LOCKTRACK')

        layout.separator()

        box2 = layout.box()
        box2.label(text="2. Detalles Curvos (Pikachu):")
        box2.prop(props, "inlay_depth")
        box2.operator("mesh.create_inlay", icon='MOD_BOOLEAN')

classes = (
    SplitterProperties,
    MESH_OT_split_dowel,
    MESH_OT_create_inlay,
    VIEW3D_PT_splitter_ui,
)

def register():
    for cls in classes:
        bpy.utils.register_class(cls)
    bpy.types.Scene.splitter_props = bpy.props.PointerProperty(type=SplitterProperties)

def unregister():
    for cls in reversed(classes):
        bpy.utils.unregister_class(cls)
    del bpy.types.Scene.splitter_props

if __name__ == "__main__":
    register()