# Tổng quan bản tích hợp Lichess workspace

## Thông tin phiên bản và mục đích tài liệu

- Branch: `main`.
- Mã nguồn khảo sát: [`4ee86a7fd11f81099e6f9a37fa0ca8c3cad054df`](https://github.com/trantrien1/Lichess-workspace/commit/4ee86a7fd11f81099e6f9a37fa0ca8c3cad054df).
- Ngày tổng hợp: **18/11/2026**. Tài liệu này phục vụ mô tả/so sánh trong báo cáo; không phải một benchmark mới.
- Main ở snapshot này có prediction ba lớp/spectator và bình luận v2 ba giọng với Nano. Commit mới nhất đã bỏ provider Gemini TTS khỏi app bình luận. Main chưa có module WebMCP và chưa có các cập nhật voice/direct-moves/ưu thế hai màu của nhánh codex/vietnamese-voice-input. Không đồng nhất trạng thái các feature branch với main.

## 1. Bài toán và mục tiêu

Lưu bản tích hợp để thử nghiệm các mở rộng Lichess; làm mốc đối chiếu khi viết báo cáo, giúp tách thành phần đã nhập main, thành phần chỉ ở branch và kết quả thực nghiệm có bằng chứng.

## 2. Chức năng đã có trên nhánh

Người xem ván standard có panel WDL theo model/engine trong mốc prediction hiện có. Người chơi standard có thể bật bình luận tiếng Việt và chọn Mạnh Dũng, Hữu Quân, Anh Khôi. Đây là hai luồng có quyền và nguồn dữ liệu khác nhau: không mặc định người chơi main đã được xem panel hai tỷ lệ của nhánh voice.

## 3. Kiến trúc và cách triển khai

```text
Lila/SAN chính thức → (prediction: Stockfish + human model → WDL cho người xem) và (commentary: facts/template → Nano → SSE/âm thanh cho người chơi).
```

Nhánh gồm checkout trực tiếp `lila/` và các repo chess liên quan, đồng thời còn script Docker/patch từ mốc WDL. Cần xác định đang chạy đường dựng nào; không mặc định thay `lila/` sẽ sửa checkout do `scripts/dev.ps1 bootstrap` tạo dưới `infra/lila-docker/`. Bình luận mô tả ba giọng Nano, kiểm tra stale/expiry và quyền người chơi. `services/commentary/app.py` hiện chỉ chấp nhận auto/piper/vieneu, không còn Gemini TTS như snapshot v2.

## 4. Ưu điểm so với tính năng có sẵn

| Thành phần Lichess có sẵn | Phần mở rộng đã thấy trên main | Ưu điểm và phạm vi |
|---|---|---|
| Thanh cp/mate trên analysis | Prediction WDL/human pilot trên live spectator | Thêm dự đoán ba lớp và ngữ cảnh người chơi; chưa hiệu chỉnh cho cộng đồng local |
| Theo dõi SAN/điểm engine | Bình luận tiếng Việt và phụ đề | Thêm kênh nghe, không phải bằng chứng cải thiện năng lực chơi |
| Một preset Piper ở nhánh bình luận đầu | Ba BLV, chọn giọng và Nano CPU | Thêm lựa chọn và vận hành TTS local; chưa có phép đo chất lượng mù so sánh |
| Tùy chọn Gemini TTS ở v2 | Bỏ provider không dùng trong app main | Giảm nhánh cấu hình trong app; không suy ra đã xóa mọi file thử nghiệm Gemini khỏi repo |

Các nhận định “ít thao tác”, “thêm kênh nghe”, “dùng chung công việc” mô tả thiết kế/hành vi có trong code. Không chuyển chúng thành số liệu tăng năng suất, độ chính xác hoặc chất lượng học tập khi chưa có phép đo đối chứng.

## 5. Kết quả kiểm thử và bằng chứng

Các báo cáo WDL/human trong `reports/` là kết quả lịch sử theo snapshot của chúng, không phải full-stack main vừa chạy. Task list bình luận ghi 66 test Python, 7 test launcher, UI 283/285 (hai lỗi coach); log chủ yếu ở /tmp máy tác giả. Việc thêm README không chạy lại build/model/test chức năng main, cũng không sửa hai lỗi đó. Chỉ kiểm tra source, diff tài liệu và liên kết cho lần cập nhật này.

## 6. Cách dựng và thử lại

Trước tiên chọn tính năng và đường dựng: WDL Docker theo README gốc/`scripts/dev.ps1`; bình luận Nano theo README dịch vụ và cấu hình riêng của Lila. Chỉ chạy WDL Docker không chứng minh bình luận được bật. Tài liệu bình luận có nhắc `./lichess-local` và `LOCAL.md`, nhưng các tệp đó chưa có trong tree main đã khảo sát; không coi đây là launcher tái lập sau clone. Xem bảng các branch để chọn đúng bản muốn thử; không thay stack đang dùng sang main trong lần viết tài liệu.

## 7. Giới hạn và điểm chưa hoàn thành

Main chưa hợp nhất mọi branch; tên repo và README WDL gốc không phản ánh đủ bình luận. Không ghép kết quả nghiệm thu riêng từng branch thành một kết quả tích hợp chung. Không có benchmark người dùng về chất lượng học tập, tính tự nhiên giọng hay độ chính xác theo mọi nhóm người chơi. Không xem module thử nghiệm coaching/vision hoặc tool WebMCP phân tích JSON là tính năng coaching/LLM giải thích sau trận đã nghiệm thu.

## 8. Hướng phát triển và điểm cần đối chiếu

Thanh dọc Stockfish trên trang xem lại có thể được tái sử dụng để hiển thị ưu thế cho vị trí đang chọn. Mã sẵn có quy cp/mate bằng logistic; nó khác WDL ba lớp và khác W+D/2 ở nhánh voice. Cần thống nhất công thức/nguồn, giữ đúng màu và lịch sử khi tích hợp. Chưa thêm phần trăm mới vào thanh dọc trong lần cập nhật README này.

## 9. Tệp nguồn quan trọng ở đúng revision

- [`services/prediction/app/main.py`](https://github.com/trantrien1/Lichess-workspace/blob/4ee86a7fd11f81099e6f9a37fa0ca8c3cad054df/services/prediction/app/main.py)
- [`services/commentary/app.py`](https://github.com/trantrien1/Lichess-workspace/blob/4ee86a7fd11f81099e6f9a37fa0ca8c3cad054df/services/commentary/app.py)
- [`services/commentary/voices.py`](https://github.com/trantrien1/Lichess-workspace/blob/4ee86a7fd11f81099e6f9a37fa0ca8c3cad054df/services/commentary/voices.py)
- [`services/commentary/nano_worker.py`](https://github.com/trantrien1/Lichess-workspace/blob/4ee86a7fd11f81099e6f9a37fa0ca8c3cad054df/services/commentary/nano_worker.py)
- [`docs/binh-luan-vien-tieng-viet.md`](https://github.com/trantrien1/Lichess-workspace/blob/4ee86a7fd11f81099e6f9a37fa0ca8c3cad054df/docs/binh-luan-vien-tieng-viet.md)
- [`openspec/changes/local-commentary-stack/tasks.md`](https://github.com/trantrien1/Lichess-workspace/blob/4ee86a7fd11f81099e6f9a37fa0ca8c3cad054df/openspec/changes/local-commentary-stack/tasks.md)
- [`upstream-lock.json`](https://github.com/trantrien1/Lichess-workspace/blob/4ee86a7fd11f81099e6f9a37fa0ca8c3cad054df/upstream-lock.json)

## 10. Dùng tài liệu này khi viết báo cáo

Có thể dùng mục 1–2 cho bài toán/phạm vi, mục 3 cho thiết kế, mục 4 cho đóng góp và so sánh, mục 5 cho thực nghiệm, mục 7–8 cho hạn chế/hướng phát triển. Khi trích số đo, giữ nguyên tên branch, snapshot, tập kiểm thử và điều kiện máy; phân biệt số đã lưu với số vừa chạy. Không cộng các lần kiểm thử lặp thành số mẫu độc lập.

README này được tổng hợp với sự hỗ trợ của Codex. Tài liệu không suy đoán tác giả của mọi phần mã nguồn hoặc việc đã đóng góp lên upstream. Đối chiếu Lichess tại revision đã ghim thay vì khẳng định phiên bản hiện tại hoàn toàn chưa có tính năng tương tự.

- [Danh mục sáu branch](../branches/README.md)
- [Thiết kế bình luận hiện tại](../binh-luan-vien-tieng-viet.md)
- [Cài dịch vụ bình luận](../../services/commentary/README.md)
- [Model card](../../reports/human-v1/model-card.md)

Nguồn đối chiếu thanh analysis: [renderGauge](https://github.com/lichess-org/lila/blob/4eea97abce686a1cc6b07abe54cce9e10c223227/ui/lib/src/ceval/view/main.ts), [biến đổi cp/mate](https://github.com/lichess-org/lila/blob/4eea97abce686a1cc6b07abe54cce9e10c223227/ui/lib/src/ceval/winningChances.ts).
