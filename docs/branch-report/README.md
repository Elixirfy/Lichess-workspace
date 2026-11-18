# Chơi cờ bằng giọng nói tiếng Việt và ưu thế live

## Thông tin phiên bản và mục đích tài liệu

- Branch: `codex/vietnamese-voice-input`.
- Mã nguồn khảo sát: [`162bd1c1ae8ad6a2780698f18e5f8d8e61f29d4a`](https://github.com/trantrien1/Lichess-workspace/commit/162bd1c1ae8ad6a2780698f18e5f8d8e61f29d4a).
- Ngày tổng hợp: **18/11/2026**. Tài liệu này phục vụ mô tả/so sánh trong báo cáo; không phải một benchmark mới.
- Nhánh có bản triển khai Vosk + PhoWhisper, không cần LLM để hiểu lệnh; câu hợp lệ đi ngay. Nhánh kế thừa prediction và cập nhật panel hai màu cho cả người chơi lẫn người xem. Đây là nhánh đang phục vụ stack Windows local trong phiên làm việc này.

## 1. Bài toán và mục tiêu

Cho phép người Việt nói nước đi với nhiều cách gọi quân, cột và hàng; kiểm tra từ âm thanh nguyên câu tới nước đi chính thức và bot đáp. Đồng thời trình bày ưu thế hai bên bằng điểm kỳ vọng để tránh khuếch đại các dự đoán gần hòa.

## 2. Chức năng đã có trên nhánh

Giữ Shift, đọc “Tốt bê hai tới bê bốn” rồi thả. Vosk xử lý trước; câu chưa được parser xử lý sẽ được nhận lại bằng PhoWhisper local. Nước duy nhất và hợp lệ được gửi ngay, không hỏi xác nhận. Sai luật/chưa hiểu hiện thông báo; mơ hồ yêu cầu nói rõ nguồn. Có trang Thu mẫu để lưu nguyên câu khi người dùng chủ động bấm lưu. Hỗ trợ nhập thành, phong cấp và các cách nói B/D đã ghi trong báo cáo.

## 3. Kiến trúc và cách triển khai

```text
Microphone → VAD/PCM → Vosk → parser gắn các nước hợp lệ → PhoWhisper fallback khi cần → kiểm tra lượt/thế cờ → gửi nước → server/WebSocket → bot đáp.
```

Mở tiếng Việt khỏi danh sách chỉ có ở debug; thêm bộ chuẩn hóa, grammar theo thế cờ và parsing có ràng buộc. Không biến một mẩu câu sai/thiếu thành nước hợp lệ; chống gửi trùng và phản hồi ASR thuộc vị trí cũ. Dịch vụ `services/voice` chạy local; model/checksum được ghim. Panel live giữ raw WDL, hiển thị Trắng = W+D/2 và Đen = B+D/2, tổng 100%. Trên bàn chỉ còn thanh và hai số; nguồn và cách tính nằm trong tooltip. Kết quả chính thức vẫn ưu tiên.

## 4. Ưu điểm so với tính năng có sẵn

| Tính năng có sẵn / mốc trước | Phần bổ sung | Ưu điểm và giới hạn |
|---|---|---|
| Upstream đã có voice input; tiếng Việt có grammar/lexicon nhưng chỉ xuất hiện khi debug | Bật tiếng Việt để dùng trực tiếp, bổ sung parser, grammar theo thế cờ và nhiều câu tự nhiên | Mở rộng hệ thống có sẵn, không phải xây voice input từ đầu |
| Nhận dạng Vosk đơn lẻ | PhoWhisper nhận lại cùng audio khi parser chưa xử lý | Có đường phục hồi cho lỗi nhận âm; thêm chi phí CPU/độ trễ khi fallback |
| Người dùng phải xác nhận ở bản thử nghiệm trước | Câu rõ/hợp lệ đi ngay | Ít thao tác hơn; nếu ASR nhầm thành một nước hợp lệ khác thì vẫn có rủi ro đi nhầm |
| Kiểm thử transcript hoặc từ rời | Bản thu nguyên câu → ASR production → server move → bot | Đánh giá trọn luồng, không chỉ parser; tập hiện tại vẫn là dữ liệu phát triển của một người |
| W/(W+B) bỏ hòa gây 0/100 ở thế gần hòa | W+D/2, B+D/2 | Giữ ý nghĩa điểm kỳ vọng: ví dụ 0/87,6/12,4 thành 43,8/56,2; không phải chứng minh model dự đoán chính xác hơn |
| Analysis có thanh dọc đánh giá | Live panel trên cả hai bàn standard | Không phải mở tab người xem; analysis-page integration vẫn chưa triển khai |

Các nhận định “ít thao tác”, “thêm kênh nghe”, “dùng chung công việc” mô tả thiết kế/hành vi có trong code. Không chuyển chúng thành số liệu tăng năng suất, độ chính xác hoặc chất lượng học tập khi chưa có phép đo đối chứng.

## 5. Kết quả kiểm thử và bằng chứng

| Mốc đã có bằng chứng | Kết quả và cách diễn giải |
|---|---|
| `reports/voice-v1/direct-moves/`: audio người thật nguyên câu | 25/25 ca, gồm ca âm tính; 18 ca có nước người chơi và bot đáp, không phải 25 ca đều đi quân |
| Phạm vi bộ audio | Một người nói, đã dùng tinh chỉnh; không phải holdout hay độ chính xác cho mọi giọng |
| Cập nhật UI gọn hiện tại | 19/19 focused, 341/341 frontend; build/lint/stylelint/format đạt |
| Browser UI gọn | PvP có tài khoản 164 assertion, 44 mẫu từ hai bàn; bot hai màu, chín mẫu; không JS exception |
| Patch replay | Khớp 40 đường dẫn với hai patch; voice patch giữ nguyên sau đổi phần tỷ lệ |

## 6. Cách dựng và thử lại

```powershell
.\scripts\dev.ps1 bootstrap
.\scripts\dev.ps1 start
.\scriptsoice.ps1 live
node scripts/voice-recorded-e2e.mjs --direct --files --bot
```

Mở `http://localhost:8080`, tạo ván standard với bot, bật tiếng Việt và cho phép microphone. Ctrl+F5 sau cập nhật bundle. Trang thu: `http://localhost:8080/voice-asr/record`. Lệnh e2e cần bản thu local đã lưu; WAV riêng không được đưa lên Git. Xem hướng dẫn chi tiết trước khi cài model lần đầu.

## 7. Giới hạn và điểm chưa hoàn thành

Chưa kiểm tra rộng theo vùng miền, nhiều người nói hoặc nhiễu thực tế; không suy rộng 25/25 thành 100% ASR. Cột B/D, số và câu phong cấp vẫn phụ thuộc âm thanh/ngữ cảnh. Không có bước xác nhận cho nước đi nên thao tác ít hơn nhưng cần đánh giá tỷ lệ false acceptance. Không dùng LLM trong hiểu lệnh. Prediction/human model giữ giới hạn model card; engine không xét cấp độ bot. Mốc audio là bằng chứng lịch sử; lần bỏ chú thích chỉ chạy lại UI/PvP/bot, không chạy lại ASR.

## 8. Hướng phát triển và điểm cần đối chiếu

Thanh dọc Stockfish khi xem lại có thể dùng để biểu diễn ưu thế cho nước đang chọn. Nó hiện dùng logistic của cp/mate, còn panel này dùng W+D/2. Nếu tích hợp cần chọn cùng nguồn/thước đo, xử lý đổi hướng và bước replay; không gán kết quả cuối ván cho mọi vị trí quá khứ. Chưa có triển khai mới trên analysis page trong thay đổi này.

## 9. Tệp nguồn quan trọng ở đúng revision

- [`services/voice/app/main.py`](https://github.com/trantrien1/Lichess-workspace/blob/162bd1c1ae8ad6a2780698f18e5f8d8e61f29d4a/services/voice/app/main.py)
- [`services/voice/app/recognizer.py`](https://github.com/trantrien1/Lichess-workspace/blob/162bd1c1ae8ad6a2780698f18e5f8d8e61f29d4a/services/voice/app/recognizer.py)
- [`services/voice/app/recordings.py`](https://github.com/trantrien1/Lichess-workspace/blob/162bd1c1ae8ad6a2780698f18e5f8d8e61f29d4a/services/voice/app/recordings.py)
- [`scripts/voice.ps1`](https://github.com/trantrien1/Lichess-workspace/blob/162bd1c1ae8ad6a2780698f18e5f8d8e61f29d4a/scripts/voice.ps1)
- [`scripts/voice-recorded-e2e.mjs`](https://github.com/trantrien1/Lichess-workspace/blob/162bd1c1ae8ad6a2780698f18e5f8d8e61f29d4a/scripts/voice-recorded-e2e.mjs)
- [`patches/lila-vietnamese-voice.patch`](https://github.com/trantrien1/Lichess-workspace/blob/162bd1c1ae8ad6a2780698f18e5f8d8e61f29d4a/patches/lila-vietnamese-voice.patch)
- [`patches/lila-win-probability.patch`](https://github.com/trantrien1/Lichess-workspace/blob/162bd1c1ae8ad6a2780698f18e5f8d8e61f29d4a/patches/lila-win-probability.patch)
- [`reports/voice-v1/direct-moves/README.md`](https://github.com/trantrien1/Lichess-workspace/blob/162bd1c1ae8ad6a2780698f18e5f8d8e61f29d4a/reports/voice-v1/direct-moves/README.md)
- [`reports/acceptance/compact-advantage/validation.json`](https://github.com/trantrien1/Lichess-workspace/blob/162bd1c1ae8ad6a2780698f18e5f8d8e61f29d4a/reports/acceptance/compact-advantage/validation.json)

## 10. Dùng tài liệu này khi viết báo cáo

Có thể dùng mục 1–2 cho bài toán/phạm vi, mục 3 cho thiết kế, mục 4 cho đóng góp và so sánh, mục 5 cho thực nghiệm, mục 7–8 cho hạn chế/hướng phát triển. Khi trích số đo, giữ nguyên tên branch, snapshot, tập kiểm thử và điều kiện máy; phân biệt số đã lưu với số vừa chạy. Không cộng các lần kiểm thử lặp thành số mẫu độc lập.

README này được tổng hợp với sự hỗ trợ của Codex. Tài liệu không suy đoán tác giả của mọi phần mã nguồn hoặc việc đã đóng góp lên upstream. Đối chiếu Lichess tại revision đã ghim thay vì khẳng định phiên bản hiện tại hoàn toàn chưa có tính năng tương tự.

- [Luồng đi ngay và audio thật](../../reports/voice-v1/direct-moves/README.md)
- [Giao diện tỷ lệ hiện tại](../../reports/acceptance/compact-advantage/README.md)
- [So sánh ASR trước đây](../../reports/voice-v1/asr-comparison/README.md)
- [Model card prediction](../../reports/human-v1/model-card.md)

Nguồn đối chiếu thanh analysis: [renderGauge](https://github.com/lichess-org/lila/blob/4eea97abce686a1cc6b07abe54cce9e10c223227/ui/lib/src/ceval/view/main.ts), [biến đổi cp/mate](https://github.com/lichess-org/lila/blob/4eea97abce686a1cc6b07abe54cce9e10c223227/ui/lib/src/ceval/winningChances.ts).

Nguồn đối chiếu voice input sẵn có: [danh sách ngôn ngữ](https://github.com/lichess-org/lila/blob/4eea97abce686a1cc6b07abe54cce9e10c223227/ui/voice/src/languages.ts), [grammar và lexicon](https://github.com/lichess-org/lila/blob/4eea97abce686a1cc6b07abe54cce9e10c223227/ui/voice/README.md).
