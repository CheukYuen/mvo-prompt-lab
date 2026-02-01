"""Log runs to JSONL files with artifacts."""

import json
from datetime import datetime
from pathlib import Path
from typing import Any


class RunLogger:
    """Log runs to JSONL files with artifacts."""

    def __init__(self, runs_dir: Path = None):
        self.runs_dir = runs_dir or Path(__file__).parent.parent.parent / "runs"

    def _get_run_dir(self) -> Path:
        """Get or create today's run directory."""
        today = datetime.now().strftime("%Y-%m-%d")
        day_dir = self.runs_dir / today
        day_dir.mkdir(parents=True, exist_ok=True)
        return day_dir

    def _get_next_run_number(self, day_dir: Path) -> int:
        """Get the next run number for today."""
        existing = list(day_dir.glob("run_*.jsonl"))
        if not existing:
            return 1

        numbers = []
        for f in existing:
            try:
                num = int(f.stem.split("_")[1])
                numbers.append(num)
            except (IndexError, ValueError):
                continue

        return max(numbers, default=0) + 1

    def log_run(self, data: dict) -> Path:
        """
        Log a complete run to JSONL file.

        Args:
            data: Dict containing params, constraints, response, validation, etc.

        Returns:
            Path to the created log file
        """
        day_dir = self._get_run_dir()
        run_num = self._get_next_run_number(day_dir)

        # Create run file
        run_file = day_dir / f"run_{run_num:03d}.jsonl"

        # Build log record
        record = {
            "timestamp": datetime.now().isoformat(),
            "run_number": run_num,
            **data,
        }

        # Write JSONL (single line)
        with open(run_file, "w", encoding="utf-8") as f:
            f.write(json.dumps(record, ensure_ascii=False, default=str) + "\n")

        # Save artifacts
        self._save_artifacts(day_dir, run_num, data)

        return run_file

    def _save_artifacts(self, day_dir: Path, run_num: int, data: dict):
        """Save additional artifacts for a run."""
        artifacts_dir = day_dir / f"run_{run_num:03d}_artifacts"
        artifacts_dir.mkdir(exist_ok=True)

        # Save system prompt if available
        if "system_prompt" in data:
            prompt_file = artifacts_dir / "system_prompt.txt"
            with open(prompt_file, "w", encoding="utf-8") as f:
                f.write(data["system_prompt"])

        # Save user payload if available
        if "user_payload" in data:
            payload_file = artifacts_dir / "user_payload.json"
            with open(payload_file, "w", encoding="utf-8") as f:
                json.dump(data["user_payload"], f, ensure_ascii=False, indent=2)

        # Save raw response if available
        if "response" in data:
            response_file = artifacts_dir / "raw_response.txt"
            with open(response_file, "w", encoding="utf-8") as f:
                f.write(data["response"])

        # Save validation details
        if "validation" in data:
            validation_file = artifacts_dir / "validation.json"
            with open(validation_file, "w", encoding="utf-8") as f:
                json.dump(data["validation"], f, indent=2, ensure_ascii=False)
