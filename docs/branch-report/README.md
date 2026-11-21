# Hồ sơ báo cáo — voice tiếng Việt

## Phạm vi, nguồn và phân công

Nhánh này được dựng trên main `2fe21556654885236fe3851ac0e420804b225865`.
Tỷ lệ live/review, model và bằng chứng tỷ lệ thuộc phần chung; delta chỉ thêm
voice. Toàn bộ triển khai voice lấy từ mốc đã công bố `e4d8477`, được lưu nguyên
ở `codex/archive-voice-and-probability-e4d8477`. Bản vá voice giữ checksum
`92bda6c2ea1be33b41391e375a1e30afd89509e64a65fa263286c147d6b1b88c`.

## Thiết kế

Mic/resample 16 kHz → Vosk grammar theo thế cờ; trường hợp cần thiết gọi
PhoWhisper local có VAD/context → chuẩn hóa/parser tiếng Việt → giao với nước
hợp lệ của vị trí hiện tại → điều khiển bàn/server. Không dùng LLM để hiểu câu.
Kết quả ASR không tự tạo quyền đi; phải đúng lượt, hợp lệ và còn đúng revision.
Chế độ đi ngay chỉ thực hiện khi xác định duy nhất một nước, lỗi/mơ hồ có phản
hồi. Mất kết nối/kết thúc ván dừng mic và vô hiệu kết quả đang chờ.

Source ở `lila/ui/voice/`, hook vòng đời trong `lila/ui/round/src/ctrl.ts`;
ASR/recorder ở `services/voice/`; harness/model installer ở `scripts/voice*`.
Docker dùng patch tái lập trên upstream ghim trong `upstream-lock.json`.
Monorepo `lila/` cũng có mã voice, nhưng vẫn cần dựng ASR và route proxy.

## Ưu điểm so với tính năng có sẵn

| Có sẵn / mốc trước | Bổ sung | Phạm vi của nhận định |
|---|---|---|
| Lichess có voice nhưng chưa có tiếng Việt ở mốc upstream | Tên quân/ô, từ–đến, nhập thành/phong cấp và biến thể B/D | Tăng phạm vi câu nói được hỗ trợ, không bảo đảm mọi giọng |
| Vosk đơn thuần dễ nhầm âm ngắn | PhoWhisper local, grammar và nước hợp lệ | Có bằng chứng audio cụ thể; chưa đủ để khái quát cộng đồng |
| Người chơi xác nhận liên tục | Đi ngay nếu nước duy nhất và hợp lệ | Giảm thao tác, không mặc định đo được thời gian tiết kiệm |
| Chỉ nhìn transcript | Recorder + kiểm tra nước server/bot | Kiểm tra đủ luồng thay vì chỉ ASR |

## Bằng chứng, giới hạn và cách chạy

Log và kết quả chi tiết từng lần chạy được lưu local.
Giữ nguyên cách chia dữ liệu và provenance; nhiều lần nghe lại cùng audio là
regression, không phải test set mới. Không cộng số test các branch thành nghiệm
thu toàn nhóm. Giọng/mic/tiếng ồn/mạng ảnh hưởng nhận dạng và độ trễ.

[README gốc](../../README.md) có lệnh chạy, URL và model; audio riêng của người
dùng vẫn bị ignore. Không công bố việc chạy lại benchmark người thật/LLM hoặc
đánh giá học cờ trong lần tổ chức Git này.

Tài liệu tổng hợp với hỗ trợ Codex. Khi viết báo cáo cần trích revision, nguồn
dữ liệu, điều kiện và giới hạn thay vì chỉ nêu con số cao nhất.
