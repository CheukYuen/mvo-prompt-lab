# MVO Prompt Lab

## 项目概述
MVP 项目，验证 LLM（Qwen）能否在 V3 业务规则下输出合规的四大类资产配置权重。

## 技术栈
- Python 3.10+
- DashScope SDK（阿里云通义千问 API）
- NumPy（组合波动率计算）
- PyYAML（Prompt 版本管理）

## 项目结构
```
mvo-prompt-lab/
├── src/promptlab/          # 核心代码
│   ├── cli.py              # CLI 入口，自然语言解析
│   ├── batch.py            # 批量验证流水线
│   ├── rules_engine.py     # V3 规则引擎，约束计算
│   ├── dashscope_client.py # Qwen API 封装
│   ├── validator.py        # 输出验证（含 ann_vol 计算）
│   ├── prompt_store.py     # Prompt 模板加载/渲染
│   └── logger.py           # 运行日志记录
├── prompts/                # Prompt 模板（版本化）
│   ├── registry.yaml       # 版本注册表
│   └── allocation_test.v001.md
├── inputs/
│   ├── fixtures/           # 业务规则数据
│   │   ├── v3_rules_pack.json  # V3 约束参数
│   │   └── v3_market_pack.json # 协方差矩阵
│   └── batch/              # 批量测试数据
│       └── mvo_105_weights_saa_v3.csv
└── runs/                   # 运行日志（按日期）
    ├── YYYY-MM-DD/         # 单次运行
    └── batch_YYYYMMDD_HHMMSS/  # 批量运行
```

## 核心模块

### rules_engine.py
计算三大约束：
```python
cash_min = CASH_MIN_STAGE[life_stage]
sigma_cap = clip(SIGMA_STAGE_MAX[life_stage] * M_RISK[risk_level])
risk_asset_max = clip(RISK_ASSET_MAX_STAGE[life_stage] * K_RISK[risk_level] * K_NEED_RISKASSET[need])
```

### validator.py
验证模型输出：
1. JSON 解析
2. 权重整数 0-100，sum=100
3. w_cash >= cash_min
4. (w_equity + w_commodity) <= risk_asset_max
5. ann_vol = sqrt(w^T Σ w) <= sigma_cap

## 常用命令

```bash
# 激活虚拟环境
source .venv/bin/activate

# 运行（自然语言）
python -m promptlab run --user "给我单身青年C3增值的配置"

# 运行（明确参数）
python -m promptlab run --life_stage 单身青年 --risk_level C3 --need 增值

# Dry Run（仅查看 Prompt）
python -m promptlab run --user "退休C1保值" --dry_run

# 指定 Prompt 版本
python -m promptlab run --user "..." --prompt_version v002
```

## 批量验证命令

```bash
# 基本用法 - 调用大模型 API 验证 105 个配置
python -m promptlab batch --input inputs/batch/mvo_105_weights_saa_v3.csv --use_csv_constraints

# Dry Run - 仅验证 CSV 格式，不调用 API
python -m promptlab batch --input inputs/batch/mvo_105_weights_saa_v3.csv --use_csv_constraints --dry_run

# 指定输出目录和 API 调用间隔
python -m promptlab batch --input xxx.csv --output runs/exp_001 --delay 2.0 --use_csv_constraints

# 从第 50 行继续（中断恢复）
python -m promptlab batch --input xxx.csv --use_csv_constraints --continue_from 50
```

### 批量验证参数

| 参数 | 说明 |
|------|------|
| `--input, -i` | 输入 CSV 文件路径 (必需) |
| `--output, -o` | 输出目录 (默认: runs/batch_TIMESTAMP) |
| `--use_csv_constraints` | 使用 CSV 中的约束参数 (推荐) |
| `--dry_run` | 仅验证 CSV，不调用 API |
| `--delay` | API 调用间隔秒数 (默认: 1.0) |
| `--continue_from` | 从指定行继续 |

### 计算分工

