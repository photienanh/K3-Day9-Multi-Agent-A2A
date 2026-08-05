# Member Role Report — Day 9: Multi Agent A2A

Báo cáo này ghi lại phần triển khai và kiểm chứng hệ thống multi-agent giải quyết khiếu nại Olist.

## 1. Thông tin cá nhân

| Thông tin       | Nội dung     |
| --------------- | ------------ |
| Họ và tên       | Phó Viết Tiến Anh  |
| MSSV            | 2A202601341       |
| Khóa/Lớp        | K3         |
| Vai trò chính   | Thiết kế orchestrator, policy engine và verifier |
| Ngày hoàn thành | 2026-08-05 |

## 2. Vai trò và phạm vi công việc

### Phần việc sở hữu

| Module/deliverable | File/hàm phụ trách | Input nhận vào | Output bàn giao   | Trạng thái                            |
| ------------------ | ------------------ | -------------- | ----------------- | ------------------------------------- |
| Multi-agent pipeline | `src/agents.py`, `src/pipeline.py` | 50 input JSON, 4 bảng CSV liên quan | 50 output JSON và trace | Hoàn thành |
| Data/policy/verifier | `src/data_repository.py`, `src/policy.py`, `src/validate.py` | Input, CSV, policy | Fact snapshot, policy oracle, validation | Hoàn thành |
| Tài liệu | `architecture.md`, báo cáo này | Source và artifact chạy thật | Sơ đồ, contract, kết quả | Hoàn thành |

### Việc hỗ trợ ngoài phạm vi chính

| Hoạt động                 | Thành viên/module được hỗ trợ | Kết quả                 |
| ------------------------- | ----------------------------- | ----------------------- |
| Tích hợp và tài liệu | Toàn pipeline | Chạy được từ `.venv`, metadata tái lập được |

## 3. Kết quả theo vai trò

| Nhiệm vụ đã thực hiện | File/hàm/artifact liên quan | Kết quả bàn giao          | Cách xác minh   |
| --------------------- | --------------------------- | ------------------------- | --------------- |
| Xây fact collector và 6 nhánh policy | `src/data_repository.py`, `src/policy.py` | Quyết định cho 50/50 case | `.venv/bin/python -m src.validate` |
| Orchestrate domain/policy/coordinator agents | `src/agents.py`, `logging/trace.jsonl` | LangGraph handoff dùng `gpt-4o-mini` | `.venv/bin/python -m src.pipeline` |
| Kiểm tra artifact nộp bài | `src/validate.py`, `output/` | 50 JSON hợp lệ | `.venv/bin/python -m src.validate` |

Artifact chính là `output/EC_001.json` đến `output/EC_050.json`. Mỗi file truy nguyên được qua các event cùng `case_id` trong `logging/trace.jsonl`; validation kiểm tra lại evidence và refund từ CSV thay vì tin output của model.

## 4. Giải thích phần kỹ thuật đã thực hiện

### Vấn đề cần giải quyết

Phần việc giải quyết việc phối hợp nhiều chuyên môn nhưng vẫn bảo đảm kết luận có thể kiểm chứng. LLM phù hợp để audit/handoff, còn join, so sánh thời gian, cộng tiền và whitelist evidence cần tính xác định để tránh hallucination.

### Cách triển khai

CSV được index theo `order_id`, sau đó mỗi case tạo một fact snapshot chứa order, items, payments và các giá trị tổng hợp. Ba domain agent chạy song song. Policy engine xét lần lượt canceled, unavailable, late seller, late logistics, split payment và late claim không được hỗ trợ. Policy Agent và Coordinator audit candidate qua handoff. Verifier cuối dựng tập evidence hợp lệ từ chính row nguồn, đối chiếu refund và cardinality rồi mới ghi file.

### Input, output và contract

| Thành phần              | Mô tả                                  |
| ----------------------- | -------------------------------------- |
| Input                   | `input/EC_*.json`, orders/items/payments/sellers CSV |
| Output                  | 50 JSON theo schema, trace JSONL, metadata JSON |
| Module phụ thuộc        | LangGraph, langchain-openai, OpenAI SDK, Pydantic, python-dotenv |
| Module sử dụng output   | Verifier, hệ thống chấm bài |
| Điều kiện lỗi cần xử lý | Thiếu order, thiếu API key, policy không match, evidence giả, sai giới hạn schema |

