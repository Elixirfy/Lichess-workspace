# Dữ liệu Lichess: ghi chú kỹ thuật

Tài liệu này dành cho người sửa phần thu thập dữ liệu hoặc tính đặc trưng. Nó
ghi lại ý nghĩa thật của các trường trong API Lichess, vì nhiều trường dễ hiểu
nhầm và hiểu nhầm sẽ làm sai đặc trưng một cách lặng lẽ. Các điểm dưới đây được
kiểm tra ngày 8/11/2026 trên 20 ván thật (1.633 nửa nước) và đối chiếu với mã
nguồn Lichess trong repo này.

## Các trường của API export

| Trường | Ý nghĩa và cách xử lý |
|---|---|
| `createdAt` | Thời điểm tạo ván (mili giây UTC), dùng làm mốc bắt đầu ván. Tham số `since` của API lọc theo trường này, không theo lúc ván kết thúc. `until` là cận loại trừ. |
| `lastMoveAt` | Thời điểm nước cuối, **không phải** lúc ván kết thúc: xin thua hay chấp nhận hòa không đổi giá trị này. |
| `clock.initial`, `clock.increment` | Tính bằng giây. Người chơi berserk có thể có đồng hồ khác. |
| `clocks[i]` | Thời gian còn lại của bên vừa đi sau nửa nước `i+1`, tính bằng **centi giây** (chia 100). Đây không phải thời gian suy nghĩ. |
| Độ dài `clocks` | Có thể dài hơn số nửa nước một phần tử khi ván kết thúc giữa hai nước (hết giờ, xin thua): phần tử cuối là đồng hồ đã dừng của bên đang đến lượt. |
| Hai nước đầu | Không tính giờ và không cộng thêm giờ. Thời gian suy nghĩ của chúng để **trống**, không coi là đi ngay. |
| `analysis[i].eval` | Đánh giá sau nửa nước `i+1`, đơn vị centipawn, theo góc nhìn **Trắng**. Không có phần tử cho thế cờ ban đầu. |
| `analysis[i].mate` | Số nước tới chiếu hết, có dấu, theo góc nhìn Trắng. **0 là trường hợp đặc biệt**: bên đến lượt đã bị chiếu hết; xác định người thắng theo lượt đi, không theo dấu. |
| `analysis[i].best` | Nước Lichess đề xuất **thay cho** nước vừa đi, không phải cho thế cờ tiếp theo. |
| `division.middle`, `.end` | Chỉ số nửa nước bắt đầu trung cuộc và tàn cuộc. Có thể vắng mặt. |
| `players.*.analysis.accuracy` | Độ chính xác cả ván đã làm tròn. Code tính lại từ công thức gốc. |

## Thời điểm kết thúc ván

Để chỉ dùng các ván đã kết thúc trước ván đang xét, mỗi ván có một cận trên
`end_upper_ms` của thời điểm kết thúc:

- ván kết thúc bằng một nước (chiếu hết, hòa tự động): `lastMoveAt` cộng 20 ms;
- ván kết thúc giữa hai nước: `lastMoveAt` cộng thời gian đồng hồ đã chạy của bên
  đến lượt, cộng thêm 1 giây an toàn;
- thiếu đồng hồ hoặc lịch sử bất thường: dùng thời điểm nhận được phản hồi API;
  với dump thì dùng giờ kết thúc trong header (độ phân giải giây) cộng 1 giây.

Không bao giờ cộng dồn thời gian suy nghĩ để đoán giờ kết thúc, vì Lichess bù trễ
mạng và cho thêm giờ.

## Thời gian suy nghĩ

```text
thời gian suy nghĩ = đồng hồ trước đó của chính người đó − đồng hồ hiện tại + thời gian cộng thêm
```

- Nước kết thúc ván không được cộng thêm giờ.
- Phần đồng hồ đã dùng tính trên đồng hồ đầu tiên quan sát được, nên đúng cả với
  ván berserk.
- Giá trị âm dưới −0,1 giây (do đối thủ cho thêm giờ, đi lại) được đánh dấu và để
  trống. Sai số âm nhỏ do nén đồng hồ được làm tròn về 0.

## Công thức

