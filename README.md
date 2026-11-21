# Lichess — chơi cờ bằng giọng nói tiếng Việt

Branch `codex/vietnamese-voice-input` chỉ bổ sung **voice tiếng Việt** trên nền
[commit chung `2fe2155`](https://github.com/trantrien1/Lichess-workspace/commit/2fe21556654885236fe3851ac0e420804b225865).
Tỷ lệ live và thanh ưu thế xem lại thuộc `main`, được kế thừa nguyên vẹn.
Code bình luận Nano/ba BLV của nhóm cũng được giữ nguyên từ main.

Lịch sử kết hợp cũ được giữ tại
[nhánh lưu trữ](https://github.com/trantrien1/Lichess-workspace/tree/codex/archive-voice-and-probability-e4d8477).
Branch này được dựng lại từ main để phần chênh lệch chỉ có voice, cấu hình ASR,
recorder, fixture và bằng chứng của tính năng đó.

## Tính năng

Mic trên web → Vosk với grammar theo thế cờ → PhoWhisper local khi cần → parser
tiếng Việt → đối chiếu nước hợp lệ → đi quân. **Chưa dùng LLM**. Chế độ đi ngay
không yêu cầu xác nhận khi câu lệnh xác định duy nhất một nước; câu sai/không hợp
lệ có phản hồi. Không tự chọn nước khi còn mơ hồ. Âm thanh cũ bị loại sau đổi
lượt, mất kết nối hoặc kết thúc ván.

Hỗ trợ tên quân, ô đích, từ–đến, ăn quân, nhập thành, phong cấp; nhiều cách đọc
cột B/D và dạng “cột hai hàng hai”. Có trang thu nguyên câu ngay trên web và
harness kiểm tra từ ASR qua parser đến nước thực nhận ở server và phản hồi bot.
Các cách đọc còn phụ thuộc giọng, tiếng ồn, ngắt câu và ngữ cảnh nước hợp lệ.

| Upstream / mốc trước | Phần voice bổ sung | Lợi ích |
|---|---|---|
| Voice chưa có grammar cờ tiếng Việt | Từ vựng và nhiều cấu trúc câu tiếng Việt | Dùng lời nói quen thuộc |
| Chỉ một kết quả ASR | Vosk + PhoWhisper/VAD local và ràng buộc thế cờ | Có đường xử lý câu khó mà không cần LLM |
| Xác nhận mỗi nước | Đi ngay với nước hợp lệ, duy nhất | Giảm thao tác khi chơi |
| Khó tái hiện lỗi người đọc | Recorder và báo cáo audio/server/bot | Giữ bằng chứng và đo lại |

## Chạy Docker local

Dùng Docker Desktop Linux containers, Git, PowerShell, Node và `uv`.

```powershell
.\scripts\dev.ps1 bootstrap
.\scripts\dev.ps1 start
.\scripts\voice.ps1 live
```

`live` chuẩn bị/kiểm checksum model local, bật `voice_asr`, build UI và reload
proxy. Trên bàn chơi bật microphone, chọn tiếng Việt, cấp quyền mic rồi nói.
Web: [http://localhost:8080](http://localhost:8080).
Recorder: [http://localhost:8080/voice-asr/record](http://localhost:8080/voice-asr/record).
Không phát hành audio người dùng trong `artifacts/voice-recordings/`; fixture WAV
đã công bố trong `scripts/fixtures/voice/` có nguồn/giấy phép riêng.

Source voice được cập nhật cả trong `lila/` của nhóm và
`patches/lila-vietnamese-voice.patch` cho checkout Docker đã khóa revision.
Workflow monorepo cần cấu hình proxy `/voice-asr/*` và service/model tương ứng;
chỉ build UI không tự khởi động PhoWhisper.

## Kiểm thử và báo cáo

```powershell
.\scripts\voice.ps1 check
.\scripts\voice.ps1 browser
```

[Hồ sơ tính năng](docs/branch-report/README.md) ghi kiến trúc, ưu điểm và
giới hạn. Log, ảnh và kết quả từng lần chạy được lưu local; chạy lại
các lệnh kiểm thử để đánh giá source hiện tại.

Phần dùng chung: [danh mục branch](docs/branches/README.md),
[model card xác suất](reports/human-v1/model-card.md). Không sửa công thức,
model hay bản vá tỷ lệ trong delta của nhánh voice.