| 步骤 | 执行方 | 说明 |
|------|--------|------|
| 解析 CSV | Python | 读取 105 行配置参数 |
| 约束校验 | Python | 检查约束参数是否合法 |
| 渲染 Prompt | Python | 将参数填入模板 |
| **生成权重** | **大模型 API** | Qwen 输出 w_cash/w_bond/w_equity/w_commodity |
| 验证权重 | Python | 检查 sum=100、cash_min、risk_asset_max |
| 计算波动率 | Python | `ann_vol = sqrt(w^T Σ w)` |
| 比对偏差 | Python | LLM 输出 vs CSV 预期权重 |

### 核心代码片段

#### 1. 解析 CSV (batch.py)
```python
def load_csv(self) -> List[BatchTestCase]:
    with open(self.input_csv, "r", encoding="utf-8-sig") as f:
        reader = csv.DictReader(f)
        for idx, row in enumerate(reader):
            test_case = BatchTestCase(
                row_index=idx,
                life_stage=row["life_stage"],
                risk_level=row["risk_level"],
                need=row["need"],
                csv_sigma_cap=float(row["sigma_cap"]),
                csv_cash_min=int(round(float(row["cash_min"]) * 100)),
                csv_risk_asset_max=int(round(float(row["risk_asset_max"]) * 100)),
                expected=ExpectedWeights(
                    w_cash=int(row["w_cash"]),
                    w_bond=int(row["w_bond"]),
                    w_equity=int(row["w_equity"]),
                    w_commodity=int(row["w_commodity"]),
                ),
            )
```

#### 2. 约束校验 (batch.py)
```python
def validate_constraint_consistency(self, test_case: BatchTestCase) -> tuple[bool, Dict]:
    computed = self.engine.compute_constraints(
        test_case.life_stage, test_case.risk_level, test_case.need,
    )
    sigma_match = abs(computed["sigma_cap"] - test_case.csv_sigma_cap) < 1e-6
    cash_match = computed["cash_min"] == test_case.csv_cash_min
    risk_match = computed["risk_asset_max"] == test_case.csv_risk_asset_max
    return sigma_match and cash_match and risk_match, computed
```

#### 3. 渲染 Prompt (batch.py)
```python
market_data = self.store.get_market_data()
context = {
    "life_stage": test_case.life_stage,
    "risk_level": test_case.risk_level,
    "need": test_case.need,
    **constraints,
    **market_data,
    "sigma_cap_pct": f"{constraints['sigma_cap']*100:.2f}",
}
system_prompt = self.store.render("allocation_test", self.prompt_version, context)
```

#### 4. 调用 Qwen API (batch.py)
```python
response = self.client.chat(
    system_prompt=system_prompt,
    user_message=user_payload,
)
# response 示例: {"weights": {"w_cash": 10, "w_bond": 40, "w_equity": 45, "w_commodity": 5}}
```

#### 5. 验证 LLM 输出 (validator.py)
```python
def validate(self, response: str, constraints: dict, market_pack: dict) -> ValidationResult:
    # 1. JSON 解析
    parsed = self._parse_json(response)
    weights = parsed.get("weights", {})

    # 2-3. 格式检查 + sum=100
    total = sum(weights[k] for k in self.WEIGHT_KEYS)
    checks["sum_100"] = total == 100

    # 4. cash_min 检查
    checks["cash_min"] = weights["w_cash"] >= constraints["cash_min"]

    # 5. risk_asset_max 检查
    risk_assets = weights["w_equity"] + weights["w_commodity"]
    checks["risk_asset_max"] = risk_assets <= constraints["risk_asset_max"]

    # 6. sigma_cap 检查 (调用波动率计算)
    computed_vol, _ = self._compute_ann_vol(weights, market_pack["sigma_ann"])
    checks["sigma_cap"] = computed_vol <= constraints["sigma_cap"] + self.VOL_TOLERANCE
```

#### 6. 波动率计算 - Python 核心 (validator.py)
```python
def _compute_ann_vol(self, weights: dict, sigma_ann: list) -> tuple[float, float]:
    """ann_vol = sqrt(w^T @ Σ @ w)"""
    w = np.array([
        weights["w_cash"] / 100.0,
        weights["w_bond"] / 100.0,
        weights["w_equity"] / 100.0,
        weights["w_commodity"] / 100.0,
    ])
    sigma = np.array(sigma_ann)  # 4x4 协方差矩阵
    variance = w @ sigma @ w     # 矩阵运算
    return float(np.sqrt(variance)), float(variance)
```

