# Lichess Workspace: Tilt và AI Coach

Nhánh riêng của [trantrien1](https://github.com/trantrien1), bổ sung hai
module vào bản Lichess chạy local của nhóm:

- **Tilt** nhận biết dấu hiệu chơi mất bình tĩnh qua các ván blitz và nhắc
  người chơi nghỉ.
- **AI Coach** trả lời câu hỏi bằng tiếng Việt về ván vừa kết thúc, dựa trên
  phân tích Stockfish của chính ván đó.

Nhánh được dựng trên `main`, nên vẫn có đủ các tính năng chung của nhóm. Phần
chung được mô tả ở [README của nhánh main](https://github.com/trantrien1/Lichess-workspace/blob/main/README.md);
README này chỉ nói về hai module trên.

## Tính năng

| Module | Người dùng thấy ở đâu | Thành phần chính |
|---|---|---|
| Tilt | Tab **Tilt** trong trang ván, lời nhắc trên trang chủ, trang `/account/tilt` | `lila/modules/tilt`, `tilt/` |
| AI Coach | Tab **AI Coach** khi xem lại ván đã kết thúc | `lila/modules/aiCoach` |

Cả hai module chỉ hiện với người chơi của ván. Người xem và đối thủ không thấy
kết quả Tilt của nhau. Trong lúc đang chơi, cả hai module đều ẩn.

### 1. Tilt

Với mỗi ván blitz đã kết thúc, hệ thống ước tính khả năng người chơi đang
"tilt", tức là chơi kém đi rõ rệt so với chính mình sau những ván thua trong
cùng một phiên. Kết quả là điểm 0–100 và một trong ba mức: **Thấp** (dưới 10),
**Đáng chú ý** (10–30) và **Cao** (từ 30). Tab Tilt nêu lý do bằng lời thường,
ví dụ thua liên tiếp hoặc đi nhanh hơn nhịp quen thuộc.

Khi người chơi có hai ván mức Cao liên tiếp, hoặc một ván Cao trong một phiên
thua nhiều, trang chủ hiện lời nhắc nghỉ. Lời nhắc hiện tối đa một lần mỗi
phiên, cách nhau ít nhất 30 phút, và tắt được ở `/account/tilt`.

**Cách hoạt động**

1. Lila đưa mỗi ván cờ tiêu chuẩn có đồng hồ (không đấu máy) vào hàng đợi
   `tilt_queue`, mỗi người chơi một mục.
2. Worker Python lấy ván, tự phân tích bằng Stockfish và so với thói quen của
   chính người chơi đó: độ chính xác, số nước hỏng, thời gian suy nghĩ, kết
   quả các ván trước trong phiên.
3. Mô hình M-v3 (XGBoost có hiệu chỉnh xác suất) cho điểm, dựa trên thông tin
   trước ván và 20 nửa nước đầu. Kết quả được ghi lại cho lila hiển thị.

Mô hình học từ một bộ luật nhãn gồm 5 luật ngữ cảnh trong phiên và 7 luật bằng
chứng hành vi, chạy trên 67.014 lượt người–ván của 404 người chơi Lichess. Trên
hai tập giữ riêng, PR-AUC đạt 0,458 và 0,451, so với tỉ lệ nền khoảng 0,075 và
mốc so sánh tốt nhất 0,267 / 0,253.

**Giới hạn:** điểm cao nghĩa là ván khớp với mẫu hành vi của bộ luật, không
phải đo cảm xúc thật. Mô hình chỉ chấm ván blitz và kém tin cậy hơn với ván
dưới 20 nửa nước.

Tài liệu: [báo cáo tổng kết](tilt/reports/tilt_final_report.md) ·
[đặc tả triển khai](tilt/reports/label_v3_deployment.md) ·
[bộ luật nhãn v3](tilt/reports/label_v3_preregistration.md) ·
[gói Python và pipeline dữ liệu](tilt/README.md)

### 2. AI Coach

Sau khi ván kết thúc, mỗi người chơi mở tab AI Coach và hỏi về ván của mình,
ví dụ "Nước nào làm tôi thua?" hay "Lẽ ra tôi nên đi gì ở nước 18?". Mỗi
người chơi có một cuộc hội thoại riêng. Giới hạn là 50 câu hỏi mỗi ngày và 30
lượt mỗi ván.

**Cách hoạt động**

1. Ở câu hỏi đầu tiên, nếu ván chưa được phân tích, lila gửi ván cho fishnet
   phân tích bằng Stockfish (khoảng 10 giây với fishnet local) rồi mới trả lời.
2. Lila dựng bản tóm tắt sự kiện của ván: toàn bộ nước đi (đi lại bằng
   scalachess), kết quả, độ chính xác, các nước bị đánh dấu sai, nước tốt nhất
   và biến của Stockfish, kèm ghi chú ăn quân và chênh lệch vật chất.
3. Mô hình ngôn ngữ (mặc định Claude Haiku 4.5) chỉ trả lời từ bản tóm tắt đó.
   Prompt cấm bịa nước đi, cấm mô tả thế cờ ngoài dữ liệu và cấm phán xét gian
   lận. Câu trả lời được truyền về từng đoạn để hiện dần trên giao diện.

Câu hỏi tiếng Việt được trả lời bằng tiếng Việt, theo bảng thuật ngữ cờ vua
đặt sẵn trong prompt. Chữ trên giao diện có cả tiếng Việt và tiếng Anh, theo
ngôn ngữ của trang.

Tài liệu: [script đánh giá các model](lila/bin/ai-coach-eval.mjs) (bộ câu hỏi
cố định, đối chiếu câu trả lời với phân tích Stockfish, đo độ trễ và chi phí)

## Cấu trúc thư mục

Chỉ liệt kê phần thuộc hai module này; phần còn lại giống `main`.

```text
.
├── lila/
│   ├── modules/tilt/                 Hàng đợi, kết quả, lời nhắc trang chủ, giao diện tab Tilt
│   ├── modules/aiCoach/              Tóm tắt sự kiện ván, prompt, gọi mô hình, giao diện tab AI Coach
│   ├── app/controllers/              Tilt.scala, AiCoach.scala
│   ├── ui/analyse/src/aiCoach/       Frontend tab AI Coach
│   ├── ui/lib/css/component/_tilt.scss
│   └── bin/ai-coach-eval.mjs         Đánh giá và so sánh model cho AI Coach
└── tilt/                             Gói Python của Tilt
    ├── src/tilt/                     Thu thập ván, feature, bộ luật nhãn, huấn luyện, worker cho lila
    ├── scripts/                      start-lichess.sh (chạy cả hệ thống), fishnet-local.py
    ├── tests/                        Test unit, integration, regression
    ├── reports/                      Báo cáo từng giai đoạn nghiên cứu
    └── docs/                         Tài liệu kỹ thuật và nghiên cứu
```

## Công nghệ

| Phần | Công nghệ |
|---|---|
| Module trong lila | Scala 3, Play Framework, MongoDB |
| Frontend | TypeScript, Snabbdom, Sass |
| Tilt | Python 3.12, pandas, XGBoost, scikit-learn, python-chess, Stockfish |
| AI Coach | Claude qua Anthropic Messages API (hoặc API tương thích OpenAI), fishnet |

## Cài đặt và chạy

Cần mọi thứ để chạy lila như ở [README của main](https://github.com/trantrien1/Lichess-workspace/blob/main/README.md)
(Java, sbt, Node.js, pnpm, MongoDB, Redis), thêm Python 3.12 và Stockfish ở
`/usr/games/stockfish`.

**1. Cài gói Python của Tilt** (tại thư mục gốc repo)

```sh
python3.12 -m venv tilt/.venv
tilt/.venv/bin/pip install -r tilt/requirements-lock.txt
tilt/.venv/bin/pip install -e 'tilt[test]'
```

Venv này cũng chạy fishnet local cho AI Coach.

**2. Chuẩn bị mô hình Tilt**

Worker cần mô hình đã huấn luyện trong `tilt/data/processed/models/` và chuỗi
salt dùng để ẩn danh tên người chơi trong `~/.tilt-salt`. Dữ liệu và mô hình
không nằm trong repo. Cách thu thập và huấn luyện ở [tilt/README.md](tilt/README.md).

**3. Khóa API cho AI Coach**

Ghi khóa API vào `~/.ai-coach-key` (`chmod 600`), hoặc đặt biến môi trường
`AI_COACH_API_KEY`. Không ghi khóa vào repo. Các biến tùy chọn:

| Biến | Mặc định | Ý nghĩa |
|---|---|---|
| `AI_COACH_PROVIDER` | `anthropic` | `anthropic` hoặc `openai` (API tương thích OpenAI) |
| `AI_COACH_URL` | API Anthropic | Địa chỉ API hoặc gateway |
| `AI_COACH_MODEL` | `claude-haiku-4-5-20251001` | Model trả lời |
| `AI_COACH_EFFORT` | trống | `low` / `medium` / `high` cho Opus, Sonnet |

**4. Bật Tilt trong lila**

Thêm vào `lila/conf/application.conf`:

```hocon
tilt.enabled = true
```

**5. Chạy**

```sh
cd lila && ./ui/build && cd ..
tilt/scripts/start-lichess.sh
```

Script bật lila-ws, worker Tilt, fishnet local và lila, rồi mở ở
http://localhost:9663. Ctrl+C dừng tất cả. Log nằm ở `~/.lichess-logs/`.
Worker Tilt hoặc AI Coach không có mô hình hay khóa thì script bỏ qua phần đó
và báo trên màn hình.

## Kiểm thử

| Phạm vi | Lệnh |
|---|---|
| Tilt trong lila | trong `lila/`: `sbt 'tilt/Test/testOnly lila.tilt.*'` |
| AI Coach | trong `lila/`: `sbt 'aiCoach/Test/testOnly lila.aiCoach.*'` |
| Gói Python Tilt | tại gốc repo: `tilt/.venv/bin/python -m pytest tilt/tests` |

## Quyền riêng tư

- Kết quả Tilt và hội thoại AI Coach chỉ người chơi của ván xem được.
- Tên người chơi trong dữ liệu huấn luyện được ẩn danh bằng salt riêng. Dữ
  liệu thô, salt và khóa API không bao giờ đưa vào repo.
- Câu hỏi gửi cho AI Coach chỉ kèm dữ liệu của ván đó (nước đi, kết quả,
  rating, phân tích), không kèm tên tài khoản.

## Giấy phép

Hai module trong lila theo giấy phép của lila ([GNU AGPL v3](lila/LICENSE)).
Cảm ơn [Lichess](https://lichess.org), [Stockfish](https://stockfishchess.org)
và [Anthropic](https://www.anthropic.com).
