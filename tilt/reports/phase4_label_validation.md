# Phase 4: Kiểm định nhãn yếu (weak label validation)

Ngày: 2026-11-14. Phạm vi: chỉ đọc các hàng **train** của `weak_by_player` và `weak_by_time`. Không đọc nhãn
validation hay test, không huấn luyện hay chọn mô hình, không đổi LF, công thức nhãn, baseline hay split.

> **The model predicts a behavioral proxy of tilt, not independently validated anger.**
>
> Hiện có 0 nhãn cảm xúc của người thật (`data/raw/labels/labels.sqlite` không tồn tại). Mọi con số trong các phase
> 1–4 đo mức khớp với nhãn yếu, không đo cơn giận hay sự bực bội.

Tái lập: `TILT_SALT="$(cat ~/.tilt-salt)" .venv/bin/python -m tilt.evaluation.phase4 --data data --out ~/tilt-phase4/module`
(trong `tilt/`). Kết quả: `~/tilt-phase4/module/phase4_analysis.json` (chỉ trong WSL). Code:
`src/tilt/evaluation/phase4.py`, test `tests/unit/test_phase4.py`.

Quy ước: "tỉ lệ TILT" = tỉ lệ nhãn TILT trong các hàng có nhãn; "phủ" (coverage) = tỉ lệ hàng có nhãn. AUC là
ROC-AUC thô của một đại lượng với nhãn yếu (dưới 0,5 nghĩa là giá trị cao đi với NOT_TILT). Hai con số "a / b" là
by_player / by_time.

## 1. Nhãn yếu được tạo ra thế nào

| | by_player | by_time |
|---|---|---|
| Hàng train | 22.316 | 25.403 |
| Có nhãn | 6.428 (29%) | 7.200 (28%) |
| Tỉ lệ TILT | 15,1% | 14,9% |
| Người chơi | 122 (trung vị 44 nhãn/người; 5 người nhiều nhất = 9,1% nhãn) | 189 (36; 7,4%) |
| Tốc độ | 100% blitz | 100% blitz |

Số lần mỗi LF bỏ phiếu (by_player; by_time tương tự):

| LF | Phiếu | Số lần | Điều kiện chính |
|---|---|---|---|
| abandon | TILT | 66 | thua do bỏ ván (`timeout`) ở thế còn chơi được |
| early_resign | TILT | 155 | đầu hàng ≤ 60 nửa nước khi eval > −150 |
| carryover | TILT | 730 | thua ván trước cùng phiên, nghỉ ≤ 60 s, `deviation_mean_cpl_z` ≥ 1,5 |
| session_spiral | TILT | 24 | ≥ 3 thua liền trong phiên, nghỉ ngắn dần, z ≥ 1,5 |
| fast_erratic_after_loss | TILT | 139 | thua ván trước, nghỉ ≤ 120 s, nghĩ ≤ 65% mức thường, z ≥ 1 |
| normal_accuracy | NOT | 4.893 | ván "đàng hoàng" (≥ 40 nửa nước), độ chính xác ≥ mức thường, \|z\| ≤ 1 |
| rest_and_recover | NOT | 735 | đàng hoàng, nghỉ 5–30 phút rồi ván sau \|z\| ≤ 1 |
| calm_play | NOT | **0** | đàng hoàng, 0 sự kiện bất lợi |
| composed_loss | NOT | 48 | thua ≥ 80 nửa nước, đầu hàng ở thế thua rõ, nghỉ rồi chơi bình thường |
| expected_loss | NOT | 242 | thua người hơn ≥ 200 Elo, chơi gần mức thường |

- 100% nhãn TILT đến từ hàng chỉ có phiếu TILT; 99,7% nhãn NOT từ hàng chỉ có phiếu NOT; 14 / 16 hàng có phiếu
  xung đột. Dawid–Skene vì vậy gần như không phân xử gì: nhãn ≈ "có LF nào bỏ phiếu và phiếu đó là gì".
