# Ưu thế Trắng/Đen theo thời gian thực

Tính năng hiển thị ưu thế của hai bên bằng phần trăm để người chơi dễ theo dõi
sự thay đổi của thế cờ trong các ván standard. Thanh ngang nằm trên giao diện
chơi với bot, chơi giữa hai người và trang người xem. Khi xem lại ván đấu,
thanh dọc bên cạnh bàn cờ hiển thị tỷ lệ tại nước đang chọn. Phần này được
phát triển trên `main`.

## Cơ sở phát triển

Lichess đã có Stockfish, điểm đánh giá cp/mate và thanh đánh giá trong trang
phân tích. Phần bổ sung dùng lại các thành phần đó, đưa tỷ lệ ra giao diện
chơi và dùng cùng một công thức cho cả lúc chơi lẫn xem lại.

Ban đầu, tỷ lệ được suy ra từ WDL của Stockfish. Sau khi thử thấy nhiều thế cờ
dồn về mức 99%, phần hiển thị được chuyển sang
[Win% của Lichess](https://lichess.org/page/accuracy), tính trực tiếp từ điểm cp.

## Luồng xử lý

Lila lấy lịch sử nước đi và trạng thái ván rồi gửi tới dịch vụ prediction.
Stockfish phân tích trong worker riêng, trả điểm theo góc nhìn Trắng. Kết quả
được lưu đệm theo ván và toàn bộ lịch sử nước đi để nhiều người xem có thể dùng
chung một lần tính. Worker có giới hạn tài nguyên và hàng đợi để việc đánh giá
không cản xử lý nước đi.

Sau một nước mới, hoàn tác hoặc kết nối lại, giao diện đối chiếu lịch sử trước
khi nhận kết quả. Phản hồi của thế cờ cũ được bỏ. Khi xem lại, thanh dọc đọc
đánh giá của đúng nước đang chọn, kể cả khi người dùng mở một nhánh phân tích.

## Công thức hiển thị

```text
cp     = giới hạn điểm Stockfish trong [−1000, 1000]
Trắng  = round(100 / (1 + exp(-0.00368208 × cp)))
Đen    = 100 − Trắng
```

Điểm dương nghiêng về Trắng, điểm âm nghiêng về Đen. Hai số là số nguyên và
luôn cộng thành 100%:

| Điểm Stockfish | Trắng | Đen |
|---|---|---|
| 0 cp | 50% | 50% |
| +100 cp | 59% | 41% |
| +300 cp | 75% | 25% |

Giới hạn cp khiến tỷ lệ quy đổi nằm trong khoảng 2–98%. Dự báo chiếu hết của
engine cũng được quy về ±1.000 cp. Khi ván hoặc vị trí đã có kết quả xác định,
thanh hiển thị theo kết quả đó. Kết quả của ván chỉ áp dụng tại điểm cuối
nhánh chính; các nước trước đó vẫn dùng đánh giá của vị trí đang xem. Ván hòa
chính thức có thông báo kết quả riêng trên giao diện chơi.

Nếu thiếu điểm cp/mate, giao diện dùng WDL của engine: `W + D/2` cho Trắng,
`B + D/2` cho Đen, sau đó làm tròn. Nguồn tính được ghi trong tooltip.

## Ưu điểm so với tính năng có sẵn

| Nội dung | Phần bổ sung |
|---|---|
| Xem đánh giá khi đang chơi | Người chơi xem trực tiếp trên bàn của mình, cả khi đấu bot và đấu người. |
| Đọc thanh đánh giá khi xem lại | Có nhãn Trắng/Đen và phần trăm tại từng nước, dùng cùng công thức với thanh ngang. |
| Tỷ lệ quá sát 100% | Dùng Win% từ điểm cp và giới hạn điểm trước khi quy đổi. |
| Nhiều người xem cùng ván | Dùng chung kết quả phân tích; kiểm tra lịch sử để tránh hiển thị số cũ sau hoàn tác. |

## Kết quả đã ghi nhận và hạn chế

Lần so sánh Win% với WDL dùng 118 thế cờ từ 24 ván, cùng kết quả phân tích
Stockfish 15.1 trong 250 ms cho mỗi thế. Số thế có tỷ lệ của một bên từ 95%
trở lên giảm từ 49 xuống 5. Đây là kết quả trên bộ thử dùng để so sánh hai
cách hiển thị.

Ở đợt tích hợp công thức này, 62/62 test liên quan đã qua; các luồng đấu người,
đấu máy, người xem và xem lại đã được thử trên Chromium. Log từng lần chạy
được lưu local. Các lệnh trong README gốc dùng để kiểm tra lại phiên bản hiện tại.

Win% phản ánh đánh giá thế cờ của engine. Cấp độ bot, trình độ người chơi và
khả năng tìm ra nước tốt trong thời gian còn lại chưa được tính vào chỉ số này.
Khi xem lại, phiên bản hoặc độ sâu engine khác với lúc chơi có thể cho số khác.
Giao diện mobile một cột tiếp tục ẩn thanh dọc theo bố cục của Lichess.

Thử nghiệm dự đoán theo rating và đồng hồ được mô tả riêng trong
[model card](../../reports/human-v1/model-card.md); kết quả đó không được dùng
để tính Win% đang hiển thị.

## Các file chính

- [Quy đổi Win%](../../lila/ui/lib/src/ceval/winningChances.ts).
- [Thanh ngang khi chơi](../../lila/ui/round/src/view/winProbability.ts).
- [Thanh dọc khi xem lại](../../lila/ui/lib/src/ceval/view/main.ts) và [xử lý kết quả cuối ván](../../lila/ui/analyse/src/advantage.ts).
- [Dịch vụ prediction](../../services/prediction/).
- [Bản vá Docker](../../patches/lila-win-probability.patch) và [phiên bản nguồn](../../upstream-lock.json).

Xem [README gốc](../../README.md) để cài đặt, chạy và kiểm thử.

Có sử dụng Codex để hỗ trợ triển khai và biên soạn tài liệu.
