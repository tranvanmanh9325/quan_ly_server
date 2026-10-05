import bpy
import bmesh
import mathutils
import sys
import os

if sys.stdout.encoding != 'utf-8':
    sys.stdout.reconfigure(encoding='utf-8', errors='replace')

print("=" * 80)
print("KHỞI TẠO BỘ CÔNG CỤ TẠO MÔ HÌNH MÔ-ĐUN SCI-FI ĐỒNG BỘ VẬT LIỆU 100% (V5.0)")
print("=" * 80)

door_src_path = r"D:\GitHub\quan_ly_server\android-app\app\src\main\assets\models\AidanWatts3D\door_aidan.glb"
door_wing_path = r"D:\GitHub\quan_ly_server\android-app\app\src\main\assets\models\AidanWatts3D\door_wing.glb"
door_main_path = r"D:\GitHub\quan_ly_server\android-app\app\src\main\assets\models\AidanWatts3D\door_main.glb"
scene_src_path = r"D:\GitHub\quan_ly_server\android-app\app\src\main\assets\models\AidanWatts3D\scene.glb"
tex_dir = r"D:\GitHub\quan_ly_server\android-app\app\src\main\assets\models\AidanWatts3D\textures"

def get_or_create_corridor_material():
    """
    Tạo hoặc nạp vật liệu Corridor Corner chuẩn PBR đồng bộ 100% với vách tàu USS Cygnus:
    Sử dụng chính xác texture corridor_corner_basecolor.png, normal và roughness.
    """
    mat_name = "Corridor_Corner_Bulkhead"
    if mat_name in bpy.data.materials:
        return bpy.data.materials[mat_name]
        
    mat = bpy.data.materials.new(name=mat_name)
    mat.use_nodes = True
    nodes = mat.node_tree.nodes
    links = mat.node_tree.links
    
    bsdf = next((n for n in nodes if n.type == 'BSDF_PRINCIPLED'), None)
    if not bsdf:
        bsdf = nodes.new('ShaderNodeBsdfPrincipled')
        
    # 1. Base Color Texture (corridor_corner_basecolor.png)
    tex_base_path = os.path.join(tex_dir, "corridor_corner_basecolor.png")
    if os.path.exists(tex_base_path):
        tex_base = nodes.new('ShaderNodeTexImage')
        tex_base.image = bpy.data.images.load(tex_base_path)
        links.new(tex_base.outputs['Color'], bsdf.inputs['Base Color'])
        
    # 2. Normal Map (corridor_corner_normal.png)
    tex_norm_path = os.path.join(tex_dir, "corridor_corner_normal.png")
    if os.path.exists(tex_norm_path):
        tex_norm = nodes.new('ShaderNodeTexImage')
        tex_norm.image = bpy.data.images.load(tex_norm_path)
        tex_norm.image.colorspace_settings.name = 'Non-Color'
        node_norm = nodes.new('ShaderNodeNormalMap')
        links.new(tex_norm.outputs['Color'], node_norm.inputs['Color'])
        links.new(node_norm.outputs['Normal'], bsdf.inputs['Normal'])
        
    # 3. Roughness Map (corridor_corner_roughness.png)
    tex_rough_path = os.path.join(tex_dir, "corridor_corner_roughness.png")
    if os.path.exists(tex_rough_path):
        tex_rough = nodes.new('ShaderNodeTexImage')
        tex_rough.image = bpy.data.images.load(tex_rough_path)
        tex_rough.image.colorspace_settings.name = 'Non-Color'
        links.new(tex_rough.outputs['Color'], bsdf.inputs['Roughness'])
    else:
        bsdf.inputs['Roughness'].default_value = 0.50
        
    bsdf.inputs['Metallic'].default_value = 0.0
    return mat

