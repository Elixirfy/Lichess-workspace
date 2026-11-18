# Danh mục README các branch — 18/11/2026

Repo có sáu branch remote tại thời điểm khảo sát. Mỗi branch có `README.md` ở gốc dẫn tới `docs/branch-report/README.md` của chính nhánh. Chọn nhánh đúng trước khi trích mô tả hoặc kết quả cho báo cáo.

| Branch | Nội dung chính / khác biệt cần nhớ | README |
|---|---|---|
| `main` | Tổng quan bản tích hợp Lichess workspace | [Đọc tài liệu](https://github.com/trantrien1/Lichess-workspace/blob/main/docs/branch-report/README.md) |
| `codex/live-win-probability` | Dự đoán kết quả ván cờ theo thời gian thực | [Đọc tài liệu](https://github.com/trantrien1/Lichess-workspace/blob/codex/live-win-probability/docs/branch-report/README.md) |
| `feature/commentary` | Bình luận viên tiếng Việt — phiên bản Piper | [Đọc tài liệu](https://github.com/trantrien1/Lichess-workspace/blob/feature/commentary/docs/branch-report/README.md) |
| `feature/commentary-v2` | Bình luận viên tiếng Việt v2 — ba giọng và VieNeu Nano | [Đọc tài liệu](https://github.com/trantrien1/Lichess-workspace/blob/feature/commentary-v2/docs/branch-report/README.md) |
| `feature/webmcp` | WebMCP: tìm kiếm ván và trả dữ liệu phân tích cho agent | [Đọc tài liệu](https://github.com/trantrien1/Lichess-workspace/blob/feature/webmcp/docs/branch-report/README.md) |
| `codex/vietnamese-voice-input` | Giọng nói tiếng Việt, ưu thế live và thanh dọc xem lại | [Đọc tài liệu](https://github.com/trantrien1/Lichess-workspace/blob/codex/vietnamese-voice-input/docs/branch-report/README.md) |

## Trạng thái khác nhau giữa các nhánh

- `main`: prediction ba lớp/spectator và bình luận v2 Nano; chưa có WebMCP hoặc các cập nhật của voice branch. Provider Gemini TTS đã bị bỏ khỏi app bình luận.
- `codex/live-win-probability`: mốc prediction ba lớp cho spectator, có model người chơi thử nghiệm; không có voice/direct moves hiện tại.
- `codex/vietnamese-voice-input`: Vosk + PhoWhisper, tiếng Việt đi ngay; ưu thế W+D/2, B+D/2 cho cả hai người chơi và người xem. Hai dòng chú thích live đã chuyển vào tooltip. Thanh dọc xem lại dùng cùng phép tính cho node đang chọn.
- `feature/commentary`: bản bình luận Piper một preset; endpoint LLM diễn đạt là tùy chọn.
- `feature/commentary-v2`: ba BLV và Nano; còn tùy chọn Gemini TTS trong snapshot này. Không đồng nhất TTS với LLM suy luận nội dung.
- `feature/webmcp`: hai tool search/analyse trả JSON; cần search backend/index hoặc PGN có eval tương ứng. Không tự tạo lời giải thích sau trận bằng LLM.

## Quy tắc dùng bằng chứng

README mỗi nhánh chỉ rõ revision, kiểm thử đã lưu, kiểm thử chưa chạy lại, giới hạn dữ liệu và tính năng chưa tích hợp. Ưu điểm về thiết kế không phải benchmark chất lượng người dùng. Không ghép các số của từng branch thành kết quả nghiệm thu tích hợp trên main.

Lần cập nhật tài liệu kiểm tra đường dẫn, revision, phạm vi diff và liên kết trong các README mới; không chạy build/model cho cả sáu branch. Việc bỏ hai dòng chú thích trên nhánh voice được kiểm thử riêng và có bằng chứng trong `reports/acceptance/compact-advantage/` của nhánh đó.