- 71–72% hàng train không có phiếu nào, nên không có nhãn.
- **calm_play không bao giờ bỏ phiếu**: mọi ván ≥ 40 nửa nước đều có ít nhất 1 sự kiện bất lợi (0 ván có
  `adverse_events == 0`). Đây là một LF chết, ghi nhận ở đây, không sửa (quy tắc của kế hoạch).
- Cấu trúc đáng chú ý: 3/5 LF TILT đòi z ≥ 1,5 hoặc ≥ 1 (chơi tệ hơn mức thường của mình); 3/5 LF NOT đòi \|z\| ≤ 1
  hoặc độ chính xác ≥ mức thường. Mọi LF NOT đòi ván ≥ 40 nửa nước (Phase 1: ván có nhãn < 40 nửa nước là 100% TILT).

## 2. Nhãn có phụ thuộc quá nhiều vào thua ván không? — **Có, theo cấu tạo**

- **100%** nhãn TILT có ván hiện tại hoặc ván trước là thua (cả hai split). Đây là cấu tạo, không phải phát hiện:
  abandon/early_resign đòi thua ván này; carryover/fast_erratic đòi thua ván trước; session_spiral đòi chuỗi thua.
  Không có đường nào để một ván thắng sau một ván thắng thành TILT.
- 81,6% / 83,0% nhãn TILT có ván hiện tại thua (NOT: 54,6% / 55,5%).

| Kết quả | Phủ | Tỉ lệ TILT |
|---|---|---|
| Thua | 36,7% / 36,2% | 21,0% / 20,7% |
| Hòa | 46,2% / 44,5% | 2,4% / 2,3% |
| Thắng | 19,3% / 18,8% | 8,0% / 7,3% |
| Thua, ≥ 40 nửa nước | 41,3% / 41,5% | 12,2% / 11,6% |
| Không thua, ≥ 40 nửa nước | 25,7% / 25,3% | 5,8% / 5,1% |

- Thua là điều kiện **cần** nhưng không **đủ**: quy tắc "chỉ dùng kết quả" ở Phase 1 đạt PR-AUC validation
  0,18 / 0,17, chỉ hơn tỉ lệ nền 0,137 một chút.
- Nghĩa thực tế: người tức giận sau một ván thắng (ví dụ thắng may, bị đối thủ khiêu khích trong chat) hoặc tức giận
  ngay ván đầu phiên không bao giờ được gắn TILT. Nhãn đo "phản ứng xấu sau thất bại", không đo cảm xúc nói chung.

## 3. Nhãn có đồng nhất chơi kém với tilt không? — **Gần như có, nhưng chỉ khi đi sau một ván thua**

AUC của chất lượng nước đi với nhãn:

| Đại lượng | Tất cả | ≥ 40 nửa nước |
|---|---|---|
| `deviation_mean_cpl_z` (CPL so với mức thường của chính mình) | 0,880 / 0,862 | 0,948 / 0,933 |
| `mean_cpl` | 0,843 / 0,817 | 0,886 / 0,862 |
| `mean_accuracy` (đảo chiều) | 0,896 / 0,883 | 0,907 / 0,899 |
| `blunder_rate` | 0,836 / 0,812 | 0,879 / 0,852 |

Theo nhóm z:

| z | Phủ | Tỉ lệ TILT |
|---|---|---|
| < −1 (tốt hơn thường) | 3,9% / 3,5% | 34,5% / 44,0% |
| −1..0 | 48,0% / 48,2% | 2,6% / 2,8% |
| 0..1 | 24,8% / 24,9% | 2,9% / 4,1% |
| 1..1,5 | 6,5% / 6,9% | 44,8% / 40,0% |
| ≥ 1,5 | 31,0% / 28,7% | 89,2% / 89,1% |

Chơi tệ (z ≥ 1,5) theo bối cảnh:

| | Phủ | Tỉ lệ TILT |
|---|---|---|
| sau một ván thua | 60,0% / 57,5% | 94,6% / 94,4% |
| không sau ván thua | 4,1% / 3,7% | 15,8% / 16,9% |
| ván này thua | 31,9% / 29,8% | 89,1% / 89,4% |
| ván này thắng | 28,5% / 25,6% | 89,2% / 87,6% |

