# Branch và phân công

Danh sách sau khi dọn nhánh ngày 20/11/2026: còn 5 branch trên GitHub.

## Các branch còn dùng

| Branch | Vai trò |
|---|---|
| [main](https://github.com/trantrien1/Lichess-workspace/tree/main) | Bản chung có Win% cho hai người chơi, người xem và thanh dọc khi review, cùng code bình luận của nhóm |
| [codex/vietnamese-voice-input](https://github.com/trantrien1/Lichess-workspace/tree/codex/vietnamese-voice-input) | Tính năng voice tiếng Việt giữ riêng; Win% hiện tại được quản lý trên main |
| [feature/webmcp](https://github.com/trantrien1/Lichess-workspace/tree/feature/webmcp) | Nhánh công cụ tìm kiếm/phân tích JSON riêng |
| [feature/coach](https://github.com/trantrien1/Lichess-workspace/tree/feature/coach) | Nhánh coaching của nhóm, còn thay đổi riêng so với main |
| [feature/tilt-and-ai-coach](https://github.com/trantrien1/Lichess-workspace/tree/feature/tilt-and-ai-coach) | Nhánh Tilt/AI Coach, còn thay đổi riêng so với main |

## Các mốc đã chuyển thành tag

Bốn branch cũ đã được xóa trên remote sau khi tạo và kiểm tra tag cùng tên,
trỏ đúng commit cuối của từng branch. Các tag giữ nguyên toàn bộ lịch sử tới
mốc đó và giúp các liên kết báo cáo cũ tiếp tục truy cập được.

| Tag lưu trữ | Commit | Nội dung |
|---|---|---|
| [codex/live-win-probability](https://github.com/trantrien1/Lichess-workspace/tree/codex/live-win-probability) | `78e300b` | Mốc WDL lịch sử; phần tính năng đã có trong main, chỉ còn tài liệu riêng chưa gộp |
| [feature/commentary](https://github.com/trantrien1/Lichess-workspace/tree/feature/commentary) | `782dd5e` | Mốc bình luận Piper; phần tính năng đã có trong main, chỉ còn tài liệu riêng chưa gộp |
| [feature/commentary-v2](https://github.com/trantrien1/Lichess-workspace/tree/feature/commentary-v2) | `82b47ae` | Mốc bình luận Nano/ba bình luận viên; phần tính năng đã có trong main, chỉ còn tài liệu riêng chưa gộp |
| [codex/archive-voice-and-probability-e4d8477](https://github.com/trantrien1/Lichess-workspace/tree/codex/archive-voice-and-probability-e4d8477) | `e4d8477` | Bản kết hợp voice và tỷ lệ cũ, giữ làm lịch sử trước khi tách nhánh |

Đợt dọn này không gộp thêm code vào main hoặc voice và không xóa commit của
các mốc lưu trữ. Muốn phát triển tiếp từ một tag, tạo branch mới từ
`refs/tags/<tên-tag>` để phân biệt rõ branch và tag.

Mỗi branch hoặc tag giữ README chuyên đề và các mốc bằng chứng của nó.
Không đồng nhất nội dung của một branch tính năng với phần đã hợp nhất vào
main. Các tài liệu cũ có revision cố định được giữ làm lịch sử.
