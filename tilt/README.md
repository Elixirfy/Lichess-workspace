# Pipeline dữ liệu tilt và weak-label model — mục 2.3–2.6

Gói Python 3.12 thu thập ván cờ chuẩn, tạo đặc trưng hành vi và thu nhãn **do con người cung cấp**. Mục 2.4–2.6 bổ sung pipeline **weak-label model** riêng: các nhãn suy luận là proxy hành vi, **không đo cảm xúc** và không ghi vào kho nhãn con người. Xem [WEAK_LABELS.md](docs/research/WEAK_LABELS.md) cho ngưỡng, anti-circularity, mô hình, đánh giá và giới hạn.

```bash
export TILT_SALT=$(cat ~/.tilt-salt)
# Chỉ chạy khi features/manifest.json đã có; không khởi chạy Stockfish.
tilt/.venv/bin/python -m tilt weak-label --users-file ~/tilt-users.txt
tilt/.venv/bin/python -m tilt train --threads 2
tilt/.venv/bin/python -m tilt evaluate
tilt/.venv/bin/python -m tilt score --player '<username>' --game '<id>'
```

Kết quả nằm trong `data/processed/out/MODEL_REPORT.md`, `weak_*.parquet` và `data/processed/models/`.
Chỉ dùng các tài khoản trong cohort; không đưa đối thủ thiếu lịch sử vào tập học.
Tất cả metric đo mức đồng thuận với weak labels; chưa có kiểm định bằng nhãn con người.
Điểm cả ván dự đoán sau khi ván kết thúc; timeline prefix là thử nghiệm, chưa có calibration cấp cửa sổ.

## Cài đặt

Chạy tại thư mục gốc monorepo:

```bash
python3.12 -m venv tilt/.venv
source tilt/.venv/bin/activate
python -m pip install -r tilt/requirements-lock.txt
python -m pip install -e 'tilt[test]'
python -m tilt --help
```

Stockfish mặc định là `/usr/games/stockfish`. Có thể dùng binary khác với `--engine`. Mỗi worker dùng 1 thread; `--processes` quy định số tiến trình. Mọi dữ liệu mặc định nằm trong `tilt/data/` đã được git-ignore. `--data` phải đặt **trước** tên lệnh; hãy giữ đường dẫn tùy chỉnh bên trong `tilt/data/` để tránh commit nhầm dữ liệu.

## Thu thập qua API

```bash
python -m tilt collect-api DrNykterstein --max 20 --perf-type blitz,bullet
# users.txt: mỗi dòng một username; chấp nhận CSV do sample-players tạo.
python -m tilt collect-api --users-file tilt/data/external/users.txt --max 1000 \
  --since 1735689600000 --until 1738367999999 --perf-type blitz,rapid
```

Có thể đặt `LICHESS_TOKEN` trong môi trường; chương trình không in hay lưu token. Không cần token cho API công khai. Một khóa file dùng chung cho các lệnh HTTP của gói bảo đảm chỉ có **một request đang hoạt động**, kể cả trong khi đọc stream và chờ 429. Nếu gặp 429, đóng response rồi chờ đủ **60 giây**, sau đó retry. User-Agent: `tilt-research-dataset/0.1`.

Mỗi response được lưu nguyên byte NDJSON sau giải mã HTTP trong một file gzip riêng theo người chơi. Lần đầu lấy tối đa `--max` ván mới nhất; các lần sau lấy tăng dần theo `createdAt`, với mốc `since` được điều chỉnh theo nhánh truy vấn Lichess (không perf: `watermark + 1`; có perf: `watermark`, vì nhánh search dùng so sánh nghiêm ngặt). Cursor lưu cả `created_at` mới nhất và `oldest_created_at` cũ nhất, tách riêng theo bộ lọc since/until/perf. `--backfill` dùng `until=oldest_created_at` (cận loại trừ), `sort=dateDesc` và `--max` để lấy các ván cũ hơn. Mỗi lượt mở rộng mốc cũ nhất; response rỗng báo đã hết lịch sử trong bộ lọc. Nếu cursor cũ chỉ có mốc mới nhất, lượt backfill đầu có thể tải trùng một phần; index chống trùng giữ dữ liệu nhất quán. Chỉ cập nhật cursor khi response hoàn tất; Parquet có index chống trùng game id. Nếu bị ngắt, chạy lại lệnh và/hoặc khôi phục những dòng raw đã ghi:

```bash
python -m tilt normalize
```

`since` của API lọc **thời điểm tạo ván**, không phải thời điểm ván kết thúc. Ván còn đang chơi ở lượt tải trước nhưng được tạo trước watermark có thể cần backfill bằng một khoảng `--since/--until` khác. `--max` giới hạn số trả về mỗi lượt; nếu lấy chưa hết phần mới, tiếp tục chạy lại. Không dùng collector này để cập nhật analysis mới của game id đã nhập: nguồn đầu tiên được giữ; muốn thay nguồn phải xây một data root mới từ raw. Chính sách này giúp tránh thay đổi dữ liệu âm thầm.

Để lấy lịch sử **X tháng gần nhất**, ví dụ 6 tháng (lệnh `date` của GNU/Linux), giữ nguyên mốc `since` cho mọi lượt:

```bash
HISTORY_START_MS="$(date -u -d '6 months ago' +%s)000"
# Lượt đầu lấy các ván mới nhất trong khoảng.
python -m tilt collect-api alice --since "$HISTORY_START_MS" --max 1000
# Lặp lại lệnh này đến khi báo không còn ván cũ trong khoảng đã chọn.
python -m tilt collect-api alice --since "$HISTORY_START_MS" --max 1000 --backfill
```

Nếu có `--perf-type` hoặc `--until`, giữ nguyên chúng khi backfill để dùng đúng cursor. Mỗi lượt `--backfill` đi lùi; lượt không có cờ đó vẫn đi tới các ván mới. `until` loại trừ trên cả nhánh Mongo và search; xem nguồn repo ở API_SEMANTICS.