### Cách xác minh

```bash
.venv/bin/python -m src.pipeline
.venv/bin/python -m src.validate
```

- **Kết quả mong đợi:** 50 output hợp lệ và trace của lần chạy mới nhất.
- **Kết quả thực tế:** Run `run_20260805T040937Z_459dfb80` hoàn tất 50/50 case, 200 model call, 87.968 token và 1.652 trace event; validation PASS cho output, evidence, arithmetic, trace và metadata.
- **Artifact/log:** `output/`, `logging/trace.jsonl`, `logging/metadata.json`; không chứa secret.

## 5. Một quyết định kỹ thuật quan trọng

- **Bối cảnh:** Model có thể tổng hợp tốt nhưng không nên là nguồn sự thật cho tiền và evidence ID.
- **Các phương án đã cân nhắc:** Cho một prompt sinh toàn output; hoặc tách domain agents và dùng deterministic verifier.
- **Phương án đã chọn:** Domain handoff bằng model, policy candidate và verification bằng code.
- **Lý do:** Vẫn có phối hợp multi-agent thật nhưng kết quả có tính tái lập, giảm false-positive evidence và sai số tiền.
- **Bằng chứng quyết định phù hợp:** `src/validate.py` dựng lại facts từ CSV và kiểm tra được 50/50 case; Policy Agent khớp policy oracle 50/50 sau contract audit, trong khi bất đồng ở domain review vẫn được ghi rõ để Coordinator lọc.

## 6. Một lỗi hoặc blocker đã xử lý

- **Triệu chứng/lỗi nguyên văn:** `Could not find a version that satisfies the requirement langchain-openai==1.4.1`.
- **Lệnh hoặc bước tái hiện:** `.venv/bin/python -m pip install 'langchain-openai==1.4.1'` trong sandbox không có network.
- **Nguyên nhân gốc:** DNS/network của môi trường sandbox bị giới hạn, không phải package không tồn tại.
- **Cách xử lý:** Cho phép đúng lệnh pip truy cập network và cài dependency vào `.venv`.
- **Cách xác minh sau khi sửa:** `pip check` báo không có dependency hỏng, compile toàn bộ `src/` thành công và Structured Output smoke test nhận response thật.
- **Điều học được:** Cần phân biệt lỗi index/package với giới hạn network của runtime và luôn cô lập dependency trong virtual environment.

## 7. Hiểu biết về luồng end-to-end

1. `claimed_order_id` nối vào orders, order_items và order_payments; `seller_id` trong item được đối chiếu sellers. Fact collector đóng gói snapshot theo case.
2. Order/Seller kiểm tra handoff, Payment đối soát tiền, Delivery so sánh deadline. Policy nhận cả ba kết quả và Coordinator tổng hợp bất đồng.
3. Policy engine áp dụng first-match để tạo candidate, Policy Agent dùng model audit candidate từ ba handoff; Verifier độc lập kiểm tra schema, nguồn evidence, số tiền và giới hạn trước khi ghi.
4. Dataset không có refund ledger, transaction/tracking giả định. Evidence dựng từ CSV ngăn model tạo ID không tồn tại và tránh mất điểm false positive.
5. Canceled hoặc unavailable đã thanh toán được hoàn toàn; giao trễ được hoàn freight. Split payment hợp lệ và claim giao trễ sai không hoàn tiền.

## 8. Cam kết của thành viên

Đánh dấu sau khi tự kiểm tra:

- [x] Nội dung báo cáo phản ánh đúng phần việc và mức hiểu của tôi.
- [x] Tôi có thể giải thích luồng end-to-end, không chỉ module mình phụ trách.
- [x] Tôi không ghi “đã chạy thành công” cho phần chưa được kiểm chứng.
- [x] Báo cáo không chứa `.env`, API key, token hoặc secret.
- [x] Báo cáo này không phải bản sao nguyên văn của báo cáo nhóm hoặc báo cáo thành viên khác.

**Họ và tên:** Phó Viết Tiến Anh
**Ngày xác nhận:** 2026-08-05
