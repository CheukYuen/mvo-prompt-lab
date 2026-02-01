"""V3 rules engine for computing portfolio constraints."""

import json
from pathlib import Path
from typing import TypedDict


class Constraints(TypedDict):
    cash_min: int
    sigma_cap: float
    risk_asset_max: int


class RulesEngine:
    """Compute portfolio constraints from V3 rules."""

    def __init__(self, rules_path: Path = None, market_path: Path = None):
        base = Path(__file__).parent.parent.parent / "inputs" / "fixtures"
        self.rules_path = rules_path or base / "v3_rules_pack.json"
        self.market_path = market_path or base / "v3_market_pack.json"

        self.rules_pack = self._load_json(self.rules_path)
        self.market_pack = self._load_json(self.market_path)

        self._validate_rules_pack()

    def _load_json(self, path: Path) -> dict:
        with open(path, "r", encoding="utf-8") as f:
            return json.load(f)

    def _validate_rules_pack(self):
        """Validate rules pack structure."""
        required_keys = [
            "CASH_MIN_STAGE",
            "SIGMA_STAGE_MAX",
            "M_RISK",
            "RISK_ASSET_MAX_STAGE",
            "K_RISK",
            "K_NEED_RISKASSET",
            "CLIP",
            "enums",
        ]
        for key in required_keys:
            if key not in self.rules_pack:
                raise ValueError(f"Missing required key in rules pack: {key}")

    def validate_inputs(self, life_stage: str, risk_level: str, need: str) -> None:
        """Validate input parameters against enums."""
        enums = self.rules_pack["enums"]

        if life_stage not in enums["life_stages"]:
            raise ValueError(
                f"Invalid life_stage: {life_stage}. Valid: {enums['life_stages']}"
            )
        if risk_level not in enums["risk_levels"]:
            raise ValueError(
                f"Invalid risk_level: {risk_level}. Valid: {enums['risk_levels']}"
            )
        if need not in enums["needs"]:
            raise ValueError(f"Invalid need: {need}. Valid: {enums['needs']}")

    def compute_constraints(
        self, life_stage: str, risk_level: str, need: str
    ) -> Constraints:
        """
        Compute portfolio constraints from client profile.

        Formulas:
        - cash_min = CASH_MIN_STAGE[life_stage]
        - sigma_cap = clip(SIGMA_STAGE_MAX[life_stage] * M_RISK[risk_level], min, max)
        - risk_asset_max = clip(
            RISK_ASSET_MAX_STAGE[life_stage] * K_RISK[risk_level] * K_NEED_RISKASSET[need],
            min, max
          )
        """
        self.validate_inputs(life_stage, risk_level, need)

        rp = self.rules_pack
        clip = rp["CLIP"]

        # Cash minimum (integer percentage)
        cash_min = rp["CASH_MIN_STAGE"][life_stage]

        # Sigma cap (float, annualized volatility)
        raw_sigma = rp["SIGMA_STAGE_MAX"][life_stage] * rp["M_RISK"][risk_level]
        sigma_cap = max(clip["sigma_cap_min"], min(clip["sigma_cap_max"], raw_sigma))

        # Risk asset max (integer percentage)
        raw_risk = (
            rp["RISK_ASSET_MAX_STAGE"][life_stage]
            * rp["K_RISK"][risk_level]
            * rp["K_NEED_RISKASSET"][need]
        )
        risk_asset_max = int(
            max(clip["risk_asset_max_min"], min(clip["risk_asset_max_max"], raw_risk))
        )

        return Constraints(
            cash_min=cash_min, sigma_cap=sigma_cap, risk_asset_max=risk_asset_max
        )
