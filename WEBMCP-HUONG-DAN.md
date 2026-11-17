# WebMCP trên lila — hướng dẫn dễ hiểu

Tài liệu này giải thích **tính năng WebMCP trong bản fork lila này là gì, chạy thế nào, dùng ra sao và sửa ở đâu khi hỏng**. Cách giải thích ưu tiên ví dụ và hình dung trực quan; các chi tiết kiểu "đã sửa file nào, khác bản yêu cầu gốc ở chỗ nào" nằm trong [`WEBMCP.md`](WEBMCP.md).

> **TL;DR**
> - WebMCP cho phép **agent AI trong trình duyệt** gọi các hàm do trang web cung cấp.
> - Bản fork này cung cấp **2 tool**: `lichess_search_games` (điền + chạy tìm kiếm nâng cao) và `lichess_analyse_game` (trả các bước ngoặt của một ván dưới dạng JSON).
> - Toàn bộ logic nằm trong **một file**: `lila/ui/lib/src/webmcp.ts`; chỉ thêm **một dòng import** vào `lila/ui/site/src/site.ts`.
> - Tool **trả dữ liệu JSON**, không viết câu văn. LLM/agent tự diễn giải.
> - Trình duyệt không có WebMCP thì trang vẫn chạy bình thường; `window.__ltw` luôn có để test bằng console.

---

## 1. WebMCP là gì? (cách hình dung)

Hãy tưởng tượng trang web là một **quầy dịch vụ**. WebMCP là **tấm bảng menu** đặt trên quầy:

- Mỗi món trên menu là một **tool**, gồm:
  - `name`: tên món (ví dụ `lichess_search_games`);
  - `description`: mô tả bằng lời để agent biết khi nào nên gọi;
  - `inputSchema`: các tham số hợp lệ (kiểu JSON Schema);
  - `execute`: hàm thực sự chạy khi agent gọi món đó.
- **Agent/LLM là khách**: đọc menu, chọn món, đưa tham số, nhận kết quả.
- Tool ở đây **chỉ trả dữ liệu có cấu trúc** (JSON). Agent tự viết câu trả lời cho người dùng.

Điểm khác với một "MCP server" riêng:

| MCP server riêng | WebMCP trong trang |
|---|---|
| Chạy process riêng, mở cổng | Chạy ngay trong tab đang mở |
| Không thấy DOM/session của trang | Dùng được form, URL, session đăng nhập hiện tại |
| Phải cấu hình/kết nối | Trang tự đăng ký tool khi tải |

WebMCP vẫn là **early preview**: tên API và nơi đặt API đã đổi vài lần (`navigator.modelContext` / `document.modelContext`; `registerTool` / `provideTools` / `provideContext`). Vì vậy code **dò từng biến thể** và bọc `try/catch`, không bao giờ làm hỏng trang.

---

## 2. Tính năng này thêm gì?

Hai tool, phục vụ hai nhóm câu hỏi:

| Tool | Người dùng hỏi kiểu | Tool làm gì | Phụ thuộc |
|---|---|---|---|
| `lichess_search_games` | "Tìm các ván Blitz của tôi từ 2024", "Tìm ván tôi thắng bằng quân Trắng", "Tìm ván đấu với máy level ≤ 5" | Điền form advanced search của lila rồi **tự chạy query** (mặc định) | Form search trên trang; backend `lila-search` + Elasticsearch để có kết quả |
| `lichess_analyse_game` | "10 nước bước ngoặt của ván này", "3 nước sụp đổ lớn nhất", "nước hay nhất của Trắng" | Đọc PGN đã được **server phân tích**, tính các bước ngoặt và trả JSON | Ván phải có `[%eval]` do server lưu (fishnet/server analysis) |

Ví dụ hội thoại:

```text
Người dùng: "Tìm giúp tôi các ván Blitz của thibault từ đầu năm 2024"
Agent: gọi lichess_search_games({ white: "thibault", perf: "Blitz", dateMin: "2024-01-01" })
Tool:  điền form, tự submit, trả query + URL
Agent: "Đã mở kết quả tìm kiếm..." (agent tự viết lời)

Người dùng: "Ván này có nước nào sụp đổ không?"
Agent: gọi lichess_analyse_game({ topN: 5, order: "importance" })
Tool:  trả các turning point + bestMove + game metadata
Agent: "Nước lớn nhất là Nc6 ở nước 2, đánh giá đổi 0.65..." (agent tự viết lời)
```

---

## 3. Kiến trúc: một file, một dòng import

