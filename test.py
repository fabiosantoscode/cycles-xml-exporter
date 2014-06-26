
# run this with
# $ blender some_test_file.blend --background --python test.py
# and look at the output

from sys import stdout

import bpy

import io_scene_cycles
from io_scene_cycles.export_cycles import export_cycles

scene = bpy.data.scenes["Scene"]

export_cycles(stdout, scene)

