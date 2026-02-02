# MVO Prompt Lab

MVP 项目，用于验证"模型能否在给定 V3 规则下输出四大类资产配置权重"。

## 功能

- 输入客户画像（人生阶段、风险等级、投资需求）
- 自动计算三大约束（现金下限、波动率上限、风险资产上限）
- 注入业务规则 + 协方差矩阵到 System Prompt
- 调用 Qwen API（DashScope）获取配置权重
- 验证权重满足所有约束条件
- 运行记录落盘

## 快速开始

### 1. 创建虚拟环境

```bash
python3 -m venv .venv
source .venv/bin/activate
```

### 2. 安装依赖

```bash
pip install -e .
```

> **注意**：本项目使用 `src/` 目录结构，必须通过 `pip install` 安装后才能运行 `python -m promptlab`。
>
> - **开发环境**：使用 `pip install -e .`（editable mode），修改代码立即生效
> - **生产环境**：使用 `pip install .`，代码复制到 `site-packages`，更稳定安全

### 3. 配置 API Key

复制 `.env.example` 为 `.env` 并填入你的 DashScope API Key：

```bash
cp .env.example .env
```

编辑 `.env`：

```
DASHSCOPE_API_KEY=your_actual_api_key_here
QWEN_MODEL=qwen3-235b-a22b-instruct-2507
```

### 4. 运行

#### 方式一：自然语言输入

```bash
python -m promptlab run --user "给我单身青年C3增值的配置"
```

#### 方式二：明确参数

```bash
python -m promptlab run --life_stage 单身青年 --risk_level C3 --need 增值
```

#### 方式三：Dry Run（仅查看 Prompt）

```bash
python -m promptlab run --user "退休C1保值" --dry_run
```

### 5. 批量验证

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

#### 批量验证参数

| 参数 | 说明 |
|------|------|
| `--input, -i` | 输入 CSV 文件路径 (必需) |
| `--output, -o` | 输出目录 (默认: runs/batch_TIMESTAMP) |
| `--use_csv_constraints` | 使用 CSV 中的约束参数 (推荐) |
| `--dry_run` | 仅验证 CSV，不调用 API |
| `--delay` | API 调用间隔秒数 (默认: 1.0) |
| `--continue_from` | 从指定行继续 |

#### 批量验证输出

运行完成后在 `runs/batch_YYYYMMDD_HHMMSS/` 目录下生成：

| 文件 | 用途 |
|------|------|
| `results.csv` | 每行结果，便于 Excel 分析 |
| `summary.json` | 汇总统计 (通过率、偏差分布) |
| `batch.jsonl` | 完整日志 (含原始响应) |

## 参数说明

| 参数 | 可选值 | 默认值 |
|------|--------|--------|
| `life_stage` | 刚毕业, 单身青年, 二人世界, 小孩学前, 小孩成年前, 子女成年, 退休 | 单身青年 |
| `risk_level` | C1, C2, C3, C4, C5 | C3 |
| `need` | 保值, 增值, 传承 | 增值 |

## 输出示例

### 成功案例

```
============================================================
客户画像 (Client Profile)
============================================================
  人生阶段: 单身青年
  风险等级: C3
  投资需求: 增值

============================================================
计算约束 (Computed Constraints)
============================================================
  现金下限 (cash_min): 5%
  波动率上限 (sigma_cap): 0.2000 (20.00%)
  风险资产上限 (risk_asset_max): 80%

============================================================
验证结果 (Validation Result)
============================================================

解析权重 (Parsed Weights):
  w_cash: 5%
  w_bond: 45%
  w_equity: 40%
  w_commodity: 10%

组合年化波动率 (Portfolio Ann Vol): 0.103580 (10.36%)
  sigma_cap: 0.200000 (20.00%)
  Status: ✓ PASS

约束检查 (Constraint Checks):
  ✓ sum_100
  ✓ cash_min
  ✓ risk_asset_max
  ✓ sigma_cap

============================================================
总体结果: ✓ 通过 (PASS)
============================================================
```

### 失败案例（模型计算错误）

```
============================================================
验证结果 (Validation Result)
============================================================

解析权重 (Parsed Weights):
  w_cash: 20%
  w_bond: 80%
  w_equity: 6%
  w_commodity: 6%

约束检查 (Constraint Checks):
  ✗ sum_100

错误 (Errors):
  ✗ Weights sum to 112, not 100

============================================================
总体结果: ✗ 失败 (FAIL)
============================================================
```

## 运行记录

每次运行会在 `runs/YYYY-MM-DD/` 目录下生成：

- `run_XXX.jsonl`: 完整运行记录
- `run_XXX_artifacts/`: 详细文件
  - `system_prompt.txt`: 发送给模型的完整 Prompt
  - `user_payload.json`: 用户输入参数
  - `raw_response.txt`: 模型原始输出
  - `validation.json`: 验证结果详情

## 迭代 Prompt

1. 复制现有 Prompt 文件：
   ```bash
   cp prompts/allocation_test.v001.md prompts/allocation_test.v002.md
   ```

2. 更新 `prompts/registry.yaml`：
   ```yaml
   prompts:
     allocation_test:
       current: v002  # 更新当前版本
       versions:
         v001:
           file: allocation_test.v001.md
           description: "Initial V3 rules-based allocation prompt"
         v002:
           file: allocation_test.v002.md
           description: "Improved prompt with better constraint handling"
   ```

3. 运行测试：
   ```bash
   python -m promptlab run --user "单身青年C3增值" --prompt_version v002
   ```

## 项目结构

```
mvo-prompt-lab/
├── pyproject.toml          # 项目配置
├── .env.example            # 环境变量模板
├── README.md               # 本文件
├── CLAUDE.md               # Claude Code 上下文
├── prompts/
│   ├── registry.yaml       # Prompt 版本注册
│   └── allocation_test.v001.md  # Prompt 模板
├── inputs/fixtures/
│   ├── v3_rules_pack.json  # V3 规则配置
│   └── v3_market_pack.json # 市场数据（协方差矩阵）
├── runs/                   # 运行记录
└── src/promptlab/
    ├── __init__.py
    ├── __main__.py
    ├── cli.py              # 命令行接口
    ├── rules_engine.py     # 约束计算引擎
    ├── dashscope_client.py # DashScope API 客户端
    ├── prompt_store.py     # Prompt 模板管理
    ├── validator.py        # 输出验证器
    └── logger.py           # 运行记录器
```

## V3 规则说明

### 约束计算公式

```
cash_min = CASH_MIN_STAGE[life_stage]
sigma_cap = clip(SIGMA_STAGE_MAX[life_stage] × M_RISK[risk_level])
risk_asset_max = clip(RISK_ASSET_MAX_STAGE[life_stage] × K_RISK[risk_level] × K_NEED_RISKASSET[need])
```

### 波动率计算

```
ann_vol = sqrt(w^T × Σ × w)
```

其中 `w` 为权重向量（小数），`Σ` 为年化协方差矩阵。

## License

MIT
