import os
import json
import glob
from core.data_loader import DataLoader
from core.llm_client import LLMClient
from core.tracer import Tracer
from agents.coordinator_agent import CoordinatorAgent

def main():
    print("Initializing DataLoader...")
    data_loader = DataLoader(data_dir="data")
    
    print("Initializing LLMClient...")
    llm_client = LLMClient()
    
    tracer = Tracer(log_path="logging/trace.jsonl")
    coordinator = CoordinatorAgent(data_loader, llm_client)

    input_files = sorted(glob.glob("input/EC_*.json"))
    if not input_files:
        print("No input files found in input/ directory.")
        return

    os.makedirs("output", exist_ok=True)

    print(f"Processing {len(input_files)} cases...")
    
    for file_path in input_files:
        with open(file_path, "r", encoding="utf-8") as f:
            input_case = json.load(f)
            
        case_id = input_case["case_id"]
        print(f"Processing {case_id}...")
        
        try:
            final_output, agent_traces = coordinator.process(input_case)
            
            output_path = os.path.join("output", f"{case_id}.json")
            with open(output_path, "w", encoding="utf-8") as out_f:
                json.dump(final_output, out_f, indent=2, ensure_ascii=False)
                
            tracer.log(case_id, agent_traces, final_output)
            print(f"  -> Success. Saved to {output_path}")
        except Exception as e:
            print(f"  -> Failed: {e}")

if __name__ == "__main__":
    main()