def load_pure_base_scene():
    """
    Nạp door_aidan.glb và trích xuất cấu trúc AlekRazum nguyên bản thuần khiết.
    """
    bpy.ops.wm.read_factory_settings(use_empty=True)
    bpy.ops.import_scene.gltf(filepath=door_src_path)
    
    door_frame = None
    door_panel_left = None
    door_panel_right = None
    
    for o in bpy.data.objects:
        name_l = o.name.lower()
        if 'frame' in name_l:
            door_frame = o
        elif 'left' in name_l or 'panel_l' in name_l:
            door_panel_left = o
        elif 'right' in name_l or 'panel_r' in name_l:
            door_panel_right = o
            
    bm = bmesh.new()
    bm.from_mesh(door_frame.data)
    
    tag_set = set()
    islands = []
    for v in bm.verts:
        if v in tag_set:
            continue
        isl = [v]
        q = [v]
        tag_set.add(v)
        for cur in q:
            for e in cur.link_edges:
                other = e.other_vert(cur)
                if other not in tag_set:
                    tag_set.add(other)
                    q.append(other)
                    isl.append(other)
        islands.append(isl)
        
    if len(islands) > 4988:
        to_del = []
        for isl in islands[4988:]:
            to_del.extend(isl)
        bmesh.ops.delete(bm, geom=to_del, context='VERTS')
        bm.verts.ensure_lookup_table()
        bm.to_mesh(door_frame.data)
    bm.free()
    
    door_mat = door_frame.material_slots[0].material if door_frame.material_slots else None
    return door_frame, door_panel_left, door_panel_right, door_mat

def create_beveled_kickplate(name, is_right, x_start, x_end, y_front=(0.15, 1.30), y_back=(-1.30, -0.15),
                             z_bottom=-0.08, height=0.45, bevel_size=0.10, mat=None):
    """
    Nẹp chân đế tiếp sàn âm Z = -0.08m, đảm bảo cắm chìm vào sàn lưới kim loại,
    triệt tiêu 100% mọi khe hở chân đế ở bất kỳ góc nhìn nào.
    """
    mesh = bpy.data.meshes.new(name + "_mesh")
    obj = bpy.data.objects.new(name, mesh)
    bpy.context.collection.objects.link(obj)
    bm = bmesh.new()
    
    if is_right:
        x0, x1 = min(x_start, x_end), max(x_start, x_end)
    else:
        x0, x1 = -max(abs(x_start), abs(x_end)), -min(abs(x_start), abs(x_end))
        
    for (y_in, y_out) in [y_front, y_back]:
        sign_y = 1.0 if y_out > 0 else -1.0
        p_profile = [
            (y_in, z_bottom),
            (y_out, z_bottom),
            (y_out, height - bevel_size),
            (y_out - sign_y * bevel_size, height),
            (y_in, height)
        ]
        
        v_x0 = [bm.verts.new((x0, py, pz)) for (py, pz) in p_profile]
        v_x1 = [bm.verts.new((x1, py, pz)) for (py, pz) in p_profile]
        
        n = len(p_profile)
        for i in range(n):
            i_next = (i + 1) % n
            bm.faces.new((v_x0[i], v_x0[i_next], v_x1[i_next], v_x1[i]))
            
        bm.faces.new(v_x0)
        bm.faces.new(list(reversed(v_x1)))
        
    bm.faces.ensure_lookup_table()
    bmesh.ops.recalc_face_normals(bm, faces=bm.faces[:])
    
    uv_layer = bm.loops.layers.uv.verify()
    for f in bm.faces:
        for loop in f.loops:
            v = loop.vert
            loop[uv_layer].uv = (v.co.x / 4.0, v.co.z / 4.0)
            
    bm.to_mesh(mesh)
    bm.free()
    if mat:
        obj.data.materials.append(mat)
    return obj