```text
lila/ui/site/src/site.ts            ← bundle "site" chạy trên mọi trang của lila
        │
        └── import 'lib/webmcp'     ← 1 dòng side-effect ở cuối file
                    │
                    ▼
        lila/ui/lib/src/webmcp.ts
                    ├── tool 1: lichess_search_games
                    ├── tool 2: lichess_analyse_game
                    ├── window.__ltw = { searchGames, analyseGame, tools, debug, attempts, register, browserTools }
                    ├── đăng ký với WebMCP nếu trình duyệt có API
                    └── tự chạy lại "pending search" sau khi điều hướng
```

Vì `site.ts` là bundle chung, **mọi trang** của lila đều có `window.__ltw`, kể cả khi trình duyệt chưa hỗ trợ WebMCP.

Không có: MCP server riêng, dependency mới, thay đổi `package.json`, hay đụng vào `ui/round/**` (winbar là tính năng khác).

### 3.1 Luồng tìm kiếm

```text
Agent gọi lichess_search_games(input)
        │
        ├─ Trang có form.search__form?
        │       │
        │       ├─ CÓ ──▶ 1. Xoá state cũ của form (search mới, không rò rỉ filter cũ)
        │       │          2. Điền players.a / players.b (ghế gốc)
        │       │          3. Điền các select phụ thuộc (white/black/winner/loser)
        │       │          4. Điền hasAi trước, rồi aiLevel*
        │       │          5. Điền các field còn lại; snap bucket số nếu cần
        │       │          6. Dựng query + URL từ FormData
        │       │          7. submit=true? → requestSubmit() sau ~50 ms
        │       │          8. Trả JSON { status, filled, warnings, query, url, ... }
        │       │
        │       └─ KHÔNG ──▶ đang ở /games/search?
        │                       ├─ phải ──▶ trả lỗi NO_FORM (tránh vòng lặp)
        │                       └─ không ──▶ lưu input vào sessionStorage,
        │                                      chuyển tới /games/search,
        │                                      trả { status: 'navigating', pending: true }
        │                                      → trang mới tự chạy lại search đã lưu (1 lần)
```

### 3.2 Luồng phân tích

```text
Agent gọi lichess_analyse_game({ gameId?, url?, topN?, order?, mover? })
        │
        ├─ Xác định gameId: tham số → URL → ván đang mở (URL trang) → page-init-data
        │       └─ không có ván nào → { status: 'skipped', hasEval: false } (không phải lỗi)
        │
        ├─ fetch('/game/export/{id}?evals=1')
        ├─ Bỏ header PGN, bỏ biến thể ( ... ), chỉ đọc dòng chính
        ├─ Tách SAN + đọc comment { [%eval ...] } gắn sau mỗi nước
        ├─ Đổi eval → expected score (góc nhìn Trắng) → delta giữa 2 nước liên tiếp
        ├─ Lọc theo mover, xếp theo |delta|, lấy topN, gắn importanceRank/isBiggest
        ├─ Tìm bestMove (nước đạt expected score cao nhất cho bên đi)
        └─ Trả JSON; nếu ván chưa có eval → error NO_EVAL (vẫn là kết quả hợp lệ)
```

---

## 4. Dùng thử ngay trong Console

Mở bản local (ví dụ `http://localhost:9663`), nhấn **Ctrl+Shift+R** sau khi build, rồi mở DevTools Console.

### 4.1 Tìm kiếm

```js
// Điền form + tự chạy query (mặc định submit = true)
await __ltw.searchGames({ white: 'thibault', perf: 'Blitz', dateMin: '2024-01-01' })

// Chỉ điền form, không điều hướng — tiện xem tool trả gì
await __ltw.searchGames({ white: 'thibault', submit: false })

// Đấu với máy, rating trung bình dưới 2000
await __ltw.searchGames({ hasAi: 'computer', ratingMax: 1999, submit: false })
```

### 4.2 Phân tích

```js
await __ltw.analyseGame({ topN: 10 })                     // 10 bước ngoặt, theo thời gian
await __ltw.analyseGame({ topN: 3, order: 'importance' }) // 3 swing lớn nhất
await __ltw.analyseGame({ mover: 'white' })               // chỉ nước Trắng + bestMove của Trắng
await __ltw.analyseGame({ gameId: 'abcd1234' })           // ván cụ thể
```

### 4.3 Bộ API `window.__ltw`

| Thuộc tính | Ý nghĩa |
|---|---|
| `searchGames(input)` | Chạy tool 1 (cùng hàm mà agent gọi) |
| `analyseGame(input)` | Chạy tool 2 |
| `tools` | Mảng 2 định nghĩa tool (name/description/inputSchema/execute) |
| `debug()` | Trả trạng thái 3 nơi có thể có API WebMCP |
| `attempts` | Log các lần đăng ký: host nào, API nào, `ok`, `error` |
| `register()` | Thử đăng ký lại (dùng khi polyfill/extension inject API **sau** khi trang tải) |
| `browserTools()` | Hỏi thẳng trình duyệt xem nó đang giữ tool nào (`host.getTools()`) |