- Một ván chơi tệ hơn mức thường mà đi ngay sau một ván thua gần như luôn thành TILT (94%). Cùng mức chơi tệ nhưng
  không sau ván thua thì hiếm khi có nhãn (phủ 4%), và khi có thì phần lớn là NOT.
- Như vậy nhãn ≈ **"chơi tệ hơn mức thường của mình VÀ ngay sau thất bại"**, cộng thêm các ván kết thúc đột ngột.
  Nó không phân biệt được tilt với mệt mỏi, mất tập trung, hay một đối thủ mạnh bất thường xuất hiện sau ván thua.
- Nhóm z < −1 có tỉ lệ TILT 34–44% là do ván ngắn/bỏ ván (z tính trên ít nước), không phải vì chơi tốt bị coi là tilt.
- Vì z là một đầu vào trực tiếp của LF, AUC 0,95 là **hệ quả của định nghĩa nhãn**, không phải bằng chứng về cảm xúc.
  Phase 0/1 đã giữ z ngoài bộ feature của mô hình vì lý do này.

## 4. Nhãn có nhầm áp lực thời gian với giận dữ không? — **Không; nếu có thì ngược lại**

| Kết thúc | Phủ | Tỉ lệ TILT |
|---|---|---|
| Hết giờ (`outoftime`) | 40,0% / 39,0% | 6,6% / 6,4% |
| Bị chiếu hết | 41,6% / 40,7% | 11,1% / 10,5% |
| Đầu hàng | 16,5% / 16,6% | 29,0% / 27,7% |
| Bỏ ván (`timeout`) | 15,9% / 16,0% | 100% / 100% |

Tỉ lệ nước đi của chính mình khi đồng hồ thấp (`clock_pressure == 'low'`):

| | Phủ | Tỉ lệ TILT |
|---|---|---|
| 0% | 24,1% / 24,1% | 20,9% / 20,4% |
| > 0 và ≤ 20% | 33,9% / 33,0% | 10,1% / 8,3% |
| > 20% | 41,5% / 41,3% | 6,3% / 6,2% |

- Các LF NOT coi hết giờ là một kết thúc "đàng hoàng", nên ván thua vì hết giờ ít bị gắn TILT. Ván nhiều nước đi
  dưới áp lực thời gian có tỉ lệ TILT **thấp** hơn.
- AUC của tỉ lệ áp lực thời gian: 0,363 / 0,365 (≥ 40: 0,435). AUC của đồng hồ thấp nhất (`min_clock_fraction`):
  0,740 / 0,746, nhưng chỉ 0,58 trên ván ≥ 40 nửa nước. Còn nhiều giờ lúc kết thúc đi với TILT vì đầu hàng sớm và
  bỏ ván, không phải vì áp lực thời gian.
- Rủi ro theo chiều khác: fast_erratic_after_loss (đi nhanh hơn mức thường sau một ván thua) chiếm 14,3% / 13,0% nhãn
  TILT. Đi nhanh có thể là giận, nhưng cũng có thể là chiến thuật "đánh nhanh" có chủ đích. Nhãn không phân biệt
  được hai điều này.
- Nhãn không gắn "bị ép thời gian" với "giận", nhưng nó không biết gì về việc người chơi **cảm thấy** thế nào khi bị
  ép thời gian. Người hoảng loạn khi gần hết giờ có thể bị bỏ sót.

## 5. Nhãn có nhầm lối chơi tấn công với tilt không? — **Không trực tiếp**

Không LF nào đọc cờ lối chơi (tấn công, mạo hiểm, thí quân, phòng thủ).

