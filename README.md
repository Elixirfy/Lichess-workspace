# Lichess - chơi cờ bằng giọng nói tiếng Việt

Nhánh `codex/vietnamese-voice-input` bổ sung cách đi quân bằng lời nói tiếng Việt
cho bản Lichess tự host. Người chơi bật mic, đọc nước đi và hệ thống thực hiện
nếu câu lệnh xác định được một nước hợp lệ.

## Cách hoạt động

Vosk nhận dạng tiếng nói ngay trên trình duyệt, với bộ câu lệnh được tạo từ
các nước có thể đi ở thế cờ hiện tại. Khi Vosk chưa xử lý được câu nói, âm thanh
được chuyển tới PhoWhisper chạy trên máy local để nhận dạng tiếp.

Kết quả nhận dạng được phân tích thành tên quân, ô xuất phát, ô đích và các
thông tin như ăn quân hoặc phong cấp. Hệ thống đối chiếu lại với nước hợp lệ
trước khi gửi lên server. Nếu chỉ còn một lựa chọn, quân đi ngay; câu chưa rõ
hoặc không hợp lệ sẽ có thông báo để người chơi đọc lại hoặc chọn nước.

Phần nhận dạng hiện dùng Vosk, PhoWhisper và bộ phân tích lệnh cờ, chưa tích hợp LLM.

## Một số cách nói

```text
Tốt trắng e hai e bốn
Mã nhảy lên ép ba
Tốt bê hai tới bê bốn
Tốt từ cột đê hàng hai đến cột đê hàng bốn
Nhập thành ngắn
Tốt e bảy tới e tám phong cấp thành hậu
```

Nhập thành và phong cấp cần thế cờ cho phép thực hiện nước đó. Với cột B/D,
có thể đọc “bê/đê”, “bờ/dờ”, “bi/đi” hoặc dùng số cột, chẳng hạn
“cột hai hàng hai”. Nếu mic nghe nhầm âm ngắn, đọc rõ “cột bê, hàng hai”
hoặc “cột đê, hàng hai” sẽ dễ phân biệt hơn.

## Run

Cần Docker Desktop ở chế độ Linux containers, Git, PowerShell, Node.js và `uv`.
Chạy tại thư mục gốc:

```powershell
.\scripts\dev.ps1 bootstrap
.\scripts\dev.ps1 start
.\scripts\voice.ps1 live
```

Lệnh `live` chuẩn bị model, bật dịch vụ `voice_asr`, build giao diện và cập nhật
proxy. Sau đó mở [http://localhost:8080](http://localhost:8080), vào một ván đấu,
bật mic, chọn tiếng Việt và cấp quyền microphone cho trình duyệt.

Trang [thu âm mẫu](http://localhost:8080/voice-asr/record) dùng để ghi lại nguyên
câu khi cần kiểm tra lỗi nhận dạng. Bản thu riêng được lưu trong
`artifacts/voice-recordings/` trên máy local. Các file WAV có trong repo là
[dữ liệu kiểm thử CC0](scripts/fixtures/voice/README.md).

## Kiểm tra và mã nguồn

```powershell
.\scripts\voice.ps1 check
.\scripts\voice.ps1 browser
```

[Tài liệu tính năng](docs/branch-report/README.md) giải thích thiết kế,
các cách nói được hỗ trợ và hạn chế của việc nhận dạng.

- [Phía trình duyệt](lila/ui/voice/src/) xử lý mic, bộ câu lệnh và việc chọn nước.
- [Dịch vụ ASR](services/voice/) chạy PhoWhisper và trang thu âm.
- [Bản vá voice](patches/lila-vietnamese-voice.patch) dùng cho bản dựng Docker.

Nếu build trực tiếp từ `lila/`, cần cấu hình thêm dịch vụ ASR và proxy
`/voice-asr/*`.

Phần dùng chung có tài liệu phân nhánh và hồ sơ mô hình dự đoán.
[Danh mục branch](docs/branches/README.md) · [Model card xác suất](reports/human-v1/model-card.md)