---

## 5. Tool 1 — `lichess_search_games`

### 5.1 Input

Mọi field đều **optional**. Có hai cách truyền người chơi:

```js
// Cách "đúng schema": players.*
__ltw.searchGames({ players: { white: 'thibault' }, perf: 'Blitz' })

// Cách shortcut phẳng (tiện cho agent/người dùng)
__ltw.searchGames({ white: 'thibault', perf: 'Blitz' })
```

| Nhóm | Field | Ghi chú |
|---|---|---|
| Người chơi | `players.a`, `players.b` | Hai "ghế" gốc; là text input |
| Người chơi | `players.white`, `players.black`, `players.winner`, `players.loser` | Thường là `<select>` (một số bản render thành text input; tool xử lý cả hai); **chỉ có tác dụng nếu username trùng `players.a` hoặc `players.b`** |
| Shortcut | `white`, `black`, `winner`, `loser` | Viết tắt của `players.*` |
| Kết quả | `winnerColor` | `white` / `black` |
| Thể loại | `perf` | `bullet`, `blitz`, `rapid`, `classical`, `correspondence`, `chess960`, ... |
| Nguồn | `source` | `lobby`, `friend`, `tournament`, `import`, ... |
| Chế độ | `mode` | `casual` / `rated` |
| Trạng thái | `status` | `resign`, `outoftime`, `draw`, `mate`, ... |
| Đối thủ | `hasAi` | `human` / `computer` |
| Máy | `aiLevelMin`, `aiLevelMax` | 1–8; chỉ có tác dụng khi `hasAi=computer` |
| Số nước | `turnsMin`, `turnsMax` | Form dùng bucket cố định |
| Rating | `ratingMin`, `ratingMax` | Bucket 100 điểm |
| Thời lượng | `durationMin`, `durationMax` | Giây, bucket cố định |
| Đồng hồ | `clockInit`, `clockInc` | Giây, option cố định |
| Ngày | `dateMin`, `dateMax` | `yyyy-MM-dd`; kiểm tra `min`/`max` của input |
| Phân tích | `analysed` | `true` = chỉ ván đã phân tích |
| Sắp xếp | `sortField`, `sortOrder` | `date`/`turns`/`rating`; `desc`/`asc` |
| Hành vi | `submit` | Mặc định `true`; `false` = chỉ điền form |

### 5.2 Quy tắc "ghế" người chơi (quan trọng nhất)

Server lila **chỉ giữ** `players.white/black/winner/loser` nếu username đó **cũng là `players.a` hoặc `players.b`** (`SearchPlayer.oneOf`). Nếu không có `players.a/b`, các filter người chơi này bị bỏ âm thầm; query khi đó có thể rỗng (không có kết quả) hoặc chỉ còn các filter khác.

Tool xử lý hộ:

- `{ white: 'astra' }` → tool tự thêm `players.a=astra` (báo trong `autoFilled` + `warnings`).
- `{ white: 'astra', black: 'bob' }` → điền `players.a=astra`, `players.b=bob`.
- `{ players: { a: 'astra' }, winner: 'bob' }` → giữ `players.a=astra`, điền `players.b=bob` (ghế trống).
- `{ players: { a: 'astra', b: 'bob' }, winner: 'carol' }` → **bỏ** `winner` (cả 2 ghế đã bị chiếm bởi tên khác), ghi `skipped` + `warnings`.

Trên trang `/@user/search`, `players.a` là **hidden input** chứa chính chủ tài khoản. Tool giữ hidden input này, nên `{ loser: 'astra' }` trên trang của bạn sẽ thành "các ván giữa bạn và astra, astra thua" — đúng ý.

### 5.3 Tool làm gì, theo thứ tự

1. **Xoá state cũ của form** (mỗi lần gọi là một query mới):
   - xoá `data-req-*`;
   - clear mọi `input` (trừ `hidden`), `select`, `textarea`;
   - **không dùng `form.reset()`** vì trên trang kết quả, lila pre-fill giá trị cũ thành HTML default — `reset()` sẽ khôi phục chúng.
2. **Điền `players.a` / `players.b` trước**, vì `bits.gameSearch.ts` rebuild các select white/black/winner/loser từ hai ô này.
3. **Điền 4 select người chơi**, thêm `<option>` nếu username chưa có; đồng thời set `data-req-*` để nếu bits rebuild muộn (ví dụ sau `site.load`) thì lựa chọn vẫn được giữ.
4. **Set `hasAi` trước `aiLevel*`** và bắn `change`, vì row `.aiLevel` bị ẩn khi Opponent ≠ Computer. Nếu chỉ truyền aiLevel, tool tự đặt `hasAi=computer`; nếu `hasAi=human` thì bỏ aiLevel kèm cảnh báo.
5. **Các field còn lại**:
   - `<select>`: khớp **value** trước, rồi **nhãn** (đã chuẩn hoá dấu tiếng Việt/hoa-thường), rồi khớp một phần;
   - bucket số: nếu không khớp option, **snap** sang option hợp lệ gần nhất và ghi `warnings`;
   - `date`: kiểm tra định dạng `yyyy-MM-dd` + `min`/`max`;
   - checkbox: set `.checked`;
   - bắn cả `input` và `change` để lila cập nhật UI.
