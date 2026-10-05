import cv2, numpy as np

cap = cv2.VideoCapture("test/tmpy8evxmno.mp4")

sub_defs = [
    (1,  56, 109, 440, 600, 110, 460, "an_sang"),
    (2, 110, 272, 510, 640, 100, 470, "soan_hop_dong"),
    (3, 273, 462, 440, 650,  90, 490, "di_gap_khach"),
    (4, 978, 1093, 470, 570,  90, 480, "mua_them_do_an"),
    (5, 1316, 1394, 450, 630,  80, 500, "tu_van_khach_xong"),
    (6, 1395, 1455, 470, 570, 100, 470, "kiem_tra_du_an"),
    (7, 1456, 1578, 460, 570,  40, 535, "tiep_tuc_di_gap_khach"),
    (8, 1579, 1745, 470, 570, 110, 440, "xong_viec_di_ve"),
]

sub_frames = {sid: [] for sid in range(1, 9)}
total = int(cap.get(cv2.CAP_PROP_FRAME_COUNT))
for f in range(total):
    ret, fr = cap.read()
    if not ret: break
    for sid, sf, ef, y1, y2, x1, x2, name in sub_defs:
        if sf <= f <= ef and (f - sf) % max(1, (ef - sf)//15) == 0:
            sub_frames[sid].append(cv2.cvtColor(fr[y1:y2, x1:x2], cv2.COLOR_BGR2GRAY))
cap.release()

k11 = cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (11, 11))
for sid, sf, ef, y1, y2, x1, x2, name in sub_defs:
    frames = sub_frames[sid]
    if len(frames) > 0:
        stack = np.array(frames, dtype=np.float32)
        var = np.var(stack, axis=0)
        mean = np.mean(stack, axis=0)
        th_mean = 165 if sid == 8 else 185
        text_core = ((var < 55) & (mean > th_mean)).astype(np.uint8) * 255
        # Dilate 2 iterations with k11 to fully swallow stroke and all drop shadows
        mask_dil = cv2.dilate(text_core, k11, iterations=2)
        out_path = f"test/round3/sub_masks/mask_sub_{sid:02d}.png"
        cv2.imwrite(out_path, mask_dil)
        print(f"Sub {sid} ({name}): active pixels = {np.sum(mask_dil > 0)}")

# Dilate title mask aggressively to engulf drop shadow
title_base = cv2.imread("test/round3/hosted_inpaint_tests/mask_k19.png", 0)
k7 = cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (7, 7))
title_dil = cv2.dilate(title_base, k7, iterations=2)
cv2.imwrite("test/round3/hosted_inpaint_tests/mask_k19_dilated.png", title_dil)
print("Aggressive dilated title mask saved!")
