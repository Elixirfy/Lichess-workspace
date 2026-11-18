# Dự đoán kết quả ván cờ theo thời gian thực

## Thông tin phiên bản và mục đích tài liệu

- Branch: `codex/live-win-probability`.
- Mã nguồn khảo sát: [`60aba5b8c3605455c196303742b0e7808dc20fd5`](https://github.com/trantrien1/Lichess-workspace/commit/60aba5b8c3605455c196303742b0e7808dc20fd5).
- Ngày tổng hợp: **18/11/2026**. Tài liệu này phục vụ mô tả/so sánh trong báo cáo; không phải một benchmark mới.
- Mốc nền tảng của dịch vụ Stockfish WDL và mô hình kết quả người chơi. Nhánh này hiển thị ba lớp Trắng thắng / Hòa / Đen thắng cho người xem; không có các cập nhật hai tỷ lệ, mở quyền người chơi và giọng nói mới trên nhánh voice.

## 1. Bài toán và mục tiêu

Giúp người xem nhận biết thay đổi thế cờ bằng đầu ra xác suất ba lớp, đồng thời thử nghiệm việc xét rating và đồng hồ. Tách bài toán đánh giá engine khỏi bài toán dự đoán kết quả của người chơi.

## 2. Chức năng đã có trên nhánh

Người xem mở một ván standard đang diễn ra. Panel lấy WDL từ server sau mỗi nước. Khi đủ ngữ cảnh, hiển thị mô hình người chơi có nhãn thử nghiệm; nếu không, dùng engine. Endpoint ở mốc này từ chối người đang chơi. Replay ẩn số live; mất kết nối xóa số cũ; kết quả chính thức ghi đè dự đoán.

## 3. Kiến trúc và cách triển khai

```text
WebSocket lịch sử ván → round UI → endpoint Scala → worker Python/cache → Stockfish → human model nếu đủ ngữ cảnh → một bộ WDL trên UI.
```

Stockfish nhận toàn bộ lịch sử SAN, quy WDL về phía Trắng. Worker giới hạn hàng đợi/cache và đồng xử lý các yêu cầu cùng thế cờ. Revision chứa lịch sử, trạng thái và người thắng, chống dùng nhầm kết quả khi hoàn tác rồi đi nước khác ở cùng ply. Mô hình logistic đa lớp có 23 đặc trưng, xuất JSON; phục vụ không cần sklearn. Worker dùng hai engine, một thread/engine, ngân sách tìm kiếm 250 ms theo cấu hình nghiệm thu.

## 4. Ưu điểm so với tính năng có sẵn

| Có sẵn / cách làm đối chiếu | Phần bổ sung trên nhánh | Ưu điểm và phạm vi |
|---|---|---|
| Thanh đánh giá Stockfish trên trang phân tích, điểm centipawn/mate | WDL ba lớp trên trang người xem ván live | Phân biệt thắng/hòa/thua và không cần chuyển sang analysis; chưa có so sánh người dùng để kết luận dễ hiểu hơn bao nhiêu |
| Đánh giá engine chủ yếu từ thế cờ | Pilot thêm rating và đồng hồ | Có thể mô tả sai sót của người chơi trong phạm vi dữ liệu; chưa hiệu chỉnh cho cộng đồng local |
| Mỗi client có thể tự chạy phân tích | Worker/cache dùng chung theo game và lịch sử | Giảm công việc engine trùng lặp; không khẳng định capacity ngoài phép thử local |
| Chỉ dùng ply làm khóa | Khóa đầy đủ lịch sử và kết quả | Xử lý đúng hoàn tác, thay nước, reconnect và kết thúc |

Các nhận định “ít thao tác”, “thêm kênh nghe”, “dùng chung công việc” mô tả thiết kế/hành vi có trong code. Không chuyển chúng thành số liệu tăng năng suất, độ chính xác hoặc chất lượng học tập khi chưa có phép đo đối chứng.

## 5. Kết quả kiểm thử và bằng chứng

| Bằng chứng đã lưu trước lần viết README này | Cách sử dụng trong báo cáo |
|---|---|
| `reports/acceptance/simple-panel/validation.json`: 265 test frontend, 210 assertion browser | Mốc UI đơn giản của chính nhánh này; không thay bằng số 341 của nhánh voice |
| Báo cáo nghiệm thu: 56 test Python; p95 browser khoảng 554 ms ở lượt có tài khoản, 20 lượt đi đầu | Số đo local lịch sử, không phải benchmark vừa chạy lại |
| Model card: log loss 0,712218; Brier 0,455070 | Chỉ cho protocol/tập dữ liệu đã công bố |
| Log loss giảm khoảng 12% so với baseline tần suất huấn luyện | Không diễn giải thành tăng 12% tỷ lệ thắng hoặc tốt hơn mọi engine |

## 6. Cách dựng và thử lại

```powershell
.\scripts\dev.ps1 bootstrap
.\scripts\dev.ps1 start
.\scripts\dev.ps1 check
.\scripts\dev.ps1 browser -HumanPlayers
```

Mở `http://localhost:8080` trong một phiên **người xem**. Trên checkout đã bootstrap, mã Lila ở `infra/lila-docker/repos/lila`; thay đổi được tái lập từ patch. Không dùng hướng dẫn launcher WSL của nhánh bình luận cho nhánh này.

## 7. Giới hạn và điểm chưa hoàn thành

Dữ liệu model là prefix archive đã có phân tích, không đại diện trọn tháng; lớp hòa ít. Tập tháng 10 đã được xem hai lần sau sửa lỗi lấy mẫu, không còn là holdout nguyên vẹn. Temperature calibration không cải thiện mọi metric ở tập tháng 10. Model chỉ hỗ trợ standard blitz/rapid trong phạm vi rating/clock/ply của model card. Đồng hồ trôi giữa hai nước chưa kích hoạt dự đoán mới. Các đầu ra chưa được chứng minh hiệu chỉnh cho người dùng local.

## 8. Hướng phát triển và điểm cần đối chiếu

Có thể tái sử dụng thanh dọc ở trang xem lại để hiển thị ưu thế cho **nước đang chọn**, dùng eval sẵn có thay vì chạy thêm một dịch vụ. Hiện nhánh này chưa tích hợp analysis page. Thanh Lichess có sẵn dùng biến đổi logistic của centipawn/mate; không được tự coi nó là WDL hoặc xác suất thắng cá nhân. Cần thống nhất thước đo trước khi dùng cả thanh dọc và panel live.

## 9. Tệp nguồn quan trọng ở đúng revision

- [`services/prediction/app/engine.py`](https://github.com/trantrien1/Lichess-workspace/blob/60aba5b8c3605455c196303742b0e7808dc20fd5/services/prediction/app/engine.py)
- [`services/prediction/app/scheduler.py`](https://github.com/trantrien1/Lichess-workspace/blob/60aba5b8c3605455c196303742b0e7808dc20fd5/services/prediction/app/scheduler.py)
- [`services/prediction/app/human.py`](https://github.com/trantrien1/Lichess-workspace/blob/60aba5b8c3605455c196303742b0e7808dc20fd5/services/prediction/app/human.py)
- [`services/prediction/training/train.py`](https://github.com/trantrien1/Lichess-workspace/blob/60aba5b8c3605455c196303742b0e7808dc20fd5/services/prediction/training/train.py)
- [`patches/lila-win-probability.patch`](https://github.com/trantrien1/Lichess-workspace/blob/60aba5b8c3605455c196303742b0e7808dc20fd5/patches/lila-win-probability.patch)
- [`reports/human-v1/model-card.md`](https://github.com/trantrien1/Lichess-workspace/blob/60aba5b8c3605455c196303742b0e7808dc20fd5/reports/human-v1/model-card.md)
- [`reports/acceptance/simple-panel/validation.json`](https://github.com/trantrien1/Lichess-workspace/blob/60aba5b8c3605455c196303742b0e7808dc20fd5/reports/acceptance/simple-panel/validation.json)

## 10. Dùng tài liệu này khi viết báo cáo

Có thể dùng mục 1–2 cho bài toán/phạm vi, mục 3 cho thiết kế, mục 4 cho đóng góp và so sánh, mục 5 cho thực nghiệm, mục 7–8 cho hạn chế/hướng phát triển. Khi trích số đo, giữ nguyên tên branch, snapshot, tập kiểm thử và điều kiện máy; phân biệt số đã lưu với số vừa chạy. Không cộng các lần kiểm thử lặp thành số mẫu độc lập.

README này được tổng hợp với sự hỗ trợ của Codex. Tài liệu không suy đoán tác giả của mọi phần mã nguồn hoặc việc đã đóng góp lên upstream. Đối chiếu Lichess tại revision đã ghim thay vì khẳng định phiên bản hiện tại hoàn toàn chưa có tính năng tương tự.

- [Model và giới hạn](../../reports/human-v1/model-card.md)
- [Nghiệm thu](../../reports/acceptance/bao-cao-nghiem-thu.md)
- [Nhiệm vụ engine](../../openspec/changes/live-win-probability/tasks.md)

Nguồn đối chiếu thanh analysis: [renderGauge](https://github.com/lichess-org/lila/blob/4eea97abce686a1cc6b07abe54cce9e10c223227/ui/lib/src/ceval/view/main.ts), [biến đổi cp/mate](https://github.com/lichess-org/lila/blob/4eea97abce686a1cc6b07abe54cce9e10c223227/ui/lib/src/ceval/winningChances.ts).
