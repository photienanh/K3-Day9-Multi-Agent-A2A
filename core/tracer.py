import json
import os
from datetime import datetime

class Tracer:
    def __init__(self, log_path: str = "logging/trace.jsonl"):
        self.log_path = log_path
        log_dir = os.path.dirname(self.log_path)
        if log_dir:
            os.makedirs(log_dir, exist_ok=True)
        # Xóa file cũ nếu có để ghi đợt chạy mới nhất
        if os.path.exists(self.log_path):
            os.remove(self.log_path)

    def log(self, case_id: str, agent_traces: list, final_output: dict):
        trace_record = {
            "case_id": case_id,
            "timestamp": datetime.now().isoformat(),
            "agent_traces": agent_traces,
            "final_output": final_output
        }
        with open(self.log_path, "a", encoding="utf-8") as f:
            f.write(json.dumps(trace_record, ensure_ascii=False) + "\n")
