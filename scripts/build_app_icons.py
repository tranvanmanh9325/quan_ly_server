import os
from PIL import Image, ImageDraw, ImageFilter

def build_icons():
    workspace = r"d:\GitHub\quan_ly_server"
    brain_dir = r"C:\Users\Kirito\.gemini\antigravity\brain\57e9609b-334b-4c9a-b119-d76e78bb890d"
    src_path = os.path.join(brain_dir, "tieu_bao_bao_icon_1789534295152.jpg")
    res_dir = os.path.join(workspace, "android-app", "app", "src", "main", "res")
    
    src = Image.open(src_path).convert("RGBA")
    
    # 1. Master Canvas (1080 x 1080)
    CANVAS_SIZE = 1080
    VIEWPORT_SIZE = 720
    SAFE_ZONE_DIAMETER = 620 # 62dp safe zone for generous breathing room
    
    scale = SAFE_ZONE_DIAMETER / 910.0
    new_w = int(src.width * scale)
    new_h = int(src.height * scale)
    resized_src = src.resize((new_w, new_h), Image.Resampling.LANCZOS)
    
    # Background #010206
    bg = Image.new("RGBA", (CANVAS_SIZE, CANVAS_SIZE), (1, 2, 6, 255))
    
    # Halo center alignment
    halo_cx = int(515 * scale)
    halo_cy = int(521 * scale)
    paste_x = CANVAS_SIZE // 2 - halo_cx
    paste_y = CANVAS_SIZE // 2 - halo_cy + 8 # Optical center nudge
    
    # Full composite canvas (1080 x 1080)
    full_composite = bg.copy()
    full_composite.paste(resized_src, (paste_x, paste_y), resized_src)
    
    # Foreground canvas with soft alpha falloff outside the halo
    halo_rad = int(465 * scale) + 16
    mask_canvas = Image.new("L", (CANVAS_SIZE, CANVAS_SIZE), 0)
    mdraw = ImageDraw.Draw(mask_canvas)
    mdraw.ellipse((CANVAS_SIZE//2 - halo_rad, CANVAS_SIZE//2 - halo_rad + 8,
                   CANVAS_SIZE//2 + halo_rad, CANVAS_SIZE//2 + halo_rad + 8), fill=255)
    mask_canvas = mask_canvas.filter(ImageFilter.GaussianBlur(14))
    
    fg_canvas = Image.new("RGBA", (CANVAS_SIZE, CANVAS_SIZE), (0, 0, 0, 0))
    fg_canvas.paste(full_composite, (0, 0))
    fg_canvas.putalpha(mask_canvas)
    
    # Viewport crop (720 x 720) for Legacy Icons
    viewport = full_composite.crop((180, 180, 900, 900))
    vw, vh = viewport.size
    
    # Legacy Squircle / Rounded Rectangle
    legacy_square = Image.new("RGBA", (vw, vh), (0, 0, 0, 0))
    sq_mask = Image.new("L", (vw, vh), 0)
    sdraw = ImageDraw.Draw(sq_mask)
    sdraw.rounded_rectangle((0, 0, vw, vh), radius=150, fill=255)
    legacy_square.paste(viewport, (0, 0))
    legacy_square.putalpha(sq_mask)
    
    # Legacy Round (Circle)
    legacy_round = Image.new("RGBA", (vw, vh), (0, 0, 0, 0))
    c_mask = Image.new("L", (vw, vh), 0)
    cdraw = ImageDraw.Draw(c_mask)
    cdraw.ellipse((0, 0, vw, vh), fill=255)
    legacy_round.paste(viewport, (0, 0))
    legacy_round.putalpha(c_mask)
    
    # High-Res Store Icon (512 x 512)
    store_icon = full_composite.resize((512, 512), Image.Resampling.LANCZOS)
    store_path = os.path.join(brain_dir, "ic_launcher_store_512.png")
    store_icon.save(store_path)
    print(f"Saved store icon: {store_path}")
    
    # Density Buckets: (folder_name, icon_size, fg_size)
    densities = [
        ("mipmap-mdpi", 48, 108),
        ("mipmap-hdpi", 72, 162),
        ("mipmap-xhdpi", 96, 216),
        ("mipmap-xxhdpi", 144, 324),
        ("mipmap-xxxhdpi", 192, 432),
    ]
    
    for folder, icon_size, fg_size in densities:
        target_dir = os.path.join(res_dir, folder)
        os.makedirs(target_dir, exist_ok=True)
        
        # 1. ic_launcher.png (legacy rounded square)
        sq_out = legacy_square.resize((icon_size, icon_size), Image.Resampling.LANCZOS)
        sq_out.save(os.path.join(target_dir, "ic_launcher.png"))
        
        # 2. ic_launcher_round.png (legacy round)
        rd_out = legacy_round.resize((icon_size, icon_size), Image.Resampling.LANCZOS)
        rd_out.save(os.path.join(target_dir, "ic_launcher_round.png"))
        
        # 3. ic_launcher_foreground.png (adaptive foreground)
        fg_out = fg_canvas.resize((fg_size, fg_size), Image.Resampling.LANCZOS)
        fg_out.save(os.path.join(target_dir, "ic_launcher_foreground.png"))
        
        print(f"Generated {folder}: ic_launcher={icon_size}x{icon_size}, fg={fg_size}x{fg_size}")

if __name__ == "__main__":
    build_icons()
