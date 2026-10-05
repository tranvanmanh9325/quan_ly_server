import bpy
import bmesh
import mathutils
import sys
import os
import shutil

if sys.stdout.encoding != 'utf-8':
    sys.stdout.reconfigure(encoding='utf-8', errors='replace')

print("=" * 80)
print("KHỞI TẠO BỘ CÔNG CỤ TẠO MÔ HÌNH CỬA SCI-FI HOÀN MỸ - CHUẨN SENIOR (V6.0)")
print("=" * 80)

# Đường dẫn nguồn chuẩn gốc 100% của tác giả AlekRazum
verified_src_path = r"D:\GitHub\quan_ly_server\.agents\teamwork_preview_explorer_m1_1\verified_door_aidan.glb"
door_aidan_path = r"D:\GitHub\quan_ly_server\android-app\app\src\main\assets\models\AidanWatts3D\door_aidan.glb"
door_wing_path = r"D:\GitHub\quan_ly_server\android-app\app\src\main\assets\models\AidanWatts3D\door_wing.glb"
door_main_path = r"D:\GitHub\quan_ly_server\android-app\app\src\main\assets\models\AidanWatts3D\door_main.glb"

def load_verified_base():
    """
    Nạp mô hình gốc chuẩn từ verified_door_aidan.glb:
    - door_frame (89k verts)
    - door_panel_left (11k verts)
    - door_panel_right (11k verts)
    - Vật liệu chuẩn sci_fi_door
    """
    bpy.ops.wm.read_factory_settings(use_empty=True)
    bpy.ops.import_scene.gltf(filepath=verified_src_path)
    
    door_frame = None
    door_panel_left = None
    door_panel_right = None
    
    for o in bpy.data.objects:
        nl = o.name.lower()
        if 'frame' in nl:
            door_frame = o
        elif 'left' in nl or 'panel_l' in nl:
            door_panel_left = o
        elif 'right' in nl or 'panel_r' in nl:
            door_panel_right = o
            
    door_mat = door_frame.material_slots[0].material if door_frame and door_frame.material_slots else None
    
    # Thay thế texture Albedo bằng texture Trắng sứ USS Cygnus đồng bộ 100%
    porcelain_tex_path = r"D:\GitHub\quan_ly_server\android-app\app\src\main\assets\models\AidanWatts3D\textures\door_albedo_porcelain.png"
    if door_mat and door_mat.use_nodes and os.path.exists(porcelain_tex_path):
        bsdf = next((n for n in door_mat.node_tree.nodes if n.type == 'BSDF_PRINCIPLED'), None)
        if bsdf and bsdf.inputs['Base Color'].is_linked:
            for l in bsdf.inputs['Base Color'].links:
                if l.from_node.type == 'TEX_IMAGE':
                    new_img = bpy.data.images.load(porcelain_tex_path)
                    l.from_node.image = new_img
                    print(f"Đã cập nhật Base Color sang texture Trắng sứ: {new_img.name} ({new_img.size[:]})")
                    
    print(f"Loaded verified base: frame={door_frame.name}, panels=({door_panel_left.name}, {door_panel_right.name}), mat={door_mat.name if door_mat else None}")
    return door_frame, door_panel_left, door_panel_right, door_mat

