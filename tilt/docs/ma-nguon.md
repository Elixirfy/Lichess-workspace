# Mã nguồn

## Cấu trúc thư mục

```text
tilt/
├── pyproject.toml, requirements-lock.txt   Khai báo gói, phiên bản thư viện đã kiểm tra
├── .env.example                            Mẫu biến môi trường (không chứa giá trị thật)
├── LICENSE, NOTICE                         AGPL, giống Lichess (có công thức port từ Lichess)
├── src/tilt/                               Gói Python
│   ├── __main__.py                         Dòng lệnh: python -m tilt <lệnh>
│   ├── common/                             Dùng chung: công thức Lichess, Stockfish
│   ├── data/                               Thu thập, chuẩn hóa, lưu trữ ván
│   ├── features/                           Tính đặc trưng
│   ├── labels/                             Nhãn: bộ luật v3, nhãn yếu, nhãn người
│   ├── training/                           Huấn luyện mô hình
│   ├── evaluation/                         Đánh giá mô hình
│   └── service/                            Chấm điểm trực tiếp cho lila (worker)
├── scripts/
│   ├── start-lichess.sh                    Chạy cả hệ thống local
│   └── fishnet-local.py                    Fishnet local cho phân tích máy và AI Coach
├── tests/
│   ├── unit/                               Test từng module
│   └── integration/                        Test cả chuỗi xử lý trên dữ liệu tổng hợp nhỏ
├── reports/                                Báo cáo gốc (xem mục lục tài liệu)
├── docs/                                   Tài liệu này
└── data/                                   Dữ liệu riêng tư, không đưa vào git
```

Gói được cài ở chế độ editable (`pip install -e`), nên code trong `src/` có
hiệu lực ngay, không cần cài lại sau khi sửa.

## Các gói và module

Các gói xếp theo vai trò. Hướng phụ thuộc chính đi từ trên xuống: `common` →
`data` → `features`, `labels` → `training` → `evaluation` → `service`. Có hai
chỗ đi ngược, giữ nguyên để không đổi mã đã khóa: `features/prefix_features.py` dùng
hàm `dynamics` của `service/score.py`, và `evaluation/compare_p3b.py` dùng
`service/deployment.py`, `service/score.py`.

### `common/`: dùng chung

| Tệp | Vai trò |
|---|---|
| `formulas.py` | Công thức port từ mã nguồn Lichess: cơ hội thắng, độ chính xác nước và ván, phân loại sai lầm, chia giai đoạn ván, thể thức. Mỗi hàm ghi đường dẫn tới mã gốc. |
| `engine.py` | Chạy Stockfish với ngân sách cố định, MultiPV = 2, nhiều tiến trình, bộ đệm SQLite theo FEN + cấu hình. |

### `data/`: dữ liệu ván

| Tệp | Vai trò |
|---|---|
| `collect.py` | Tải ván qua API công khai (tuần tự, tiếp tục được khi bị ngắt) và đọc dump tháng của Lichess. |
| `normalize.py` | Đổi dữ liệu API/PGN về một schema chung: đồng hồ tính bằng giây, đánh giá theo góc nhìn Trắng. |
| `storage.py` | Ghi Parquet theo lô nhỏ, chỉ mục SQLite chống trùng. Định nghĩa thư mục dữ liệu mặc định `tilt/data`. |
| `dataset.py` | Ghép nhãn người, giả danh id, kiểm tra rò rỉ, chia tập (pipeline nhãn người cũ). |
| `cohort_build.py` | Dựng cohort dữ liệu cho vòng v3 (bị khóa hash). |

### `features/`: đặc trưng

| Tệp | Vai trò |
|---|---|
| `features.py` | Đặc trưng theo nước, cửa sổ, sự kiện, ván, buổi chơi; mức thường lệ chỉ từ các ván trước. |
| `behavior.py` | Đặc trưng hành vi bổ sung của Phase 2 (P3-B dùng). |
| `model_features.py` | Danh sách đặc trưng hợp lệ cho mô hình cũ, loại các cột liên quan đến nhãn yếu. |
| `prefix_features.py` | 104 đặc trưng của M-v3 (trước ván + 20 nửa nước đầu) (bị khóa hash). |

