# Member Role Report — Day 9: Multi Agent A2A

## 1. Thông tin cá nhân

| Thông tin       | Nội dung                                                    |
| --------------- | ----------------------------------------------------------- |
| Họ và tên       | Phan Trọng Tiến                                              |
| MSSV            | 2A202601095                                                  |
| Khóa/Lớp        | K3                                                           |
| Vai trò chính   | Xây dựng pipeline multi-agent (Policy engine + Verifier) và script validation độc lập |
| Ngày hoàn thành | 2026-08-05                                                   |

## 2. Vai trò và phạm vi công việc

### Phần việc sở hữu

| Module/deliverable | File/hàm phụ trách | Input nhận vào | Output bàn giao | Trạng thái |
| ------------------ | ------------------ | -------------- | --------------- | ---------- |
| Pipeline A2A 6 agent (Coordinator, OrderSeller, Payment, Delivery, Policy, Verifier) | `src/pipeline.py` | `input/EC_*.json` + 9 CSV Olist | 50 file `output/EC_*.json` đúng schema | Hoàn thành |
| Runner + trace + metadata | `src/run_cases.py` | Toàn bộ thư mục `input/` | `output/`, `logging/trace.jsonl`, `logging/metadata.json` | Hoàn thành |
| LLM cross-check agent (tùy chọn, ≤10B) | `src/llm.py` (`GroqCrossChecker`, model khai báo trong code: `llama-3.1-8b-instant`, 8B) | Findings của các agent + decision | AGREE/DISAGREE ghi vào trace | Hoàn thành |
| Script validation độc lập | `scripts/validate_outputs.py` | `output/` + CSV gốc | Report pass/fail cho 50 case | Hoàn thành |
| Script profiling phân bố case | `scripts/profile_cases.py` | 50 input + CSV | Thống kê nhánh rule của 50 case chính thức | Hoàn thành |

### Việc hỗ trợ ngoài phạm vi chính

| Hoạt động | Thành viên/module được hỗ trợ | Kết quả |
| --------- | ----------------------------- | ------- |
| Viết tài liệu kiến trúc | `architecture.md` (root repo) | Sơ đồ mermaid, bảng quyền truy cập dữ liệu từng agent, decision tree kín 7 nhánh, quy tắc dựng output, mô tả verifier loop |

## 3. Kết quả theo vai trò

| Nhiệm vụ đã thực hiện | File/hàm/artifact liên quan | Kết quả bàn giao | Cách xác minh |
| --------------------- | --------------------------- | ---------------- | ------------- |
| Cài đặt decision tree EC_POLICY_V1 theo đúng thứ tự ưu tiên 6 rule | `src/pipeline.py::PolicyAgent.decide` | 50 output phân loại đúng nhánh (0 case UNCLASSIFIED) | `python src/run_cases.py` |
| Verifier kiểm tra schema, giới hạn số lượng, evidence tồn tại thật trong CSV, đối chiếu lại tiền độc lập | `src/pipeline.py::VerifierAgent` | 50/50 case pass verifier ngay round 0 (ghi trong `logging/trace.jsonl`) | Đọc `logging/trace.jsonl`, step `verifier_agent -> coordinator: pass (round 0)` |
| Validation end-to-end độc lập (không import lại pipeline, tự tính ground truth từ CSV) | `scripts/validate_outputs.py` | `ALL CHECKS PASSED` cho 50 case | `python scripts/validate_outputs.py` |
| Chạy chính thức 50 case, ghi trace và metadata | `src/run_cases.py` | `logging/trace.jsonl` (lượt chạy mới nhất, không append), `logging/metadata.json` (runtime 2.03s) | Đọc 2 file trong `logging/` |

Nêu một output cụ thể mà phần việc của bạn tạo ra hoặc giúp xác minh:

`scripts/validate_outputs.py` tái cài đặt toàn bộ rule từ đầu (không dùng lại code trong `src/pipeline.py`) rồi đối chiếu 50 file output với ground truth tự tính từ CSV: primary issue, case_status, 4 số tiền, entities, evidence, root cause, responsible party và action. Kết quả chạy thật: `Checked 50 cases. ALL CHECKS PASSED`. Đây là "second opinion" bảo đảm output nộp không bị hard gate vì sai schema, sai tiền hoặc evidence không tồn tại.

## 4. Giải thích phần kỹ thuật đã thực hiện

### Vấn đề cần giải quyết

Từ một khiếu nại tự do của khách hàng (chỉ tin được `claimed_order_id`), hệ thống phải đối chiếu 4 nguồn dữ liệu (orders, order_items, order_payments, sellers) để xác định primary issue trong 6 loại, bên chịu trách nhiệm, khoản hoàn và action — trong đó mọi con số phải kiểm chứng được từ CSV, không được suy diễn sự kiện không tồn tại (Olist không có refund ledger hay tracking checkpoint).

