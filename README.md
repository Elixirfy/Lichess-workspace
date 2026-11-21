# Lichess workspace — bản dùng chung của nhóm

Phần **ưu thế Trắng–Đen** dùng chung của nhóm có thanh ngang lúc chơi và thanh
dọc khi xem lại ván standard. Cả hai dùng [Win% của Lichess](https://lichess.org/page/accuracy),
làm tròn số nguyên với tổng đúng 100%. Tooltip ghi nguồn của số hiển thị.
Đây là ưu thế từ thế cờ. Độ chính xác dự đoán kết quả theo trình độ người chơi
chưa được kiểm chứng cho cộng đồng local.

Phần **giọng nói tiếng Việt Vosk + PhoWhisper, recorder và đi ngay** nằm ở
[nhánh voice riêng](https://github.com/trantrien1/Lichess-workspace/tree/codex/vietnamese-voice-input).
Nhánh đó kế thừa phần tỷ lệ từ main; không sở hữu một bản tỷ lệ khác. Voice
input có sẵn của upstream không bị xóa khỏi main.

Giữ nguyên bình luận tiếng Việt Nano/ba BLV và phần việc đã có của nhóm.
[Thiết kế bình luận](docs/binh-luan-vien-tieng-viet.md),
[cài dịch vụ](services/commentary/README.md). Các nhánh coach/WebMCP tiếp tục
độc lập; lần tách này không tự nhập chúng vào main.

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

## Cách tính và dữ liệu

Live nhận lịch sử, trạng thái, rating và đồng hồ từ Lila. Worker Stockfish có
giới hạn CPU, hàng đợi và cache, dùng chung công việc theo vị trí. Giao diện
lấy điểm Stockfish theo góc nhìn Trắng và giới hạn ở ±1.000 cp, kể cả dự báo
chiếu hết. Công thức là `100 / (1 + exp(-0.00368208 × cp))`. Sau khi làm tròn
Trắng, Đen bằng 100 trừ phần Trắng. [Mã WinPercent của Lichess](https://github.com/lichess-org/scalachess/blob/master/core/src/main/scala/eval.scala).

API giữ WDL và dự báo thử nghiệm theo trình độ ở các trường riêng. Khi thiếu
điểm engine hợp lệ, giao diện dùng `W + D/2`, `B + D/2` từ engine WDL và ghi
nguồn trong tooltip. Phản hồi cũ bị loại sau nước mới, takeback và reconnect.
Kết quả chính thức được ưu tiên. Ván hủy có trạng thái riêng.

Khi xem lại, thanh dọc áp dụng cùng công thức cho **nước đang chọn**. Engine
và độ sâu khác nhau có thể cho điểm khác ngay trên cùng một thế. Chỉ điểm cuối
ván của nhánh chính gốc lấy kết quả chính thức. Lật bàn giữ đúng tỷ lệ của từng
màu. Giao diện mobile một cột ẩn thanh dọc theo upstream.

[Model card và giới hạn](reports/human-v1/model-card.md),
[thanh dọc review](reports/acceptance/replay-advantage/README.md),
[quyền và lifecycle](openspec/changes/live-win-probability/specs/win-probability/spec.md).

## Kiểm thử và bằng chứng

[Báo cáo tách phần chung](reports/acceptance/shared-probability/README.md) ghi
kiểm tra trên source main và đối chiếu hai nhánh. Các báo cáo acceptance cũ giữ
revision/điều kiện ban đầu; một số chứa kiểm tra tương thích voice trong lịch
sử, không có nghĩa main chứa ASR hoặc các lệnh audio đó chạy được trên main.

```powershell
.\scripts\dev.ps1 check -Full
.\scripts\dev.ps1 browser -HumanPlayers
node scripts/ai-smoke.mjs --probability --signed-in
```

Lệnh full không thay bằng incremental test. Không khẳng định test/build mới
đã qua chỉ dựa trên log cũ. Vị trí code chính: `lila/ui/lib/src/ceval/wdl.ts`,
`lila/ui/round/src/winProbability.ts`, `lila/ui/analyse/src/advantage.ts`,
`lila/app/controllers/Round.scala`, `services/prediction/`,
`patches/lila-win-probability.patch`. [Nhiệm vụ và evidence](openspec/changes/live-win-probability/tasks.md).