| AUC | Tất cả | ≥ 40 nửa nước | Thua, ≥ 40 |
|---|---|---|---|
| `attack_rate` | 0,352 / 0,351 | 0,423 / 0,411 | 0,492 / 0,475 |
| `risk_rate` | 0,504 / 0,471 | 0,498 / 0,482 | 0,521 / 0,504 |
| `sacrifice_rate` | 0,609 / 0,569 | 0,648 / 0,614 | 0,629 / 0,579 |
| `defensive_rate` | 0,394 / 0,389 | 0,476 / 0,464 | 0,424 / 0,408 |

- Lối chơi tấn công đi với **ít** TILT hơn (phần tư tấn công cao nhất trên ván ≥ 40: 6,0% / 5,5%, thấp nhất 11,4% /
  11,7%). Trong các ván thua ≥ 40 nửa nước, AUC về gần 0,5, tức mối liên hệ chủ yếu đi qua kết quả ván.
- `sacrifice_rate` có AUC 0,58–0,65. Cờ "thí quân" trong pipeline dựa trên eval của engine, nên một phần là nước đi
  mất chất bị gắn nhầm là thí quân; nó trùng với chất lượng nước đi (mục 3) hơn là với lối chơi.
- Người chơi tấn công bị gắn TILT khi tấn công thất bại và làm z tăng sau một ván thua, tức là qua mục 2–3, không qua
  lối chơi.

## 6. Có thiên lệch theo Elo hoặc tốc độ không? — **Có một ít theo Elo; tốc độ không đánh giá được**

| Elo | Phủ | Tỉ lệ TILT | Phủ (≥ 40) | Tỉ lệ TILT (≥ 40) |
|---|---|---|---|---|
| < 1200 | 30,2% / 29,6% | 19,6% / 18,2% | 40,0% / 40,0% | 9,0% / 8,5% |
| 1200–1599 | 31,4% / 30,8% | 13,1% / 13,3% | 36,5% / 35,6% | 7,8% / 8,0% |
| 1600–1999 | 29,2% / 28,4% | 14,9% / 16,1% | 32,5% / 31,7% | 10,0% / 10,2% |
| ≥ 2000 | 26,0% / 25,5% | 13,3% / 11,9% | 27,5% / 27,1% | 10,4% / 9,1% |

| Chênh Elo (mình − đối thủ) | Phủ | Tỉ lệ TILT |
|---|---|---|
| ≤ −200 | 50,8% / 52,1% | 6,6% / 11,8% |
| −200..200 | 28,3% / 27,7% | 15,7% / 15,1% |
| ≥ 200 | 24,8% / 24,6% | 12,7% / 11,4% |

- Người < 1200 có tỉ lệ TILT cao hơn trên toàn bộ, nhưng trên ván ≥ 40 nửa nước thì các nhóm Elo gần bằng nhau
  (8–10%). Phần chênh đến từ ván ngắn (bỏ ván, đầu hàng sớm, chiếu hết nhanh) phổ biến hơn ở Elo thấp.
- Độ phủ giảm khi Elo tăng (ván ≥ 40: 40% ở < 1200, 27% ở ≥ 2000), vì LF NOT đòi độ chính xác ≥ mức thường và \|z\|
  ≤ 1, khó thỏa hơn khi phân bố hẹp hơn. Mô hình vì vậy học ít hơn từ người chơi mạnh.
- Thua người mạnh hơn nhiều được expected_loss bỏ phiếu NOT, nên tỉ lệ TILT thấp hơn (6,6% / 11,8%). Đây là quy tắc
  có chủ ý, nhưng nghĩa là người tức vì thua người mạnh hơn bị gắn NOT.
- Tốc độ: 100% ván là blitz. Không thể nói gì về bullet, rapid hay classical; mọi kết quả chỉ áp dụng cho blitz.

## 7. Tóm tắt giới hạn

1. Nhãn là **proxy hành vi**: "chơi tệ hơn mức thường sau một thất bại, hoặc kết thúc ván đột ngột khi thua".
   Không có đường nào để tilt không liên quan đến thua (cảm xúc sau ván thắng, ván đầu phiên) được gắn TILT.