### `labels/`: nhãn

| Tệp | Vai trò |
|---|---|
| `tilt_rules.py` | Bộ luật v3: 5 luật ngữ cảnh, 7 luật cách chơi, bảng kết hợp (bị khóa hash). |
| `dev_split.py` | Cách chia dữ liệu phát triển của v3, hàm hash dùng chung (bị khóa hash). |
| `weak_labels.py` | Nhãn yếu của P3-B. |
| `labels.py` | Kho nhãn người thật và hàm giả danh id bằng HMAC (`private_id`). M-v3 không dùng nhãn người; nó học từ bộ luật. |

### `training/`: huấn luyện

| Tệp | Vai trò |
|---|---|
| `train.py` | Huấn luyện cây (XGBoost, LightGBM, Random Forest) cho nhãn yếu, hiệu chỉnh xác suất; hàm `predict_bundle` dùng chung. |
| `sequence.py` | Mô hình LSTM nhỏ chạy CPU (thử nghiệm ở vòng nhãn yếu). |
| `distill.py` | Huấn luyện M-v3: dựng ma trận, fit hai đầu, hiệu chỉnh, gộp điểm (bị khóa hash). |

### `evaluation/`: đánh giá

| Tệp | Vai trò |
|---|---|
| `evaluate.py` | Đánh giá mô hình nhãn yếu; hàm `contributions` (SHAP) dùng cho P3-B. |
| `eval_metrics.py` | Cách chia dữ liệu, ma trận đặc trưng, các mô hình mốc và hàm đo (PR-AUC, ROC, ECE). Trước là `phase1.py`. |
| `p3b_features.py` | Các bộ đặc trưng hành vi, trong đó có bộ của P3-B. Trước là `phase3.py`. |
| `model_fit.py` | Cách fit XGBoost + Platt, bootstrap, danh sách cột cấm, chọn mô hình cuối (P3-B). Trước là `phase5.py`. |
| `compare_p3b.py` | So sánh với P3-B trên cả ván ở vòng S4 (bị khóa hash). |
| `final_holdout.py` | Chấm phần đánh giá cuối đúng một lần (S5). |

### `service/`: chấm điểm cho lila

| Tệp | Vai trò |
|---|---|
| `lila_worker.py` | Worker đọc `tilt_queue`, tải ván, chạy Stockfish, chấm, ghi kết quả. |
| `live_scoring.py` | Chấm M-v3: nạp và kiểm tra bundle, kiểm tra hash mã, tính lý do, bộ luật sau ván. |
| `score.py` | Chấm P3-B (chạy ẩn) và dòng thời gian thử nghiệm theo nửa nước. |
| `deployment.py` | Nạp mô hình P3-B, từ chối khi bundle không khớp. |

Worker chỉ gọi trực tiếp các module trong `service/`; phần lớn module khác được
nạp gián tiếp qua đó. Chỉ `evaluation/final_holdout.py` và các lệnh nghiên cứu ở
bảng dưới là không dùng khi chạy thật.

## Dòng lệnh