### Cách triển khai

Nguyên tắc thiết kế: **mọi con số và phép so sánh timestamp đều do tool pandas tính; LLM (nếu bật) chỉ cross-check phân loại, không bao giờ ghi đè số liệu**. Coordinator nhận case, phát task song song cho OrderSeller Agent (order status, item rows, tổng item/freight, seller nào bàn giao sau `shipping_limit_date`) và Payment Agent (payment rows, tổng payment, đối soát với item+freight sai số 0.10 BRL). Delivery Agent chỉ nhìn timestamps trong findings để kết luận late và phân định seller/carrier. Policy Agent áp 6 rule theo đúng thứ tự ưu tiên của đề (canceled → unavailable → late seller → late logistics → split payment → unsupported claim) cộng nhánh vét cạn phòng thủ, rồi dựng draft output đủ schema. Verifier Agent kiểm tra độc lập; fail thì trả error list về Policy Agent sửa lại (tối đa 2 vòng). Timestamps so sánh theo chuỗi nguyên văn CSV (format đồng nhất `YYYY-MM-DD HH:MM:SS` nên so chuỗi an toàn), đúng yêu cầu "không chuyển múi giờ".

### Input, output và contract

| Thành phần | Mô tả |
| ---------- | ----- |
| Input | `input/EC_xxx.json` (case_id, claimed_order_id, policy_version) + 9 CSV Olist trong `data/` |
| Output | `output/EC_xxx.json` đúng schema đề: assessment, affected_entities, root_cause_analysis, evidence_ids, financial_resolution, resolution_actions |
| Module phụ thuộc | `DataStore` (lớp đọc CSV, index theo `order_id`), `src/llm.py` (cross-check tùy chọn) |
| Module sử dụng output | `src/run_cases.py` ghi file; `scripts/validate_outputs.py` chấm lại độc lập |
| Điều kiện lỗi cần xử lý | Order không có item row (8 case unavailable): `item_ids`/`seller_ids` rỗng, `item_total = freight_total = 0.0`; `order_delivered_customer_date` hoặc `carrier_date` NULL: không được kết luận late; case canceled vẫn có seller trễ (EC_008): rule ưu tiên 1 thắng, không rơi xuống late_delivery |

### Cách xác minh

```bash
python src/run_cases.py
python scripts/validate_outputs.py
```

- **Kết quả mong đợi:** 50 output sinh ra đủ, mỗi case in primary_issue + refund; script validate báo pass toàn bộ.
- **Kết quả thực tế:** 50 case chạy trong 2.03s, phân bố 9 unsupported_late_claim / 9 valid_split_payment / 8 late_delivery_seller / 8 late_delivery_logistics / 8 canceled_order_paid / 8 unavailable_order_paid; validate in `Checked 50 cases. ALL CHECKS PASSED`.
- **Artifact/log:** `output/EC_001.json`…`EC_050.json`, `logging/trace.jsonl`, `logging/metadata.json` (không chứa secret).

## 5. Một quyết định kỹ thuật quan trọng

- **Bối cảnh:** Đặt phần tính tiền và so sánh timestamp ở đâu — để LLM tự đọc dữ liệu và lập luận, hay tách thành tool deterministic?
- **Các phương án đã cân nhắc:** (1) LLM đọc rows CSV và tự kết luận issue + tính refund; (2) toàn bộ số liệu do pandas tính trong từng agent, LLM ≤10B chỉ đóng vai auditor cross-check phân loại (AGREE/DISAGREE) và không có quyền ghi đè.
- **Phương án đã chọn:** Phương án 2.
- **Lý do:** Điểm chấm phụ thuộc số tiền chính xác đến 0.005 BRL và evidence ID phải tồn tại thật trong CSV — model 8B dễ tính sai tổng hoặc bịa ID, mỗi lỗi như vậy là false positive hoặc hard gate. Tool pandas cho kết quả reproducible 100%, chi phí gần bằng 0, còn vai trò multi-agent (phân công, handoff, kiểm chứng) vẫn giữ nguyên đúng tinh thần đề.
- **Bằng chứng quyết định phù hợp:** 50/50 case pass verifier ngay round 0 và pass script validate độc lập; toàn bộ run chỉ mất 2.03s; `logging/trace.jsonl` ghi rõ từng handoff giữa các agent.

## 6. Một lỗi hoặc blocker đã xử lý