Chi tiết trường API và kết quả smoke thật: [API_SEMANTICS.md](docs/architecture/API_SEMANTICS.md). Nguồn chính thức: [Lichess API](https://lichess.org/api#tag/Games/operation/apiGamesUser).

## Dump tháng và chọn người chơi

```bash
python -m tilt collect-dump tilt/data/external/downloads/tiny.pgn.zst \
  --users-file tilt/data/external/users.txt --speeds blitz,rapid --min-games 20 --limit 10000
python -m tilt collect-dump \
  https://database.lichess.org/standard/lichess_db_standard_rated_2025-01.pgn.zst \
  --users-file tilt/data/external/users.txt --speeds blitz --min-games 20
python -m tilt sample-players tilt/data/external/downloads/month.pgn.zst \
  --output tilt/data/external/sample.csv --min-games 20 --per-stratum 10 \
  --rating-band-width 200 --seed 42 --speeds blitz,rapid \
  --since 1735689600000 --until 1738367999999
```

Nguồn có thể là PGN nhỏ, `.pgn.zst` cục bộ, hoặc URL dump tháng chính thức trên [database.lichess.org](https://database.lichess.org/). Zstandard được giải nén qua stream, **không ghi PGN giải nén ra đĩa**. SQLite staging chứa các ván ứng viên đã chuẩn hóa, tránh giữ cả dump trong RAM; staging được xóa sau lượt nhập hoặc khi lỗi. `collect-dump` bắt buộc có `--users` (danh sách tên), `--users-file` hoặc `--limit`, kể cả khi đã lọc speed/thời gian. Cả hai lệnh có `--max-staging-gb` (mặc định **5 GiB**): từ chối trước khi đọc dump nếu dung lượng đĩa trống thấp hơn mức này; khi staging vượt giới hạn thì dừng, báo lỗi và xóa SQLite cùng file journal. Giới hạn tính cả trang chưa flush và file phụ; không giới hạn dung lượng Parquet đầu ra. Muốn quét nhiều hơn, chọn người chơi/limit nhỏ hơn hoặc tăng giới hạn phù hợp với dung lượng đĩa. Bản ghi Parquet được ghi theo batch 100 ván. Cần đủ dung lượng cho dữ liệu đã chọn; đây không phải lưu trữ miễn phí.

`--limit` đếm ván ứng viên sau bộ lọc người chơi/speed/thời gian, **trước** lọc min-games. Min-games tính trong phần dump đã quét và khoảng thời gian đã chọn; khi có limit thì không khẳng định đó là tổng cả tháng. Với users-file, chỉ cần một người chơi mục tiêu đủ số ván để giữ ván. Sampling đếm riêng từng người/speed; chia band bằng rating trung bình, chọn theo hash seed cố định trong từng tầng band×speed. CSV có thể có một người trong nhiều tầng; collector khử trùng username. Sampling chỉ đọc header để không phân tích mọi nước không cần thiết.

Cả hai nguồn ghi cùng schema `normalized/games/*.parquet` và `normalized/moves/*.parquet`; một hàng moves ứng với một ply đã chơi. Không nhập biến thể cờ khác. Ván lỗi/biến thể trong dump được bỏ qua và có số đếm trong kết quả lệnh.

## Stockfish và feature

```bash
python -m tilt analyze --engine /usr/games/stockfish --nodes 100000 --processes 4 --hash-mb 64
# Hoặc budget độ sâu cố định:
python -m tilt analyze --depth 16 --processes 2
python -m tilt features --window 12 --min-prior-games 5 --session-gap-minutes 30 --max-history-games 200
```

`analyze` điền vị trí thiếu eval và bổ sung best/second-best cho các vị trí còn lại. Luôn MultiPV=2 (chỉ một PV nếu chỉ có một nước hợp lệ), ngân sách cố định, White POV, ghi phiên bản engine, SHA256 binary, options, số node/depth thực tế. Cache khóa bằng **FEN đầy đủ + settings**; chạy lại cùng cấu hình không tìm kiếm lại. Đổi binary/budget tạo khóa khác. Engine được reset cho từng vị trí, đóng khi kết thúc batch; không phụ thuộc warm hash hay thứ tự worker. Chỉ FEN được gửi nên không biết lịch sử lặp lại thế cờ; đây là hạn chế phân tích được ghi trong settings. Eval có sẵn từ Lichess được giữ, không bị thay âm thầm bởi engine cục bộ.

Feature tạo ở cấp nước, cửa sổ N **ply toàn bàn** (chỉ tổng hợp nước của người mục tiêu trong đó), sự kiện, ván–người chơi, và phiên–người chơi. [FEATURES.md](docs/guides/FEATURES.md) định nghĩa đơn vị và nguồn từng cột. Các bảng feature không có cột nhãn. Cửa sổ hậu sự kiện và feature cả ván/phiên là hồi cứu; có `available_after_ply` cho cửa sổ/sự kiện. Không dùng thông tin hậu sự kiện cho dự đoán tại lúc sự kiện xảy ra.

Phiên mới bắt đầu khi khoảng nghỉ từ kết thúc ván trước đến lúc bắt đầu ván mới **lớn hơn 30 phút** (cấu hình được). Nếu thiếu thời điểm kết thúc, dùng khoảng cách giữa hai lần bắt đầu làm proxy và ghi `session_gap_basis=start_gap_proxy`. Ván chồng thời gian vẫn có thể cùng phiên, nhưng kết quả/feature của ván chưa kết thúc không vào lịch sử baseline, chuỗi thua hay recent form. Các feature được tính trong RAM trên cohort đã nhập; không chạy `features` trực tiếp trên toàn bộ hàng tỷ ván chưa lọc.

## Quy tắc không rò rỉ

Với ván G, chỉ nhận lịch sử của **cùng người** có `end_upper_ms < G.start_ms`. Không dùng thứ tự file, thời điểm bắt đầu của ván cũ hoặc `lastMoveAt` thay cho điều kiện đó. `end_upper_ms` bảo thủ tính từ terminal move hoặc đồng hồ dừng; nếu không xác định được thì dùng cận quan sát cho API, hoặc để thiếu với dump. Header kết thúc PGN có độ phân giải giây nên cộng biên một giây. Xem chi tiết và giới hạn ở API_SEMANTICS.

Baseline dùng tối đa **K=200 ván gần nhất đã kết thúc đủ sớm**, cùng người và speed, sắp theo `(end_upper_ms, game_id)`; chỉnh bằng `--max-history-games K` (>0). Áp dụng cùng K cho baseline cấp nước/ván, ngưỡng `normal_cpl` phục hồi và baseline session khi xuất dataset. Chọn K ván trước rồi mới lọc pressure/lợi thế/giá trị thiếu; không lùi thêm để bù số ván thiếu. Manifest feature, manifest xuất và data card ghi lại K. Thống kê median/MAD và danh sách giá trị theo context được chuẩn bị một lần cho mỗi ván, nên mỗi nước không quét lại lịch sử. Chuỗi thua/rematch, recent form và tổng số ván lịch sử vẫn giữ định nghĩa cũ, không cắt theo K.

Baseline cấp ván cùng speed; baseline cấp nước còn cùng áp lực đồng hồ (<20% / bình thường / không rõ) và trạng thái lợi thế. Dùng median và MAD, tối thiểu mặc định **5 ván lịch sử có giá trị hợp lệ cho feature đó**. Thiếu lịch sử thì median/MAD/z-score/BDS tương ứng để thiếu; không điền population mean. Scale là `max(1.4826 × MAD, unit_floor)`, floor được công khai trong FEATURES. Không fit scaler hay imputer bằng toàn bộ dữ liệu.

Behavioral Deviation Score (BDS) = `10 × mean(min(10, abs(z)))` trên các z hợp lệ, khoảng 0–100; có số feature tham gia. BDS là mức khác thường so với bản thân, **không phải nhãn tilt**. Test thêm một ván tương lai và ván chồng thời gian chứng minh các hàng feature trước đó không đổi.

## Salt

```bash
export TILT_SALT="$(python -c 'import secrets; print(secrets.token_hex(32))')"
# Lưu salt an toàn ngoài Git (ví dụ ~/.tilt-salt) để các phiên sau dùng lại đúng giá trị.
```

Username, game id và session id được giả danh bằng HMAC-SHA256 với salt này trước khi xuất. Nhãn người thật (nếu có) được nhập qua `tilt.labels.insert_label` vào `raw/labels/labels.sqlite`; kho nhãn từ chối salt khác với salt đã dùng khi tạo.

## Xuất dataset

```bash
python -m tilt build-dataset
python -m tilt build-dataset \
  --time-validation-ms 1738368000000 --time-test-ms 1740787200000
```

Lệnh xây lại feature từ normalized theo cấu hình đã lưu, audit điều kiện baseline, ghép **chỉ nhãn người thật** theo player và phạm vi, rồi xuất:

- `out/labelled.parquet`: một hàng/annotation, target là `target_tilt`.
- `out/by_player.parquet`: bucket hash ổn định, xấp xỉ 70/10/20 train/validation/test, người mục tiêu không trùng giữa các phần; purge game dùng chung giữa các phần.
- `out/by_time.parquet`: split theo thời gian, mặc định percentile 80/90 của thời gian bắt đầu khác nhau, hoặc cutoff chỉ định; purge phạm vi băng qua cutoff, loại phạm vi thiếu cận kết thúc.
- `out/manifest.json`: cấu hình, cutoff, target, **allowlist predictor**; metadata báo cáo và survey answers không được dùng làm predictor.
- `out/DATACARD.md`: số lượng theo speed/band/nguồn nhãn, missingness, số hàng từng split và giới hạn.

Chỉ dùng hàng có `split` là `train`, `validation` hoặc `test` khi chuẩn bị bước 2.4; hàng purge/excluded dùng cho audit. Với cohort nhỏ có thể có phần rỗng. History không nhãn đã có trước thời điểm dự đoán được phép dùng cho người ở test; nhãn test không tham gia baseline. Nhãn moment chỉ ghép feature trong khoảng ply được báo cáo, không ghép kết quả ván hay post-event window bên ngoài khoảng. Để split thời gian bảo thủ, dùng thời gian cả ván chứa moment vì dữ liệu không có timestamp chính xác mỗi ply. Nhãn session chỉ dùng phần phiên đã kết thúc/được quan sát hoàn tất tại lúc báo cáo, tránh ghép thêm ván chơi sau báo cáo dù vẫn cùng session id; baseline session chỉ dùng ván kết thúc trước lúc phiên bắt đầu.

Username/người chấm được xuất bằng HMAC-SHA256 với `TILT_SALT`. Không xuất username hay câu trả lời Likert. Game id được thay bằng `HMAC-SHA256(salt, "game:" + game_id)`, session id bằng `HMAC-SHA256(salt, "session:" + session_id)` trước khi ghi bất kỳ bảng nào trong `out/`. HMAC id phân biệt chữ hoa/thường của game id. Không xuất `previous_game_id`, danh sách game id thô hoặc username/id đối thủ; manifest và data card chỉ chứa cấu hình/thống kê. Purge ván dùng chung vẫn dùng id nội bộ nhất quán. Raw/normalized/features cục bộ vẫn giữ id gốc để ứng dụng hiển thị; bảo vệ các thư mục này. Thời gian và hành vi vẫn có thể giúp tái nhận diện; dataset **giả danh, không ẩn danh tuyệt đối**. Nếu chưa có nhãn người thật, đầu ra có 0 hàng gán nhãn: đó là kết quả đúng, không tạo nhãn thay thế.

## Cấu trúc thư mục

```text
tilt/
  pyproject.toml, requirements-lock.txt, .env.example
  src/tilt/
    __main__.py          # CLI: python -m tilt <lệnh>
    core/                # engine (Stockfish), formulas, sequence, train, score
    data/                # collect, normalize, storage, dataset
    features/            # features, model_features
    labels/              # labels (nhãn người), weak_labels
    evaluation/          # evaluate
    workers/             # lila_worker
  data/{raw,processed,external}/   # dữ liệu riêng tư, git-ignore
  tests/{unit,integration}/
  scripts/               # start-lichess.sh, fishnet-local.py
  reports/               # báo cáo tổng kết, đặc tả triển khai, bộ luật v3
  docs/{architecture,research,guides}/
```

`normalize.py` nằm trong `data/` vì nó chuyển response API/PGN thành schema lưu trữ và được `collect` gọi trực tiếp. `train.py` nằm trong `core/` cạnh `score.py`. Gói cài ở chế độ editable (`pip install -e`) vì `data/` nằm ngoài `src/`.

## Dữ liệu và quyền riêng tư

```text
tilt/
  data/                        # chỉ khung thư mục được Git theo dõi
    raw/                       # dữ liệu gốc
      api/<user>/*.ndjson.gz   # nguyên response; cursor theo bộ lọc
      labels/labels.sqlite     # nhãn, câu trả lời, consent; kho tách biệt
    processed/                 # mọi thứ code sinh ra
      index.sqlite             # game id và manifest batch đã commit
      normalized/{games,moves}/*.parquet
      engine/{cache.sqlite,selected.json}
      features/{moves,windows,events,games,sessions}.parquet
      features/manifest.json
      out/{labelled,by_player,by_time}.parquet
      out/{DATACARD.md,manifest.json}
      out/weak_*.parquet       # proxy hành vi; tách biệt nhãn con người
      out/{MODEL_REPORT.md,weak_metrics.json,weak_manifest.json}
      models/                  # model bundles, feature lists, run manifest
    external/                  # đầu vào từ nguồn ngoài và vùng tạm
      downloads/, users.txt    # dump PGN, danh sách người chơi
      staging/                 # SQLite tạm cho dump, xóa khi hoàn tất
      lila/                    # data root riêng của lila-worker
      http.lock                # khóa giới hạn tốc độ HTTP dùng chung
```

Raw username, lịch sử ván, survey answers và thời gian báo cáo là dữ liệu cá nhân. **Không commit bất kỳ file data, `.env`, salt hay token nào**; chỉ fixtures tổng hợp nhỏ trong `tests/fixtures/` được theo dõi. Hạn chế quyền truy cập máy và backup, thống nhất thời hạn giữ/xóa và yêu cầu rút consent trong nhóm. Việc dữ liệu cờ công khai không thay thế đồng ý sử dụng câu trả lời nghiên cứu. Không đăng dữ liệu này lên dịch vụ khác qua app.

## Tích hợp vào web lila

Theo cùng mẫu với Kaladin (`lila/modules/irwin/src/main/KaladinApi.scala`): lila ghi yêu cầu vào một collection MongoDB, dịch vụ Python bên ngoài ghi kết quả ngược lại.

- `lila/modules/tilt`: khi bật `tilt.enabled = true` (mặc định `false` trong `conf/base.conf`; bản local đặt trong `conf/application.conf`), mỗi ván chuẩn có đồng hồ, giữa hai người (không AI/BOT) kết thúc sẽ tạo một document cho mỗi người chơi trong `tilt_queue`. Index nằm trong `lila/bin/mongodb/indexes.js`. Xóa tài khoản thì xóa luôn các document của người đó.
- Trang `/account/tilt` (mục **Tilt** trong menu tài khoản) chỉ hiện điểm của chính người đăng nhập: điểm 0–100, mức, cờ ngưỡng và 3 yếu tố ảnh hưởng nhất.
- `python -m tilt lila-worker`: đọc các document chưa có `response`, tải tối đa 200 ván gần nhất của người chơi từ API export của lila (`--lila-url`, mặc định `http://localhost:9663`) vào data root riêng `tilt/data/external/lila`, chạy Stockfish với đúng cấu hình feature của mô hình, dựng feature, chấm bằng mô hình đã chọn trong `--data` (mặc định `tilt/data`), rồi ghi `response = {at, pred: {score, flag, factors}}` hoặc `{at, err}`. Ván chưa xuất kịp được giữ lại tối đa 2 phút; lila chưa chạy thì yêu cầu vẫn nằm trong hàng đợi.

```bash
pip install -e 'tilt[lila]'          # pymongo
TILT_SALT="$(cat ~/.tilt-salt)" tilt/.venv/bin/python -m tilt lila-worker   # --once để chạy một lượt
```

`tilt/scripts/start-lichess.sh` tự khởi động worker khi có `tilt/data/processed/models` và `~/.tilt-salt` (log: `~/.lichess-logs/tilt.log`). Điểm vẫn là proxy hành vi của weak label, không đo cảm xúc. Mô hình chỉ học trên ván blitz và chưa được kiểm chứng bằng nhãn con người; xem `data/out/MODEL_REPORT.md`.

## Kiểm thử

```bash
python -m pytest tilt/tests -q        # hoặc tilt/tests/unit, tilt/tests/integration
```

Test chặn toàn bộ HTTP, dùng NDJSON/PGN tổng hợp nhỏ (tự nén zstd trong test), kiểm tra công thức port, clock/increment/mate zero, retry 429/resume, min-games/sampling, no-leakage, kho nhãn, split, bộ luật v3, worker lila và chấm điểm trực tiếp. Test engine thực chạy Stockfish với 1000 node trên vài vị trí cục bộ; bỏ qua riêng test đó nếu không có binary. Không test nào tải dump thật. `requirements-lock.txt` ghi phiên bản môi trường đã kiểm tra.

Mã port công thức tham chiếu đường dẫn Lichess ngay cạnh hàm; giữ giấy phép AGPL của nguồn (LICENSE/NOTICE). Không có commit tự động. Ngoài `tilt/`, chỉ phần tích hợp ở trên chạm vào `lila/`.
