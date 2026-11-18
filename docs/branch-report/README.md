# WebMCP: tìm kiếm ván và trả dữ liệu phân tích cho agent

## Thông tin phiên bản và mục đích tài liệu

- Branch: `feature/webmcp`.
- Mã nguồn khảo sát: [`018ada98bf067eebc08e73d06575de6033546342`](https://github.com/trantrien1/Lichess-workspace/commit/018ada98bf067eebc08e73d06575de6033546342).
- Ngày tổng hợp: **18/11/2026**. Tài liệu này phục vụ mô tả/so sánh trong báo cáo; không phải một benchmark mới.
- Nhánh cung cấp hai tool ở trong trang Lila: `lichess_search_games` và `lichess_analyse_game`. Tool trả JSON, không tự viết lời giải thích hay thay engine. Có tài liệu kỹ thuật `WEBMCP.md` và hướng dẫn sử dụng `WEBMCP-HUONG-DAN.md`.

## 1. Bài toán và mục tiêu

Cho agent gọi chức năng web bằng đầu vào có cấu trúc, dùng form và session hiện tại, thay vì phải suy đoán tọa độ màn hình để thao tác.

## 2. Chức năng đã có trên nhánh

Search tool điền/tự submit form advanced search, xử lý bộ lọc phụ thuộc và xóa trạng thái cũ giữa hai lần tìm. Analyse tool đọc PGN chứa eval server, trả bước ngoặt, đánh giá trước/sau, độ thay đổi và thứ hạng; hỗ trợ chọn số lượng, bên đi và thứ tự. Không có eval thì trả NO_EVAL, không tự chạy phân tích server mới.

## 3. Kiến trúc và cách triển khai

```text
Agent → schema tool trong trang → search: DOM/form/session → lila-search/Elasticsearch; analyse: PGN export có eval → parser và xếp hạng → JSON → agent diễn đạt.
```

`lila/ui/lib/src/webmcp.ts` được import từ bundle site. Có feature detection nhiều biến thể WebMCP và đường console `window.__ltw` khi browser không hỗ trợ API native. Search có pending request qua điều hướng, xử lý seats a/b trước white/black/winner/loser, hasAi trước aiLevel, bộ lọc số theo bucket và trả warning/skipped. Tool phân tích dựa trên eval đã lưu, không dùng WDL model của prediction để xếp hạng.

## 4. Ưu điểm so với tính năng có sẵn

| Tính năng có sẵn | Mở rộng WebMCP | Ưu điểm và giới hạn |
|---|---|---|
| Form advanced search dùng bằng tay | Input/schema có cấu trúc cho agent | Tái sử dụng logic/quyền hiện có; không phải công cụ tìm kiếm mới |
| Agent click/đọc DOM hoặc ảnh màn hình | Tool có tên, schema và JSON | Giảm phụ thuộc tọa độ/nhận ảnh; chưa có benchmark end-to-end so độ bền hay token |
| Form có bộ lọc và phụ thuộc phức tạp | Tự xử lý ghế người chơi, hasAi, reset state và bucket | Tránh sót filter của truy vấn trước; vẫn chịu giới hạn form/server |
| Trang phân tích hiển thị eval/PGN | Dữ liệu bước ngoặt có xếp hạng để agent sử dụng | Thuận tiện lập báo cáo tự động; không phải tự chạy Stockfish hay giải thích chiến thuật bằng LLM |
| Cần triển khai thêm MCP server để làm cầu nối | Tool chạy trong trang và session hiện tại | Không thêm server MCP cho phần này; vẫn cần browser/agent hỗ trợ hoặc console test |

Các nhận định “ít thao tác”, “thêm kênh nghe”, “dùng chung công việc” mô tả thiết kế/hành vi có trong code. Không chuyển chúng thành số liệu tăng năng suất, độ chính xác hoặc chất lượng học tập khi chưa có phép đo đối chứng.

## 5. Kết quả kiểm thử và bằng chứng

`WEBMCP.md` ghi 29/29 test, type-aware lint sạch và các probe search/index trên máy phát triển ngày 07/11/2026. Đó là kết quả lịch sử được tài liệu hóa, chưa chạy lại trong lần viết README. Có file test để tái lập; không có benchmark agent/LLM xuyên suốt. Không suy luận “29/29” thành WebMCP native hoạt động trên mọi trình duyệt.

## 6. Cách dựng và thử lại

```sh
cd lila
node ui/test webmcp.test.ts
./ui/build
```

Trên Lila đã chạy, đăng nhập và mở `/games/search`; có thể kiểm tra trong console:

```js
await window.__ltw.searchGames({ white: 'thibault', perf: 'Blitz', submit: false });
await window.__ltw.analyseGame({ gameId: 'abcd1234', topN: 5, order: 'importance' });
```

Thay game ID bằng ván thật có eval. Tìm kiếm có kết quả cần `lila-search`, Elasticsearch, index và `search.enabled`; console chỉ điền form không bảo đảm backend đã bật. Cấu hình local nằm trong hai tài liệu WebMCP; không sao chép địa chỉ/cookie từ máy tác giả.

## 7. Giới hạn và điểm chưa hoàn thành

API browser còn phụ thuộc môi trường; nhánh có cả fallback API cũ nên cần thử trên browser/đặc tả đang dùng. Tool không kèm LLM hay giải thích tiếng Việt. Eval chạy trong browser không tự được lưu thành eval server; cần PGN có [%eval]. Search local chưa index có thể trả rỗng dù Mongo có game. Theo tài liệu triển khai, game import/anonymous chưa chắc được bộ lọc index chấp nhận. Không thay quyền đăng nhập của advanced search.

## 8. Hướng phát triển và điểm cần đối chiếu

Đánh giá trên một tập truy vấn chuẩn và ván đã phân tích: đúng filter, dữ liệu đủ, số lần agent phải sửa, độ trễ và token. Có thể nối LLM diễn giải JSON sau trận nhưng chưa coi đó là tính năng đã hoàn tất trong nhánh WebMCP.

## 9. Tệp nguồn quan trọng ở đúng revision

- [`lila/ui/lib/src/webmcp.ts`](https://github.com/trantrien1/Lichess-workspace/blob/018ada98bf067eebc08e73d06575de6033546342/lila/ui/lib/src/webmcp.ts)
- [`lila/ui/lib/tests/webmcp.test.ts`](https://github.com/trantrien1/Lichess-workspace/blob/018ada98bf067eebc08e73d06575de6033546342/lila/ui/lib/tests/webmcp.test.ts)
- [`lila/ui/site/src/site.ts`](https://github.com/trantrien1/Lichess-workspace/blob/018ada98bf067eebc08e73d06575de6033546342/lila/ui/site/src/site.ts)
- [`WEBMCP.md`](https://github.com/trantrien1/Lichess-workspace/blob/018ada98bf067eebc08e73d06575de6033546342/WEBMCP.md)
- [`WEBMCP-HUONG-DAN.md`](https://github.com/trantrien1/Lichess-workspace/blob/018ada98bf067eebc08e73d06575de6033546342/WEBMCP-HUONG-DAN.md)

## 10. Dùng tài liệu này khi viết báo cáo

Có thể dùng mục 1–2 cho bài toán/phạm vi, mục 3 cho thiết kế, mục 4 cho đóng góp và so sánh, mục 5 cho thực nghiệm, mục 7–8 cho hạn chế/hướng phát triển. Khi trích số đo, giữ nguyên tên branch, snapshot, tập kiểm thử và điều kiện máy; phân biệt số đã lưu với số vừa chạy. Không cộng các lần kiểm thử lặp thành số mẫu độc lập.

README này được tổng hợp với sự hỗ trợ của Codex. Tài liệu không suy đoán tác giả của mọi phần mã nguồn hoặc việc đã đóng góp lên upstream. Đối chiếu Lichess tại revision đã ghim thay vì khẳng định phiên bản hiện tại hoàn toàn chưa có tính năng tương tự.

- [Tài liệu triển khai](../../WEBMCP.md)
- [Hướng dẫn dễ hiểu](../../WEBMCP-HUONG-DAN.md)
