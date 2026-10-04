#!/usr/bin/env python3
import sys, os, argparse, cv2
import numpy as np

DEFAULT_FRAMES = [146, 258, 371, 483, 596, 708, 821, 933, 1046, 1158, 1271, 1383, 1496, 1608, 1721, 1832]

def generate_collage(video_path: str, output_path: str, layout: str = '2x8', frame_indices = None):
    cap = cv2.VideoCapture(video_path)
    if not cap.isOpened():
        raise RuntimeError(f'Cannot open video: {video_path}')
    
    total_frames = int(cap.get(cv2.CAP_PROP_FRAME_COUNT))
    fps = cap.get(cv2.CAP_PROP_FPS) or 29.98
    
    if frame_indices is None:
        if total_frames == 1945:
            frame_indices = DEFAULT_FRAMES
        else:
            step = total_frames / 17.0
            frame_indices = [int(round((i + 1) * step)) for i in range(16)]
            
    print(f'Generating collage for {video_path} with frames: {frame_indices}')
    
    # Target tile resolution: Parent uses 256 x 455
    tile_w, tile_h = 256, 455
    
    tiles = []
    for f_idx in frame_indices:
        cap.set(cv2.CAP_PROP_POS_FRAMES, min(f_idx, total_frames - 1))
        ret, frame = cap.read()
        if not ret or frame is None:
            tile = np.zeros((tile_h, tile_w, 3), dtype=np.uint8)
        else:
            tile = cv2.resize(frame, (tile_w, tile_h), interpolation=cv2.INTER_AREA)
        # Optional: draw frame number overlay in tiny corner
        # cv2.putText(tile, f'f{f_idx}', (5, 20), cv2.FONT_HERSHEY_SIMPLEX, 0.5, (0, 255, 0), 1, cv2.LINE_AA)
        tiles.append(tile)
    cap.release()
    
    if layout == '4x4':
        rows = [np.hstack(tiles[r*4:(r+1)*4]) for r in range(4)]
        collage = np.vstack(rows)
    else: # 2x8 (Parent standard)
        row1 = np.hstack(tiles[:8])
        row2 = np.hstack(tiles[8:16])
        collage = np.vstack([row1, row2])
        
    os.makedirs(os.path.dirname(os.path.abspath(output_path)), exist_ok=True)
    cv2.imwrite(output_path, collage)
    print(f'Collage saved to {output_path} (shape: {collage.shape})')
    return collage

if __name__ == '__main__':
    parser = argparse.ArgumentParser(description='Tự động tạo ảnh collage 16 ô chuẩn Parent check để đối chiếu visual')
    parser.add_argument('--input', '-i', required=True, help='Đường dẫn video đầu vào')
    parser.add_argument('--output', '-o', required=True, help='Đường dẫn ảnh collage đầu ra')
    parser.add_argument('--layout', '-l', choices=['2x8', '4x4'], default='2x8', help='Bố cục collage (mặc định 2x8 chuẩn Parent)')
    args = parser.parse_args()
    generate_collage(args.input, args.output, args.layout)
