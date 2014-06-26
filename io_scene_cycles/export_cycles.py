
import os
import xml.etree.ElementTree as etree
import xml.dom.minidom as dom



def export_cycles(fp, scene):
    for node in gen_scene_nodes(scene):
        write(node, fp)

    return {'FINISHED'}

def gen_scene_nodes(scene):
    yield film_node(scene)

    yield camera_node(scene)

    # for object in scene.shaders:
    #     pass #gen_shader_nodes(scene)

    for object in scene.objects:
        node = object_node(object, scene=scene)
        if node is not None:
            yield node


def camera_node(scene):
    camera = scene.camera.data

    if camera.type == 'ORTHO':
        camera_type = 'orthogonal'
    elif camera.type == 'PERSP':
        camera_type = 'perspective'
    else:
        raise Exception('Camera type %r unknown!' % camera.type)

    return etree.Element('camera', {
        'type': camera_type,

        # fabio: untested values. assuming to be the same as found here:
        # http://www.blender.org/documentation/blender_python_api_2_57_release/bpy.types.Camera.html#bpy.types.Camera.clip_start
        'nearclip': str(camera.clip_start),
        'farclip': str(camera.clip_end),
        'focaldistance': str(camera.dof_distance),
    })


def film_node(scene):
    render = scene.render
    scale = scene.render.resolution_percentage / 100.0
    size_x = int(scene.render.resolution_x * scale)
    size_y = int(scene.render.resolution_y * scale)

    return etree.Element('film', {'width': str(size_x), 'height': str(size_y)})

def object_node(object, scene):
    if object.type == 'MESH':
        return mesh_node(object, scene)
    elif object.type == 'LAMP':
        return lamp_node(object)
    elif object.type == 'CAMERA':
        return
    else:
        raise NotImplementedError('Object type: %r' % object.type)

    return node


def lamp_node(object):
    # TODO export shader here? Where?

    return etree.Element('light', {
        'P': '%f %f %f' % (
            object.location[0],
            object.location[1],
            object.location[2])
    })

def mesh_node(object, scene):
    mesh = object.to_mesh(scene, True, 'PREVIEW')

    # generate mesh node
    nverts = ""
    verts = ""

    P = ' '.join(space_separated_coords(v.co) for v in mesh.vertices)

    for i, f in enumerate(mesh.tessfaces):
        nverts += str(len(f.vertices)) + " "

        for v in f.vertices:
            verts += str(v) + " "
        verts += " "

    mesh = etree.Element('mesh', attrib={'nverts': nverts, 'verts': verts, 'P': P})

    mesh = wrap_in_transforms(mesh, object)

    return mesh


def wrap_in_transforms(xml_element, object):
    wrapper = etree.Element('transform', { 'matrix': space_separated_matrix(object.matrix_world) })
    wrapper.append(xml_element)

    return wrapper

def space_separated_coords(coords):
    return ' '.join(map(str, coords))

def space_separated_matrix(matrix):
    return ' '.join(space_separated_coords(row) for row in matrix)

def strip(root):
    root.text = None
    root.tail = None
    for elem in root:
        strip(elem)

def write(node, fp):
    # strip(node)
    s = etree.tostring(node, encoding='unicode')
    # s = dom.parseString(s).toprettyxml()
    fp.write(s)
    fp.write('\n')