2. Độ dài ván và chất lượng nước đi so với chính mình gần như quyết định nhãn (Phase 1–3: chỉ độ dài đạt PR-AUC
   0,656 / 0,608, hơn mọi mô hình hành vi; z có AUC 0,95 trên ván ≥ 40).
3. Áp lực thời gian **không** bị coi là tilt; hết giờ được tính là kết thúc đàng hoàng. Lối chơi tấn công không bị coi
   là tilt trực tiếp.
4. Thiên lệch: ván ngắn ở Elo thấp, độ phủ thấp hơn ở Elo cao, thua người mạnh hơn thì bị gắn NOT, chỉ có blitz.
5. 71% hàng không có nhãn; calm_play là LF chết; Dawid–Skene gần như không phân xử vì phiếu hầu như không xung đột.
6. Không có nhãn cảm xúc thật. **The model predicts a behavioral proxy of tilt, not independently validated anger.**

## 8. Giao thức thu nhãn cảm xúc

Các quyết định thiết kế trong mục 8–9 do Fable 5.2 đưa ra (ngày 2026-11-14) theo yêu cầu của người dùng. Hiện chưa có
nhãn người nào (`data/raw/labels/labels.sqlite` chưa tồn tại). Phần này là đặc tả để thu ở phase sau; Phase 4 không
thu dữ liệu và không sửa code.

### Mục tiêu đo

- Nhãn chính: mức tức giận do người chơi tự báo cáo cho một ván, thang 0–10, hỏi ngay sau ván.
- Nhãn phụ: mức bực bội 0–10, điểm "tilt" 0–10 (câu `TILT_ITEM` sẵn có), độ chắc chắn về câu trả lời 1–5.
- Năm mục Likert 1–5 sẵn có (bực bội, tức giận, muốn gỡ, bốc đồng, tập trung) chỉ hỏi trong label-app, không hỏi
  trong prompt sau ván, vì blitz chỉ chịu được khoảng 4 câu.
- Nhị phân hóa để tính chỉ số phân loại: tức giận ≥ 5 là dương. Ngưỡng này cố định trước khi thu; ngưỡng 4 và 6 chỉ
  là phân tích độ nhạy.
- Nhãn cảm xúc chỉ đến từ chính người chơi. Nhãn `expert`, nhãn do LLM hoặc do quy tắc suy ra từ nước đi không
  được dùng làm nhãn cảm xúc.

### Câu hỏi trong prompt sau ván

Cùng một bộ câu, cùng thứ tự, cho mọi kết quả ván:

1. "Trong ván vừa rồi, bạn tức giận ở mức nào?" (0 = không hề, 10 = cực kỳ)
2. "Trong ván vừa rồi, bạn bực bội ở mức nào?" (0–10)
3. "Bạn cảm thấy 'tilt' (bực bội, mất bình tĩnh hoặc chơi bốc đồng) ở mức nào?" (0–10)
4. "Bạn chắc chắn về các câu trả lời trên ở mức nào?" (1–5)
5. Tùy chọn, chỉ hiện khi câu 1 ≥ 3: "Đánh dấu đoạn bạn tức giận nhất", chọn một khoảng nước đi trên danh sách
   nước đi không có đánh giá engine. Tối đa 1 đoạn.

Có nút "Bỏ qua" một chạm. Không có ô nhập chữ tự do.

### Thời điểm và kênh

| Kênh | Điều kiện | Vai trò |
|---|---|---|
| Prompt trong fork lila (trang ván, chỉ người chơi ván đó thấy) | trả lời ≤ 5 phút sau khi ván kết thúc, trước mọi thông tin engine | phân tích chính |
| Cùng prompt, trả lời muộn (từ `/account/tilt`) | trễ từ 5 phút đến 24 giờ | nhóm "trễ", phân tích riêng |
| Label-app | trễ ≤ 24 giờ và chưa xem biểu đồ eval/đồng hồ của ván đó | nhóm "trễ", phân tích riêng |
| Bất kỳ kênh nào | trễ > 24 giờ, hoặc đã xem eval trước khi trả lời | chỉ thăm dò, không vào phân tích chính |

