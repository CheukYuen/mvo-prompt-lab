"""Manage prompt templates and rendering."""

import json
import re
from pathlib import Path

import yaml


class PromptStore:
    """Manage prompt templates and rendering."""

    def __init__(self, prompts_dir: Path = None):
        self.prompts_dir = prompts_dir or Path(__file__).parent.parent.parent / "prompts"
        self.registry_path = self.prompts_dir / "registry.yaml"
        self.registry = self._load_registry()

    def _load_registry(self) -> dict:
        with open(self.registry_path, "r", encoding="utf-8") as f:
            return yaml.safe_load(f)

    def get_version(self, prompt_name: str, version: str = None) -> str:
        """Get the template filename for a prompt version."""
        prompt_config = self.registry["prompts"].get(prompt_name)
        if not prompt_config:
            raise ValueError(f"Unknown prompt: {prompt_name}")

        version = version or prompt_config["current"]
        version_config = prompt_config["versions"].get(version)
        if not version_config:
            raise ValueError(f"Unknown version {version} for prompt {prompt_name}")

        return version_config["file"]

    def load_template(self, prompt_name: str, version: str = None) -> str:
        """Load a prompt template."""
        template_file = self.get_version(prompt_name, version)
        template_path = self.prompts_dir / template_file
        with open(template_path, "r", encoding="utf-8") as f:
            return f.read()

    def render(self, prompt_name: str, version: str = None, context: dict = None) -> str:
        """
        Render a prompt template with context using simple string substitution.

        Supports {{ variable }} syntax.
        """
        template = self.load_template(prompt_name, version)
        context = context or {}

        # Simple template substitution for {{ variable }}
        def replace_var(match):
            var_name = match.group(1).strip()
            if var_name in context:
                return str(context[var_name])
            return match.group(0)  # Keep original if not found

        rendered = re.sub(r"\{\{\s*(\w+)\s*\}\}", replace_var, template)
        return rendered

    def get_market_data(self) -> dict:
        """Load and format market data for prompt context."""
        market_path = (
            Path(__file__).parent.parent.parent
            / "inputs"
            / "fixtures"
            / "v3_market_pack.json"
        )

        with open(market_path, "r", encoding="utf-8") as f:
            market = json.load(f)

        return {
            "asset_order": ", ".join(market["asset_order"]),
            "sigma_ann_matrix": self._format_matrix(market["sigma_ann"]),
            "corr_matrix": self._format_matrix(market["corr"], precision=4),
        }

    def _format_matrix(self, matrix: list, precision: int = 6) -> str:
        """Format a matrix as aligned columns."""
        lines = []
        for row in matrix:
            formatted = [f"{val:>{precision + 4}.{precision}f}" for val in row]
            lines.append("  ".join(formatted))
        return "\n".join(lines)