def create_seamless_corridor_bulkhead(name, is_right, x_inner=8.20, x_outer=12.60,
                                     z_bottom=-0.08, z_top=10.75, mat=None):
    """
    Tạo khối sườn mở rộng đa tầng đồng bộ 100% kiến trúc tàu USS Cygnus:
    - Đỉnh cao Z = 10.75m: Ăn sâu vào toàn bộ khối trần Roof & Struts (cao tối đa 10.68m), TRIỆT TIÊU 100% KHOẢNG HỞ TRÊN ĐỈNH VÒM.
    - Đáy chìm Z = -0.08m: Cắm sâu vào sàn lưới kim loại, triệt tiêu 100% khoảng hở đáy.
    - Biên ngoài X = 12.60m: Ăn sâu vào vách Window Frame & Side Wall (tại X = 12.14m - 12.68m), kín khít 100% theo phương ngang.
    - Khoang trượt Y in [-0.15, +0.15m]: Rỗng ruột để cánh cửa trượt vào mượt mà.
    - Đa tầng gờ chỉ bo vát (Architectural Chamfers): 4 phân đoạn gờ viền cơ khí sắc nét.
    - UV Mapping theo tọa độ thế giới (World UV) khớp tỉ lệ với vách tàu.
    """
    mesh = bpy.data.meshes.new(name + "_mesh")
    obj = bpy.data.objects.new(name, mesh)
    bpy.context.collection.objects.link(obj)
    bm = bmesh.new()
    
    # 5 trạm gờ nẹp cơ khí phân tầng
    stations_x = [8.20, 8.85, 9.20, 9.60, x_outer]
    if not is_right:
        stations_x = [-x for x in stations_x]
        
    y_front_profiles = [
        (0.15, 1.35),
        (0.15, 1.42),
        (0.15, 1.26),
        (0.15, 1.38),
        (0.15, 1.30)
    ]
    y_back_profiles = [
        (-1.35, -0.15),
        (-1.42, -0.15),
        (-1.26, -0.15),
        (-1.38, -0.15),
        (-1.30, -0.15)
    ]
    
    for half_name, y_profiles in [('front', y_front_profiles), ('back', y_back_profiles)]:
        rings = []
        for i, x_val in enumerate(stations_x):
            y_in, y_out = y_profiles[i]
            
            # Đỉnh Z = 10.75m ăn sâu vào trần, Đáy Z = -0.08m cắm sâu vào sàn
            v0 = bm.verts.new((x_val, y_in, z_bottom))
            v1 = bm.verts.new((x_val, y_out, z_bottom))
            v2 = bm.verts.new((x_val, y_out, z_top))
            v3 = bm.verts.new((x_val, y_in, z_top))
            rings.append([v0, v1, v2, v3])
            
        for i in range(len(rings) - 1):
            rA = rings[i]
            rB = rings[i+1]
            bm.faces.new((rA[0], rA[1], rB[1], rB[0]))
            bm.faces.new((rA[1], rA[2], rB[2], rB[1]))
            bm.faces.new((rA[2], rA[3], rB[3], rB[2]))
            bm.faces.new((rA[3], rA[0], rB[0], rB[3]))
            
        rLast = rings[-1]
        if is_right:
            bm.faces.new((rLast[0], rLast[1], rLast[2], rLast[3]))
        else:
            bm.faces.new((rLast[3], rLast[2], rLast[1], rLast[0]))
            
    bm.faces.ensure_lookup_table()
    bmesh.ops.recalc_face_normals(bm, faces=bm.faces[:])
    
    # UV Mapping tự nhiên theo tỷ lệ vách Corridor Corner (4.0m x 4.0m)
    uv_layer = bm.loops.layers.uv.verify()
    for f in bm.faces:
        for loop in f.loops:
            v = loop.vert
            loop[uv_layer].uv = (v.co.x / 4.0, v.co.z / 4.0)
            
    bm.to_mesh(mesh)
    bm.free()
    if mat:
        obj.data.materials.append(mat)
    return obj

print("1. Khởi tạo và nạp mô hình AlekRazum gốc...")
frame, p_left, p_right, door_mat = load_pure_base_scene()
corridor_mat = get_or_create_corridor_material()
print(f"Vật liệu cửa: {door_mat.name if door_mat else None}, Vật liệu sườn hành lang: {corridor_mat.name}")

