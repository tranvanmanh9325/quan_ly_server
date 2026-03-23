# Quản Lý Server (Dashboard)

Dự án quản lý server với giao diện Frontend (React/Vite) và Backend (Java/Spring Boot). Hệ thống được container hóa hoàn toàn bằng Docker.

---

## 🚀 Hướng Dẫn Deploy (Thủ công)
Nếu bạn muốn chạy dự án này trên môi trường Local hoặc Server mới:
1. Đảm bảo đã cài đặt `Docker` và `Docker Compose`.
2. Tạo file `.env` mẫu trong thư mục `backend/` theo định dạng `application.properties`.
3. Chạy lệnh:
   ```bash
   docker compose up -d --build
   ```
4. Truy cập Frontend tại port `5173` và Backend tại port `8080`.

---

## ⚡ Hướng Dẫn Thiết Lập CI/CD Tự Động (GitHub Actions)
Dự án này đã được cấu hình tự động Deploy (CI/CD) thông qua **GitHub Actions Self-Hosted Runner**. Bất cứ khi nào có code mới Push lên nhánh `main`, Server sẽ tự động Pull code và Rebuild hệ thống mà không cần thao tác tay.

### Bước 1: Lấy thông tin cài đặt Runner từ GitHub
1. Truy cập vào trang GitHub của dự án này.
2. Chọn thanh tab **Settings** ➡️ Chọn **Actions** (ở cột bên trái) ➡️ Chọn **Runners**.
3. Bấm vào nút màu xanh lá **"New self-hosted runner"**.
4. Ở phần *Runner image*, chọn hệ điều hành **Linux** và Architecture là **x64**.

### Bước 2: Cài đặt Runner trên Server (Ubuntu/Debian)
Mở Terminal SSH kết nối vào Server của bạn và chạy CÁC MẪU LỆNH Y HỆT như GitHub vừa cấp cho bạn ở màn hình trên.
*(Tham khảo luồng các lệnh cơ bản GitHub cấp dưới đây)*

**1. Tải Runner về server:**
```bash
# Tạo folder actions-runner và di chuyển vào đó
mkdir actions-runner && cd actions-runner

# Tải gói cài đặt mới nhất từ Github
curl -o actions-runner-linux-x64-x.x.x.tar.gz -L https://github.com/actions/runner/releases/download/vX.X.X/actions-runner-linux-x64-x.x.x.tar.gz

# Giải nén
tar xzf ./actions-runner-linux-x64-x.x.x.tar.gz
```

**2. Cấu hình liên kết với Repository:**
```bash
# Chạy script cấu hình kèm Token (Copy y hệt lệnh GitHub cấp)
./config.sh --url https://github.com/TEN_CUA_BAN/quan_ly_server --token XXXXXXXXXX
```
*Lưu ý: Khi Command hỏi tên runner, thư mục hay label... **HÃY BẤM ENTER LIÊN TỤC** để xài cấu hình mặc định.*

### Bước 3: Cài đặt Agent chạy ngầm (QUAN TRỌNG)
Để Runner luôn phiên trực tiếp kể cả khi bạn tắt cửa sổ Terminal SSH hay khởi động lại server, bạn PHẢI cài đặt nó dưới dạng System Service:
Vẫn đang ở trong thư mục `actions-runner`, chạy 2 lệnh sau:
```bash
sudo ./svc.sh install
sudo ./svc.sh start
```

### Bước 4: Kiểm tra trạng thái
- Mở lại trang Github ở **Settings > Actions > Runners**, nếu thấy Runner hiển thị chữ màu xanh lá cây **"Idle"**, tức là bạn đã setup thành công!
- Từ giờ, mỗi lần thao tác `git push origin main`, bạn có thể theo dõi tiến độ Server tự Build tại tab **Actions** trên GitHub.