#### 7. 比对偏差 (batch.py)
```python
def compare_weights(self, llm_weights: Dict, expected: ExpectedWeights) -> WeightDeviation:
    diffs = {
        "w_cash_diff": llm_weights["w_cash"] - expected.w_cash,
        "w_bond_diff": llm_weights["w_bond"] - expected.w_bond,
        "w_equity_diff": llm_weights["w_equity"] - expected.w_equity,
        "w_commodity_diff": llm_weights["w_commodity"] - expected.w_commodity,
    }
    return WeightDeviation(
        **diffs,
        total_abs_diff=sum(abs(v) for v in diffs.values()),
        max_single_diff=max(abs(v) for v in diffs.values()),
    )
```

### 输出文件

运行完成后在 `runs/batch_YYYYMMDD_HHMMSS/` 目录下生成：

| 文件 | 用途 |
|------|------|
| results.csv | 每行结果，便于 Excel 分析 |
| summary.json | 汇总统计 (通过率、偏差分布) |
| batch.jsonl | 完整日志 (含原始响应) |

## 迭代 Prompt

1. 复制 `prompts/allocation_test.v001.md` 为 `v002.md`
2. 更新 `prompts/registry.yaml` 的 `current` 字段
3. 运行测试验证效果

## 参数枚举

| 参数 | 可选值 |
|------|--------|
| life_stage | 刚毕业, 单身青年, 二人世界, 小孩学前, 小孩成年前, 子女成年, 退休 |
| risk_level | C1, C2, C3, C4, C5 |
| need | 保值, 增值, 传承 |

## 架构图