- **Triệu chứng/lỗi nguyên văn:** Các case order `unavailable` bị vỡ logic: không có item row nên đoạn tính `item_total`/`freight_total` bằng `sum()` trên DataFrame rỗng, và draft ban đầu vẫn sinh evidence `item:...` không tồn tại — verifier báo `evidence item missing` (đúng loại lỗi bị đề tính false positive).
- **Lệnh hoặc bước tái hiện:** `python src/run_cases.py` với các case unavailable (nhóm 8 case không có item row).
- **Nguyên nhân gốc:** Code dựng output giả định mọi order đều có ít nhất một item row; không xử lý nhánh `order_items` rỗng theo yêu cầu mục 6 của đề ("nếu order không có item row, `item_ids`, `seller_ids` để rỗng và `item_total_brl`, `freight_total_brl` bằng 0.0").
- **Cách xử lý:** `OrderSellerAgent.analyze` trả `item_total = freight_total = 0.0` khi không có item; `PolicyAgent.draft` chỉ sinh evidence `item:`/`seller:` từ item rows thật sự tồn tại; `VerifierAgent._check_evidence` tra ngược từng evidence ID vào CSV để chặn loại lỗi này tái phát.
- **Cách xác minh sau khi sửa:** `python scripts/validate_outputs.py` → `ALL CHECKS PASSED`; kiểm tra trực tiếp output các case unavailable có `item_ids: []`, `seller_ids: []`, `item_total_brl: 0.0`, `freight_total_brl: 0.0` nhưng `payment_total_brl > 0` và refund = tổng payment.
- **Điều học được:** Với dữ liệu thật, "mọi order đều có item" là giả định sai; và verifier phải kiểm tra evidence bằng cách tra ngược vào nguồn dữ liệu chứ không chỉ kiểm tra format chuỗi.

## 7. Hiểu biết về luồng end-to-end

**Câu trả lời:** (các câu hỏi trong template gốc nói về pipeline Crossref/RAG; dưới đây tôi trả lời theo phần tương ứng của bài lab Day 9)

1. **Dữ liệu đi từ input đến output như thế nào?** `input/EC_xxx.json` → Coordinator lấy `claimed_order_id` → OrderSeller Agent join orders + order_items (status, tổng tiền, seller trễ hạn), Payment Agent đọc order_payments và đối soát → Delivery Agent so timestamps để kết luận late và phân định seller/carrier → Policy Agent áp 6 rule EC_POLICY_V1 theo thứ tự ưu tiên và dựng draft → Verifier kiểm tra rồi ghi `output/EC_xxx.json`; mỗi handoff ghi một dòng vào `logging/trace.jsonl`.
2. **Chất lượng output được đo bằng gì?** Bằng ground truth độc lập: `scripts/validate_outputs.py` tự tính lại issue, refund, entities, evidence từ CSV gốc (không dùng lại code pipeline) rồi so với từng output — tương đương dùng evaluation set với đáp án tự dựng để đo độ đúng của hệ thống.
3. **Quality check khác gì monitoring trong bài này?** Verifier (quality check) chạy trong pipeline, chặn từng output sai schema/tiền/evidence trước khi ghi file; còn `trace.jsonl` + `metadata.json` là lớp quan sát sau khi chạy — cho biết hệ thống đã handoff thế nào, chạy bao lâu, có dùng LLM không, nhưng không chặn output.
4. **Vì sao phải kiểm tra cùng một bộ 50 case cho mọi thay đổi?** Vì phân bố case (6 nhánh rule) là cố định; mọi lần sửa rule đều chạy lại đủ 50 input và validate lại toàn bộ — nếu đổi bộ test giữa chừng thì không thể biết một thay đổi làm tốt lên hay chỉ do case dễ hơn.
5. **Sửa lỗi được xem là thành công dựa trên artifact nào?** Ba mức: verifier pass round 0 trong `trace.jsonl`, `scripts/validate_outputs.py` in `ALL CHECKS PASSED` cho đủ 50 case, và output các case biên (unavailable không item, canceled có seller trễ) đúng từng trường theo mục 6 của đề.

## 8. Cam kết của thành viên

Đánh dấu sau khi tự kiểm tra:

- [x] Nội dung báo cáo phản ánh đúng phần việc và mức hiểu của tôi.
- [x] Tôi có thể giải thích luồng end-to-end, không chỉ module mình phụ trách.
- [x] Tôi không ghi “đã chạy thành công” cho phần chưa được kiểm chứng.
- [x] Báo cáo không chứa `.env`, API key, token hoặc secret.
- [x] Báo cáo này không phải bản sao nguyên văn của báo cáo nhóm hoặc báo cáo thành viên khác.

**Họ và tên:** Phan Trọng Tiến
**Ngày xác nhận:** 2026-08-05
