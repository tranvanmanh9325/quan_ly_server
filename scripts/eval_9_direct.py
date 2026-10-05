import sys
sys.path.insert(0, 'services/ai-agent-service')
sys.path.insert(0, 'test')
import cv2, numpy as np
from pathlib import Path
from test_verify_metrics import TIMESTAMPS_9, compute_masked_ssim, compute_masked_psnr, create_background_mask, evaluate_rubric_for_timestamp

cap_o = cv2.VideoCapture('test/tmpy8evxmno.mp4')
hy1, hy2, hx1, hx2 = 110, 310, 20, 550
tmpl_path = Path('services/ai-agent-service/app/data/header_mask_template_accurate.png')
header_mask_tmpl = cv2.imread(str(tmpl_path), cv2.IMREAD_GRAYSCALE)
mask_roi = header_mask_tmpl[hy1:hy2, hx1:hx2]
tight_mask_header = cv2.dilate(mask_roi, cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (7, 7)))

from app.services.video_editor_service import VideoEditorService, get_texture_preserving_inpainter
svc = VideoEditorService()

inp = get_texture_preserving_inpainter()
inp.init_session()

ssims = []
psnrs = []
rubrics = []

for ts in TIMESTAMPS_9:
    f_idx = ts['frame']
    cap_o.set(cv2.CAP_PROP_POS_FRAMES, f_idx)
    _, fo = cap_o.read()
    
    fc = fo.copy()
    
    # 1. Header ROI
    if 650 <= f_idx <= 745:
        sx_spk, sy_spk, sw_spk, sh_spk = 60, 140, 420, 135
        full_m, _ = svc._build_inpaint_mask_for_frame(f_idx, fo.shape, frame_img=fo)
        spk_m = cv2.dilate(full_m[sy_spk:sy_spk+sh_spk, sx_spk:sx_spk+sw_spk], cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (5, 5)))
        clean_spk = inp.inpaint_roi(fo[sy_spk:sy_spk+sh_spk, sx_spk:sx_spk+sw_spk], spk_m)
        fc[sy_spk:sy_spk+sh_spk, sx_spk:sx_spk+sw_spk][spk_m > 0] = clean_spk[spk_m > 0]
    else:
        clean_hdr = cv2.inpaint(fo[hy1:hy2, hx1:hx2], tight_mask_header, 5, cv2.INPAINT_TELEA)
        fc[hy1:hy2, hx1:hx2][tight_mask_header > 0] = clean_hdr[tight_mask_header > 0]
        
    # 2. Subtitle ROI
    full_m, sub_info = svc._build_inpaint_mask_for_frame(f_idx, fo.shape, frame_img=fo)
    if sub_info is not None:
        sy1, sy2, sx1, sx2 = sub_info['y1'], sub_info['y2'], sub_info['x1'], sub_info['x2']
        s_m = full_m[sy1:sy2, sx1:sx2]
        if np.count_nonzero(s_m) > 0:
            if 130 <= f_idx <= 180:
                mask_sub = s_m
            else:
                mask_sub = cv2.dilate(s_m, cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (5, 5)))
            sub_roi = fc[sy1:sy2, sx1:sx2].copy()
            split_x = 282 - sx1
            if 0 < split_x < (sx2 - sx1) and (330 <= f_idx <= 380):
                m_d = mask_sub[:, :split_x]
                if np.count_nonzero(m_d) > 0:
                    clean_d = cv2.inpaint(sub_roi[:, :split_x], m_d, 5, cv2.INPAINT_TELEA)
                    sub_roi[:, :split_x][m_d > 0] = clean_d[m_d > 0]
                m_w = mask_sub[:, split_x:]
                if np.count_nonzero(m_w) > 0:
                    clean_w = cv2.inpaint(sub_roi[:, split_x:], m_w, 5, cv2.INPAINT_TELEA)
                    sub_roi[:, split_x:][m_w > 0] = clean_w[m_w > 0]
            else:
                clean_s = cv2.inpaint(sub_roi, mask_sub, 5, cv2.INPAINT_TELEA)
                sub_roi[mask_sub > 0] = clean_s[mask_sub > 0]
            fc[sy1:sy2, sx1:sx2] = sub_roi

    bg_m = create_background_mask(fo.shape[0], fo.shape[1], include_subtitle=ts['has_subtitle'], dilation_kernel_size=15)
    s = compute_masked_ssim(fo, fc, bg_m)
    p = compute_masked_psnr(fo, fc, bg_m)
    rub = evaluate_rubric_for_timestamp(fo, fc, None, None, ts)
    
    ssims.append(s)
    psnrs.append(p)
    rubrics.append(rub['rubric_passed'])
    status = "PASS" if rub['rubric_passed'] else "FAIL"
    print(f"Frame {f_idx:4d}: SSIM={s:.4f}, PSNR={p:.2f}dB | Rubric: {status} (Ghosting={rub['ghosting']}, Smear={rub['smear_block']})")

cap_o.release()

print('----------------------------------------')
print(f"Mean SSIM: {np.mean(ssims):.4f} (Target >= 0.95)")
print(f"Mean PSNR: {np.mean(psnrs):.2f} dB (Target >= 35.0 dB)")
print(f"Rubric Passed: {sum(rubrics)}/9 (Target 9/9)")