6. **Dựng `query`/`url`** từ toàn bộ `FormData` hiện tại (bỏ giá trị rỗng).
7. **Submit mặc định**: gọi `form.requestSubmit()` sau ~50 ms — trễ để JSON kịp trả về trước khi trang điều hướng. `submit: false` để chỉ điền form.

Không hardcode id số của `<select>`: tool lấy nhãn từ `window.i18n` (và fallback tiếng Anh), nên chạy được cả khi UI đang ở tiếng Việt. Với `sortField`, bạn cứ truyền `date` / `turns` / `rating`; tool khớp qua nhãn "Date" / "Number of turns" / "Rating" rồi dùng value nội bộ của form (bản lila này dùng `d` / `t` / `a`, không phải chuỗi dài).

### 5.4 Output

```json
{
  "status": "filled",
  "filled": ["players.a", "players.white", "perf", "dateMin"],
  "autoFilled": ["players.a"],
  "warnings": [
    "players.a was set to \"thibault\" because players.white only works when that username is players.a or players.b."
  ],
  "skipped": [{ "field": "source", "reason": "option not found" }],
  "query": "players.a=thibault&players.white=thibault&perf=2&dateMin=2024-01-01",
  "url": "/games/search?players.a=thibault&players.white=thibault&perf=2&dateMin=2024-01-01#results",
  "submitted": true
}
```

| Field | Nghĩa |
|---|---|
| `filled` | Các field tool vừa set trong lần gọi này |
| `autoFilled` | Các field tool **tự thêm** vì ràng buộc phụ thuộc (là tập con của `filled`) |
| `warnings` | Giải thích vì sao tự thêm/bỏ field; cũng báo khi ràng buộc đã được thoả bởi ghế có sẵn |
| `skipped` | Field không điền được + lý do; **không throw** |
| `query` / `url` | Query/URL dựng từ `FormData`; có thể chứa default sẵn có của trang |
| `submitted` | Có gọi submit hay không |

Lưu ý: `status: "filled"` nghĩa là "đã chạy xong việc điền form", **không** đảm bảo mọi field đều điền được — hãy đọc `filled`/`skipped`/`warnings`.

### 5.5 Một số tình huống thực tế

```js
// Người dùng: "tìm ván tôi thắng, rating dưới 2000"
await __ltw.searchGames({ winner: 'astra', ratingMax: 1999 })
// → tự điền players.a=astra, ratingMax snap 1900 (bucket 100 điểm), có warning
```

```js
// Người dùng: "tìm ván của tôi đấu với máy level 1-5"
await __ltw.searchGames({ hasAi: 'computer', aiLevelMin: 1, aiLevelMax: 5 })
```

```js
// Người dùng: "tôi thua astra"
// Trên trang /@user/search (players.a hidden = bạn)
await __ltw.searchGames({ loser: 'astra' })
// → giữ players.a=hidden, điền players.b=astra, players.loser=astra
```

### 5.6 Điều dễ hiểu nhầm

- `perf: 'Blitz'` được map sang **value số** của form (con số cụ thể do form quyết định, ví dụ `2` trong bộ test), nên `query` sẽ hiện dạng `perf=2` — đó là điều bình thường.
- `ratingMax: 1999` không có option đúng; tool chọn bucket gần nhất **không vượt quá** 1999 (ví dụ 1900) và cảnh báo. Đây là snap có chủ đích, không phải lỗi.
- `players.winner` bị bỏ nếu cả 2 ghế đã là người khác. Muốn tìm "A thắng B" thì truyền `players: { a: 'A', b: 'B' }` + `winner: 'A'`.
- Nếu trang không có form, tool **điều hướng** tới `/games/search` và tự chạy lại search đã lưu. Nếu `sessionStorage` bị chặn, agent cần gọi lại tool trên trang mới.
- Đang ở `/games/search` mà vẫn không thấy form → trả `NO_FORM` thay vì điều hướng vòng lặp.

---

## 6. Tool 2 — `lichess_analyse_game`

### 6.1 Input

```jsonc
{
  "gameId": "abcd1234",      // 8 chữ/số; hoặc "url": "https://lichess.org/game/abcd1234"
  "topN": 10,                // mặc định 10, kẹp trong [1, 100]
  "order": "chronological",  // "chronological" (mặc định) | "importance"
  "mover": "both"            // "both" (mặc định) | "white" | "black"
}
```

