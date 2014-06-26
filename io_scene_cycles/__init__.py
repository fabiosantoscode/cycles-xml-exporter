#
# Copyright 2011-2013 Blender Foundation
#
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
# http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License
#

# XML exporter for generating test files, not intended for end users

import bpy
from bpy_extras.io_utils import ExportHelper
from bpy.props import PointerProperty, StringProperty


class CyclesXMLSettings(bpy.types.PropertyGroup):
    @classmethod
    def register(cls):
        bpy.types.Scene.cycles_xml = PointerProperty(
                                        type=cls,
                                        name="Cycles XML export Settings",
                                        description="Cycles XML export settings")
        cls.filepath = StringProperty(
                        name='Filepath',
                        description='Filepath for the .xml file',
                        maxlen=256,
                        default='',
                        subtype='FILE_PATH')
                        
    @classmethod
    def unregister(cls):
        del bpy.types.Scene.cycles_xml

# User Interface Drawing Code
class RenderButtonsPanel():
    bl_space_type = 'PROPERTIES'
    bl_region_type = 'WINDOW'
    bl_context = "render"

    @classmethod
    def poll(self, context):
        rd = context.scene.render
        return rd.engine == 'CYCLES'


class PHYSICS_PT_fluid_export(RenderButtonsPanel, bpy.types.Panel):
    bl_label = "Cycles XML Exporter"

    def draw(self, context):
        layout = self.layout
        
        cycles = context.scene.cycles_xml
        
        #layout.prop(cycles, "filepath")
        layout.operator("export_mesh.cycles_xml")


# Export Operator
class ExportCyclesXML(bpy.types.Operator, ExportHelper):
    """Export a scene to the Cycles Standalone XML format"""
    bl_idname = "export_mesh.cycles_xml"
    bl_label = "Export Cycles XML"

    filename_ext = ".xml"

    @classmethod
    def poll(cls, context):
        return (context.active_object is not None)

    def execute(self, context):
        filepath = bpy.path.ensure_ext(self.filepath, ".xml")

        from . import export_cycles

        return export_cycles.export_cycles(
            scene=context.scene,
            fp=open(self.filepath, 'w'))



def menu_func_export(self, context):
    self.layout.operator(ExportCyclesXML.bl_idname, text="Cycles Standalone Renderer XML (.xml)")


def register():
    bpy.utils.register_module(__name__)
    bpy.types.INFO_MT_file_export.append(menu_func_export)

def unregister():
    bpy.utils.unregister_module(__name__)
    bpy.types.INFO_MT_file_export.remove(menu_func_export)

if __name__ == "__main__":
    register()


bl_info = {
    "name": "Cycles XML exporter",
    "description": "Exports the scene to the standalone Cycles renderer's XML format (you only need this if you are using Cycles standalone.",
    "author": "Fábio Santos, TODO who else?",
    "version": (0, 1),
    "blender": (2, 69, 0),
    "location": "File > Import-Export",
    "warning": "", # used for warning icon and text in addons panel
    "wiki_url": "", # "http://wiki.blender.org/index.php/TODO
    "category": "Import-Export"
}


