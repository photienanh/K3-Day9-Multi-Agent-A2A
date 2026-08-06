import os
import json
import glob
import argparse
from concurrent.futures import ThreadPoolExecutor
from core.data_loader import DataLoader
from core.llm_client import LLMClient
from core.tracer import Tracer
from agents.coordinator_agent import CoordinatorAgent

def parse_args():
    parser = argparse.ArgumentParser(description="Run the Olist multi-agent pipeline")
    parser.add_argument(
        "--case",
        help="Run one or more comma-separated case IDs, e.g. EC_001,EC_009.",
    )
    parser.add_argument("--limit", type=int, help="Process only the first N matched cases")
    parser.add_argument("--output-dir", default="output", help="Directory for result JSON files")
    parser.add_argument(
        "--workers",
        type=int,
        default=1,
        help="Number of cases processed concurrently (default: 1)",
    )
    parser.add_argument(
        "--trace-path", default="logging/trace.jsonl", help="Path for the latest JSONL trace"
    )
    return parser.parse_args()


def main():
    args = parse_args()
    print("Initializing DataLoader...")
    data_loader = DataLoader(data_dir="data")
    
    print("Initializing LLMClient...")
    llm_client = LLMClient()
    
    tracer = Tracer(log_path=args.trace_path)
    coordinator = CoordinatorAgent(data_loader, llm_client)

    input_files = sorted(glob.glob("input/EC_*.json"))
    if args.case:
        requested_cases = {case_id.strip() for case_id in args.case.split(",")}
        input_files = [
            path
            for path in input_files
            if os.path.splitext(os.path.basename(path))[0] in requested_cases
        ]
    if args.limit is not None:
        input_files = input_files[: args.limit]
    if not input_files:
        print("No input files found in input/ directory.")
        return

    os.makedirs(args.output_dir, exist_ok=True)

    print(f"Processing {len(input_files)} cases...")
    
    def process_file(file_path):
        with open(file_path, "r", encoding="utf-8") as f:
            input_case = json.load(f)
        case_id = input_case["case_id"]
        try:
            final_output, agent_traces = coordinator.process(input_case)
            return case_id, final_output, agent_traces, None
        except Exception as exc:
            return case_id, None, None, exc

    workers = max(1, args.workers)
    if workers == 1:
        results = map(process_file, input_files)
    else:
        executor = ThreadPoolExecutor(max_workers=workers)
        results = executor.map(process_file, input_files)

    try:
        for case_id, final_output, agent_traces, error in results:
            print(f"Processing {case_id}...")
            if error is not None:
                print(f"  -> Failed: {error}")
                continue

            output_path = os.path.join(args.output_dir, f"{case_id}.json")
            with open(output_path, "w", encoding="utf-8") as out_f:
                json.dump(final_output, out_f, indent=2, ensure_ascii=False)

            tracer.log(case_id, agent_traces, final_output)
            print(f"  -> Success. Saved to {output_path}")
    finally:
        if workers > 1:
            executor.shutdown(wait=True)

if __name__ == "__main__":
    main()
