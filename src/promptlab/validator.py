"""Validate model allocation output against constraints."""

import json
import re
from typing import TypedDict, Optional, List

import numpy as np


class ValidationResult(TypedDict):
    success: bool
    weights: Optional[dict]
    errors: List[str]
    warnings: List[str]
    computed_vol: Optional[float]
    computed_var: Optional[float]
    constraints_satisfied: dict


class Validator:
    """Validate model allocation output."""

    ASSET_ORDER = ["CASH", "BOND", "EQUITY", "COMMODITY"]
    WEIGHT_KEYS = ["w_cash", "w_bond", "w_equity", "w_commodity"]
    VOL_TOLERANCE = 1e-6

    def validate(
        self, response: str, constraints: dict, market_pack: dict
    ) -> ValidationResult:
        """
        Validate model response against all constraints.

        Checks:
        1. Valid JSON parsing
        2. All weights are integers 0-100
        3. Weights sum to 100
        4. Cash weight >= cash_min
        5. Equity + Commodity <= risk_asset_max
        6. Portfolio volatility <= sigma_cap

        Args:
            response: Raw model response text
            constraints: Dict with cash_min, sigma_cap, risk_asset_max
            market_pack: Dict with sigma_ann covariance matrix

        Returns:
            ValidationResult with success flag, errors, and computed values
        """
        errors = []
        warnings = []
        weights = None
        computed_vol = None
        computed_var = None
        checks = {}

        # 1. Parse JSON
        try:
            parsed = self._parse_json(response)
            weights = parsed.get("weights", {})
        except ValueError as e:
            errors.append(f"JSON parse error: {e}")
            return ValidationResult(
                success=False,
                weights=None,
                errors=errors,
                warnings=warnings,
                computed_vol=None,
                computed_var=None,
                constraints_satisfied={},
            )

        # 2. Check all weights are valid integers
        for key in self.WEIGHT_KEYS:
            if key not in weights:
                errors.append(f"Missing weight: {key}")
                continue
            w = weights[key]
            if not isinstance(w, int):
                errors.append(f"Weight {key} is not an integer: {w}")
            elif w < 0 or w > 100:
                errors.append(f"Weight {key} out of range [0,100]: {w}")

        if errors:
            return ValidationResult(
                success=False,
                weights=weights,
                errors=errors,
                warnings=warnings,
                computed_vol=None,
                computed_var=None,
                constraints_satisfied={},
            )

        # 3. Check sum = 100
        total = sum(weights[k] for k in self.WEIGHT_KEYS)
        checks["sum_100"] = total == 100
        if not checks["sum_100"]:
            errors.append(f"Weights sum to {total}, not 100")

        # 4. Check cash minimum
        checks["cash_min"] = weights["w_cash"] >= constraints["cash_min"]
        if not checks["cash_min"]:
            errors.append(
                f"Cash weight {weights['w_cash']}% < minimum {constraints['cash_min']}%"
            )

        # 5. Check risk asset max
        risk_assets = weights["w_equity"] + weights["w_commodity"]
        checks["risk_asset_max"] = risk_assets <= constraints["risk_asset_max"]
        if not checks["risk_asset_max"]:
            errors.append(
                f"Risk assets {risk_assets}% > maximum {constraints['risk_asset_max']}%"
            )

        # 6. Compute and check portfolio volatility
        computed_vol, computed_var = self._compute_ann_vol(
            weights, market_pack["sigma_ann"]
        )
        checks["sigma_cap"] = (
            computed_vol <= constraints["sigma_cap"] + self.VOL_TOLERANCE
        )
        if not checks["sigma_cap"]:
            errors.append(
                f"Portfolio volatility {computed_vol:.6f} > cap {constraints['sigma_cap']:.6f}"
            )

        # Warnings for edge cases
        if weights["w_cash"] == constraints["cash_min"]:
            warnings.append("Cash weight at exact minimum")
        if risk_assets == constraints["risk_asset_max"]:
            warnings.append("Risk assets at exact maximum")
        if abs(computed_vol - constraints["sigma_cap"]) < 0.001:
            warnings.append("Portfolio volatility very close to cap")

        return ValidationResult(
            success=len(errors) == 0,
            weights=weights,
            errors=errors,
            warnings=warnings,
            computed_vol=computed_vol,
            computed_var=computed_var,
            constraints_satisfied=checks,
        )

    def _parse_json(self, response: str) -> dict:
        """
        Extract and parse JSON from response.
        Handles markdown code blocks and extra text.
        """
        # Clean up common issues
        cleaned = response.strip()

        # Try direct parse first
        try:
            return json.loads(cleaned)
        except json.JSONDecodeError:
            pass

        # Try to extract from markdown code block
        json_match = re.search(r"```(?:json)?\s*(\{.*?\})\s*```", cleaned, re.DOTALL)
        if json_match:
            return json.loads(json_match.group(1))

        # Try to find raw JSON object (greedy match for nested braces)
        json_match = re.search(r"\{[^{}]*(?:\{[^{}]*\}[^{}]*)*\}", cleaned)
        if json_match:
            return json.loads(json_match.group(0))

        raise ValueError("No valid JSON found in response")

    def _compute_ann_vol(self, weights: dict, sigma_ann: list) -> tuple[float, float]:
        """
        Compute annualized portfolio volatility.

        Formula: ann_vol = sqrt(w^T @ Sigma @ w)

        Args:
            weights: Dict with w_cash, w_bond, w_equity, w_commodity (0-100)
            sigma_ann: 4x4 covariance matrix

        Returns:
            Tuple of (annualized volatility, variance)
        """
        # Convert weights to decimal numpy array in correct order
        w = np.array(
            [
                weights["w_cash"] / 100.0,
                weights["w_bond"] / 100.0,
                weights["w_equity"] / 100.0,
                weights["w_commodity"] / 100.0,
            ]
        )

        # Convert covariance matrix to numpy
        sigma = np.array(sigma_ann)

        # Compute portfolio variance: w^T @ Sigma @ w
        variance = w @ sigma @ w

        # Return standard deviation (volatility) and variance
        return float(np.sqrt(variance)), float(variance)