def build_beveled_kickplate(name, is_right, x_start, x_end, mat, z_bottom=-0.08, height=0.45, bevel=0.10):
    """
    Nẹp chân đế tiếp sàn phẳng, chìm âm Z = -0.08m triệt tiêu mọi khe hở chân đế.
    UV mapping vào vùng trắng sứ chân cửa của sci_fi_door.
    """
    mesh = bpy.data.meshes.new(name + "_mesh")
    obj = bpy.data.objects.new(name, mesh)
    bpy.context.collection.objects.link(obj)
    bm = bmesh.new()
    
    if is_right:
        x0, x1 = min(x_start, x_end), max(x_start, x_end)
    else:
        x0, x1 = -max(abs(x_start), abs(x_end)), -min(abs(x_start), abs(x_end))
        
    y_ranges = [(0.18, 1.35), (-1.35, -0.18)]
    for (y_in, y_out) in y_ranges:
        sign_y = 1.0 if y_out > 0 else -1.0
        p_profile = [
            (y_in, z_bottom),
            (y_out, z_bottom),
            (y_out, height - bevel),
            (y_out - sign_y * bevel, height),
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
    
    # UV Map cùng tên UVMap với khung cửa gốc
    uv_layer = bm.loops.layers.uv.new("UVMap")
    for f in bm.faces:
        for loop in f.loops:
            v = loop.vert
            # Map vào vùng trắng sứ phẳng của texture (U in [0.20, 0.35], V in [0.15, 0.25])
            norm_u = 0.20 + (v.co.x - x0) / max(0.01, (x1 - x0)) * 0.15
            norm_v = 0.15 + (v.co.z - z_bottom) / max(0.01, (height - z_bottom)) * 0.10
            loop[uv_layer].uv = (norm_u, norm_v)
            
    bm.to_mesh(mesh)
    bm.free()
    if mat:
        obj.data.materials.append(mat)
    return obj

def build_architectural_bulkhead(name, is_right, mat, x_inner=8.20, x_outer=12.60, z_bottom=-0.08, z_top=10.75):
    """
    Tạo khối sườn mở rộng cơ khí đa tầng tiếp nối mượt mà từ khung cửa ra sát vách tàu:
    - Kín khít 100% đỉnh trần (Z = 10.75m), đáy sàn (Z = -0.08m), vách bên (X = ±12.60m).
    - Rỗng lòng khoang trượt ở giữa (Y in [-0.20, 0.20m]) cho cánh cửa lọt vào.
    - 5 tầng gờ vát mechanical chamfers tinh xảo.
    - Dùng DUY NHẤT vật liệu sci_fi_door đồng bộ 100% màu sắc và độ bóng với khung cửa!
    - Kênh UVMap duy nhất, map vào vùng kim loại trắng sứ cao cấp của texture albedo.
    """
    mesh = bpy.data.meshes.new(name + "_mesh")
    obj = bpy.data.objects.new(name, mesh)
    bpy.context.collection.objects.link(obj)
    bm = bmesh.new()
    
    # 5 trạm gờ nẹp cơ khí phân tầng
    stations_x = [8.20, 8.80, 9.40, 10.20, 11.20, x_outer]
    if not is_right:
        stations_x = [-x for x in stations_x]
        
    y_front_profiles = [
        (0.20, 1.35),
        (0.20, 1.45),
        (0.20, 1.28),
        (0.20, 1.42),
        (0.20, 1.32),
        (0.20, 1.38)
    ]
    y_back_profiles = [
        (-1.35, -0.20),
        (-1.45, -0.20),
        (-1.28, -0.20),
        (-1.42, -0.20),
        (-1.32, -0.20),
        (-1.38, -0.20)
    ]
    
    for half_name, y_profiles in [('front', y_front_profiles), ('back', y_back_profiles)]:
        rings = []
        for i, x_val in enumerate(stations_x):
            y_in, y_out = y_profiles[i]
            v0 = bm.verts.new((x_val, y_in, z_bottom))
            v1 = bm.verts.new((x_val, y_out, z_bottom))
            v2 = bm.verts.new((x_val, y_out, z_top))
            v3 = bm.verts.new((x_val, y_in, z_top))
            rings.append([v0, v1, v2, v3])
            
        for i in range(len(rings) - 1):
            rA = rings[i]
            rB = rings[i+1]
            bm.faces.new((rA[0], rA[1], rB[1], rB[0])) # Mặt đáy sàn
            bm.faces.new((rA[1], rA[2], rB[2], rB[1])) # Mặt trước/sau lộ ngoài
            bm.faces.new((rA[2], rA[3], rB[3], rB[2])) # Mặt đỉnh trần
            bm.faces.new((rA[3], rA[0], rB[0], rB[3])) # Mặt trong khe túi trượt
            
        rLast = rings[-1]
        if is_right:
            bm.faces.new((rLast[0], rLast[1], rLast[2], rLast[3])) # Mặt hông ngoài cùng áp sát tường
        else:
            bm.faces.new((rLast[3], rLast[2], rLast[1], rLast[0]))
            
    bm.faces.ensure_lookup_table()
    bmesh.ops.recalc_face_normals(bm, faces=bm.faces[:])
    
    # UV Map đặt tên CHÍNH XÁC là "UVMap"
    uv_layer = bm.loops.layers.uv.new("UVMap")
    x_min_span = min(stations_x)
    x_max_span = max(stations_x)
    span_len = max(0.01, x_max_span - x_min_span)
    
    for f in bm.faces:
        for loop in f.loops:
            v = loop.vert
            # Map chuẩn xác vào vùng sơn trắng sứ tinh khiết của texture cửa:
            # U in [0.15, 0.40], V in [0.45, 0.85]
            fx = (v.co.x - x_min_span) / span_len
            fz = (v.co.z - z_bottom) / (z_top - z_bottom)
            u_coord = 0.15 + fx * 0.25
            v_coord = 0.45 + fz * 0.40
            loop[uv_layer].uv = (u_coord, v_coord)
            
    bm.to_mesh(mesh)
    bm.free()
    if mat:
        obj.data.materials.append(mat)
    return obj

# =========================================================================
# 1. TẠO TỆP DOOR_WING.GLB (CHO 2 CỬA MẠN STARBOARD & PORT)
# =========================================================================
print("\n" + "=" * 60)
print("1. TẠO DOOR_WING.GLB (CỬA MẠN STARBOARD & PORT)")
print("=" * 60)
frame, p_left, p_right, door_mat = load_verified_base()

kick_r = build_beveled_kickplate("kick_r", is_right=True, x_start=6.50, x_end=8.30, mat=door_mat)
kick_l = build_beveled_kickplate("kick_l", is_right=False, x_start=-6.50, x_end=-8.30, mat=door_mat)

bpy.ops.object.select_all(action='DESELECT')
frame.select_set(True)
kick_r.select_set(True)
kick_l.select_set(True)
bpy.context.view_layer.objects.active = frame
bpy.ops.object.join()
frame.data.polygons.foreach_set('use_smooth', [True] * len(frame.data.polygons))

# Đảm bảo chỉ có 1 material slot duy nhất
while len(frame.material_slots) > 1:
    frame.active_material_index = len(frame.material_slots) - 1
    bpy.ops.object.material_slot_remove()

bpy.ops.export_scene.gltf(
    filepath=door_wing_path,
    export_format='GLB',
    use_selection=False,
    export_apply=True,
    export_yup=True
)
print(f"-> Xuất door_wing.glb thành công: {os.path.getsize(door_wing_path)} bytes")

# =========================================================================
# 2. TẠO TỆP DOOR_MAIN.GLB (CHO CỬA CHÍNH NGÃ BA ĐUÔI TÀU)
# =========================================================================
print("\n" + "=" * 60)
print("2. TẠO DOOR_MAIN.GLB (CỬA CHÍNH NGÃ BA ĐUÔI TÀU)")
print("=" * 60)
frame, p_left, p_right, door_mat = load_verified_base()

bulkhead_r = build_architectural_bulkhead("bulkhead_r", is_right=True, mat=door_mat, x_inner=8.20, x_outer=12.60)
bulkhead_l = build_architectural_bulkhead("bulkhead_l", is_right=False, mat=door_mat, x_inner=8.20, x_outer=12.60)
kick_mid_r = build_beveled_kickplate("kick_mid_r", is_right=True, x_start=6.50, x_end=8.30, mat=door_mat)
kick_mid_l = build_beveled_kickplate("kick_mid_l", is_right=False, x_start=-6.50, x_end=-8.30, mat=door_mat)

bpy.ops.object.select_all(action='DESELECT')
frame.select_set(True)
bulkhead_r.select_set(True)
bulkhead_l.select_set(True)
kick_mid_r.select_set(True)
kick_mid_l.select_set(True)
bpy.context.view_layer.objects.active = frame
bpy.ops.object.join()
frame.data.polygons.foreach_set('use_smooth', [True] * len(frame.data.polygons))

# Đảm bảo chỉ có 1 material slot duy nhất là sci_fi_door
while len(frame.material_slots) > 1:
    frame.active_material_index = len(frame.material_slots) - 1
    bpy.ops.object.material_slot_remove()

# Kiểm tra lại kích thước khung thành phẩm
box_main = [frame.matrix_world @ mathutils.Vector(b) for b in frame.bound_box]
xs = [v.x for v in box_main]
zs = [v.z for v in box_main]
print(f"Kích thước door_main thành phẩm:")
print(f"  X: [{min(xs):.3f}, {max(xs):.3f}] (Tổng rộng: {max(xs)-min(xs):.3f}m)")
print(f"  Z: [{min(zs):.3f}, {max(zs):.3f}] (Tổng cao: {max(zs)-min(zs):.3f}m)")

bpy.ops.export_scene.gltf(
    filepath=door_main_path,
    export_format='GLB',
    use_selection=False,
    export_apply=True,
    export_yup=True
)
print(f"-> Xuất door_main.glb thành công: {os.path.getsize(door_main_path)} bytes")

# Đồng bộ file dự phòng door_aidan.glb
shutil.copyfile(door_main_path, door_aidan_path)
print(f"-> Đã đồng bộ door_aidan.glb: {os.path.getsize(door_aidan_path)} bytes")

print("\n" + "=" * 80)
print("XUẤT MÔ HÌNH V6.0 HOÀN TOÀN THÀNH CÔNG!")
print("=" * 80)
