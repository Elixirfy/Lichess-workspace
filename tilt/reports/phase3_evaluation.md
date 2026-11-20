# Phase 3: đánh giá biến thể hành vi

Ngày 2026-11-14. Biến thể và quy tắc nằm trong `phase3_preregistration.md`, viết trước khi chạy. Chạy trên Colab
(xgboost 2.1.4, scikit-learn 1.6.1), 1.000 lần bootstrap theo cụm người chơi, seed 42, mất 32 s.

- Code: `src/tilt/evaluation/phase3.py`, test ở `tests/unit/test_phase3.py` (10 test).
- Bảng số: `phase3_metrics.csv`.
- Kết quả đầy đủ chỉ nằm trong WSL, ở `~/tilt-phase3/out/phase3_results.json` (sha256 `64ea8c0f…`), cùng dự đoán
  validation.

Kết quả là dự đoán nhãn yếu, không phải phát hiện tức giận. Mọi số đều trên validation; test vẫn niêm phong.

## Kiểm tra trước

| Kiểm tra | Kết quả |
|---|---|
| Manifest split trùng Phase 1 | đạt ở cả hai split (`3243a255…`, `034a3e09…`) |
| M3 chạy lại trong ±0,005 của 0,449 / 0,370 | đạt: 0,44902 / 0,37035 |
| Số lần bootstrap bị bỏ (chính / phụ) | 0 / 0 ở cả hai split |

## Kết quả

PR-AUC trên validation, kèm khoảng tin cậy 95% bootstrap. Tỉ lệ lớp:

- mọi dòng có nhãn: 0,137 ở cả hai split;
- ván ≥ 40 nửa nước: 0,079 (A) và 0,093 (B).

**A = by_player** (n = 1.922; ≥ 40 nửa nước: 1.802)

| Mô hình | Cột | Chính | ≥ 40 nửa nước | ROC-AUC | η² điểm ~ độ dài |
|---|---|---|---|---|---|
| M3 | 8 | 0,449 [0,343; 0,538] | 0,137 [0,097; 0,209] | 0,729 | 0,226 |
| P3-D | 12 | 0,588 [0,487; 0,666] | 0,145 [0,102; 0,214] | 0,805 | 0,355 |
| P3-R | 8 | 0,504 [0,427; 0,574] | 0,098 [0,075; 0,130] | 0,726 | 0,079 |
| P3-B | 11 | 0,528 [0,428; 0,609] | 0,160 [0,107; 0,237] | 0,774 | 0,332 |
| P3-DB | 15 | 0,611 [0,516; 0,683] | 0,166 [0,115; 0,247] | 0,812 | 0,449 |
| B-length | 1 | 0,656 [0,564; 0,723] | 0,150 [0,102; 0,218] | 0,826 | 0,862 |

**B = by_time** (n = 1.549; ≥ 40 nửa nước: 1.474)

| Mô hình | Cột | Chính | ≥ 40 nửa nước | ROC-AUC | η² điểm ~ độ dài |
|---|---|---|---|---|---|
| M3 | 8 | 0,370 [0,299; 0,445] | 0,149 [0,115; 0,203] | 0,692 | 0,222 |
| P3-D | 12 | 0,488 [0,413; 0,567] | 0,163 [0,123; 0,217] | 0,743 | 0,362 |
| P3-R | 8 | 0,462 [0,383; 0,536] | 0,108 [0,079; 0,149] | 0,672 | 0,068 |
| P3-B | 11 | 0,437 [0,365; 0,511] | 0,153 [0,119; 0,212] | 0,713 | 0,312 |
| P3-DB | 15 | 0,520 [0,448; 0,590] | 0,169 [0,129; 0,225] | 0,754 | 0,449 |
| B-length | 1 | 0,608 [0,539; 0,671] | 0,216 [0,157; 0,295] | 0,816 | 0,865 |

**Chênh lệch ghép cặp so với M3**: ước lượng điểm [CI 95%].

| Biến thể | Chính A | Chính B | ≥ 40 nửa nước A | ≥ 40 nửa nước B |
|---|---|---|---|---|
| P3-D | +0,137 [0,104; 0,170] | +0,118 [0,080; 0,159] | +0,008 [−0,009; 0,026] | +0,014 [−0,002; 0,033] |
| P3-R | +0,055 [−0,015; 0,137] | +0,091 [0,020; 0,160] | −0,040 [−0,098; 0,004] | −0,041 [−0,090; 0,000] |
| P3-B | +0,078 [0,057; 0,103] | +0,065 [0,031; 0,098] | +0,022 [0,001; 0,045] | +0,005 [−0,017; 0,026] |
| P3-DB | +0,160 [0,120; 0,201] | +0,147 [0,100; 0,196] | +0,030 [0,004; 0,060] | +0,019 [−0,008; 0,047] |

**Áp quy tắc một cách cơ học:**

- P3-D, P3-B và P3-DB đạt cả 1a, 1b và 1c.
- Mục 3 chọn P3-D: P3-DB cao nhất (0,611); P3-D kém nó dưới 0,05 và có ít cột hơn; P3-B (0,528) không nằm trong
  khoảng 0,05.
