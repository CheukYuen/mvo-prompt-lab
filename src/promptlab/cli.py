"""Command-line interface for running allocation tests."""

import argparse
import json
import re
import sys
from pathlib import Path

from promptlab.rules_engine import RulesEngine
from promptlab.prompt_store import PromptStore
from promptlab.dashscope_client import DashScopeClient
from promptlab.validator import Validator
from promptlab.logger import RunLogger


def parse_natural_language(text: str) -> dict:
    """Extract parameters from Chinese natural language."""
    result = {}

    # Life stage patterns
    stage_patterns = {
        "刚毕业": r"刚毕业|毕业生|应届",
        "单身青年": r"单身青年|单身|青年",
        "二人世界": r"二人世界|新婚|丁克",
        "小孩学前": r"小孩学前|学前|幼儿|学龄前",
        "小孩成年前": r"小孩成年前|小孩|孩子|未成年",
        "子女成年": r"子女成年|空巢|子女独立",
        "退休": r"退休",
    }

    # Risk level patterns
    risk_patterns = {
        "C1": r"C1|保守型|非常保守",
        "C2": r"C2|稳健型|稳健",
        "C3": r"C3|平衡型|平衡",
        "C4": r"C4|进取型|进取",
        "C5": r"C5|激进型|非常激进|激进",
    }

    # Need patterns
    need_patterns = {
        "保值": r"保值|保本|安全|稳定",
        "增值": r"增值|增长|成长",
        "传承": r"传承|遗产|财富传承",
    }

    for value, pattern in stage_patterns.items():
        if re.search(pattern, text):
            result["life_stage"] = value
            break

    for value, pattern in risk_patterns.items():
        if re.search(pattern, text):
            result["risk_level"] = value
            break

    for value, pattern in need_patterns.items():
        if re.search(pattern, text):
            result["need"] = value
            break

    return result


def parse_inputs(
    user_text: str = None,
    life_stage: str = None,
    risk_level: str = None,
    need: str = None,
) -> dict:
    """Parse and merge inputs with defaults."""
    defaults = {"life_stage": "单身青年", "risk_level": "C3", "need": "增值"}

    # Parse natural language if provided
    if user_text:
        parsed = parse_natural_language(user_text)
        defaults.update(parsed)

    # Override with explicit parameters
    if life_stage:
        defaults["life_stage"] = life_stage
    if risk_level:
        defaults["risk_level"] = risk_level
    if need:
        defaults["need"] = need

    return defaults


