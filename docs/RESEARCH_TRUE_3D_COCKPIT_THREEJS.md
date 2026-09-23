# BÁO CÁO NGHIÊN CỨU CHUYÊN SÂU: THIẾT KẾ KHÔNG GIAN BUỒNG LÁI & NHÂN VẬT BẰNG 3D ENGINE THỰC SỰ

## Dự án: Buồng Lái Không Gian 3D & Trợ Lý Ảo Tiểu Bảo Bảo (`android-app`)

- **Ngày thực hiện**: 15/09/2026
- **Tác giả**: Principal 3D Graphics & Game Engine Architect
- **Mục tiêu**: Xóa bỏ hoàn toàn việc dùng ảnh 2D làm nền không gian buồng lái; tự tay lập trình kiến tạo toàn bộ không gian buồng lái 3D (3D Geometry, 3D Mesh, 3D Lights, 3D Rune Platform) kết hợp mô hình nhân vật nữ 3D (.glb) có tư thế tự nhiên và hỗ trợ xoay 360 độ hoàn hảo trên mọi thiết bị.

---

## 1. NGUYÊN NHÂN GỐC RỄ (ROOT CAUSE ANALYSIS)

Người dùng đã gửi ảnh chụp thực tế từ màn hình máy tính và chỉ ra 3 thiếu sót chí mạng:

1. **Không gian buồng lái vẫn là ảnh phẳng 2D**:
   - Dù nhân vật đã là 3D nhưng không gian buồng lái phía sau vẫn bị gán bằng `background: url('...cockpit_background_clean.webp')`. Người dùng nhìn thấy rõ đây là một tấm ảnh dẹp chứ không phải không gian 3D được code dựng hình thật.
2. **Nhân vật bị lỗi T-Pose và chưa khớp dáng đứng concept**:
   - Model 3D mặc định đang ở tư thế dang 2 tay ngang (T-Pose), làm mất đi vẻ đẹp tự nhiên và thần thái duyên dáng của nhân vật AI trong concept art.
3. **Thao tác xoay chuột bị nuốt trên LDPlayer**:
   - Cử chỉ chuột trên WebView nhúng trong Jetpack Compose bị chặn bởi hệ thống touch dispatcher của Android nếu không bật cờ `requestDisallowInterceptTouchEvent(true)`.
   - Cần bổ sung cả thanh điều khiển góc xoay (Rotation Slider) và các nút xoay nhanh trực quan để người dùng có thể xoay 360 độ một cách dễ dàng và mượt mà nhất.

---

## 2. GIẢI PHÁP KIẾN TRÚC: TRUE 3D ENGINE SCENE (THREE.JS + GLTF LOADER)

Thay vì dùng ảnh tĩnh, chúng ta sử dụng **Three.js Engine** (Engine 3D WebGL mạnh nhất thế giới) để lập trình dựng nên toàn bộ không gian buồng lái 3D thời gian thực:

### 2.1. Không Gian Buồng Lái 3D Hình Học Thực Thụ (3D Geometry & Lights)

1. **Bầu Trời Vũ Trụ 3D (3D Deep Space Starfield)**:
   - Hệ thống 1500 hạt sao 3D (`THREE.Points`) phân bố trong không gian hình cầu bán kính 50m.
   - Quả cầu hành tinh 3D quay chậm ngoài cửa sổ không gian (`THREE.SphereGeometry`).
2. **Khung Vòm Buồng Lái Phi Thuyền 3D (3D Cockpit Structural Mesh)**:
   - Dựng các thanh dầm kim loại vòm buồng lái bằng hình học 3D (`THREE.CylinderGeometry` & `THREE.BoxGeometry`).
   - Hai dải đèn neon trần 3D phát sáng thực sự với 2 nguồn sáng điểm `THREE.PointLight(0x00e5ff, 2.5, 12)` rọi ánh sáng xanh cyan từ trần tàu xuống không gian buồng lái.
3. **Bệ Sàn Kim Loại Rune 3D (3D Cybernetic Rune Platform)**:
   - Bệ đứng lục giác 3D kim loại (`THREE.CylinderGeometry(radius, radius, height, 6)`).
   - Biểu tượng rune và các đường mạch điện cybernetic phát sáng pulsing glow (dao động sóng năng lượng) với nguồn sáng `THREE.PointLight(0x00ffea, 2.0, 6)` chiếu từ dưới chân nhân vật lên cơ thể 3D.
4. **Hệ Thống Màn Hình 3D Hologram Trôi Nổi**:
   - Màn hình radar 3D quét mục tiêu 360 độ liên tục.
   - Bảng telemetry "United AI System" bay lơ lửng trong không gian tại các toạ độ $(x, y, z)$ thực.

### 2.2. Nhân Vật Nữ 3D: Đặt Xương & Cử Động Tự Nhiên (Humanoid Rigging & Idle Dynamic)

- Bằng cách can thiệp vào các khớp xương humanoid (`J_Bip_L_UpperArm`, `J_Bip_R_UpperArm`, `J_Bip_L_LowerArm`, `J_Bip_R_LowerArm`), chúng ta hạ hai cánh tay xuống khép nhẹ dọc thân người, tạo dáng đứng tự nhiên, thanh tú (Natural Standing Pose).
- Tích hợp nhịp thở ngực sinh học (`J_Bip_C_Chest`) dao động hình sin nhịp nhàng theo thời gian thực.

### 2.3. Điều Khiển Xoay 360 Độ Đa Kênh (Multi-Channel 360 Rotation)

- **Kênh 1: Cảm ứng chuột / vuốt tay trực tiếp (OrbitControls)**: Kéo chuột trái xoay tự do 360 độ quanh nhân vật, lăn chuột zoom in/out, kéo chuột phải pan camera.
- **Kênh 2: Thanh trượt xoay 360° (Interactive Rotation Slider)**: Kéo trượt từ 0° đến 360° xoay mượt mà tức thì.
- **Kênh 3: Các nút xoay nhanh**: "Chính Diện (0°)", "Góc Nghiêng (90°)", "Sau Lưng (180°)", "Tự Động Xoay (Auto-Rotate)".
- **Fix lỗi nuốt sự kiện cảm ứng trên Android**: `parent.requestDisallowInterceptTouchEvent(true)`.

---

## 3. LỘ TRÌNH TRIỂN KHAI

1. Cập nhật `Cockpit3DView.kt` bổ sung cơ chế Touch Intercept Bypass cho WebView.
2. Xây dựng trang `cockpit_3d.html` hoàn chỉnh bằng Three.js: Dựng không gian buồng lái 3D, sàn rune 3D, đèn 3D, nạp mô hình 3D, chỉnh pose tự nhiên và tích hợp OrbitControls.
3. Biên dịch APK và kiểm định thực tế thô qua MCP LDPlayer bằng các thao tác kéo xoay 360 độ và chụp ảnh màn hình ở các góc độ.