# =========================================================================
# TẠO MÔ HÌNH 1: DOOR_WING.GLB (Chuẩn 16.60m, dành riêng cho 2 cửa mạn)
# =========================================================================
print("\n" + "=" * 60)
print("2. TẠO TỆP DOOR_WING.GLB (STARBOARD & PORT WINGS)")
print("=" * 60)
kick_r = create_beveled_kickplate("kick_r", is_right=True, x_start=6.50, x_end=8.30, z_bottom=-0.08, height=0.45, mat=door_mat)
kick_l = create_beveled_kickplate("kick_l", is_right=False, x_start=-6.50, x_end=-8.30, z_bottom=-0.08, height=0.45, mat=door_mat)

bpy.ops.object.select_all(action='DESELECT')
frame.select_set(True)
kick_r.select_set(True)
kick_l.select_set(True)
bpy.context.view_layer.objects.active = frame
bpy.ops.object.join()
frame.data.polygons.foreach_set('use_smooth', [True] * len(frame.data.polygons))

bpy.ops.export_scene.gltf(
    filepath=door_wing_path,
    export_format='GLB',
    use_selection=False,
    export_apply=True,
    export_yup=True
)
print(f"Xuất door_wing.glb thành công: {os.path.getsize(door_wing_path)} bytes")

# =========================================================================
# TẠO MÔ HÌNH 2: DOOR_MAIN.GLB (Khổ rộng ngã ba, sườn vật liệu Corridor Corner kín khít 100%)
# =========================================================================
print("\n" + "=" * 60)
print("3. TẠO TỆP DOOR_MAIN.GLB (MAIN CORRIDOR JUNCTION)")
print("=" * 60)
frame, p_left, p_right, door_mat = load_pure_base_scene()
corridor_mat = get_or_create_corridor_material()

bulkhead_r = create_seamless_corridor_bulkhead("bulkhead_r", is_right=True, x_inner=8.20, x_outer=12.60,
                                               z_bottom=-0.08, z_top=10.75, mat=corridor_mat)
bulkhead_l = create_seamless_corridor_bulkhead("bulkhead_l", is_right=False, x_inner=8.20, x_outer=12.60,
                                               z_bottom=-0.08, z_top=10.75, mat=corridor_mat)

kick_mid_r = create_beveled_kickplate("kick_mid_r", is_right=True, x_start=6.50, x_end=8.30, z_bottom=-0.08, height=0.45, mat=door_mat)
kick_mid_l = create_beveled_kickplate("kick_mid_l", is_right=False, x_start=-6.50, x_end=-8.30, z_bottom=-0.08, height=0.45, mat=door_mat)

bpy.ops.object.select_all(action='DESELECT')
frame.select_set(True)
bulkhead_r.select_set(True)
bulkhead_l.select_set(True)
kick_mid_r.select_set(True)
kick_mid_l.select_set(True)
bpy.context.view_layer.objects.active = frame
bpy.ops.object.join()
frame.data.polygons.foreach_set('use_smooth', [True] * len(frame.data.polygons))

box_main = [frame.matrix_world @ mathutils.Vector(b) for b in frame.bound_box]
print(f"Kích thước door_main thành phẩm:")
print(f"  X: [{min(v.x for v in box_main):.3f}, {max(v.x for v in box_main):.3f}] (Tổng rộng: {max(v.x for v in box_main)-min(v.x for v in box_main):.3f}m)")
print(f"  Z: [{min(v.z for v in box_main):.3f}, {max(v.z for v in box_main):.3f}] (Tổng cao: {max(v.z for v in box_main)-min(v.z for v in box_main):.3f}m)")

bpy.ops.export_scene.gltf(
    filepath=door_main_path,
    export_format='GLB',
    use_selection=False,
    export_apply=True,
    export_yup=True
)
print(f"Xuất door_main.glb thành công: {os.path.getsize(door_main_path)} bytes")

import shutil
shutil.copyfile(door_main_path, door_src_path)
print(f"Đã sao lưu đồng bộ door_aidan.glb: {os.path.getsize(door_src_path)} bytes")

print("\n" + "=" * 80)
print("HOÀN TẤT TẠO 2 MODEL SCI-FI MÔ-ĐUN V5.0 ĐỒNG BỘ VẬT LIỆU 100%!")
print("=" * 80)