- `delay_seconds` được ghi cho mọi báo cáo, tính từ lúc ván kết thúc.
- Label-app hiện hiển thị biểu đồ eval và đồng hồ ở trang `/games`. Chừng nào chưa ẩn chúng trước khi chấm, mọi nhãn
  từ label-app mang `saw_eval = true`.

### Lấy mẫu ván

- Mỗi ván rated đã kết thúc của người tham gia được hỏi với xác suất 1/2. Việc chọn dựa trên hash của `game_id` với
  một khóa cố định, nên kiểm tra lại được và không phụ thuộc kết quả ván, đối thủ hay vị trí trong phiên.
- Không lấy mẫu theo kết quả (ví dụ "mọi ván sau khi thua") và không đặt trần theo thứ tự trong phiên. Cả hai làm
  lệch tỉ lệ tức giận quan sát được; trần theo thứ tự còn cắt đúng các ván cuối phiên, nơi tilt dễ xảy ra nhất.
- Mọi prompt đã hiện đều được ghi lại với trạng thái `answered`, `skipped` hoặc `dismissed`. Tỉ lệ trả lời được báo
  cáo theo kết quả ván và theo cách ván kết thúc.

### Làm mù

- Trước khi trả lời hoặc bỏ qua, người chơi không thấy đánh giá engine, accuracy, số blunder hay biểu đồ đồng hồ
  của ván đó.
- Trong suốt đợt thu, tab "Tilt", điểm của mô hình và cảnh báo "nhiều ván bị flag liên tiếp" bị tắt với tài khoản
  tham gia.
- Người chơi luôn biết kết quả ván. Điều này không ẩn được và là một giới hạn của nhãn.

### Trường dữ liệu

| Trường | Kiểu | Ghi chú |
|---|---|---|
| `player_id` | chuỗi | HMAC-SHA256 của định danh với `TILT_SALT` (`labels.pseudonym` / `labels.private_id`) |
| `game_id` | chuỗi | id ván trong hệ thống nguồn |
| `segment_start`, `segment_end` | số nguyên (nửa nước) | mặc định là cả ván; khác đi khi người chơi đánh dấu một đoạn |
| `anger_self_report` | 0–10 | nhãn chính |
| `frustration_self_report` | 0–10 | phụ |
| `tilt_score` | 0–10 | phụ |
| `confidence` | 1–5 | phụ |
| `timestamp`, `report_ms` | thời gian UTC | lúc gửi báo cáo |
| `delay_seconds` | số thực | từ lúc ván kết thúc tới lúc gửi |
| `channel` | `lila_prompt` \| `label_app` | |
| `saw_eval` | đúng/sai | đã xem thông tin engine của ván trước khi trả lời hay chưa |
| `prompt_status` | `answered` \| `skipped` \| `dismissed` | ghi cả prompt không được trả lời |
| `source` | `self_report` | giá trị duy nhất được nhận làm nhãn cảm xúc |
| `consent_version` | chuỗi | phiên bản văn bản đồng thuận đã chấp nhận |

Bảng `labels` hiện tại chưa có `anger_self_report`, `frustration_self_report`, `confidence`, `channel`, `saw_eval`
và `prompt_status`; mục tức giận và bực bội đang là Likert 1–5 trong `questionnaire_json`, còn `tilt_score` là bắt
buộc. Việc mở rộng lược đồ thuộc phase triển khai, không thuộc Phase 4.

### Quy mô và điều kiện dừng

- Pilot: 10–15 người, mỗi người ít nhất 20 ván rated được hỏi. Pilot chỉ kiểm tra tính khả thi: tỉ lệ trả lời, phân
  bố điểm tức giận, tỉ lệ ván có tức giận ≥ 5, số ván tính được feature. Pilot không dùng để kết luận về mô hình.
- Đợt thu dừng theo một ngày hoặc một số báo cáo định trước. Trong lúc thu không so điểm mô hình với nhãn người.

### Đồng thuận và riêng tư