- P3-R đạt mục 2, nhưng không phải mô hình chính vì đã có biến thể thêm feature được nhận.

## Chẩn đoán hậu nghiệm

Các chẩn đoán dưới đây làm sau khi đã thấy kết quả validation. Chúng chỉ để ghi nhận, không dùng để chọn mô hình tốt
hơn. Phần chạy trên validation chỉ đọc số nửa nước, không đọc nhãn.

**1. Điểm của mô hình tách ván dưới 40 nửa nước đến mức nào.** Đo bằng max(AUC, 1 − AUC). Ván ngắn chiếm 6,2% (A)
và 4,8% (B) validation.

| | M3 | P3-D | P3-R | P3-B | P3-DB | B-length |
|---|---|---|---|---|---|---|
| A | 0,836 | 0,980 | 0,944 | 0,925 | 0,983 | 1,0 |
| B | 0,850 | 0,978 | 0,983 | 0,921 | 0,981 | 1,0 |

**2. Từng input riêng lẻ, trên train.** Khả năng tách ván dưới 40 nửa nước:

- tỉ lệ cả ván: 0,52–0,68 (`defensive_rate` 0,676);
- tỉ lệ p40: 0,50–0,55;
- `risk_volatility_3w`: 0,68; `attack_trend_3w` và `behavior_change_point`: 0,54.

Từng cột p40 riêng lẻ gần như không tách được, nhưng mô hình có chúng thì tách gần hoàn hảo.

**3. Cơ chế của nhóm D, kiểm chứng trên train ở cả hai split, không đọc nhãn.**

| | Ván < 40 nửa nước | Ván ≥ 40 nửa nước |
|---|---|---|
| p40 bằng tỉ lệ cả ván (cả 4 tỉ lệ) | 100% | khoảng 2% |
| Cả 4 giá trị p40 là bội của 1/20 | 18% | 100% |

Với ván ≥ 40 nửa nước, tiền tố luôn có đúng 20 nước của mình. Với ván ngắn, tiền tố là cả ván. Vì vậy nhóm D mã hóa
"ván dưới 40 nửa nước" theo cấu tạo.

Cơ chế của nhóm B (tỉ lệ tính trên ít nước nên dao động mạnh) mới là giả thuyết, chưa kiểm chứng.

## Thay đổi sau đăng ký

Có một thay đổi, thực hiện sau khi đã thấy kết quả validation. Danh sách biến thể, metric, quy tắc và các bảng số không
đổi; không chạy lại mô hình nào. Fable 5.2 quyết định thay đổi này, theo cách làm người dùng đã giao.

**Vô hiệu việc nhận các biến thể chứa nhóm D (P3-D, P3-DB); rút nhãn "ít phụ thuộc độ dài" của P3-R.**

- Theo quy tắc: P3-D, P3-B, P3-DB được nhận; mô hình chính là P3-D.
- Sau thay đổi: chỉ P3-B được nhận; mô hình chính là P3-B.
- Lý do: 4 cột `*_p40` mã hóa "ván dưới 40 nửa nước" theo cấu tạo. Kiểm tra trên train, không đọc nhãn, ở cả hai split:
  - ván dưới 40 nửa nước: p40 bằng đúng tỉ lệ cả ván ở 100% dòng, trên cả 4 tỉ lệ; ván ≥ 40 nửa nước: khoảng 2%;
  - ván ≥ 40 nửa nước: cả 4 giá trị p40 là bội của 1/20 ở 100% dòng (tiền tố luôn có đúng 20 nước của mình); ván dưới
    40 nửa nước: 18%.
- Ngưỡng 40 trùng ngưỡng mà mọi LF bỏ phiếu NOT đòi hỏi, nên dòng có nhãn dưới 40 nửa nước 100% là TILT. Đây là lỗi
  định nghĩa feature của Phase 2, không phải tương quan thống kê. Báo cáo Phase 2 có ghi tiền tố chỉ khác nhau ở ván
  dưới 40 nửa nước nhưng bỏ sót hệ quả này; mục 1 của bản đăng ký nhận nhóm D dựa trên tiền đề sai đó.
- Căn cứ: cùng nguyên tắc đã dùng ở mục 1 bản đăng ký để bỏ chỉ báo thiếu của nhóm B ("thiếu ⇔ ván ngắn ⇒ 100% TILT").
  Không thêm quy tắc chọn mới.
- Hướng của thay đổi: bảo thủ. PR-AUC chính của mô hình chính giảm từ 0,588 xuống 0,528 (A) và từ 0,488 xuống 0,437
  (B).
- Bằng chứng đi kèm là chẩn đoán hậu nghiệm 1 ở trên, chỉ ghi nhận.
- Không sửa định nghĩa nhóm D và không chạy lại trong Phase 3. Nhóm D bị rút khỏi danh sách ứng viên. Mọi định nghĩa
  thay thế phải được đăng ký trước ở phase sau và qua audit cấu trúc.

