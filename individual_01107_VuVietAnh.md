# Member Role Report — Day 9: Multi Agent A2A

> Mỗi thành viên trong nhóm tự hoàn thành mẫu này để báo cáo đúng vai trò, phần việc và mức hiểu của mình. Không sao chép nguyên báo cáo chung hoặc báo cáo của thành viên khác. Thay nội dung trong dấu `[ ]` và xóa các dòng hướng dẫn không cần thiết trước khi nộp.

## 1. Thông tin cá nhân

| Thông tin       | Nội dung      |
| --------------- | ------------- |
| Họ và tên       | Vũ Việt Anh   |
| MSSV            | 2A202601107   |
| Khóa/Lớp        | K3 / E403     |
| Vai trò chính   | AI Agent Prompt Engineer / Optimizer |
| Ngày hoàn thành | 2026-08-05    |

## 2. Vai trò và phạm vi công việc

### Phần việc sở hữu

| Module/deliverable | File/hàm phụ trách | Input nhận vào | Output bàn giao   | Trạng thái                            |
| ------------------ | ------------------ | -------------- | ----------------- | ------------------------------------- |
| Tối ưu Agent Trích xuất Thực thể | `prompts/order_seller_agent.md`, `prompts/payment_agent.md` | Lịch sử đơn hàng, thông tin thanh toán (JSON) | Danh sách chính xác các entities (seller_ids, items, payments) | Hoàn thành |
| Tối ưu Policy Agent | `prompts/policy_agent.md` | Dữ liệu tổng hợp từ các agent trước | Kết luận nguyên nhân gốc (Root Cause) & Hành động (Actions) | Hoàn thành |

### Việc hỗ trợ ngoài phạm vi chính

| Hoạt động                 | Thành viên/module được hỗ trợ | Kết quả                 |
| ------------------------- | ----------------------------- | ----------------------- |
| Cải thiện Logic Coordinator | `coordinator_agent.py` | Đảm bảo luồng xử lý không bị lỗi khi thiếu items |
| Re-run và đóng gói dữ liệu | Toàn bộ pipeline `main.py` | Tạo ra file `output.zip` chuẩn cấu trúc `output/EC_*.json` nộp hệ thống thành công. |

## 3. Kết quả theo vai trò

| Nhiệm vụ đã thực hiện | File/hàm/artifact liên quan | Kết quả bàn giao          | Cách xác minh   |
| --------------------- | --------------------------- | ------------------------- | --------------- |
| Sửa lỗi thiếu Entity liên quan | `prompts/order_seller_agent.md` | Trích xuất đủ 100% item_ids, seller_ids | So khớp kết quả ở file JSON đầu ra |
| Sửa lỗi Nguyên nhân gốc và Hành động | `prompts/policy_agent.md` | Ánh xạ chuẩn xác 100% Rule sang Root Cause Code | Hệ thống grader trả về điểm tối đa |

Nêu một output cụ thể mà phần việc của bạn tạo ra hoặc giúp xác minh:
Tối ưu hóa các file hệ thống Prompts giúp mô hình `gpt-4o-mini` đạt được độ chính xác tuyệt đối trong việc tuân thủ các Rules e-commerce, đạt điểm tối đa trên hệ thống chấm điểm tự động.

## 4. Giải thích phần kỹ thuật đã thực hiện

### Vấn đề cần giải quyết
Hệ thống ban đầu dùng `gpt-4o-mini` phân tích các case khiếu nại (Customer Cases) để tìm ra root cause và entities nhưng thường xuyên bị bỏ sót (ví dụ thiếu sót payment_rows, seller_ids) hoặc chọn sai action/code so với Policy V1 do prompt chưa đủ nghiêm ngặt.

### Cách triển khai
Áp dụng kỹ thuật Prompt Engineering chặt chẽ:
- Thêm chỉ thị `CRITICAL` yêu cầu trích xuất toàn vẹn (exhaustive extraction) cho Order & Seller Agent và Payment Agent.
- Xây dựng bảng ánh xạ (Explicit Mapping) cụ thể trong `policy_agent.md` để ép LLM trả về chính xác chuỗi `root_cause_code` và mảng `resolution_actions` theo từng rule mà không tự sáng tạo.

### Input, output và contract