| Trường hợp | Hành vi |
|---|---|
| `gameId` có | Dùng luôn; sai định dạng → `INVALID_GAME_ID` |
| Chỉ `url` | Trích id 8 ký tự từ URL |
| Không truyền gì | Lấy ván đang mở: URL `/game/...`, `/analyse/...`, `/analysis/...`; nếu URL không có id thì đọc `page-init-data` |
| Không có ván nào | `{ status: "skipped", hasEval: false }` — **không phải lỗi** |

`topN` cho phép quét cả ván bằng `topN: 100`. `order: "importance"` xếp theo `|delta|` giảm dần; mặc định `"chronological"` xếp theo `ply` để dễ theo dõi diễn biến.

### 6.2 Cách đọc dữ liệu (đơn giản hoá)

1. Gọi `GET /game/export/{id}?evals=1` để lấy PGN.
2. Bỏ header `[White "..."]`, bỏ biến thể trong `( ... )`, chỉ đọc dòng chính.
3. Tách từng nước SAN; bỏ số nước, `!?`, token kết quả `1-0`, `0-1`, `1/2-1/2`, `*`.
4. Đọc comment `{ [%eval X] }` ngay sau mỗi nước. `[%eval]` **luôn theo góc nhìn Trắng**.
5. Đổi eval thành **expected score** (xác suất kỳ vọng quy về `-1 … 1`) bằng đúng công thức của `ui/lib/src/ceval/winningChances.ts`.
6. `delta` của một nước = expected score sau nước đó − expected score của nước có eval hợp lệ gần nhất trước đó. Nếu thiếu eval ở giữa, tool nối với mốc hợp lệ gần nhất.

### 6.3 Hiểu các con số

| Khái niệm | Ý nghĩa |
|---|---|
| `evalBefore` / `evalAfter` | Đánh giá **trước/sau** nước, đơn vị **tốt**, góc nhìn **Trắng** |
| `mateBefore` / `mateAfter` | Nếu là mate: chỉ số mate; dương = Trắng thắng, âm = Đen thắng |
| `esBefore` / `esAfter` | Expected score `-1 … 1`, góc nhìn Trắng |
| `delta` | `esAfter - esBefore`, góc nhìn Trắng |
| `kind` | Phân loại theo **độ lớn** `|delta|`: `blunder` ≥ 0.30, `mistake` ≥ 0.15, `inaccuracy` ≥ 0.07, còn lại `fine` |
| `importanceRank` | Hạng theo `|delta|` trong tập kết quả; `1` = swing lớn nhất |
| `isBiggest` | Đúng **một** phần tử có `true` |
| `bestMove` | Nước mà **bên đi nước đó** đạt expected score cao nhất; không phải "swing lớn nhất" |
| `expectedScoreForMover` | Điểm `-1 … 1` **góc nhìn bên đi nước đó**; dương = có lợi cho họ |

**Cẩn thận với `kind`:** đây là nhãn theo **độ lớn cú swing**, không phải lời buộc tội "người này đánh dở". Muốn biết ai mất lợi thế, kết hợp `mover` với dấu `delta`:

- `mover = white` và `delta < 0` → Trắng mất lợi thế;
- `mover = black` và `delta > 0` → Đen mất lợi thế (vì expected score của Trắng tăng);
- các trường hợp còn lại là nước có lợi cho bên vừa đi.

Mate được quy đổi thành tốt theo `±(21 - min(10, |N|))` (thực tế khoảng ±11 … ±20) để vẫn là số, còn `mateBefore/After` nói rõ mate. Riêng `#0` (nước vừa chiếu hết) không có dấu trong PGN; tool lấy dấu từ SAN `#` và bên đi nước đó; nếu không phải nước chiếu hết thì coi như không có eval mới.

### 6.4 Output (ví dụ lấy từ test, rút gọn)

PGN test: `1. e4 {0.20} e5 {0.10} 2. Qh5 {2.00} Nc6 {#3}`