- Văn bản đồng thuận có phiên bản riêng cho việc hỏi cảm xúc sau ván (đề xuất tên `research-v3-emotion`, chưa có
  trong code); bản `draft-research-v2-oauth` không bao trùm việc này. Mỗi báo cáo lưu phiên bản đã chấp nhận, và đổi
  văn bản thì phải xin đồng thuận lại.
- Người tham gia từ 18 tuổi, tự nguyện, không gắn với điểm số hay phần thưởng. Họ được bỏ qua bất kỳ câu nào và
  được rút lui bất kỳ lúc nào; khi rút lui, mọi báo cáo của họ bị xóa.
- `TILT_SALT` không được commit hay in ra. Câu trả lời thô chỉ nằm ở `tilt/data/raw/labels` trong WSL: không commit,
  không chép sang Windows.
- Báo cáo chỉ nêu số liệu gộp, không có bảng theo từng người.
- Các câu hỏi không phải thang đo tâm lý đã được chuẩn hóa và không dùng để chẩn đoán.
- Giao thức này chưa qua hội đồng đạo đức nào. Nhóm cần hỏi giảng viên hướng dẫn về thủ tục trước khi thu.

### Giới hạn đã biết

- Người tham gia là một nhóm nhỏ, quen nhau, chơi trên fork chạy local. Họ không đại diện cho người chơi blitz
  trên Lichess mà mô hình được huấn luyện.
- Người bỏ ván vì tức giận có thể không trả lời prompt, nên dữ liệu thiếu không ngẫu nhiên.
- Việc bị hỏi sau ván có thể làm người chơi thay đổi cách chơi.
- Tự báo cáo một mục, một lần, chịu ảnh hưởng của kết quả ván và của cách mỗi người dùng thang điểm.

## 9. Thiết kế đánh giá với nhãn thật

Chưa có nhãn thật, nên phần này chưa có kết quả. Cho tới khi có: **mô hình dự đoán một proxy hành vi của tilt,
chưa được kiểm chứng độc lập với sự tức giận** (The model predicts a behavioral proxy of tilt, not independently
validated anger).

### Nguyên tắc

- Nhãn người chỉ dùng để đánh giá. Không huấn luyện, không chọn feature, không chọn ngưỡng và không hiệu chỉnh lại
  trên nhãn người. Muốn làm các việc đó thì cần một phase riêng, có đăng ký trước.
- Mô hình, feature và ngưỡng được đóng băng trước khi so với nhãn người. Phép so chạy đúng một lần.
- Đánh giá này không mở tập test nhãn yếu đang niêm phong, và không sửa LF hay nhãn yếu.

### Dữ liệu được tính

- Phân tích chính chỉ gồm ván có báo cáo ≤ 5 phút, `saw_eval = false`, chơi sau thời điểm đóng băng mô hình và tính
  được đủ feature của mô hình.
- Ván không tính được feature (ví dụ người chơi chưa đủ lịch sử để tính độ lệch so với mức quen thuộc) bị loại và
  được đếm trong báo cáo.
- Người tham gia có tài khoản nằm trong dữ liệu huấn luyện được tách thành tầng "người đã thấy" và không vào phân
  tích chính. Việc đối chiếu dùng id đã băm.
- Mọi khoảng tin cậy dùng bootstrap theo cụm người chơi.

### Đối tượng so sánh

| Đối tượng | Vai trò |
|---|---|
| P3-B (mô hình chính cuối Phase 3) | mô hình chính |
| M3 | mô hình phụ |
| B-result (chỉ dùng kết quả ván) | mốc quan trọng nhất |
| B-length (chỉ dùng độ dài ván) | mốc |
| Nhãn yếu Dawid–Skene | mốc: nhãn mà mô hình học theo |

### Chỉ số

- Chính: PR-AUC của P3-B trên nhãn "tức giận ≥ 5", kèm tỉ lệ dương và khoảng tin cậy 95%.
- So sánh then chốt: chênh lệch PR-AUC ghép cặp giữa P3-B và B-result, và giữa P3-B và B-length. Mục 2 cho thấy
  nhãn yếu gắn chặt với việc thua, nên mô hình chỉ có giá trị nếu hơn được "ván này thua".