def run_allocation(
    user_text: str = None,
    life_stage: str = None,
    risk_level: str = None,
    need: str = None,
    prompt_version: str = None,
    dry_run: bool = False,
):
    """Run a single allocation test."""
    # 1. Parse inputs
    params = parse_inputs(user_text, life_stage, risk_level, need)
    print(f"\n{'='*60}")
    print("客户画像 (Client Profile)")
    print(f"{'='*60}")
    print(f"  人生阶段: {params['life_stage']}")
    print(f"  风险等级: {params['risk_level']}")
    print(f"  投资需求: {params['need']}")

    # 2. Compute constraints
    engine = RulesEngine()
    constraints = engine.compute_constraints(**params)
    print(f"\n{'='*60}")
    print("计算约束 (Computed Constraints)")
    print(f"{'='*60}")
    print(f"  现金下限 (cash_min): {constraints['cash_min']}%")
    print(f"  波动率上限 (sigma_cap): {constraints['sigma_cap']:.4f} ({constraints['sigma_cap']*100:.2f}%)")
    print(f"  风险资产上限 (risk_asset_max): {constraints['risk_asset_max']}%")

    # 3. Build prompt
    store = PromptStore()
    market_data = store.get_market_data()

    context = {
        **params,
        **constraints,
        **market_data,
        "sigma_cap_pct": f"{constraints['sigma_cap']*100:.2f}",
    }

    system_prompt = store.render("allocation_test", prompt_version, context)
    user_payload = {
        "params": params,
        "constraints": constraints,
        "message": "请生成资产配置权重。",
    }

    if dry_run:
        print(f"\n{'='*60}")
        print("System Prompt (dry-run mode)")
        print(f"{'='*60}")
        print(system_prompt)
        return

    # 4. Call API
    print(f"\n{'='*60}")
    print("调用模型 (Calling Model)...")
    print(f"{'='*60}")

    try:
        client = DashScopeClient()
        response = client.chat(
            system_prompt=system_prompt,
            user_message=json.dumps(user_payload, ensure_ascii=False),
        )
    except Exception as e:
        print(f"API Error: {e}")
        sys.exit(1)

    print(f"\n模型原始输出 (Raw Response):")
    print("-" * 40)
    print(response)
    print("-" * 40)

    # 5. Validate
    validator = Validator()
    result = validator.validate(response, constraints, engine.market_pack)

    print(f"\n{'='*60}")
    print("验证结果 (Validation Result)")
    print(f"{'='*60}")

    if result["weights"]:
        print(f"\n解析权重 (Parsed Weights):")
        for k, v in result["weights"].items():
            print(f"  {k}: {v}%")

    if result["computed_vol"] is not None:
        vol_status = "✓ PASS" if result["constraints_satisfied"].get("sigma_cap", False) else "✗ FAIL"
        print(f"\n组合年化波动率 (Portfolio Ann Vol): {result['computed_vol']:.6f} ({result['computed_vol']*100:.4f}%)")
        print(f"  sigma_cap: {constraints['sigma_cap']:.6f} ({constraints['sigma_cap']*100:.4f}%)")
        print(f"  Status: {vol_status}")

    if result["constraints_satisfied"]:
        print(f"\n约束检查 (Constraint Checks):")
        for check, passed in result["constraints_satisfied"].items():
            status = "✓" if passed else "✗"
            print(f"  {status} {check}")

    if result["errors"]:
        print(f"\n错误 (Errors):")
        for err in result["errors"]:
            print(f"  ✗ {err}")

    if result["warnings"]:
        print(f"\n警告 (Warnings):")
        for warn in result["warnings"]:
            print(f"  ⚠ {warn}")

    overall = "✓ 通过 (PASS)" if result["success"] else "✗ 失败 (FAIL)"
    print(f"\n{'='*60}")
    print(f"总体结果: {overall}")
    print(f"{'='*60}")

    # 6. Log
    logger = RunLogger()
    log_file = logger.log_run(
        {
            "params": params,
            "constraints": constraints,
            "system_prompt": system_prompt,
            "user_payload": user_payload,
            "response": response,
            "validation": result,
        }
    )
    print(f"\n运行记录已保存: {log_file}")


def main():
    """Main CLI entry point."""
    parser = argparse.ArgumentParser(
        description="MVO Prompt Lab - Test LLM portfolio allocation capabilities"
    )
    subparsers = parser.add_subparsers(dest="command", help="Available commands")

    # Run command
    run_parser = subparsers.add_parser("run", help="Run a single allocation test")
    run_parser.add_argument(
        "--user", "-u", type=str, help="Natural language user input (Chinese)"
    )
    run_parser.add_argument(
        "--life_stage", type=str, help="Life stage override"
    )
    run_parser.add_argument(
        "--risk_level", type=str, help="Risk level override (C1-C5)"
    )
    run_parser.add_argument(
        "--need", type=str, help="Investment need override"
    )
    run_parser.add_argument(
        "--prompt_version", type=str, help="Prompt version to use (e.g., v001)"
    )
    run_parser.add_argument(
        "--dry_run", action="store_true", help="Show prompt without calling API"
    )

    args = parser.parse_args()

    if args.command == "run":
        run_allocation(
            user_text=args.user,
            life_stage=args.life_stage,
            risk_level=args.risk_level,
            need=args.need,
            prompt_version=args.prompt_version,
            dry_run=args.dry_run,
        )
    else:
        parser.print_help()


if __name__ == "__main__":
    main()
