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
│   ├── rules_engine.py     # V3 规则引擎，约束计算
│   ├── dashscope_client.py # Qwen API 封装
│   ├── validator.py        # 输出验证（含 ann_vol 计算）
│   ├── prompt_store.py     # Prompt 模板加载/渲染
│   └── logger.py           # 运行日志记录
├── prompts/                # Prompt 模板（版本化）
│   ├── registry.yaml       # 版本注册表
│   └── allocation_test.v001.md
├── inputs/fixtures/        # 业务规则数据
│   ├── v3_rules_pack.json  # V3 约束参数
│   └── v3_market_pack.json # 协方差矩阵
└── runs/                   # 运行日志（按日期）
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

## 代码风格
- 使用 type hints
- 中文注释 + 英文代码
- 模块职责单一
