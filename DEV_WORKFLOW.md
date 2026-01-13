# Quy trình test nhanh (không cần chờ GitHub Pages)

1. **Đồng bộ dữ liệu mới nhất**
   ```bash
   ./scripts/dev_sync.sh
   ```
   Script này sẽ
   - tải `data/shifts.csv` mới nhất từ GitHub (dùng token trong `bot/.env`)
   - tạo lại `data/shifts_public.csv` để dashboard public dùng.

2. **Chạy server local**
   ```bash
   npx live-server  # hoặc python3 -m http.server
   ```
   Sau đó mở:
   - `http://localhost:8080/index.html` (dashboard nội bộ)
   - `http://localhost:8080/public.html` (dashboard public)

   Với Live Server, mỗi khi bạn chỉnh HTML/CSS/JS/CSV, trang sẽ auto reload → thấy kết quả ngay, không phải chờ GitHub Pages deploy.

3. **Khi mọi thứ ổn định**
   - Commit & push như bình thường
   - GitHub Actions sẽ export CSV public và Pages sẽ cập nhật site online (mất vài phút, nhưng bạn đã kiểm tra trước qua local nên không phải đợi để xem kết quả).
