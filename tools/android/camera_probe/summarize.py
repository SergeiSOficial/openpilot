"""Summarize text-only on-phone results. Standard-library Python; no native helpers."""
from pathlib import Path
import argparse
import hashlib
import json
import re
import statistics


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("source", type=Path)
    parser.add_argument("--phase", action="append", default=[], help="User-observed phase: name=start:end seconds")
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    raw = args.source.read_bytes()
    text = raw.decode("utf-8-sig")
    samples = []
    for match in re.finditer(r"LUMA second=(\d+) stream=(\d+) frames=(\d+) mean=([\d.]+) min=(\d+) max=(\d+) hash=(-?\d+)", text):
        second, stream, frames, mean, minimum, maximum, digest = match.groups()
        samples.append(dict(second=int(second), stream=int(stream), frames=int(frames),
                            mean=float(mean), minimum=int(minimum), maximum=int(maximum)))
    phases = {}
    for phase in args.phase:
        name, bounds = phase.split("=")
        start, end = (int(value) for value in bounds.split(":"))
        phase_data = dict(start_second=start, end_second=end, streams={})
        for stream in (0, 1):
            means = [row["mean"] for row in samples if row["stream"] == stream and start <= row["second"] <= end]
            if means:
                phase_data["streams"][str(stream)] = dict(samples=len(means), median_luma=statistics.median(means))
        phases[name] = phase_data
    summary = dict(source_file=args.source.name, source_sha256=hashlib.sha256(raw).hexdigest(),
                   observations=[line.strip() for line in text.splitlines()
                                 if line.startswith(("MODEL=", "BUILD=", "TEST ", "END=", "RESULT ", "PAIR "))],
                   phases=phases)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(summary, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(summary, indent=2))


if __name__ == "__main__":
    main()