Chạy tại gốc repo: `tilt/.venv/bin/python -m tilt [--data <thư mục>] <lệnh>`.
`--data` phải đặt trước tên lệnh, mặc định là `tilt/data`. Worker và các lệnh
cần giả danh id đòi biến `TILT_SALT` (xem [Salt](#salt)).

| Lệnh | Việc làm | Dùng khi |
|---|---|---|
| `lila-worker` | Chấm các ván trong `tilt_queue` của lila | chạy thật |
| `collect-api` | Tải ván của người chơi qua API Lichess | nghiên cứu |
| `normalize` | Dựng lại bảng chuẩn hóa từ dữ liệu gốc đã tải | nghiên cứu |
| `collect-dump` | Đọc dump PGN tháng của Lichess | nghiên cứu |
| `sample-players` | Chọn người chơi theo khoảng rating từ dump | nghiên cứu |
| `analyze` | Phân tích Stockfish các thế cờ còn thiếu | nghiên cứu |
| `features` | Tính đặc trưng và mức thường lệ | nghiên cứu |
| `build-dataset` | Ghép nhãn người, giả danh, chia tập | nghiên cứu (chưa có nhãn người) |
| `weak-label`, `train`, `evaluate`, `score` | Pipeline nhãn yếu của P3-B | nghiên cứu |

Các bước của vòng v3 chạy bằng module riêng, ví dụ
`python -m tilt.training.distill` và `python -m tilt.service.live_scoring`.

Ví dụ thu thập:

```bash
python -m tilt collect-api <tên> --max 200 --perf-type blitz
python -m tilt collect-api --users-file tilt/data/external/users.txt --max 300 --perf-type blitz
python -m tilt analyze --nodes 5000 --processes 4
python -m tilt features --min-prior-games 5 --session-gap-minutes 30 --max-history-games 200
```

Ý nghĩa các trường dữ liệu và quy tắc tải ở [Dữ liệu Lichess](du-lieu-lichess.md).

## Thư mục dữ liệu `tilt/data`

```text
tilt/data/                           Không đưa vào git
├── raw/                             Dữ liệu gốc: api/<user>/*.ndjson.gz, labels/labels.sqlite
├── processed/                       Dữ liệu do code sinh ra
│   ├── normalized/, index.sqlite    Bảng ván và nước đã chuẩn hóa, chỉ mục chống trùng
│   ├── engine/                      Bộ đệm Stockfish
│   ├── features/                    Đặc trưng; manifest.json là cấu hình worker phải dùng lại
│   ├── out/                         Kết quả nghiên cứu
│   └── models/                      Mô hình: deployed_v3.json + v3/, deployed.json + phase5/
└── external/                        Dữ liệu từ nguồn ngoài
    ├── lila-v3/{raw,processed}/     Dữ liệu của worker cho M-v3
    ├── lila/{raw,processed}/        Dữ liệu của worker cho P3-B
    ├── downloads/, users.txt        Dump PGN, danh sách người chơi (nghiên cứu)
    ├── staging/                     SQLite tạm khi đọc dump, tự xóa
    └── http.lock                    Khóa bảo đảm mỗi lúc chỉ một request tới Lichess
```

Thư mục này chứa tên người chơi, lịch sử ván và mô hình đã huấn luyện, nên toàn
bộ bị `tilt/.gitignore` bỏ qua. Không commit dữ liệu, `.env`, salt hay token.
Khi cần chuyển dữ liệu sang máy khác, chép trực tiếp (ví dụ `rsync`), không qua
git.

**Về các tệp `.gitkeep` trước đây.** Git không lưu thư mục rỗng, nên trước đây
mỗi thư mục `raw/`, `processed/`, `external/` có một tệp rỗng `.gitkeep` để git
giữ lại khung thư mục. Các tệp này không quan trọng: mọi chỗ ghi dữ liệu đều tự
tạo thư mục khi cần (`mkdir(parents=True, exist_ok=True)` trong `storage.py`,
`lila_worker.py`, `live_scoring.py`). Vì vậy chúng đã được xóa, và `.gitignore` chỉ
còn một dòng `data/`.

## Salt

```bash
export TILT_SALT="$(python -c 'import secrets; print(secrets.token_hex(32))')"
```

Tên người chơi, id ván và id buổi chơi được giả danh bằng HMAC-SHA256 với salt
này trước khi xuất ra bảng nghiên cứu. Lưu salt ngoài git (ví dụ
`~/.tilt-salt`, quyền 600) để các lần sau dùng lại đúng giá trị; đổi salt thì
các id giả danh cũ không khớp nữa. Không in salt ra màn hình hay log.

## Mã bị khóa bằng hash

Mã tính đặc trưng, bộ luật và huấn luyện của M-v3 phải giống hệt bản đã đánh
giá. Worker kiểm tra SHA-256 của sáu tệp sau mỗi khi khởi động
(`FROZEN` trong `service/live_scoring.py`):

| Tệp | SHA-256 (22/11/2026) |
|---|---|
| `features/prefix_features.py` | `0da5bb60…` |
| `labels/tilt_rules.py` | `08e0ee97…` |
| `labels/dev_split.py` | `a64b2594…` |
| `data/cohort_build.py` | `08f33a44…` |
| `training/distill.py` | `3147bdd0…` |
| `evaluation/compare_p3b.py` | `448862b7…` |

Hash còn được ghi ở `FROZEN` trong `evaluation/compare_p3b.py` (ba tệp đầu) và trong
test `tests/unit/test_final_holdout.py`.

Ngày 22/11/2026 mã nguồn được sắp xếp lại theo vai trò: `core/` và `workers/`
được tách thành `common/`, `training/`, `service/`; `v3_train.py` chuyển từ
`evaluation/` sang `training/`. Lần đó chỉ sửa dòng import và chuỗi đường dẫn,
rồi cập nhật hash ở ba chỗ trên. Sau đó các tệp được đổi tên cho rõ nghĩa, chỉ đổi
tên module trong code, không đổi logic:

| Tên cũ | Tên mới |
|---|---|
| `evaluation/phase1.py`, `phase3.py`, `phase5.py` | `eval_metrics.py`, `p3b_features.py`, `model_fit.py` |
| `data/cohort_v3.py` | `data/cohort_build.py` |
| `features/prefix_v3.py` | `features/prefix_features.py` |
| `labels/rules_v3.py`, `split_v3.py` | `labels/tilt_rules.py`, `dev_split.py` |
| `training/v3_train.py` | `training/distill.py` |
| `evaluation/v3_p3b.py`, `v3_holdout.py` | `evaluation/compare_p3b.py`, `final_holdout.py` |
| `service/live_v3.py` | `service/live_scoring.py` |

Chữ "v3" vẫn còn trong tên mô hình (M-v3), tên dữ liệu (`deployed_v3.json`,
`lila-v3`) và tên báo cáo, vì đó là tên phiên bản bộ luật chứ không phải tên tệp.
Cả ba lần, điểm chấm lại 122 ván local
giống hệt trước khi sửa. Hash cũ của bản đánh giá vẫn nằm trong
[`label_v3_deployment.md`](../reports/label_v3_deployment.md) và
`label_v3_preregistration.md`.

Khi buộc phải sửa một tệp bị khóa (chỉ khi thật cần, ví dụ đổi tên module):

1. Ghi lại điểm của các ván local trước khi sửa.
2. Sửa, rồi tính hash mới: `sha256sum tilt/src/tilt/<tệp>`.
3. Cập nhật `FROZEN` trong `evaluation/compare_p3b.py` trước (vì hash của chính
   `compare_p3b.py` phụ thuộc vào đó), rồi `FROZEN` trong `service/live_scoring.py` và
   dict trong `tests/unit/test_final_holdout.py`.
4. Chạy lại toàn bộ test và chấm lại các ván local, so với điểm ở bước 1.

## Cài đặt

Chạy tại gốc repo:

```bash
python3.12 -m venv tilt/.venv
tilt/.venv/bin/pip install -r tilt/requirements-lock.txt
tilt/.venv/bin/pip install -e 'tilt[test,lila]'
tilt/.venv/bin/python -m tilt --help
```

Stockfish mặc định ở `/usr/games/stockfish`, đổi bằng `--engine`.

## Kiểm thử

```bash
tilt/.venv/bin/python -m pytest tilt/tests -q          # toàn bộ, khoảng 3 phút
tilt/.venv/bin/python -m pytest tilt/tests/unit -q     # chỉ test đơn vị
```

- Test chặn mọi request HTTP và chỉ dùng dữ liệu tổng hợp nhỏ, không tải dump
  thật.
- Test engine chạy Stockfish thật với 1.000 nút trên vài thế cờ; tự bỏ qua nếu
  máy không có Stockfish.
- Một số test đọc dữ liệu nghiên cứu ở `~/tilt-labels-v3` (bản khóa của tài liệu
  bộ luật, hash của lần chạy S4); máy khác có thể trỏ tới bằng biến `S5_V3`.
- Hai test của `test_prefix_features.py` chạy trên mẫu dữ liệu thật và tự bỏ qua nếu
  chưa đặt biến `S3_REAL_CONFIG` trỏ tới các thư mục dữ liệu đó.
- `requirements-lock.txt` ghi phiên bản thư viện đã chạy test.
