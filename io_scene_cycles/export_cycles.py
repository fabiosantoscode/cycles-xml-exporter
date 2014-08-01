
import random
import math
import os
import mathutils
import bpy.types
import xml.etree.ElementTree as etree
import xml.dom.minidom as dom

_options = {}
def export_cycles(fp, scene, inline_textures=False):
    global _options
    _options = {
        'inline_textures': inline_textures
    }

    for node in gen_scene_nodes(scene):
        write(node, fp)

    return {'FINISHED'}

def gen_scene_nodes(scene):
    yield write_film(scene)
    written_materials = set()

    for object in scene.objects:
        materials = getattr(object.data, 'materials', []) or getattr(object, 'materials', [])
        for material in materials:
            if hash(material) not in written_materials:
                material_node = write_material(material)
                if material_node is not None:
                    written_materials.add(hash(material))
                    yield material_node

        node = write_object(object, scene=scene)
        if node is not None:
            yield node


def write_camera(camera, scene):
    camera = camera.data

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


def write_film(scene):
    render = scene.render
    scale = scene.render.resolution_percentage / 100.0
    size_x = int(scene.render.resolution_x * scale)
    size_y = int(scene.render.resolution_y * scale)

    return etree.Element('film', {'width': str(size_x), 'height': str(size_y)})



def write_object(object, scene):
    if object.type == 'MESH':
        node = write_mesh(object, scene)
    elif object.type == 'LAMP':
        node = write_light(object)
    elif object.type == 'CAMERA':
        node = write_camera(object, scene)
    else:
        raise NotImplementedError('Object type: %r' % object.type)

    node = wrap_in_state(node, object)
    node = wrap_in_transforms(node, object)
    return node



