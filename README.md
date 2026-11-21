# Lichess workspace — bản dùng chung của nhóm

Trên `main`, giao diện hiển thị ưu thế Trắng/Đen khi chơi và khi xem lại
các ván cờ tiêu chuẩn (standard).
Số phần trăm được tính từ đánh giá Stockfish theo công thức Win% của Lichess.

Tính năng [chơi cờ bằng giọng nói tiếng Việt](https://github.com/trantrien1/Lichess-workspace/tree/codex/vietnamese-voice-input)
được phát triển trên nhánh riêng, dùng Vosk và PhoWhisper để nhận dạng lệnh.

Giữ nguyên bình luận tiếng Việt Nano/ba BLV và phần việc đã có của nhóm.
[Thiết kế bình luận](docs/binh-luan-vien-tieng-viet.md),
[cài dịch vụ](services/commentary/README.md). Các nhánh coach/WebMCP tiếp tục
độc lập; lần tách này không tự nhập chúng vào main.

Phần **mục tiêu hằng ngày và chuỗi ngày luyện tập** cho người chơi đặt số bài
tập và số ván mỗi ngày tại `/account/daily-goal`. Đủ mục tiêu thì chuỗi ngày
tăng, bỏ lỡ một ngày thì chuỗi về 0; thẻ tiến độ nằm trên trang chủ.
[Tổng quan và kiểm thử](docs/daily-goal/README.md),
[kiến trúc](docs/daily-goal/kien-truc.md), [giao diện](docs/daily-goal/giao-dien.md),
[luồng xử lý](docs/daily-goal/luong-xu-ly.md).

[README phục vụ viết báo cáo](docs/branch-report/README.md) có kiến trúc,
ưu điểm so với Lichess sẵn có, kết quả và giới hạn.
[Danh mục branch](docs/branches/README.md).

## Hai cách chạy source

Repo có `lila/` được vendor trực tiếp và workflow Docker ghim source tại
`infra/lila-docker/repos/lila`. Phần tỷ lệ đã cập nhật ở **cả hai**; không dùng
nhầm đường dựng. Các patch bình luận cũ có phạm vi/base riêng, không áp chồng
tất cả một cách tùy ý.

Docker local cần Docker Desktop Linux containers, Git, PowerShell. Node host
dùng để chuẩn bị model browser và chạy smoke; `uv` dùng cho model/test Python.

```powershell
.\scripts\dev.ps1 bootstrap
.\scripts\dev.ps1 start
node scripts/prepare-analysis-engine.mjs
```

Web: [http://localhost:8080](http://localhost:8080). Chỉ cổng loopback được mở;
prediction/Mongo/Redis/broker nằm trong mạng Docker. `start` khởi động broker và
worker chơi AI trước web; các image được ghim trong `upstream-lock.json`.
`stop` giữ database/cache. Cấu hình này dành cho local.

Với monorepo `lila/`, cài dependency và cấu hình Lila theo môi trường của nhóm:

```sh
node scripts/prepare-analysis-engine.mjs --checkout lila
cd lila
pnpm install --frozen-lockfile
./ui/build
./lila.sh --server --batch stage
```

README bình luận từng nhắc launcher `lichess-local`/`LOCAL.md` chưa có trong
tree; không mặc định clone repo đã có launcher đó. Worker bình luận được cấu
hình riêng theo README dịch vụ; chạy Docker prediction không tự bật Nano.

## Ưu thế Trắng/Đen được tính thế nào?

Giao diện lấy điểm Stockfish theo góc nhìn Trắng, tính bằng centipawn (cp),
rồi áp dụng công thức sau. [Công thức Win% của Lichess](https://lichess.org/page/accuracy)

```text
Trắng = round(100 / (1 + exp(-0.00368208 × cp)))
Đen   = 100 − Trắng
```

Điểm `cp` được giới hạn trong khoảng −1.000 đến +1.000 nên Win% nằm trong khoảng
2–98%. Dự báo chiếu hết cũng dùng ngưỡng này. Khi đã có kết quả xác định, giao
diện hiển thị theo kết quả đó.

Thanh ngang cập nhật theo thế cờ mới nhất cho cả người chơi và người xem.
Khi xem lại, thanh dọc hiển thị ưu thế tại nước đang chọn. Nếu thiếu điểm
cp/mate, giao diện dùng WDL (thắng/hòa/thua) của engine, tính nửa điểm cho hòa
và ghi nguồn trong tooltip.
Khi mất kết nối hoặc đổi thế cờ, kết quả cũ được bỏ để chờ đánh giá mới.

Đây là cách đọc ưu thế theo engine. Trình độ người chơi và cấp độ bot chưa
được đưa vào phép tính hiển thị.

[Model card và giới hạn](reports/human-v1/model-card.md).
[Tài liệu tính năng](docs/branch-report/README.md) mô tả kiến trúc,
cách hiển thị khi chơi và khi xem lại ván đấu.

## Kiểm thử

Các lệnh dưới đây chạy lại kiểm tra trên source hiện tại. Kết quả chạy thử
được lưu local và không đưa vào Git.

```powershell
.\scripts\dev.ps1 check -Full
.\scripts\dev.ps1 browser -HumanPlayers
node scripts/ai-smoke.mjs --probability --signed-in
```

Lệnh full không thay bằng incremental test. Không khẳng định test/build mới
đã qua chỉ dựa trên log cũ. Vị trí code chính: `lila/ui/lib/src/ceval/wdl.ts`,
`lila/ui/round/src/winProbability.ts`, `lila/ui/analyse/src/advantage.ts`,
`lila/app/controllers/Round.scala`, `services/prediction/`,
`patches/lila-win-probability.patch`.
