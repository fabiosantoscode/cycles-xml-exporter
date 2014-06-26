
def export_cycles(operator, context):
    object = context.active_object

    if not object:
        raise Exception("No active object")

    mesh = object.to_mesh(scene, True, 'PREVIEW')

    if not mesh:
        raise Exception("No mesh data in active object")

    # generate mesh node
    nverts = ""
    verts = ""
    P = ""

    for v in mesh.vertices:
        P += "%f %f %f  " % (v.co[0], v.co[1], v.co[2])

    for i, f in enumerate(mesh.tessfaces):
        nverts += str(len(f.vertices)) + " "

        for v in f.vertices:
            verts += str(v) + " "
        verts += " "

    node = etree.Element('mesh', attrib={'nverts': nverts, 'verts': verts, 'P': P})
    
    # write to file
    write(node, filepath)

    return {'FINISHED'}