Các công thức trong `common/formulas.py` port đúng từ mã nguồn Lichess, mỗi hàm
ghi đường dẫn tới mã gốc.

- **Cơ hội thắng:** đánh giá centipawn bị chặn ở ±1000; chiếu hết dùng mức ±1000.
- **Phân loại nước:** theo `Advice.scala` phía máy chủ, ngưỡng không chính xác,
  sai lầm, sai lầm nghiêm trọng là mức giảm cơ hội thắng ≥ 0,1 / 0,2 / 0,3 (thang
  0–2). Nước chiếu hết luôn là nước tốt.
- **Độ chính xác nước:** theo điểm phần trăm cơ hội thắng bị mất, cộng 1 cho độ
  bất định, chặn trong [0, 100].
- **Độ chính xác ván:** trung bình của trung bình có trọng số theo độ biến động
  và trung bình điều hòa, không phải trung bình cộng độ chính xác các nước.
- Khi thế cờ ban đầu không có đánh giá engine, dùng mức +15 centipawn quen thuộc
  của Lichess và ghi rõ nguồn.

## Mức thường lệ

- Với ván G, chỉ dùng các ván của **cùng người**, cùng thể thức, có
  `end_upper_ms` nhỏ hơn lúc G bắt đầu.
- Lấy tối đa 200 ván gần nhất thỏa điều kiện trên (đổi bằng
  `--max-history-games`), chọn trước rồi mới lọc giá trị thiếu; không lùi thêm để
  bù.
- Cần ít nhất 5 ván có giá trị hợp lệ cho chỉ số đó. Thiếu thì để trống, không
  điền giá trị trung bình của người khác.
- Độ lệch dùng `max(1,4826 × MAD, ngưỡng tối thiểu)`. Ngưỡng tránh chia cho số quá
  nhỏ khi người chơi rất ổn định:

| Chỉ số | Ngưỡng theo nước | Ngưỡng theo ván |
|---|---:|---:|
| CPL | 1,0 | 1,0 (trung bình, độ lệch chuẩn) |
| Độ chính xác | 1,0 | 1,0 |
| Thời gian suy nghĩ (giây) | 0,1 | 0,1 (trung bình, độ lệch chuẩn) |
| Mất cơ hội thắng | 0,01 | |
| Độ liều lĩnh | 0,05 | 0,05 |
| Tỉ lệ sai lầm, sai lầm nghiêm trọng | | 0,01 |
| Tỉ lệ tấn công, đổi phong cách | | 0,05 |
| Vào ván ngay sau thua | | 0,05 |
| Khoảng nghỉ (giây) | | 1,0 |
| Thay đổi CPL / thời gian sau một sự kiện bất lợi | | 1,0 / 0,1 |
| Số nửa nước để hồi phục sau sự kiện | | 1,0 |

## Quy tắc khi tải dữ liệu

- Mỗi lúc chỉ có một request tới Lichess (khóa `tilt/data/external/http.lock`).
  Gặp lỗi 429 thì đóng kết nối, chờ đủ 60 giây rồi thử lại.
- Phản hồi được lưu nguyên byte, gzip theo người chơi trong `raw/api/<user>/`.
  Chỉ cập nhật con trỏ tải tiếp khi phản hồi hoàn tất; bị ngắt thì chạy lại lệnh
  hoặc `python -m tilt normalize`.
- `--backfill` tải lùi về các ván cũ hơn. Giữ nguyên `--perf-type`, `--since`,
  `--until` giữa các lần chạy để dùng đúng con trỏ.
- Dump `.pgn.zst` được giải nén theo luồng, không ghi PGN giải nén ra đĩa; bảng
  tạm SQLite bị giới hạn bởi `--max-staging-gb` (mặc định 5 GiB).
- Token `LICHESS_TOKEN` (nếu có) chỉ đọc từ biến môi trường, không bao giờ được in
  hay lưu lại.

Nguồn: [Lichess API](https://lichess.org/api#tag/Games/operation/apiGamesUser),
[định dạng dump](https://database.lichess.org/),
[codec nén đồng hồ](https://github.com/lichess-org/compression/blob/master/src/main/scala/clock/LowBitTruncator.scala).
