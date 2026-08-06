import argparse
import json
from pathlib import Path


def read_jsonl(path: Path) -> dict[str, dict]:
    records = {}
    with path.open(encoding="utf-8") as handle:
        for line in handle:
            if line.strip():
                record = json.loads(line)
                records[record["case_id"]] = record
    return records


def main() -> None:
    parser = argparse.ArgumentParser(description="Replace case records in a JSONL trace")
    parser.add_argument("base")
    parser.add_argument("replacement")
    parser.add_argument("output")
    args = parser.parse_args()

    records = read_jsonl(Path(args.base))
    records.update(read_jsonl(Path(args.replacement)))
    output_path = Path(args.output)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    with output_path.open("w", encoding="utf-8") as handle:
        for case_id in sorted(records):
            handle.write(json.dumps(records[case_id], ensure_ascii=False) + "\n")


if __name__ == "__main__":
    main()
