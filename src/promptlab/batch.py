"""Batch validation runner for testing LLM allocation outputs."""

import csv
import json
import statistics
import time
from collections import defaultdict
from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
from pathlib import Path
from typing import Optional, List, Dict

from promptlab.rules_engine import RulesEngine
from promptlab.prompt_store import PromptStore
from promptlab.dashscope_client import DashScopeClient
from promptlab.validator import Validator


class BatchStatus(Enum):
    """Status of a batch test case."""
    PENDING = "pending"
    SUCCESS = "success"
    VALIDATION_FAILED = "validation_failed"
    API_ERROR = "api_error"
    CONSTRAINT_MISMATCH = "constraint_mismatch"


@dataclass
class ExpectedWeights:
    """Expected weights from CSV (pre-computed optimal)."""
    w_cash: int
    w_bond: int
    w_equity: int
    w_commodity: int


@dataclass
class WeightDeviation:
    """Deviation between LLM output and expected weights."""
    w_cash_diff: int
    w_bond_diff: int
    w_equity_diff: int
    w_commodity_diff: int
    total_abs_diff: int
    max_single_diff: int


@dataclass
class BatchTestCase:
    """Single test case loaded from CSV."""
    row_index: int
    life_stage: str
    risk_level: str
    need: str
    # Constraints from CSV
    csv_sigma_cap: float
    csv_cash_min: int  # Integer percentage (e.g., 3 for 3%)
    csv_risk_asset_max: int  # Integer percentage
    # Expected weights from CSV
    expected: ExpectedWeights
    # Expected metrics
    expected_ann_vol: float
    expected_return: float


@dataclass
class BatchTestResult:
    """Result of a single batch test."""
    test_case: BatchTestCase
    status: BatchStatus
    # Computed constraints (from RulesEngine)
    computed_constraints: Optional[Dict] = None
    constraint_match: bool = False
    # LLM output
    llm_weights: Optional[Dict] = None
    llm_raw_response: Optional[str] = None
    # Validation result
    validation_success: bool = False
    validation_errors: List[str] = field(default_factory=list)
    computed_vol: Optional[float] = None
    # Comparison with expected
    deviation: Optional[WeightDeviation] = None
    # Timing
    api_latency_ms: Optional[float] = None
    error_message: Optional[str] = None


