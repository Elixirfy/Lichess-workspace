# Phần tỷ lệ dùng chung của nhóm

Theo yêu cầu ngày 18/11/2026, phần tỷ lệ/ưu thế được đưa vào `main` trong một
commit dùng chung: panel live trên hai bàn và người xem, phép tính `W+D/2`,
tooltip gọn, thanh dọc xem lại, chuẩn bị model browser và hạ tầng bot local.
Không đưa Vosk/PhoWhisper, recorder hoặc bản vá voice vào commit này.

Mã có cả ở `lila/` cho workflow monorepo và
`patches/lila-win-probability.patch` cho workflow Docker đã ghim upstream.
Giữ nguyên bình luận Nano/ba BLV và các thay đổi khác của main.

Các báo cáo ở thư mục acceptance khác là bằng chứng lịch sử tại revision đã
ghi, bao gồm cả lúc thử tương thích với voice. Dòng kiểm thử ASR trong các báo
cáo đó không có nghĩa main chứa tính năng voice. Muốn chạy recorder/audio smoke
phải dùng nhánh `codex/vietnamese-voice-input`. Kết quả kiểm tra tách nhánh mới
được ghi trong `validation.json` ở đây; không coi số test của nhánh cũ là số
test vừa chạy trên main.

Đầu ra engine và human model vẫn có giới hạn trong model card. Cùng công thức
không bảo đảm hai engine/độ sâu hoặc human model cho cùng một đầu vào WDL.

## Kiểm tra mới trên source main

- Tỷ lệ live/review: **38/38** test qua; toàn bộ frontend: **300/305**.
- Năm lỗi thuộc test bình luận giữ nguyên từ main: vẫn kỳ vọng sáu giọng/Piper,
  trong khi code main đã chuyển sang ba giọng Nano. Không sửa hay bỏ các test đó.
- Production UI build, lint có kiểm tra type trên 16 file, stylelint và kiểm tra
  định dạng 19 file đều qua. Kiểm tra format dùng LF đúng như blob Git; các đổi
  CRLF/i18n tạm phát sinh trên Windows khi build đã được hoàn nguyên.
- Compose hợp lệ, không chứa dịch vụ ASR; cài NNUE vào checkout `lila/` xác nhận
  đúng 1.166.381 byte và checksum đã khóa.
- Đối chiếu giữ nguyên 27 file bình luận và checksum model/patch. Báo cáo JSON
  ghi hash và các log bên cạnh để kiểm tra lại.

Lần build đầu không đọc được Git metadata của worktree Windows từ container;
lần chạy lại mount metadata Git thật ở chế độ chỉ đọc và tạo manifest thành công.
Đây không phải lỗi compile. Không chạy lại Scala full, ván browser hay benchmark
audio trong thao tác tách lịch sử Git; các bằng chứng cũ vẫn giữ revision gốc.

Chạy monorepo: chuẩn bị dependency trong `lila/`, model browser bằng
`node scripts/prepare-analysis-engine.mjs --checkout lila`, rồi build UI/Scala
theo cấu hình Lila đang dùng. Docker: `scripts/dev.ps1 bootstrap`, `start`,
`node scripts/prepare-analysis-engine.mjs`; web local ở `http://localhost:8080`.