# from the Node Wrangler, by Barte
def write_material(material):
    if not material.use_nodes:
        return None

    def xlateSocket(typename, socketname):
        for i in xlate:
            if i[0]==typename:
                for j in i[2]:
                    if j[0]==socketname:
                        return j[1]
        return socketname
    
    def xlateType(typename ):
        for i in xlate:
            if i[0]==typename:
                return i[1]
        return typename.lower()
    
    def isConnected(socket,links):
        for i in links:
            if i.from_socket is socket or i.to_socket is socket:
                return True
        return False

    def is_output(node):
        return node.type in ('OUTPUT', 'OUTPUT_MATERIAL')

    def socketIndex(node, socket):
        socketindex=0
        countname=0
        for i in node.inputs:
            if i.name == socket.name:
             countname += 1
             if i==socket:
                socketindex=countname
        if socketindex>0:
            if countname>1:
                return str(socketindex)
            else:
                return ''
        countname=0
        for i in node.outputs:
            if i.name == socket.name:
                countname += 1
                if i==socket:
                    socketindex=countname
        if socketindex>0:
            if countname>1:
                return str(socketindex)
        return ''
    #           blender        <--->     cycles
    xlate = ( ("RGB",                   "color",()),
              ("BSDF_DIFFUSE",          "diffuse_bsdf",()),
              ("BSDF_TRANSPARENT",      "transparent_bsdf",()),
              ("BUMP",                  "bump",()),
              ("FRESNEL",               "fresnel",()),
              ("MATH",                  "math",()),
              ("MIX_RGB",               "mix",()),
              ("MIX_SHADER",            "mix_closure",(("Shader","closure"),)),
              ("OUTPUT_MATERIAL",       "",()),
              ("SUBSURFACE_SCATTERING", "subsurface_scattering",()),
              ("TEX_IMAGE",             "image_texture",()),
              ("TEX_MAGIC",             "magic_texture",()),
              ("TEX_NOISE",             "noise_texture",()),
              ("TEX_COORD",             "texture_coordinate",()),
            )
    
    node_tree = material.node_tree
    # nodes, links = get_nodes_links(context)
    nodes, links = node_tree.nodes, node_tree.links

    output_nodes = list(filter(is_output, nodes))

    if not output_nodes:
        return None

    nodes = list(nodes)  # We don't want to remove the node from the actual scene.
    nodes.remove(output_nodes[0])

    shader_name = material.name
    
    node = etree.Element('shader', { 'name': shader_name })
    
    def socket_name(socket, node):
        # TODO don't do this. If it has a space, don't trust there's
        # no other with the same name but with underscores instead of spaces.
        return xlateSocket(node.type, socket.name.replace(' ', '')) + socketIndex(node, socket)
    
    def shader_node_name(node):
        if is_output(node):
            return 'output'

        return node.name.replace(' ', '_')

    def special_node_attrs(node):
        def image_src(image):
            path = node.image.filepath_raw
            if path.startswith('//'):
                path = path[2:]

            if _options['inline_textures']:
                return { 'src': path }
            else:
                import base64
                w, h = image.size
                image = image.copy()
                newimage = bpy.data.images.new('/tmp/cycles_export', width=w, height=h)
                newimage.file_format = 'PNG'
                newimage.pixels = [pix for pix in image.pixels]
                newimage.filepath_raw = '/tmp/cycles_export'
                newimage.save()
                with open('/tmp/cycles_export', 'rb') as fp:
                    return {
                        'src': path,
                        'inline': base64.b64encode(fp.read()).decode('ascii')
                    }
            
        if node.type == 'TEX_IMAGE':
            return image_src(node.image)

        return {}

    connect_later = []

    def gen_shader_node_tree(nodes):
        for i in nodes:
            node_attrs = { 'name': shader_node_name(i) }
            node_name = xlateType(i.type)
            for inputs_or_outputs in [i.inputs, i.outputs]:
                for j in inputs_or_outputs:
                    if inputs_or_outputs is i.inputs:
                        if isConnected(j,links):
                            continue
                    if hasattr(j,'default_value'):
                        el = None
                        if j.type == 'COLOR':
                            el = etree.Element('color', { 'color': '%f %f %f' % j.default_value })
                        if j.type == 'VALUE':
                            el = etree.Element('value', { 'value': '%f' % j.default_value })

                        if el is not None:
                            el.attrib['name'] = j.name + ''.join(random.choice('abcdef') for x in range(5))
                            connect_later.append(
                                (el, j)
                            )
                            yield el

                        attr_name = j.name.replace(' ', '') + socketIndex(i, j)
                        attr_val = ''
                        try:
                            attr_val = (
                                "%f" % j.default_value[0] + " " +
                                "%f" % j.default_value[1] + " " +
                                "%f" % j.default_value[2] + " ")
                            try:
                                attr_val += "%f" % j.default_value[3] + " "
                            except:
                                pass
                        except:
                            attr_val += "%f" % j.default_value + " "
                        node_attrs[attr_name] = attr_val
                    else:
                        pass # TODO ?

            node_attrs.update(special_node_attrs(i))
            yield etree.Element(node_name, node_attrs)

    for i in gen_shader_node_tree(nodes):
        if i is not None:
            node.append(i)

    for i in links:
        from_node = shader_node_name(i.from_node)
        to_node = shader_node_name(i.to_node)

        from_socket = socket_name(i.from_socket, node=i.from_node)
        to_socket = socket_name(i.to_socket, node=i.to_node)

        node.append(etree.Element('connect', {
            'from': '%s %s' % (from_node, from_socket.replace(' ', '_')),
            'to': '%s %s' % (to_node, to_socket.replace(' ', '_')),

            # forwards-compat with the new syntax for defining nodes
            'from_node': from_node,
            'to_node': to_node,
            'from_socket': from_socket,
            'to_socket': to_socket
        }))
    
    return node


def write_light(object):
    # TODO export light's shader here? Where?

    return etree.Element('light', {
        'P': '%f %f %f' % (
            object.location[0],
            object.location[1],
            object.location[2])
    })

def write_mesh(object, scene):
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

    return etree.Element('mesh', attrib={'nverts': nverts, 'verts': verts, 'P': P})

def wrap_in_transforms(xml_element, object):
    matrix = object.matrix_world

    if (object.type == 'CAMERA'):
        # In cycles, the camera points at its Z axis
        rot = mathutils.Matrix.Rotation(math.pi, 4, 'X')
        matrix = matrix.copy() * rot

    wrapper = etree.Element('transform', { 'matrix': space_separated_matrix(matrix.transposed()) })
    wrapper.append(xml_element)

    return wrapper

def wrap_in_state(xml_element, object):
    # UNSUPPORTED: Meshes with multiple materials

    try:
        material = getattr(object.data, 'materials', [])[0]
    except LookupError:
        return xml_element

    state = etree.Element('state', {
        'shader': material.name
    })

    state.append(xml_element)

    return state

def space_separated_coords(coords):
    return ' '.join(map(str, coords))

def space_separated_matrix(matrix):
    return ' '.join(space_separated_coords(row) + ' ' for row in matrix)

def write(node, fp):
    # strip(node)
    s = etree.tostring(node, encoding='unicode')
    # s = dom.parseString(s).toprettyxml()
    fp.write(s)
    fp.write('\n')

