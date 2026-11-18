# Tỷ lệ và ưu thế — phần dùng chung trên main

## Phạm vi và nguồn

Ngày 18/11/2026, theo phân công của người dùng, live/review probability thuộc
bản chung. Main nền `0d2944e`; code tỷ lệ lấy từ mốc đã kiểm thử `e4d8477`,
giữ nguyên công thức và model. Nguồn upstream/Docker trong `upstream-lock.json`;
patch hiện tại ghi bằng checksum trong báo cáo tích hợp. Voice riêng không
thay đổi bản tỷ lệ được kế thừa từ main.

## Chức năng và kiến trúc

Live: lịch sử Lila → endpoint/cached worker → Stockfish/human pilot → WDL →
điểm kỳ vọng hai màu cho cả hai người chơi/người xem standard.
Review: node đang chọn → native WDL hoặc cp-only model → cùng helper W+D/2 →
thanh dọc. Kết quả chính thức chỉ áp ở endpoint gốc, không dùng cho node quá khứ.

Nguồn có trong `lila/` và patch tái lập cho Docker. Không đưa ASR/recorder vào
main. Giữ nguyên code bình luận Nano/ba BLV của nhóm, không nhập nhánh coach hay
WebMCP trong thao tác tách ownership này.

## Ưu điểm so với tính năng có sẵn

| Có sẵn / mốc trước | Phần chung bổ sung | Ý nghĩa và giới hạn |
|---|---|---|
| Analysis có thanh cp/mate | Ưu thế W+D/2 trên thanh dọc tại node đang chọn | Tái sử dụng engine/UI; không chứng minh xác suất thắng cá nhân |
| Chỉ spectator hoặc phải mở tab khác | Panel trên cả hai bàn standard | Ít chuyển trang, server vẫn kiểm tra quyền/variant |
| W/(W+B) bỏ hòa | Cộng nửa điểm hòa cho mỗi bên | Ví dụ 0/87,6/12,4 thành 43,8/56,2 thay cho 0/100 |
| Chỉ xét thế cờ engine | Human pilot có rating/clock khi hợp lệ | Có thêm ngữ cảnh; chưa hiệu chỉnh cho cộng đồng local |
| Đánh giá riêng/trả số cũ sau takeback | Cache và revision theo toàn lịch sử | Giảm việc trùng, tránh nhầm cùng ply khác thế cờ |

## Kiểm thử và giới hạn

Các mốc cũ có 360 test frontend trên branch kết hợp và browser review 4 ván/22
snapshot. Đây là bằng chứng lịch sử, không gán nguyên số đó cho source main mới.
[Báo cáo tách phần chung](../../reports/acceptance/shared-probability/README.md)
ghi các kiểm tra vừa chạy và lỗi nền nếu còn. Không coi các snapshot lặp của
flip/reload là mẫu đánh giá model độc lập.

Human model còn thiên lệch prefix sample, ít hòa, tập tháng 10 từng được xem
lại sau sửa lấy mẫu. [Model card](../../reports/human-v1/model-card.md) là nguồn
cho protocol/metric; không biến cải thiện log loss thành tỷ lệ thắng tăng.
Không đo hiệu quả học cờ/nghe bình luận trong lần tách Git này.

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