| Thành phần              | Mô tả                                  |
| ----------------------- | -------------------------------------- |
| Input                   | Dữ liệu thô của khiếu nại khách hàng (`input/EC_*.json`) |
| Output                  | JSON chứa `affected_entities`, `root_cause_analysis`, `resolution_actions` |
| Module phụ thuộc        | `core/llm_client.py` (cung cấp parse_structured) |
| Module sử dụng output   | `coordinator_agent.py` (tổng hợp kết quả cuối cùng) |
| Điều kiện lỗi cần xử lý | JSON Schema validation failure, LLM hallucination |

### Cách xác minh

```bash
python main.py
```
- **Kết quả mong đợi:** 50 file JSON được tạo ra trong `output/` với các trường dữ liệu đầy đủ.
- **Kết quả thực tế:** Chạy thành công 50/50 cases không phát sinh Exception từ Pydantic Validator.
- **Artifact/log:** `output.zip`, `logging/trace.jsonl`

## 5. Một quyết định kỹ thuật quan trọng

- **Bối cảnh:** Điểm số đánh giá bị thấp ở phần Nguyên nhân gốc và Entity do LLM tự suy diễn.
- **Các phương án đã cân nhắc:**
  1. Cố định (Hardcode) kết quả ở code Python sau khi LLM dự đoán Rule.
  2. Dùng Prompt Engineering để ép LLM tuân thủ chặt chẽ.
- **Phương án đã chọn:** Phương án 2 (Dùng Prompt Engineering).
- **Lý do:** Yêu cầu của bài toán là không được fix cứng dữ liệu, phải linh hoạt sử dụng `gpt-4o-mini`. Phương án này giúp hệ thống khái quát hoá tốt hơn cho các case mới trong tương lai.
- **Bằng chứng quyết định phù hợp:** Điểm số grader tăng vọt lên mức tối đa (100/100).

## 6. Một lỗi hoặc blocker đã xử lý

- **Triệu chứng/lỗi nguyên văn:** ZIP upload thất bại với thông báo `ZIP phải chứa đúng output/EC_001.json đến output/EC_050.json`.
- **Lệnh hoặc bước tái hiện:** Bôi đen các file JSON và nén thủ công thành ZIP (tạo ra ZIP phẳng).
- **Nguyên nhân gốc:** Quá trình nén thủ công làm mất thư mục cha `output/`, hệ thống grader bắt buộc đường dẫn trong ZIP phải bắt đầu bằng `output/`.
- **Cách xử lý:** Sử dụng PowerShell để nén tự động thư mục: `Compress-Archive -Path .\output -DestinationPath .\output.zip -Force`
- **Cách xác minh sau khi sửa:** Up file `output.zip` mới lên grader thành công.
- **Điều học được:** Luôn phải chú ý cấu trúc đường dẫn nội bộ của file nén (archive path structure) khi làm việc với hệ thống grader tự động.

## 7. Hiểu biết về luồng end-to-end

Giải thích ngắn gọn bằng lời của bạn:
1. Luồng xử lý Multi-Agent Olist: Data Loader đọc dữ liệu JSON đầu vào, đưa cho Coordinator Agent.
2. Coordinator điều phối song song OrderSeller, Payment, và Delivery Agent để bóc tách facts.
3. Dữ liệu facts được gom lại và truyền cho Policy Agent để phân xử Rule và Action.
4. Cuối cùng, Evidence Agent chọn bằng chứng và Verifier Agent thẩm định JSON Schema trước khi xuất file.

*(Lưu ý: Các câu hỏi Crossref/Vector Index trong mẫu có vẻ là của bài Lab cũ, nhưng xét theo bài Multi-Agent A2A hiện tại thì luồng E2E được mô tả như trên)*

## 8. Cam kết của thành viên

Đánh dấu sau khi tự kiểm tra:

- [x] Nội dung báo cáo phản ánh đúng phần việc và mức hiểu của tôi.
- [x] Tôi có thể giải thích luồng end-to-end, không chỉ module mình phụ trách.
- [x] Tôi không ghi “đã chạy thành công” cho phần chưa được kiểm chứng.
- [x] Báo cáo không chứa `.env`, API key, token hoặc secret.
- [x] Báo cáo này không phải bản sao nguyên văn của báo cáo nhóm hoặc báo cáo thành viên khác.

**Họ và tên:** Vũ Việt Anh
**Ngày xác nhận:** 2026-08-05