**Điểm yếu của bản đăng ký, ghi lại và không sửa:** mục 1c chỉ đòi ước lượng điểm của Δ trên ván ≥ 40 nửa nước > 0,
không đòi CI. P3-B đạt 1c ở split B với +0,005 [−0,017; 0,026]. P3-B vẫn được giữ là "được nhận" vì chưa có lỗi cấu trúc
nào được kiểm chứng ở nhóm B.

## Kết luận

- Kiểm tra tái lập M3 đạt (0,449 / 0,370). Manifest split trùng Phase 1. Không lần bootstrap nào bị bỏ.
- Áp quy tắc đã đăng ký một cách cơ học thì P3-D, P3-B và P3-DB đều đạt mục 1, và mục 3 chọn P3-D. Kết quả này được
  giữ nguyên trong các bảng.
- Việc nhận P3-D và P3-DB bị vô hiệu vì nhóm D có lỗi cấu tạo (xem "Thay đổi sau đăng ký"). Mức tăng của P3-D gần như
  chỉ đến từ ván dưới 40 nửa nước:
  - Δ chính: +0,137 [0,104; 0,170] ở A và +0,118 [0,080; 0,159] ở B;
  - trên ván ≥ 40 nửa nước: +0,008 [−0,009; 0,026] và +0,014 [−0,002; 0,033], không phân biệt được với 0.
- Mô hình chính cuối Phase 3 là P3-B (M3 + `attack_trend_3w`, `risk_volatility_3w`, `behavior_change_point`), biến thể
  duy nhất còn đạt mục 1.
  - PR-AUC chính: 0,528 [0,428; 0,609] ở A và 0,437 ở B.
  - Δ so với M3: +0,078 [0,057; 0,103] ở A, +0,065 [0,031; 0,098] ở B.
- Giới hạn của P3-B: phần lớn mức tăng đến từ ván ngắn.
  - Trên ván ≥ 40 nửa nước, Δ là +0,022 [0,001; 0,045] ở A và +0,005 [−0,017; 0,026] ở B (không phân biệt được).
  - Điểm của P3-B tách ván dưới 40 nửa nước với AUC 0,925 / 0,921, so với 0,836 / 0,850 của M3.
  - Cơ chế (tỉ lệ tính trên ít nước nên dao động mạnh) mới là giả thuyết, chưa kiểm chứng.
- P3-R đạt mục 2 về mặt cơ học nhưng không phải mô hình chính, và không còn được coi là mốc "ít phụ thuộc độ dài".
  - η² của nó chỉ 0,079 / 0,068, nhưng điểm của nó tách ván dưới 40 nửa nước với AUC 0,944 / 0,983.
  - So với M3, P3-R không phân biệt được ở A (+0,055 [−0,015; 0,137]) và thấp hơn về ước lượng điểm trên ván ≥ 40 nửa
    nước (−0,040 / −0,041).
- Không biến thể nào vượt B-length trên chỉ số chính (0,656 / 0,608). Chỉ dùng độ dài ván vẫn dự đoán nhãn yếu tốt hơn
  mọi mô hình hành vi. Trên ván ≥ 40 nửa nước, mọi mô hình có PR-AUC 0,10–0,22 với tỉ lệ lớp 0,079 / 0,093.
- Phase 3 không chọn mô hình cuối. M3 được giữ làm mốc so sánh cho các phase sau. Nếu người dùng muốn thận trọng hơn,
  có thể mang M3 đi tiếp thay cho P3-B; đó là quyết định khi duyệt, không phải kết quả của Phase 3.

## Bài học và chốt chặn cho các phase sau

- **Audit cấu trúc** cho mọi feature mới, trên train, không đọc nhãn. Xét mẫu số, độ mịn của giá trị, quan hệ bằng
  nhau với feature khác, giá trị thiếu và giá trị điền. Loại feature nếu theo cấu tạo nó nhận ra được ván dưới 40 nửa
  nước.
- **Audit từng feature riêng lẻ là không đủ.** Từng cột p40 chỉ có AUC 0,50–0,55, nhưng kết hợp với tỉ lệ cả ván thì
  điểm mô hình đạt 0,98. Phải kiểm tra cả tổ hợp với các cột đã có.
- **Với mọi mô hình**, báo AUC của điểm số khi tách ván dưới 40 nửa nước, cạnh η². η² theo thập phân vị không nhạy với
  một nhóm chỉ chiếm 5–6%.
- **Quy tắc nhận về sau** nên đòi cận dưới CI của Δ trên ván ≥ 40 nửa nước > 0, không chỉ ước lượng điểm. PR-AUC chính
  bị ván ngắn chi phối: chúng chiếm 6,2% / 4,8% số dòng nhưng 100% là dương.
- **Chẩn đoán làm sau khi thấy kết quả** phải ghi rõ là hậu nghiệm và không dùng để chọn mô hình tốt hơn.

Dừng ở đây, chờ người dùng duyệt.