```json
{
  "gameId": "abcd1234",
  "hasEval": true,
  "plies": 4,
  "evaluatedPlies": 4,
  "order": "chronological",
  "mover": "both",
  "topN": 10,
  "bestMove": {
    "ply": 3,
    "moveNumber": 2,
    "mover": "white",
    "san": "Qh5",
    "evalAfter": 2,
    "mateAfter": null,
    "expectedScoreForMover": 0.352
  },
  "turningPoints": [
    {
      "ply": 2, "moveNumber": 1, "mover": "black", "san": "e5",
      "evalBefore": 0.2, "evalAfter": 0.1, "mateBefore": null, "mateAfter": null,
      "esBefore": 0.037, "esAfter": 0.018, "delta": -0.018,
      "kind": "fine", "importanceRank": 3, "isBiggest": false
    },
    {
      "ply": 3, "moveNumber": 2, "mover": "white", "san": "Qh5",
      "evalBefore": 0.1, "evalAfter": 2, "mateBefore": null, "mateAfter": null,
      "esBefore": 0.018, "esAfter": 0.352, "delta": 0.334,
      "kind": "blunder", "importanceRank": 2, "isBiggest": false
    },
    {
      "ply": 4, "moveNumber": 2, "mover": "black", "san": "Nc6",
      "evalBefore": 2, "evalAfter": 18, "mateBefore": null, "mateAfter": 3,
      "esBefore": 0.352, "esAfter": 0.997, "delta": 0.645,
      "kind": "blunder", "importanceRank": 1, "isBiggest": true
    }
  ],
  "game": {
    "white": "Alice",
    "black": "Bob",
    "result": "1-0"
  }
}
```

Trong ví dụ này, `Nc6` của Đen có `delta` **dương** vì expected score của Trắng tăng mạnh → Đen mới là bên sai; `kind: "blunder"` chỉ nói cú swing lớn.

### 6.5 Lỗi (đều trả JSON, không throw)

| `error` | Khi nào |
|---|---|
| `INVALID_GAME_ID` | Có truyền id nhưng không phải đúng 8 chữ/số |
| `FETCH_FAILED` | Mạng lỗi hoặc HTTP không 2xx |
| `EMPTY_PGN` | PGN không có nước đi |
| `NO_EVAL` | Không có `[%eval]` nào (ván chưa được phân tích server-side) |

Không có ván nào đang mở:

```json
{
  "gameId": null,
  "status": "skipped",
  "hasEval": false,
  "message": "No game is currently open. Pass gameId or url to analyse a specific game."
}
```

### 6.6 Câu hỏi điển hình → tham số

| Người dùng hỏi | Gọi |
|---|---|
| "10 nước bước ngoặt theo thời gian" | `{ topN: 10 }` (mặc định) |
| "3 nước sụp đổ lớn nhất" | `{ topN: 3, order: "importance" }` |
| "Nước hay nhất của Trắng" | `{ mover: "white" }` → xem `bestMove` |
| "Toàn bộ nước của Đen" | `{ mover: "black", topN: 100 }` |

### 6.7 Vì sao hay gặp `NO_EVAL` trên máy local?

Tool đọc eval **server lưu**. Nếu bạn bấm "phân tích" trên analysis board, engine chạy **phía client** và **không ghi gì vào Mongo** → PGN export không có `[%eval]` → `NO_EVAL`. Đây là hành vi đúng, không phải bug của tool.

Muốn có eval trên local, chạy fishnet trỏ vào **lila 9663** (analysis), không phải lila-fishnet 9665 (move cho bot), rồi request analysis cho ván. Chi tiết + lệnh kiểm tra + cách xoá work kẹt: xem [`WEBMCP.md` §6.4](WEBMCP.md).

Tool **không** tự chạy engine, **không** đọc DOM analysis board, **không** sửa PGN.

---

## 7. Đăng ký WebMCP — vì sao trông phức tạp?

WebMCP early preview đã đổi API nhiều lần. Code xử lý như sau:

1. Dò **độc lập** 3 nơi: `navigator.modelContext`, `document.modelContext`, `window.modelContext`.
2. Với mỗi host, thử theo thứ tự: `registerTool` → `provideTools` → `provideContext({ tools })`.
3. `registerTool` có thể async → có `.then/.catch`, lỗi ghi vào `__ltw.attempts` thay vì bị nuốt.
4. Chỉ thử mỗi host một lần (`triedHosts`) để không đăng ký trùng.
5. Toàn bộ bọc `try/catch`: API đổi shape hay lỗi quyền cũng không làm vỡ trang.
6. **Luôn** set `window.__ltw`, kể cả khi không có WebMCP → test được trên Chrome thường.

Nếu extension/polyfill inject API **sau** khi bundle chạy, gọi tay:

```js
__ltw.register()
__ltw.attempts
```

Lưu ý nhỏ: `register()` chỉ thử host **chưa thấy**. Nếu một host đã tồn tại từ đầu nhưng chưa có method, sau đó được thêm method vào **cùng object**, lần gọi lại sẽ bị bỏ qua; trường hợp thường gặp (polyfill tạo `document.modelContext` mới) thì vẫn hoạt động.

---

## 8. Yêu cầu môi trường để agent thấy tool

### 8.1 Phía trình duyệt

Cần **một trong hai**:

1. **Chrome/Chromium có WebMCP native** (bản dev/early preview), bật cờ `chrome://flags/#enable-webmcp-testing` rồi relaunch. Tên cờ/phiên bản có thể đổi theo thời gian — kiểm tra bằng `typeof document.modelContext`.
2. **Polyfill** (chỉ để test local, không đưa vào production), load **trước** khi đăng ký:

```js
const script = document.createElement('script');
script.src = 'https://unpkg.com/@mcp-b/webmcp-polyfill@6/dist/index.iife.js';
script.onload = () => {
  __ltw.register();
  console.log(__ltw.attempts);
};
document.head.append(script);
```

Điều kiện chung:

- Trang là **secure context**: `http://localhost:...` hoặc `https://...`;
- mở **đúng bản local** (`localhost:9663`), không phải `lichess.org`;
- sau khi build phải **restart lila** và **Ctrl+Shift+R** để lấy bundle `site` mới;
- extension WebMCP (Model Context Tool Inspector / MCP-B / Rook) chỉ là **công cụ xem/gọi tool**, **không tự thêm API** vào Chrome stable. Trang không có `document.modelContext` thì extension không thấy gì.
- sau khi đổi schema/description, reload cả extension/panel để nó đọc lại tool (nó có thể cache phiên trước).

### 8.2 Phía backend tìm kiếm

Advanced search của lila **không đọc trực tiếp Mongo**. Nó gọi `lila-search` (9673), service này query Elasticsearch (9200). Local mặc định `search.enabled = false`.

Nếu chưa bật backend:

- form advanced search và `__ltw.searchGames` đều trả **0 ván**, dù Mongo có dữ liệu;
- đây **không phải** lỗi WebMCP.

Cách dựng ES + lila-search + bật `search.enabled`: xem [`WEBMCP.md` §11](WEBMCP.md).

### 8.3 Phía backend phân tích

Eval cho tool 2 do **server analysis** (fishnet) tạo và lưu. Client-side analysis không được lưu. Cấu hình/kiểm tra: [`WEBMCP.md` §6.4](WEBMCP.md).

Chỉ ván **standard/chess960** mới có eval đáng tin; biến thể khác vẫn tìm kiếm được (tool 1) nhưng có thể `NO_EVAL` (tool 2).

---

## 9. Build, test, lint

```bash
cd ~/ws/lila
export PATH=$HOME/.nvm/versions/node/v24.22.1/bin:/usr/local/sbin:/usr/local/bin:/usr/sbin:/usr/bin:/sbin:/bin

# Build toàn bộ UI (tsc + esbuild + sass)
cd ui && ./build

# Test riêng module WebMCP (node:test + jsdom của repo)
cd .. && node ui/test webmcp.test.ts

# Lint 3 file liên quan
node_modules/.bin/oxlint --type-aware \
  ui/lib/src/webmcp.ts ui/lib/tests/webmcp.test.ts ui/site/src/site.ts
```

- Bộ test hiện có **29 test**, bao phủ: điền form, phụ thuộc ghế người chơi, reset state cũ, bucket số, rebuild select của bits, submit, parser PGN, eval/mate, thứ tự/topN/mover, lỗi.
- Lần chạy lại gần nhất trong phiên làm tài liệu này: **29/29 pass**.
- Sau build, `public/compiled/manifest.json` đổi hash; chỉ bundle `site` thay đổi, không xoá file cũ. Nhớ restart lila + hard reload.

---

## 10. Troubleshooting

| Triệu chứng | Nguyên nhân thường gặp | Cách xử lý |
|---|---|---|
| `__ltw` undefined | Bundle cũ chưa build/restart | Build UI, restart lila, Ctrl+Shift+R |
| Extension không thấy tool | Trình duyệt không có API, hoặc extension cache schema cũ | Chạy `__ltw.debug()`; bật cờ/polyfill; reload extension/panel |
| `attempts` có `ok: false` | `NotAllowedError` (Permissions-Policy), API đổi shape | Đọc `error`; thử host/API khác; cập nhật code nếu spec đổi |
| Search luôn 0 kết quả | `search.enabled=false`, lila-search/ES chưa chạy | Bật backend theo `WEBMCP.md` §11 |
| `NO_EVAL` | Ván chưa được phân tích server-side; eval client không lưu | Chạy fishnet cho analysis + request analysis; kiểm tra PGN export có `[%eval]` |
| `players.winner` bị bỏ | Cả `players.a` và `players.b` đã là tên khác | Truyền đúng cặp `players.a/b`, hoặc bỏ bớt filter |
| `aiLevelMin/Max` bị bỏ | `hasAi=human` | Đặt `hasAi` là `computer` hoặc bỏ aiLevel |
| Query còn filter cũ | Bạn đang test tay trên form đã có state (tool đã cố clear) | Mở tab `/games/search` mới; hoặc `submit: false` để kiểm tra |
| Trả `navigating` mãi | `sessionStorage` bị chặn hoặc form chưa sẵn sàng | Gọi lại tool trên `/games/search`; kiểm tra storage |
| Không submit | `submit: false` hoặc hàm submit không phải form handler | Mặc định `submit` là `true`; kiểm tra input |

