# Soundman Payroll Automation

Automation gồm 2 phần chính:

1. **Bot Telegram**: hỏi thông tin ca làm và push thẳng một dòng vào `data/shifts.csv` trên GitHub qua REST API.
2. **Dashboard tĩnh**: `index.html` đọc `data/shifts.csv`, tính toán base pay + OT và hiển thị bảng/tổng hợp đẹp mắt. Deploy trực tiếp lên GitHub Pages.

## Cấu trúc repo

```
.
├── bot/                   # Mã nguồn bot Telegram
│   ├── main.py
│   ├── payroll.py         # Logic tính lương + OT
│   ├── github_client.py   # Helper commit CSV lên GitHub
│   ├── requirements.txt
│   └── .env.example
├── data/
│   └── shifts.csv         # File dữ liệu mà bot sẽ append
├── dashboard/
│   ├── app.js             # Script đọc CSV + Chart.js
│   └── styles.css
└── index.html             # Dashboard chính cho GitHub Pages
```

## Thiết lập bot Telegram

1. Cài đặt Python 3.10+ và tạo virtualenv.

   ```bash
   cd bot
   python3 -m venv .venv
   source .venv/bin/activate
   pip install -r requirements.txt
   ```

2. Tạo file `.env` dựa trên `.env.example`:

   - `TELEGRAM_TOKEN`: token từ BotFather.
   - `TELEGRAM_ALLOWED_CHAT_IDS`: danh sách chat id được phép nhập (cách nhau bởi dấu phẩy). Lấy chat id bằng cách nhắn bot `@userinfobot`.
   - `GITHUB_TOKEN`: Personal Access Token có quyền `repo`.
   - `GITHUB_REPO`: ví dụ `username/soundman-payroll`.
   - `GITHUB_FILE_PATH`: mặc định `data/shifts.csv`.
   - `GITHUB_BRANCH`: nhánh cần ghi (thường là `main`).

   > Lưu ý: file `.env` đã được thêm vào `.gitignore`, vui lòng **không commit** token lên repo. Nếu lỡ push, cần xoá file khỏi lịch sử và regenerate token mới.

3. Chạy bot:

   ```bash
   python bot/main.py
   ```

   Bot sẽ hướng dẫn lần lượt: ngày → địa điểm → loại sự kiện → người trực → giờ kết thúc. Sau khi xác nhận sẽ append dòng mới vào `data/shifts.csv` với các cột: ngày, địa điểm, base pay, OT (theo block 15 phút, mỗi block = `50.000đ`).

4. Deploy bot trên service tuỳ thích (server nhà, Railway, Render...). Đừng quên cấu hình biến môi trường y hệt `.env`.

## Dashboard GitHub Pages

- `index.html` + `dashboard/app.js` dùng Chart.js và PapaParse (qua CDN) nên không cần build step.
- Khi bot (hoặc bạn) push phiên bản mới của `data/shifts.csv`, GitHub Pages cập nhật site luôn.
- Để publish:
  1. Commit toàn bộ repo lên GitHub.
2. Trong Settings → Pages → chọn Source = `Deploy from a branch`, Branch = `main`, Folder = `/`.
3. Sau vài phút dashboard sẽ sẵn sàng tại `https://<username>.github.io/<repo>/`.

### Dashboard public dùng để đối chiếu OT

- `public.html` + `dashboard/public.js` chỉ đọc dữ liệu từ `data/shifts_public.csv` (được tạo từ script `scripts/export_public_csv.py`) nên không lộ thông tin nhạy cảm.
- Chạy `python scripts/export_public_csv.py` (hoặc GitHub Action tự động hoá) mỗi khi cần cập nhật dữ liệu public rồi push file `data/shifts_public.csv`.
- Trang public nằm tại `https://<username>.github.io/<repo>/public.html`, bạn có thể gửi link này cho đối tác để họ xem giờ kết thúc, OT và tổng lương.

### Đồng bộ dữ liệu & chạy dashboard local

Bot ghi dữ liệu trực tiếp lên GitHub nên trước khi mở dashboard local bạn cần kéo file CSV mới về máy:

```bash
# tải dữ liệu từ GitHub (dùng token trong bot/.env)
python scripts/sync_data.py

# chạy server tĩnh để xem dashboard
python3 -m http.server 8000
```

`sync_data.py` đọc biến môi trường giống bot (ưu tiên `bot/.env`) và tải `data/shifts.csv` mới nhất từ GitHub API. Sau đó mở trình duyệt tới `http://localhost:8000` và refresh mỗi khi cần xem số liệu.

## Quy trình nhập liệu hằng ngày

1. Điện thoại mở Telegram, gõ `/newshift`.
2. Điền thông tin theo hướng dẫn bot.
3. Bot gửi request lên GitHub API để cập nhật `data/shifts.csv`.
4. Dashboard tự động phản ánh dữ liệu mới (có thể reload trang để xem số liệu mới nhất).

## Kiểm thử nhanh

- Sử dụng `data/shifts.csv` để nhập tay vài dòng mẫu rồi mở `index.html` trực tiếp bằng Live Server / `npx serve` để kiểm tra UI.
- Log bot có thể chạy `python bot/main.py` rồi chat với bot riêng để đảm bảo GitHub commit thành công.

## Gợi ý mở rộng

- Thêm slash command `/summary` trong bot để trả về báo cáo tuần/tháng ngay trong Telegram.
- Gắn GitHub Action kiểm tra định dạng CSV hoặc copy file sang folder `docs/` nếu muốn dùng chế độ Pages khác.
- Nếu dữ liệu nhiều, chuyển sang lưu JSON per-entry và nightly job hợp nhất.

## Ghi chú bảo mật

- Token Telegram/GitHub phải được lưu trong `.env` cục bộ, không commit lên repo. Nếu bạn đã push token trước đó, cần xoá file khỏi lịch sử và **regenerate** token mới trên Telegram/GitHub để tránh bị lạm dụng.
- Nếu muốn mở repo public để dùng GitHub Pages, hãy đảm bảo `bot/.env` không tồn tại trong lịch sử hoặc đã được xoá sạch bằng `git filter-repo`/`BFG`.***
