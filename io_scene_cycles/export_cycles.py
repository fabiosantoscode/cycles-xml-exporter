
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
        if node is not None:
            write(node, fp)

    return {'FINISHED'}

def gen_scene_nodes(scene):
    yield write_film(scene)
    written_materials = set()

    yield write_material(scene.world, 'background')

    for object in scene.objects:
        materials = getattr(object.data, 'materials', []) or getattr(object, 'materials', [])
        for material in materials:
            if hash(material) not in written_materials:
                material_node = write_material(material)
                if material_node is not None:
                    written_materials.add(hash(material))
                    yield material_node

        yield  write_object(object, scene=scene)


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
def write_material(material, tag_name='shader'):
    did_copy = False
    if not material.use_nodes:
        did_copy = True
        material = material.copy()
        material.use_nodes = True

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
    
    def isConnected(socket, links):
        for link in links:
            if link.from_socket == socket or link.to_socket == socket:
                return True
        return False

    def is_output(node):
        return node.type in ('OUTPUT', 'OUTPUT_MATERIAL', 'OUTPUT_WORLD')

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

    # tag_name is usually 'shader' but could be 'background' for world shaders
    shader = etree.Element(tag_name, { 'name': shader_name })
    
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
            
        if node.type == 'TEX_IMAGE' and node.image is not None:
            return image_src(node.image)
        elif node.type == 'RGB':
            color = space_separated_float3(
                node.outputs['Color']
                    .default_value[:3])

            return { 'value': color }
        elif node.type == 'VALUE':
            return {
                'value': '%f' % node.outputs['Value'].default_value
            }

        return {}

    connect_later = []

    def gen_shader_node_tree(nodes):
        for node in nodes:
            node_attrs = { 'name': shader_node_name(node) }
            node_name = xlateType(node.type)

            for input in node.inputs:
                if isConnected(input,links):
                    continue
                if not hasattr(input,'default_value'):
                    continue

                el = None
                sock = None
                if input.type == 'RGBA':
                    el = etree.Element('color', {
                        'value': '%f %f %f' % (
                            input.default_value[0],
                            input.default_value[1],
                            input.default_value[2],
                        )
                    })
                    sock = 'Color'
                elif input.type == 'VALUE':
                    el = etree.Element('value', { 'value': '%f' % input.default_value })
                    sock = 'Value'
                elif input.type == 'VECTOR':
                    pass  # TODO no mapping for this?
                else:
                    print('TODO: unsupported default_value for socket of type: %s', input.type);
                    print('(node %s, socket %s)' % (node.name, input.name))
                    continue

                if el is not None:
                    el.attrib['name'] = input.name + ''.join(
                        random.choice('abcdef')
                        for x in range(5))

                    connect_later.append((
                        el.attrib['name'],
                        sock,
                        node,
                        input
                    ))
                    yield el

            node_attrs.update(special_node_attrs(node))
            yield etree.Element(node_name, node_attrs)

    for snode in gen_shader_node_tree(nodes):
        if snode is not None:
            shader.append(snode)

    for link in links:
        from_node = shader_node_name(link.from_node)
        to_node = shader_node_name(link.to_node)

        from_socket = socket_name(link.from_socket, node=link.from_node)
        to_socket = socket_name(link.to_socket, node=link.to_node)

        shader.append(etree.Element('connect', {
            'from': '%s %s' % (from_node, from_socket.replace(' ', '_')),
            'to': '%s %s' % (to_node, to_socket.replace(' ', '_')),

            # uncomment to be compatible with the new proposed syntax for defining nodes
            # 'from_node': from_node,
            # 'to_node': to_node,
            # 'from_socket': from_socket,
            # 'to_socket': to_socket
        }))

    for fn, fs, tn, ts in connect_later:
        from_node = fn
        to_node = shader_node_name(tn)

        from_socket = fs
        to_socket = socket_name(ts, node=tn)

        shader.append(etree.Element('connect', {
            'from': '%s %s' % (from_node, from_socket.replace(' ', '_')),
            'to': '%s %s' % (to_node, to_socket.replace(' ', '_')),

            # uncomment to be compatible with the new proposed syntax for defining nodes
            # 'from_node': from_node,
            # 'to_node': to_node,
            # 'from_socket': from_socket,
            # 'to_socket': to_socket
        }))

    if did_copy:
        # TODO delete the material we created as a hack to support materials with use_nodes == False
        pass
    return shader


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

    P = ' '.join(space_separated_float3(v.co) for v in mesh.vertices)

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

def space_separated_float3(coords):
    float3 = list(map(str, coords))
    assert len(float3) == 3, 'tried to serialize %r into a float3' % float3
    return ' '.join(float3)

def space_separated_float4(coords):
    float4 = list(map(str, coords))
    assert len(float4) == 4, 'tried to serialize %r into a float4' % float4
    return ' '.join(float4)

def space_separated_matrix(matrix):
    return ' '.join(space_separated_float4(row) + ' ' for row in matrix)

def write(node, fp):
    # strip(node)
    s = etree.tostring(node, encoding='unicode')
    # s = dom.parseString(s).toprettyxml()
    fp.write(s)
    fp.write('\n')