class BatchRunner:
    """Orchestrate batch validation of LLM allocation outputs."""

    def __init__(
        self,
        input_csv: str,
        output_dir: str = None,
        prompt_version: str = None,
        delay_between_calls: float = 1.0,
        dry_run: bool = False,
        continue_from: int = None,
        use_csv_constraints: bool = False,
    ):
        self.input_csv = Path(input_csv)
        self.output_dir = Path(output_dir) if output_dir else self._default_output_dir()
        self.prompt_version = prompt_version
        self.delay = delay_between_calls
        self.dry_run = dry_run
        self.continue_from = continue_from or 0
        self.use_csv_constraints = use_csv_constraints

        # Initialize shared components
        self.engine = RulesEngine()
        self.validator = Validator()
        self.store = PromptStore()
        self.client = None if dry_run else DashScopeClient()

        # Results storage
        self.results: List[BatchTestResult] = []

    def _default_output_dir(self) -> Path:
        """Generate timestamped output directory."""
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        return Path(__file__).parent.parent.parent / "runs" / f"batch_{timestamp}"

    def load_csv(self) -> List[BatchTestCase]:
        """
        Load and parse input CSV file.

        CSV columns:
        - life_stage, risk_level, need (input parameters)
        - sigma_cap (float), cash_min (decimal), risk_asset_max (decimal)
        - w_cash, w_bond, w_equity, w_commodity (integer percentages)
        - ann_vol, exp_return (float metrics)
        """
        test_cases = []

        with open(self.input_csv, "r", encoding="utf-8-sig") as f:
            reader = csv.DictReader(f)

            for idx, row in enumerate(reader):
                # Parse constraints - convert decimal to percentage
                csv_cash_min = float(row["cash_min"])
                csv_risk_asset_max = float(row["risk_asset_max"])

                # If values are decimals (< 1), convert to percentage
                if csv_cash_min < 1:
                    csv_cash_min = int(round(csv_cash_min * 100))
                else:
                    csv_cash_min = int(csv_cash_min)

                if csv_risk_asset_max < 1:
                    csv_risk_asset_max = int(round(csv_risk_asset_max * 100))
                else:
                    csv_risk_asset_max = int(csv_risk_asset_max)

                test_case = BatchTestCase(
                    row_index=idx,
                    life_stage=row["life_stage"],
                    risk_level=row["risk_level"],
                    need=row["need"],
                    csv_sigma_cap=float(row["sigma_cap"]),
                    csv_cash_min=csv_cash_min,
                    csv_risk_asset_max=csv_risk_asset_max,
                    expected=ExpectedWeights(
                        w_cash=int(row["w_cash"]),
                        w_bond=int(row["w_bond"]),
                        w_equity=int(row["w_equity"]),
                        w_commodity=int(row["w_commodity"]),
                    ),
                    expected_ann_vol=float(row["ann_vol"]),
                    expected_return=float(row["exp_return"]),
                )
                test_cases.append(test_case)

        return test_cases

    def validate_constraint_consistency(
        self, test_case: BatchTestCase
    ) -> tuple[bool, Dict]:
        """
        Cross-validate CSV constraints against RulesEngine computation.
        Returns (is_consistent, computed_constraints).
        """
        computed = self.engine.compute_constraints(
            test_case.life_stage,
            test_case.risk_level,
            test_case.need,
        )

        # Check if constraints match (allow small tolerance for sigma_cap)
        sigma_match = abs(computed["sigma_cap"] - test_case.csv_sigma_cap) < 1e-6
        cash_match = computed["cash_min"] == test_case.csv_cash_min
        risk_match = computed["risk_asset_max"] == test_case.csv_risk_asset_max

        is_consistent = sigma_match and cash_match and risk_match

        return is_consistent, computed

    def compare_weights(
        self, llm_weights: Dict, expected: ExpectedWeights
    ) -> WeightDeviation:
        """Calculate deviation between LLM output and expected weights."""
        diffs = {
            "w_cash_diff": llm_weights["w_cash"] - expected.w_cash,
            "w_bond_diff": llm_weights["w_bond"] - expected.w_bond,
            "w_equity_diff": llm_weights["w_equity"] - expected.w_equity,
            "w_commodity_diff": llm_weights["w_commodity"] - expected.w_commodity,
        }
        abs_diffs = [abs(v) for v in diffs.values()]
        return WeightDeviation(
            **diffs,
            total_abs_diff=sum(abs_diffs),
            max_single_diff=max(abs_diffs),
        )

    def run_single(self, test_case: BatchTestCase) -> BatchTestResult:
        """
        Execute single test case:
        1. Validate constraints match (or use CSV constraints)
        2. Build prompt
        3. Call LLM API
        4. Validate response
        5. Compare with expected
        """
        result = BatchTestResult(test_case=test_case, status=BatchStatus.PENDING)

        # Step 1: Get constraints (either from CSV or computed)
        if self.use_csv_constraints:
            # Use constraints directly from CSV
            constraints = {
                "sigma_cap": test_case.csv_sigma_cap,
                "cash_min": test_case.csv_cash_min,
                "risk_asset_max": test_case.csv_risk_asset_max,
            }
            result.computed_constraints = constraints
            result.constraint_match = True
        else:
            # Validate constraints against RulesEngine
            is_consistent, computed = self.validate_constraint_consistency(test_case)
            result.computed_constraints = computed
            result.constraint_match = is_consistent
            constraints = computed

            if not is_consistent:
                result.status = BatchStatus.CONSTRAINT_MISMATCH
                result.error_message = (
                    f"Constraint mismatch: "
                    f"CSV sigma={test_case.csv_sigma_cap:.6f}/cash={test_case.csv_cash_min}/risk={test_case.csv_risk_asset_max} "
                    f"vs Computed sigma={computed['sigma_cap']:.6f}/cash={computed['cash_min']}/risk={computed['risk_asset_max']}"
                )
                return result

        if self.dry_run:
            result.status = BatchStatus.PENDING
            return result

        # Step 2: Build prompt
        market_data = self.store.get_market_data()
        context = {
            "life_stage": test_case.life_stage,
            "risk_level": test_case.risk_level,
            "need": test_case.need,
            **constraints,
            **market_data,
            "sigma_cap_pct": f"{constraints['sigma_cap']*100:.2f}",
        }

        system_prompt = self.store.render(
            "allocation_test", self.prompt_version, context
        )
        user_payload = json.dumps(
            {
                "params": {
                    "life_stage": test_case.life_stage,
                    "risk_level": test_case.risk_level,
                    "need": test_case.need,
                },
                "constraints": constraints,
                "message": "请生成资产配置权重。",
            },
            ensure_ascii=False,
        )

        # Step 3: Call API
        try:
            start_time = time.time()
            response = self.client.chat(
                system_prompt=system_prompt,
                user_message=user_payload,
            )
            result.api_latency_ms = (time.time() - start_time) * 1000
            result.llm_raw_response = response
        except Exception as e:
            result.status = BatchStatus.API_ERROR
            result.error_message = str(e)
            return result

        # Step 4: Validate response
        validation = self.validator.validate(
            response, constraints, self.engine.market_pack
        )
        result.validation_success = validation["success"]
        result.validation_errors = validation["errors"]
        result.computed_vol = validation["computed_vol"]
        result.llm_weights = validation["weights"]

        if not validation["success"]:
            result.status = BatchStatus.VALIDATION_FAILED
            return result

        # Step 5: Compare with expected
        result.deviation = self.compare_weights(validation["weights"], test_case.expected)
        result.status = BatchStatus.SUCCESS

        return result

    def run_batch(self) -> List[BatchTestResult]:
        """Execute all test cases with progress tracking."""
        test_cases = self.load_csv()
        total = len(test_cases)

        print(f"\n{'='*60}")
        print(f"批量验证 (Batch Validation): {total} 个测试用例")
        print(f"{'='*60}")
        print(f"  输入文件: {self.input_csv}")
        print(f"  输出目录: {self.output_dir}")
        print(f"  Prompt版本: {self.prompt_version or 'default'}")
        print(f"  运行模式: {'DRY RUN (不调用API)' if self.dry_run else 'LIVE'}")
        if self.continue_from > 0:
            print(f"  从第 {self.continue_from} 行继续")
        print(f"{'='*60}\n")

        # Create output directory
        self.output_dir.mkdir(parents=True, exist_ok=True)

        # Initialize output files
        results_csv_path = self.output_dir / "results.csv"
        batch_jsonl_path = self.output_dir / "batch.jsonl"

        # Write CSV header
        with open(results_csv_path, "w", encoding="utf-8", newline="") as f:
            writer = csv.writer(f)
            writer.writerow([
                "row_index", "life_stage", "risk_level", "need", "status",
                "llm_w_cash", "llm_w_bond", "llm_w_equity", "llm_w_commodity",
                "exp_w_cash", "exp_w_bond", "exp_w_equity", "exp_w_commodity",
                "diff_cash", "diff_bond", "diff_equity", "diff_commodity",
                "total_diff", "llm_vol", "exp_vol", "api_latency_ms", "errors"
            ])

        self.results = []

        try:
            for i, test_case in enumerate(test_cases):
                # Skip if continuing from a specific row
                if i < self.continue_from:
                    continue

                # Progress display
                progress = f"[{i+1}/{total}]"
                case_desc = f"{test_case.life_stage}/{test_case.risk_level}/{test_case.need}"
                print(f"{progress} {case_desc}...", end=" ", flush=True)

                # Run single test
                result = self.run_single(test_case)
                self.results.append(result)

                # Status display
                status_map = {
                    BatchStatus.SUCCESS: "✓ PASS",
                    BatchStatus.VALIDATION_FAILED: "✗ FAIL",
                    BatchStatus.API_ERROR: "⚠ ERR",
                    BatchStatus.CONSTRAINT_MISMATCH: "⊘ SKIP",
                    BatchStatus.PENDING: "◌ DRY",
                }
                status_str = status_map.get(result.status, "???")

                # Add deviation info for successful cases
                if result.status == BatchStatus.SUCCESS and result.deviation:
                    status_str += f" (diff={result.deviation.total_abs_diff})"

                print(status_str)

                # Save incremental result
                self._save_result_row(results_csv_path, result)
                self._save_jsonl_row(batch_jsonl_path, result)

                # Rate limiting delay (skip for dry run or last item)
                if not self.dry_run and i < total - 1:
                    time.sleep(self.delay)

        except KeyboardInterrupt:
            print("\n\n⚠ 中断! 保存部分结果...")

        # Generate final report
        report = self.generate_report()
        self._save_summary(report)
        self._print_summary(report)

        return self.results

    def _save_result_row(self, csv_path: Path, result: BatchTestResult):
        """Append a single result row to CSV."""
        tc = result.test_case
        exp = tc.expected

        row = [
            tc.row_index,
            tc.life_stage,
            tc.risk_level,
            tc.need,
            result.status.value,
        ]

        # LLM weights
        if result.llm_weights:
            row.extend([
                result.llm_weights.get("w_cash", ""),
                result.llm_weights.get("w_bond", ""),
                result.llm_weights.get("w_equity", ""),
                result.llm_weights.get("w_commodity", ""),
            ])
        else:
            row.extend(["", "", "", ""])

        # Expected weights
        row.extend([exp.w_cash, exp.w_bond, exp.w_equity, exp.w_commodity])

        # Deviations
        if result.deviation:
            row.extend([
                result.deviation.w_cash_diff,
                result.deviation.w_bond_diff,
                result.deviation.w_equity_diff,
                result.deviation.w_commodity_diff,
                result.deviation.total_abs_diff,
            ])
        else:
            row.extend(["", "", "", "", ""])

        # Metrics
        row.extend([
            result.computed_vol if result.computed_vol else "",
            tc.expected_ann_vol,
            result.api_latency_ms if result.api_latency_ms else "",
            "; ".join(result.validation_errors) if result.validation_errors else result.error_message or "",
        ])

        with open(csv_path, "a", encoding="utf-8", newline="") as f:
            writer = csv.writer(f)
            writer.writerow(row)

    def _save_jsonl_row(self, jsonl_path: Path, result: BatchTestResult):
        """Append a single result to JSONL."""
        tc = result.test_case

        record = {
            "row": tc.row_index,
            "timestamp": datetime.now().isoformat(),
            "life_stage": tc.life_stage,
            "risk_level": tc.risk_level,
            "need": tc.need,
            "status": result.status.value,
            "llm_weights": result.llm_weights,
            "expected_weights": {
                "w_cash": tc.expected.w_cash,
                "w_bond": tc.expected.w_bond,
                "w_equity": tc.expected.w_equity,
                "w_commodity": tc.expected.w_commodity,
            },
            "deviation": {
                "w_cash_diff": result.deviation.w_cash_diff,
                "w_bond_diff": result.deviation.w_bond_diff,
                "w_equity_diff": result.deviation.w_equity_diff,
                "w_commodity_diff": result.deviation.w_commodity_diff,
                "total_abs_diff": result.deviation.total_abs_diff,
            } if result.deviation else None,
            "computed_vol": result.computed_vol,
            "expected_vol": tc.expected_ann_vol,
            "api_latency_ms": result.api_latency_ms,
            "errors": result.validation_errors,
            "error_message": result.error_message,
            "raw_response": result.llm_raw_response,
        }

        with open(jsonl_path, "a", encoding="utf-8") as f:
            f.write(json.dumps(record, ensure_ascii=False, default=str) + "\n")

    def generate_report(self) -> Dict:
        """Generate comprehensive summary report."""
        total = len(self.results)
        if total == 0:
            return {"error": "No results to report"}

        # Count by status
        status_counts = defaultdict(int)
        for r in self.results:
            status_counts[r.status.value] += 1

        # Deviation statistics (only for successful cases)
        successful = [r for r in self.results if r.status == BatchStatus.SUCCESS]

        deviation_stats = {}
        if successful:
            total_diffs = [r.deviation.total_abs_diff for r in successful]
            max_diffs = [r.deviation.max_single_diff for r in successful]

            deviation_stats = {
                "count": len(successful),
                "total_abs_diff": {
                    "mean": round(statistics.mean(total_diffs), 2),
                    "median": statistics.median(total_diffs),
                    "max": max(total_diffs),
                    "std": round(statistics.stdev(total_diffs), 2) if len(total_diffs) > 1 else 0,
                },
                "max_single_diff": {
                    "mean": round(statistics.mean(max_diffs), 2),
                    "max": max(max_diffs),
                },
                "perfect_match_count": sum(1 for d in total_diffs if d == 0),
                "within_5_pct_count": sum(1 for d in total_diffs if d <= 5),
                "within_10_pct_count": sum(1 for d in total_diffs if d <= 10),
            }

        # Breakdown by parameters
        breakdown = {
            "by_life_stage": defaultdict(lambda: {"total": 0, "pass": 0, "avg_diff": []}),
            "by_risk_level": defaultdict(lambda: {"total": 0, "pass": 0, "avg_diff": []}),
            "by_need": defaultdict(lambda: {"total": 0, "pass": 0, "avg_diff": []}),
        }

        for r in self.results:
            tc = r.test_case
            for key, param in [
                ("by_life_stage", tc.life_stage),
                ("by_risk_level", tc.risk_level),
                ("by_need", tc.need),
            ]:
                breakdown[key][param]["total"] += 1
                if r.status == BatchStatus.SUCCESS:
                    breakdown[key][param]["pass"] += 1
                    breakdown[key][param]["avg_diff"].append(r.deviation.total_abs_diff)

        # Calculate averages for breakdown
        for category in breakdown.values():
            for stats in category.values():
                if stats["avg_diff"]:
                    stats["avg_diff"] = round(statistics.mean(stats["avg_diff"]), 2)
                else:
                    stats["avg_diff"] = None

        # Failed cases detail
        failed_cases = [
            {
                "row": r.test_case.row_index,
                "params": f"{r.test_case.life_stage}/{r.test_case.risk_level}/{r.test_case.need}",
                "status": r.status.value,
                "errors": r.validation_errors,
                "error_message": r.error_message,
            }
            for r in self.results
            if r.status not in [BatchStatus.SUCCESS, BatchStatus.PENDING]
        ]

        return {
            "summary": {
                "total_cases": total,
                "pass_rate": round(status_counts["success"] / total * 100, 1) if total > 0 else 0,
                "status_breakdown": dict(status_counts),
            },
            "deviation_statistics": deviation_stats,
            "breakdown": {k: dict(v) for k, v in breakdown.items()},
            "failed_cases": failed_cases,
            "timestamp": datetime.now().isoformat(),
        }

    def _save_summary(self, report: Dict):
        """Save summary report to JSON."""
        summary_path = self.output_dir / "summary.json"
        with open(summary_path, "w", encoding="utf-8") as f:
            json.dump(report, f, ensure_ascii=False, indent=2)

    def _print_summary(self, report: Dict):
        """Print summary to console."""
        print(f"\n{'='*60}")
        print("汇总报告 (Summary Report)")
        print(f"{'='*60}")

        summary = report.get("summary", {})
        print(f"\n总用例数: {summary.get('total_cases', 0)}")
        print(f"通过率: {summary.get('pass_rate', 0):.1f}%")

        print(f"\n状态分布:")
        for status, count in summary.get("status_breakdown", {}).items():
            print(f"  {status}: {count}")

        dev_stats = report.get("deviation_statistics", {})
        if dev_stats:
            print(f"\n偏差统计 (仅成功用例):")
            print(f"  完全匹配: {dev_stats.get('perfect_match_count', 0)}")
            print(f"  偏差≤5%: {dev_stats.get('within_5_pct_count', 0)}")
            print(f"  偏差≤10%: {dev_stats.get('within_10_pct_count', 0)}")
            if "total_abs_diff" in dev_stats:
                diff = dev_stats["total_abs_diff"]
                print(f"  平均总偏差: {diff.get('mean', 0)}")
                print(f"  最大总偏差: {diff.get('max', 0)}")

        failed = report.get("failed_cases", [])
        if failed:
            print(f"\n失败用例 ({len(failed)}):")
            for case in failed[:5]:  # Show first 5
                print(f"  - Row {case['row']}: {case['params']} - {case['status']}")
                if case.get("errors"):
                    print(f"    Errors: {'; '.join(case['errors'][:2])}")
            if len(failed) > 5:
                print(f"  ... 还有 {len(failed) - 5} 个失败用例")

        print(f"\n结果已保存到: {self.output_dir}")
        print(f"{'='*60}")
