
import math
import os
import mathutils
import bpy.types
import xml.etree.ElementTree as etree
import xml.dom.minidom as dom


def export_cycles(fp, scene):
    for node in gen_scene_nodes(scene):
        write(node, fp)

    return {'FINISHED'}

def gen_scene_nodes(scene):
    yield write_film(scene)
    written_materials = set()

    for object in scene.objects:
        materials = getattr(object.data, 'materials', [])
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
              ("TEX_MAGIC",             "magic_texture",()),
              ("TEX_NOISE",             "noise_texture",()),
              ("TEX_COORD",             "texture_coordinate",()),
            )
    
    node_tree = material.node_tree
    # nodes, links = get_nodes_links(context)
    nodes, links = node_tree.nodes, node_tree.links

    output_nodes = list(filter(is_output, nodes))

    nodes = list(nodes)  # We don't want to remove the node from the actual scene.
    nodes.remove(output_nodes[0])

    shader_name = material.name
    
    node = etree.Element('shader', { 'name': shader_name })
    
    def socket_name(socket):
        # TODO don't do this. If it has a space, don't trust there's
        # no other with the same name but with underscores instead of spaces.
        return socket.name.replace(' ', '_')
    
    def shader_node_name(node):
        if is_output(node):
            return 'output'

        # TODO don't do this. If it has a space, don't trust there's
        # no other with the same name but with underscores instead of spaces.
        return node.name.replace(' ', '_')
    
    for i in nodes:
        node_attrs = { 'name': shader_node_name(i) }
        node_name = xlateType(i.type)
        for inputs_or_outputs in [i.inputs, i.outputs]:
            for j in inputs_or_outputs:
                if inputs_or_outputs is i.inputs:
                    if isConnected(j,links):
                        continue
                if hasattr(j,'default_value'):
                    attr_name = j.name.replace(' ', '') + socketIndex(i, j)
                    if inputs_or_outputs is i.inputs:
                        pass
                        # xmlfile += "\n " + j.name.replace(" ","")
                    else:
                        # TODO how can i translate this?
                        # xmlfile += "\n >>" + j.name.replace(" ","")
                        pass
                    # xmlfile += socketIndex(i, j) + "=\""
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
        node.append(etree.Element(node_name, node_attrs))

    for i in links:
        # TODO links to output
        node.append(etree.Element('connect', {
            'from': ' '.join([shader_node_name(i.from_node),
                xlateSocket(i.from_node.type, i.from_socket.name.replace(' ', '')) + socketIndex(i.from_node, i.from_socket)]),
            'to': ' '.join([shader_node_name(i.to_node),
                xlateSocket(i.to_node.type, i.to_socket.name.replace(' ', '')) + socketIndex(i.to_node, i.to_socket)])
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

