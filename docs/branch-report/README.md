# Tỷ lệ và ưu thế — phần dùng chung trên main

## Phạm vi và nguồn

Phần ưu thế lúc chơi và xem lại thuộc bản dùng chung của nhóm trên `main`.
Từ commit `9d92cdc` ngày 19/11/2026, cả hai giao diện dùng Win% của Lichess.
Người chơi ở cả hai phía và người xem đều được xem ưu thế trong ván standard
trên bản tự host, theo lựa chọn phục vụ luyện tập và demo của nhóm. Nhánh
giọng nói được quản lý riêng. Revision upstream và đường dựng
Docker nằm trong `upstream-lock.json`.

## Chức năng và kiến trúc

Live lấy lịch sử từ Lila, phân tích qua Stockfish trong worker có cache và
trả điểm cp/mate theo góc nhìn Trắng. Review lấy điểm của nước đang chọn.
Cả hai gọi `lichessWinPercentages` với điểm giới hạn ở ±1.000 cp, kể cả dự
báo chiếu hết. Trắng bằng `round(100 / (1 + exp(-0.00368208 × cp)))`, Đen bằng
`100 − Trắng`. Các số hiển thị là số nguyên và cộng đúng 100%.

Khi thiếu điểm hợp lệ, giao diện dùng `W + D/2` và `B + D/2` từ WDL engine,
với tooltip nêu nguồn. API tiếp tục lưu riêng WDL và human pilot. Kết quả
chính thức được ưu tiên tại đúng điểm cuối nhánh chính của ván. Mỗi phản hồi
phải khớp lịch sử hiện tại sau nước mới, hoàn tác và kết nối lại.

Nguồn có trong `lila/` và patch tái lập cho Docker. Không đưa ASR/recorder vào
main. Giữ nguyên code bình luận Nano/ba BLV của nhóm, không nhập nhánh coach hay
WebMCP trong thao tác tách ownership này.

## Ưu điểm so với tính năng có sẵn

| Có sẵn / mốc trước | Phần chung bổ sung | Ý nghĩa và giới hạn |
|---|---|---|
| Analysis có thanh cp/mate | Win% trên thanh dọc tại nước đang chọn | Dùng chung công thức với thanh ngang lúc chơi |
| Phải mở tab người xem | Panel trên cả hai bàn standard | Theo dõi biến động sau từng nước ngay trên bàn chơi |
| WDL dồn về 99% trên nhiều thế | Chuyển điểm cp sang Win% trước khi làm tròn | Trên 118 thế, nhóm từ 95% trở lên giảm từ 49 xuống 5 |
| Dự đoán chỉ theo engine | API có thêm human pilot khi đủ rating/clock | Giữ dữ liệu thử nghiệm riêng để tiếp tục đánh giá |
| Đánh giá riêng/trả số cũ sau takeback | Cache và revision theo toàn lịch sử | Giảm việc trùng, tránh nhầm cùng ply khác thế cờ |

## Kiểm thử và giới hạn

Phép so sánh Win% dùng 118 thế từ 24 ván, cùng một lần phân tích Stockfish
15.1 trong 250 ms cho mỗi thế. Mốc tích hợp `9d92cdc` có 62/62 test liên quan
đạt và Chromium bao phủ PvP, AI, người xem và review. Các số liệu cùng điều
kiện đo nằm trong [task list](../../openspec/changes/live-win-probability/tasks.md).
Các báo cáo acceptance có revision riêng lưu kết quả của từng mốc.

Human model còn thiên lệch prefix sample, ít hòa, tập tháng 10 từng được xem
lại sau sửa lấy mẫu. [Model card](../../reports/human-v1/model-card.md) là nguồn
cho protocol/metric; không biến cải thiện log loss thành tỷ lệ thắng tăng.
Hiệu quả luyện tập và độ chính xác dự đoán kết quả thực tế cần được đánh giá
trên một bộ dữ liệu độc lập phù hợp với người chơi của máy chủ.

## Cách chạy và tài liệu

[README gốc](../../README.md), [chuẩn bị model browser](../../scripts/prepare-analysis-engine.mjs),
[spec](../../openspec/changes/live-win-probability/specs/win-probability/spec.md),
[patch](../../patches/lila-win-probability.patch),
[review](../../reports/acceptance/replay-advantage/README.md),
[bình luận đang có](../binh-luan-vien-tieng-viet.md).

Voice input có sẵn của Lichess vẫn còn; phần mở rộng tiếng Việt Vosk/PhoWhisper,
grammar mới, thu âm và đi ngay ở branch voice. WebMCP/coach do các nhánh riêng
cung cấp, chưa mặc định đã được nghiệm thu chung trên main.

README này được tổng hợp với hỗ trợ của Codex. Khi viết báo cáo, trích revision,
tập dữ liệu, điều kiện đo và giới hạn; không ghép số test các branch thành một
nghiệm thu toàn bộ nhóm.
