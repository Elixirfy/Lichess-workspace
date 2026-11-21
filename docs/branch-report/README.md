# Chơi cờ bằng giọng nói tiếng Việt

Tính năng cho phép người chơi đọc nước đi bằng tiếng Việt ngay trên bàn cờ.
Câu lệnh có thể ngắn như “mã ép ba”, hoặc đầy đủ như “tốt từ cột bê hàng hai
đến cột bê hàng bốn”. Nếu xác định được duy nhất một nước hợp lệ, hệ thống
gửi nước đi ngay và chờ đối thủ trả lời.

Phần này nằm trên nhánh `codex/vietnamese-voice-input`.
[Win% lúc chơi và xem lại](https://github.com/trantrien1/Lichess-workspace/blob/main/docs/branch-report/README.md)
thuộc phần dùng chung trên `main`.

## Cơ sở phát triển

Bản Lichess dùng làm nền đã có chức năng voice, cơ chế lấy âm thanh từ mic và
nhận dạng bằng Vosk. Phần mở rộng bổ sung bộ từ vựng, cách đọc tọa độ và bộ
phân tích câu lệnh cờ tiếng Việt. PhoWhisper được thêm làm bộ nhận dạng thứ hai
để xử lý những câu mà Vosk chưa nhận được rõ.

Việc chọn nước dựa trên câu nói và danh sách nước hợp lệ của thế cờ hiện tại.
Cách này tận dụng luật cờ để thu hẹp lựa chọn, đồng thời vẫn kiểm tra được vì
sao một câu được hiểu thành nước đi cụ thể. Hệ thống hiện chưa dùng LLM.

## Từ câu nói đến nước đi

1. Trình duyệt thu âm và đưa vào Vosk với bộ câu lệnh theo thế cờ.
2. Nếu kết quả chưa xử lý được, PhoWhisper nhận dạng lại âm thanh. Dịch vụ này
   dùng VAD để kiểm tra có tiếng nói và đưa âm thanh về 16 kHz.
3. Bộ phân tích chuẩn hóa tên quân, cột, hàng và các từ chỉ hành động.
4. Kết quả được đối chiếu với các nước hợp lệ. Một nước duy nhất được gửi lên
   server; trường hợp còn nhiều lựa chọn cần người chơi chọn rõ hơn.

Kết quả nhận dạng gắn với lượt và vị trí đang chơi. Khi đổi thế cờ, mất kết nối
hoặc kết thúc ván, kết quả đang chờ được hủy để tránh dùng cho một vị trí khác.

## Các cách nói được hỗ trợ

| Nhóm lệnh | Ví dụ |
|---|---|
| Tên quân và ô đích | “Mã nhảy lên ép ba” |
| Ô xuất phát và ô đích | “Tốt trắng e hai e bốn” |
| Nói đầy đủ cột, hàng | “Tốt từ cột bê hàng hai đến cột bê hàng bốn” |
| Cột bằng số | “Tốt từ cột hai hàng hai đến cột hai hàng bốn” |
| Nhập thành | “Nhập thành ngắn” |
| Phong cấp | “Tốt e bảy tới e tám phong cấp thành hậu” |

Cột B/D hỗ trợ các cách đọc “bê/đê”, “bờ/dờ”, “bi/đi” và số thứ tự cột.
Nhập thành, ăn quân và phong cấp đều phải phù hợp với thế cờ đang chơi.

## Ưu điểm so với tính năng có sẵn

| Nội dung | Phần bổ sung |
|---|---|
| Ngôn ngữ | Bộ lệnh cờ tiếng Việt với nhiều cách đọc tên quân và tọa độ. |
| Nhận dạng câu khó | Kết hợp Vosk và PhoWhisper với ngữ cảnh nước hợp lệ. |
| Thao tác khi chơi | Đi ngay khi câu lệnh chỉ ra một nước hợp lệ, giảm bước xác nhận lặp lại. |
| Kiểm tra lỗi nhận dạng | Có trang thu nguyên câu để nghe lại và thử từ âm thanh đến nước đi trên server. |

## Kiểm tra và hạn chế

Việc kiểm tra gồm nhận dạng câu, phân tích lệnh, chọn nước và xác nhận nước
thực nhận ở server. Với ván đấu máy, còn kiểm tra bot có trả lời sau nước đi đó.
Các bản thu dùng trong quá trình phát triển tập trung vào câu lệnh thông thường,
cột B/D và phong cấp. Công cụ thử nghiệm cùng bản thu riêng được lưu local.

Độ chính xác và thời gian nhận dạng còn phụ thuộc vào giọng đọc, mic, tiếng ồn
và cách ngắt câu. Các bộ âm thanh đã dùng để sửa lỗi cũng được dùng lại để
kiểm tra lỗi có tái diễn hay không; cần thêm người đọc và bản thu mới để đánh
giá rộng hơn. PhoWhisper chạy trên CPU nên thời gian phản hồi có thể dài hơn
Vosk xử lý tại trình duyệt.

Các lệnh kiểm tra và trang thu âm nằm trong [README gốc](../../README.md).
[Fixture WAV trong repo](../../scripts/fixtures/voice/README.md) có nguồn CC0;
một số câu được ghép từ các từ thu riêng lẻ nên cần phân biệt với lời đọc nguyên câu.

## Các file chính

- [Xử lý mic và Vosk](../../lila/ui/voice/src/).
- [Phân tích tiếng Việt](../../lila/ui/voice/src/vietnamese.ts) và [chọn, gửi nước đi](../../lila/ui/voice/src/move/voice.move.ts).
- [Nhận dạng PhoWhisper](../../services/voice/app/recognizer.py) và [trang thu âm](../../services/voice/app/static/record.html).
- [Bản vá Docker](../../patches/lila-vietnamese-voice.patch) và [phiên bản nguồn](../../upstream-lock.json).

Có sử dụng Codex để hỗ trợ triển khai và biên soạn tài liệu.