```
┌─────────────────────────────────────────────────────────────────────────────┐
│                              MVO Prompt Lab                                  │
│                         资产配置 LLM 验证系统                                  │
└─────────────────────────────────────────────────────────────────────────────┘

                              ┌─────────────┐
                              │   用户输入   │
                              │ User Input  │
                              └──────┬──────┘
                                     │
                    ┌────────────────┼────────────────┐
                    │                │                │
                    ▼                ▼                ▼
            ┌───────────┐    ┌───────────┐    ┌───────────┐
            │ --user    │    │--life_stage│   │--dry_run  │
            │ 自然语言   │    │--risk_level│   │ 调试模式   │
            │           │    │--need      │   │           │
            └─────┬─────┘    └─────┬─────┘    └─────┬─────┘
                  │                │                │
                  └────────────────┼────────────────┘
                                   ▼
┌──────────────────────────────────────────────────────────────────────────────┐
│                            cli.py (入口)                                      │
│  ┌─────────────────────────────────────────────────────────────────────────┐ │
│  │  parse_natural_language()  →  提取 life_stage, risk_level, need         │ │
│  └─────────────────────────────────────────────────────────────────────────┘ │
└──────────────────────────────────────────────────────────────────────────────┘
                                   │
         ┌─────────────────────────┼─────────────────────────┐
         │                         │                         │
         ▼                         ▼                         ▼
┌─────────────────┐    ┌─────────────────────┐    ┌─────────────────┐
│  rules_engine   │    │    prompt_store     │    │  market_pack    │
│  ───────────    │    │    ────────────     │    │  ───────────    │
│                 │    │                     │    │                 │
│ v3_rules_pack   │    │ prompts/registry    │    │ v3_market_pack  │
│      ↓          │    │      ↓              │    │      ↓          │
│ ┌─────────────┐ │    │ ┌─────────────────┐ │    │ ┌─────────────┐ │
│ │ cash_min    │ │    │ │ 加载模板 v00x   │ │    │ │ sigma_ann   │ │
│ │ sigma_cap   │ │    │ │ 渲染 {{ var }}  │ │    │ │ corr        │ │
│ │ risk_max    │ │    │ └─────────────────┘ │    │ │ asset_order │ │
│ └─────────────┘ │    │                     │    │ └─────────────┘ │
└────────┬────────┘    └──────────┬──────────┘    └────────┬────────┘
         │                        │                        │
         └────────────────────────┼────────────────────────┘
                                  │
                                  ▼
                    ┌───────────────────────────┐
                    │      System Prompt        │
                    │  ┌─────────────────────┐  │
                    │  │ 客户画像 + 约束条件  │  │
                    │  │ 市场数据 + 输出格式  │  │
                    │  └─────────────────────┘  │
                    └─────────────┬─────────────┘
                                  │
                                  ▼
                    ┌───────────────────────────┐
                    │   dashscope_client.py     │
                    │   ─────────────────────   │
                    │                           │
                    │  model: qwen3-235b-a22b   │
                    │  temperature: 0.1         │
                    │                           │
                    │     ┌───────────────┐     │
                    │     │  DashScope    │     │
                    │     │    API        │     │
                    │     └───────────────┘     │
                    └─────────────┬─────────────┘
                                  │
                                  ▼
                    ┌───────────────────────────┐
                    │      Model Response       │
                    │  ┌─────────────────────┐  │
                    │  │ {                   │  │
                    │  │   "weights": {      │  │
                    │  │     "w_cash": 10,   │  │
                    │  │     "w_bond": 40,   │  │
                    │  │     "w_equity": 45, │  │
                    │  │     "w_commodity":5 │  │
                    │  │   }                 │  │
                    │  │ }                   │  │
                    │  └─────────────────────┘  │
                    └─────────────┬─────────────┘
                                  │
                                  ▼
┌──────────────────────────────────────────────────────────────────────────────┐
│                          validator.py                                         │
│  ┌────────────────────────────────────────────────────────────────────────┐  │
│  │                         验证流程                                        │  │
│  │                                                                        │  │
│  │  1. JSON 解析      →  提取 weights 字典                                 │  │
│  │  2. 格式检查       →  整数 0-100                                        │  │
│  │  3. sum_100        →  Σ weights = 100                                  │  │
│  │  4. cash_min       →  w_cash >= cash_min                               │  │
│  │  5. risk_asset_max →  (w_equity + w_commodity) <= risk_asset_max       │  │
│  │  6. sigma_cap      →  sqrt(w^T Σ w) <= sigma_cap                       │  │
│  │                                                                        │  │
│  └────────────────────────────────────────────────────────────────────────┘  │
└──────────────────────────────────────────────────────────────────────────────┘
                                  │
                                  ▼
                    ┌───────────────────────────┐
                    │    ValidationResult       │
                    │  ┌─────────────────────┐  │
                    │  │ success: bool       │  │
                    │  │ weights: dict       │  │
                    │  │ computed_vol: float │  │
                    │  │ errors: list        │  │
                    │  │ warnings: list      │  │
                    │  └─────────────────────┘  │
                    └─────────────┬─────────────┘
                                  │
                                  ▼
                    ┌───────────────────────────┐
                    │       logger.py           │
                    │   ─────────────────────   │
                    │                           │
                    │  runs/YYYY-MM-DD/         │
                    │  ├── run_001.jsonl        │
                    │  └── run_001_artifacts/   │
                    │      ├── system_prompt    │
                    │      ├── raw_response     │
                    │      └── validation.json  │
                    └───────────────────────────┘


═══════════════════════════════════════════════════════════════════════════════
                              数据流向 (Data Flow)
═══════════════════════════════════════════════════════════════════════════════

  输入层                处理层                   模型层              验证层
  ─────                ─────                   ─────              ─────

┌─────────┐       ┌─────────────┐        ┌─────────────┐     ┌─────────────┐
│ 用户参数 │──────▶│ RulesEngine │───┐    │             │     │  Validator  │
└─────────┘       │ 约束计算     │   │    │  Qwen LLM   │     │  ─────────  │
                  └─────────────┘   │    │             │     │ • JSON解析  │
                                    ├───▶│  生成配置   │────▶│ • 约束检查  │
┌─────────┐       ┌─────────────┐   │    │             │     │ • Vol计算   │
│ 规则文件 │──────▶│ PromptStore │───┘    │             │     │             │
└─────────┘       │ 模板渲染     │        └─────────────┘     └──────┬──────┘
                  └─────────────┘                                   │
                                                                    ▼
                                                            ┌─────────────┐
                                                            │  PASS/FAIL  │
                                                            │  运行日志    │
                                                            └─────────────┘
```

## 代码风格
- 使用 type hints
- 中文注释 + 英文代码
- 模块职责单一