- Phụ:
  - ROC-AUC;
  - tương quan Spearman giữa điểm mô hình và điểm tức giận 0–10, tính chung và tính sau khi chuẩn hóa điểm theo
    từng người;
  - cùng các chỉ số trên với nhãn bực bội và điểm tilt;
  - độ nhạy với ngưỡng 4 và 6;
  - nhóm báo cáo trễ, tính riêng.
- Calibration chỉ mang tính mô tả (biểu đồ độ tin cậy). Mô hình xuất xác suất của nhãn yếu, không phải xác suất tức
  giận, nên không kỳ vọng nó khớp.

### Phân tích theo tầng

Các tầng dưới đây lặp lại năm câu hỏi của mục 2–6, lần này với nhãn thật:

- chỉ trong các ván thua, và riêng các ván thắng/hòa: điểm mô hình còn phân biệt được tức giận hay không;
- ván từ 40 nửa nước trở lên và ván ngắn hơn;
- theo mức chơi kém so với mức quen thuộc của chính người chơi;
- theo áp lực đồng hồ và theo cách ván kết thúc (hết giờ, xin thua, bỏ ván);
- theo tỉ lệ nước tấn công;
- theo nhóm rating. Thể loại thời gian chỉ xét được nếu dữ liệu thu có nhiều hơn một thể loại.

### Đánh giá nhãn yếu

- Với từng LF: trong các ván nó bỏ phiếu, bao nhiêu phần trăm có tức giận ≥ 5 (LF TILT) hoặc < 5 (LF NOT), kèm số
  ván nó bỏ phiếu.
- Với nhãn Dawid–Skene: precision, recall và độ phủ so với nhãn người.
- Với các ván không LF nào bỏ phiếu (71% số dòng train): tỉ lệ tức giận ≥ 5, để biết nhãn yếu bỏ sót những gì.
- Các kết quả này chỉ được ghi nhận. Mọi thay đổi LF hoặc nhãn thuộc về một phase khác.

### Cỡ mẫu và cách diễn giải

- Điều kiện tối thiểu để báo PR-AUC là kết quả chính: ít nhất 50 ván có tức giận ≥ 5, ít nhất 200 ván âm, từ ít
  nhất 10 người, trong đó ít nhất 5 người có từ 3 ván dương trở lên.
- Mục tiêu: 100 ván dương từ ít nhất 20 người.
- Dưới 30 ván dương: chỉ báo cáo mô tả, không kết luận về mô hình.
- Ước tính sơ bộ độ rộng khoảng tin cậy, theo công thức Hanley–McNeil cho ROC-AUC, giả định AUC 0,70 và tỉ lệ dương
  10%, coi các ván độc lập (đây là ước tính, không phải kết quả đo):

  | Số ván dương | Nửa độ rộng CI 95% |
  |---|---|
  | 30 | khoảng ±0,11 |
  | 50 | khoảng ±0,08 |
  | 100 | khoảng ±0,06 |

  Khoảng tin cậy thật sẽ rộng hơn vì các ván cụm theo người chơi, và PR-AUC thường dao động nhiều hơn ROC-AUC.
- Tỉ lệ ván có tức giận ≥ 5 chưa được đo. Nếu nó vào khoảng 10–15% thì pilot 240–300 báo cáo chỉ cho 25–45 ván
  dương, tức là chưa đủ cho kết luận chính.
- Cách diễn giải được cố định trước:
  - Nếu P3-B không hơn B-result (khoảng tin cậy của chênh lệch chứa 0), kết luận là chưa có bằng chứng mô hình đo
    được gì ngoài kết quả ván.
  - Nếu P3-B hơn B-result, kết luận chỉ áp dụng cho nhóm người tham gia và thể loại thời gian đã thu, không khái
    quát cho người chơi Lichess nói chung.