### Lệnh debug nhanh

```js
__ltw?.tools.map(t => t.name)                       // ['lichess_search_games', 'lichess_analyse_game']
__ltw?.tools.find(t => t.name === 'lichess_search_games')?.description  // bundle mới chưa?
__ltw.debug()                                       // host nào có API, có method gì
__ltw.attempts                                      // log đăng ký: host/api/ok/error
await __ltw.browserTools()                          // trình duyệt đang giữ tool nào
typeof document.modelContext                        // 'undefined' = chưa có native/polyfill
__ltw.register()                                    // thử lại sau khi polyfill inject API
```

---

## 11. Giới hạn & hướng mở rộng

**Hiện tại:**

- Tool chỉ trả JSON, không viết văn; không thay đổi hành vi trang ngoài việc điền/submit form.
- Tool 2 **không tự chạy engine**; phụ thuộc eval server lưu (fishnet).
- Eval đáng tin chủ yếu với standard/chess960; biến thể khác có thể không có.
- Tool 1 phụ thuộc backend `lila-search` + Elasticsearch; game anonymous đấu với AI có thể không được index (upstream chỉ index game có user).
- WebMCP còn early preview → API có thể đổi.

**Để dành (theo `PROMPT.md` mục 9):**

- `lichess_game_summary` (ACPL / accuracy / opening);
- `lichess_compare_games`;
- phát hiện hy sinh quân (material drop mà eval không giảm);
- share link kết quả tìm kiếm;
- tool voice tiếng Việt;
- chạy engine client trong tool 2 để khỏi phụ thuộc eval có sẵn.

---

## 12. Bản đồ file

| File | Vai trò |
|---|---|
| `lila/ui/lib/src/webmcp.ts` | **Toàn bộ logic**: 2 tool, parser PGN, tính eval/delta, đăng ký WebMCP, `window.__ltw`, auto-run pending search |
| `lila/ui/site/src/site.ts` | Thêm đúng 1 dòng `import 'lib/webmcp';` ở cuối |
| `lila/ui/lib/tests/webmcp.test.ts` | 29 test (`node:test` + jsdom) |
| `lila/ui/lib/dist/webmcp.js`, `.d.ts` | Output build |
| `WEBMCP.md` | Tài liệu triển khai chi tiết: thay đổi file, khác `PROMPT.md`, fishnet, ES/lila-search, debug sâu |
| `HUONG-DAN-KHOI-DONG.md` | Thứ tự khởi động local (lila, lila-ws, ES, lila-search, fishnet) |
| `PROMPT.md` | Yêu cầu gốc của tính năng (một số điểm đã được điều chỉnh, ví dụ `submit` mặc định `true`) |

**Muốn đọc code theo thứ tự gợi ý:**

1. Đầu file `webmcp.ts`: types + helper nhỏ (`asText`, `normalizeText`, `findOption`, `findNumericOption`) — đây là nền của việc khớp select.
2. Tool 1: `searchGames`, `playerValues`, `ensurePlayerPair`, `setFormField` — chú ý thứ tự a/b → select phụ thuộc → hasAi → aiLevel.
3. Tool 2: `analyseGame`, `parseMoves`, `parseEval`, `expectedScore`, `kindOf` — parser PGN là phần dễ đọc nhất.
4. Cuối file: `tools`, `registerHost`, `registerWithHosts`, `window.__ltw`, đoạn auto-run pending search.
5. `webmcp.test.ts` đóng vai **đặc tả chạy được**: mỗi hành vi ở trên đều có test tương ứng.

---

## 13. Thuật ngữ nhanh

| Thuật ngữ | Nghĩa |
|---|---|
| **Tool** | Một hàm trang web cung cấp cho agent, kèm schema tham số |
| **Agent/LLM** | Thành phần AI trong trình duyệt đọc tool và quyết định gọi |
| **Ply** | Nửa nước đi; ply lẻ = Trắng, ply chẵn = Đen |
| **SAN** | Ký hiệu nước đi kiểu `Nf3`, `Qxb2`, `O-O` |
| **White POV** | Góc nhìn Trắng: dương = Trắng có lợi |
| **Expected score** | Điểm kỳ vọng `-1 … 1` suy từ eval |
| **Bucket** | Nhóm giá trị cố định trong `<select>` (ví dụ rating 100 điểm/bucket) |
| **Secure context** | `https` hoặc `localhost` — điều kiện để WebMCP hoạt động |
| **Side-effect import** | Import chỉ để chạy code, không dùng export |
