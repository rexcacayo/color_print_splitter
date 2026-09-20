bl_info = {'name':'Color Print Splitter (MultiColor Kit)', 'author':'Asistente 3D', 'version':(1,1,0), 'blender':(4,2,0), 'location':'Vista 3D > N > Color Splitter', 'description':'Separa regiones con espigas e insertos, conservando el original', 'category':'Mesh'}
import bpy
from . import common

class SplitterProperties(bpy.types.PropertyGroup):
    model_unit: bpy.props.EnumProperty(name='Unidades de entrada',items=common.UNIT_ITEMS,default='SCENE')
    tolerance: bpy.props.FloatProperty(name='Holgura radial (mm)',description='Incremento radial del alojamiento; para insertos, desplazamiento normal aproximado',default=.2,min=.01,max=2)
    dowel_radius: bpy.props.FloatProperty(name='Radio de espiga (mm)',default=2,min=.1,max=30)
    dowel_length: bpy.props.FloatProperty(name='Longitud de espiga (mm)',default=6,min=.5,max=100)
    inlay_depth: bpy.props.FloatProperty(name='Profundidad de inserto (mm)',default=1.5,min=.1,max=30)
    minimum_wall: bpy.props.FloatProperty(name='Pared mínima (mm)',default=1,min=.1,max=20)

class MESH_OT_split_dowel(bpy.types.Operator):
    bl_idname='mesh.split_dowel'; bl_label='Separar con espiga'; bl_options={'REGISTER','UNDO'}
    @classmethod
    def poll(cls,context): return context.mode=='EDIT_MESH' and context.active_object is not None
    def execute(self,context):
        p=context.scene.splitter_props
        try: common.split_connectors(context,'DOWEL',p.dowel_radius,p.dowel_length,p.tolerance,p.minimum_wall,unit=p.model_unit)
        except Exception as exc:
            self.report({'ERROR'},str(exc)); return {'CANCELLED'}
        self.report({'INFO'},'Dos piezas y espiga horizontal creadas. Original conservado y oculto.'); return {'FINISHED'}

class MESH_OT_create_inlay(bpy.types.Operator):
    bl_idname='mesh.create_inlay'; bl_label='Crear inserto y alojamiento'; bl_options={'REGISTER','UNDO'}
    @classmethod
    def poll(cls,context): return context.mode=='EDIT_MESH' and context.active_object is not None
    def execute(self,context):
        p=context.scene.splitter_props
        try: common.create_inlay(context,p.inlay_depth,p.tolerance,p.minimum_wall,p.model_unit)
        except Exception as exc:
            self.report({'ERROR'},str(exc)); return {'CANCELLED'}
        self.report({'INFO'},'Inserto y base creados. Original conservado y oculto.'); return {'FINISHED'}

class VIEW3D_PT_splitter_ui(bpy.types.Panel):
    bl_label='MultiColor Splitter'; bl_idname='VIEW3D_PT_splitter_ui'; bl_space_type='VIEW_3D'; bl_region_type='UI'; bl_category='Color Splitter'
    def draw(self,context):
        layout=self.layout; p=context.scene.splitter_props
        layout.prop(p,'model_unit'); layout.prop(p,'tolerance'); layout.prop(p,'minimum_wall')
        box=layout.box(); box.label(text='Espiga: selecciona caras con borde plano')
        box.prop(p,'dowel_radius'); box.prop(p,'dowel_length'); box.operator('mesh.split_dowel',icon='MOD_BOOLEAN')
        box=layout.box(); box.label(text='Inserto: selecciona un parche de caras')
        box.prop(p,'inlay_depth'); box.operator('mesh.create_inlay',icon='MOD_SOLIDIFY')
        layout.label(text='El original se conserva oculto.')

classes=(SplitterProperties,MESH_OT_split_dowel,MESH_OT_create_inlay,VIEW3D_PT_splitter_ui)
def register(): common.register_classes(classes,'splitter_props',SplitterProperties)
def unregister(): common.unregister_classes(classes,'splitter_props')
