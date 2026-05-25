"""Business-rule configuration contracts and option reports."""

from __future__ import annotations

from pathlib import Path
import shutil
from typing import Any

from churn_model.config import DecisionRequired, ProjectConfig, load_config


REQUIRED_SECTIONS = [
    "target_definition",
    "potential_definition",
    "risk_bands",
    "prioritization_strategy",
    "model_selection_strategy",
]

EMPTY_VALUES = {None, "", "TBD", "TODO", "CHOOSE_EXPLICITLY"}

SECTION_REQUIRED_FIELDS = {
    "target_definition": ["type"],
    "potential_definition": ["type"],
    "risk_bands": ["type"],
    "prioritization_strategy": ["type"],
    "model_selection_strategy": ["type"],
}

STAGE_REQUIRED_SECTIONS = {
    "labeling": ["target_definition"],
    "training": ["target_definition", "model_selection_strategy"],
    "finalization": ["target_definition", "model_selection_strategy"],
    "scoring": [],
    "all": REQUIRED_SECTIONS,
}


def business_rules_checkpoint(
    base_config_path: str | Path = "configs/base.yaml",
    business_rules_path: str | Path = "configs/business_rules.yaml",
    template_path: str | Path = "configs/business_rules.template.yaml",
    reports_dir: str | Path = "reports",
    root: str | Path | None = None,
    required_sections: list[str] | None = None,
    stage_name: str | None = None,
) -> ProjectConfig:
    """Create/validate business rules and stop at the decision checkpoint if incomplete."""
    project_root = Path(root or ".").resolve()
    rules_path = _resolve(project_root, business_rules_path)
    template = _resolve(project_root, template_path)
    report_path = _resolve(project_root, reports_dir) / "business_rules_validation.md"

    created_from_template = False
    if not rules_path.exists():
        if not template.exists():
            raise DecisionRequired(f"Business rules template is missing: {template}")
        rules_path.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(template, rules_path)
        created_from_template = True

    cfg = load_config(base_config_path, business_rules_path=rules_path, root=project_root)
    missing = (
        validate_business_rules_fields(cfg, required_sections)
        if required_sections is not None
        else validate_business_rules_config(cfg)
    )
    validation_scope = required_sections or REQUIRED_SECTIONS
    write_business_rules_validation_report(
        report_path,
        rules_path=rules_path,
        created_from_template=created_from_template,
        missing_items=missing,
        required_sections=validation_scope,
        stage_name=stage_name or ("full pipeline" if required_sections is None else "current stage"),
    )
    if missing:
        checklist = "\n".join(f"- {item}" for item in missing)
        created_msg = " Created it from the template." if created_from_template else ""
        stage_msg = f" for {stage_name}" if stage_name else ""
        raise DecisionRequired(
            f"Business rules are incomplete{stage_msg}.{created_msg} Fill these fields before this stage can proceed:\n"
            f"{checklist}\n"
            f"See {report_path}."
        )
    return cfg


def stage_business_rules_checkpoint(
    stage_name: str,
    base_config_path: str | Path = "configs/base.yaml",
    business_rules_path: str | Path = "configs/business_rules.yaml",
    template_path: str | Path = "configs/business_rules.template.yaml",
    reports_dir: str | Path = "reports",
    root: str | Path | None = None,
) -> ProjectConfig:
    """Run decision checkpoint for a named pipeline stage."""
    if stage_name not in STAGE_REQUIRED_SECTIONS:
        raise ValueError(f"Unknown stage for business-rule checkpoint: {stage_name}")
    return business_rules_checkpoint(
        base_config_path=base_config_path,
        business_rules_path=business_rules_path,
        template_path=template_path,
        reports_dir=reports_dir,
        root=root,
        required_sections=STAGE_REQUIRED_SECTIONS[stage_name],
        stage_name=stage_name,
    )


def require_business_rules_file(path: str | Path) -> Path:
    rules_path = Path(path)
    if not rules_path.exists():
        raise DecisionRequired(
            f"Business rules file is missing: {rules_path}. "
            "Copy configs/business_rules.template.yaml to configs/business_rules.yaml and fill explicit choices."
        )
    return rules_path


def validate_business_rules_config(cfg: ProjectConfig) -> list[str]:
    """Return exact missing business-rule fields; empty list means complete."""
    rules = cfg.get("business_rules")
    missing: list[str] = []
    if not isinstance(rules, dict):
        return ["business_rules"]
    for section in REQUIRED_SECTIONS:
        section_value = rules.get(section)
        if not isinstance(section_value, dict):
            missing.append(f"business_rules.{section}")
            continue
        for field in SECTION_REQUIRED_FIELDS[section]:
            if _is_empty(section_value.get(field)):
                missing.append(f"business_rules.{section}.{field}")
    return missing


def write_business_rules_validation_report(
    path: Path,
    rules_path: Path,
    created_from_template: bool,
    missing_items: list[str],
    required_sections: list[str] | None = None,
    stage_name: str = "full pipeline",
) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    status = "PASS" if not missing_items else "BLOCKED"
    lines = [
        "# Business Rules Validation",
        "",
        f"- Status: `{status}`",
        f"- Business rules file: `{_display_path(rules_path)}`",
        f"- Created from template in this run: `{str(created_from_template).lower()}`",
        f"- Validation scope: `{stage_name}`",
        "",
        "## Required For This Stage",
        "",
    ]
    for section in required_sections or REQUIRED_SECTIONS:
        lines.append(f"- `business_rules.{section}.type`")
    lines.extend(
        [
            "",
            "## Stage Requirement Matrix",
            "",
            "- `labeling`: `business_rules.target_definition.type`",
            "- `training`: `business_rules.target_definition.type`, `business_rules.model_selection_strategy.type`",
            "- `finalization`: `business_rules.target_definition.type`, `business_rules.model_selection_strategy.type`",
            "- `scoring`: no business-rule fields required (risk is derived directly from churn probability in scoring logic).",
            "",
            "## Stage-Specific Blocking Rules",
            "",
            "- `scripts/build_labeled_dataset.py`: requires only `business_rules.target_definition`.",
            "- `scripts/train_and_evaluate.py`: requires only `business_rules.target_definition` and `business_rules.model_selection_strategy`.",
            "- `scripts/finalize_production_model.py`: requires `business_rules.target_definition`, `business_rules.model_selection_strategy`, and training artifacts (`selected_candidate_model.txt`, selected model `.joblib`, and `training_config.yaml`).",
            "- `scripts/score_input_file.py`: does not require `business_rules.potential_definition` or `business_rules.risk_bands`.",
        ]
    )
    lines.extend(["", "## Missing Or Incomplete Fields", ""])
    if missing_items:
        lines.extend(f"- [ ] `{item}`" for item in missing_items)
    else:
        lines.append("- None. Business rules are complete.")
    lines.extend(
        [
            "",
            "## Decision Checkpoint",
            "",
            "The current stage must not proceed while this report is `BLOCKED`.",
            "Fill only the listed stage-required fields in `configs/business_rules.yaml` with explicit stakeholder-approved choices.",
            "Do not add churn thresholds, active criteria, potential bands, risk bands, or prioritization thresholds unless they have been explicitly chosen.",
        ]
    )
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return path


def validate_business_rules_for_training(cfg: ProjectConfig) -> None:
    """Require explicit target and model-selection choices before training."""
    missing = validate_business_rules_fields(cfg, STAGE_REQUIRED_SECTIONS["training"])
    if missing:
        raise DecisionRequired(f"Business rules are incomplete. Missing fields: {missing}")


def validate_business_rules_for_scoring(cfg: ProjectConfig) -> None:
    """Scoring stage has no required business-rule fields."""
    missing = validate_business_rules_fields(cfg, STAGE_REQUIRED_SECTIONS["scoring"])
    if missing:
        raise DecisionRequired(f"Business rules are incomplete. Missing fields: {missing}")


def validate_business_rules_for_labeling(cfg: ProjectConfig) -> None:
    missing = validate_business_rules_fields(cfg, STAGE_REQUIRED_SECTIONS["labeling"])
    if missing:
        raise DecisionRequired(f"Business rules are incomplete. Missing fields: {missing}")


def validate_business_rules_for_finalization(cfg: ProjectConfig) -> None:
    missing = validate_business_rules_fields(cfg, STAGE_REQUIRED_SECTIONS["finalization"])
    if missing:
        raise DecisionRequired(f"Business rules are incomplete. Missing fields: {missing}")


def validate_business_rules_fields(cfg: ProjectConfig, sections: list[str]) -> list[str]:
    rules = cfg.get("business_rules")
    missing: list[str] = []
    if not isinstance(rules, dict):
        return ["business_rules"]
    for section in sections:
        section_value = rules.get(section)
        if not isinstance(section_value, dict):
            missing.append(f"business_rules.{section}")
            continue
        for field in SECTION_REQUIRED_FIELDS[section]:
            if _is_empty(section_value.get(field)):
                missing.append(f"business_rules.{section}.{field}")
    return missing


def write_business_rule_option_reports(reports_dir: Path) -> list[Path]:
    reports_dir.mkdir(parents=True, exist_ok=True)
    outputs = [
        _write(reports_dir / "target_definition_options.md", _target_options()),
        _write(reports_dir / "potential_definition_options.md", _potential_options()),
        _write(reports_dir / "risk_and_prioritization_options.md", _risk_prioritization_options()),
    ]
    return outputs


def _rules(cfg: ProjectConfig) -> dict[str, Any]:
    rules = cfg.get("business_rules")
    if not isinstance(rules, dict):
        raise DecisionRequired("`business_rules` must be a mapping with explicit configured sections.")
    return rules


def _require_sections(rules: dict[str, Any]) -> None:
    missing = [section for section in REQUIRED_SECTIONS if section not in rules]
    if missing:
        raise DecisionRequired(f"Business rules are incomplete. Missing sections: {missing}")


def _require_complete(section: dict[str, Any], section_name: str, required_keys: list[str]) -> None:
    if not isinstance(section, dict):
        raise DecisionRequired(f"Business rules section `{section_name}` must be a mapping.")
    missing = [key for key in required_keys if _is_empty(section.get(key))]
    if missing:
        raise DecisionRequired(
            f"Business rules section `{section_name}` is incomplete. "
            f"Missing explicit values for: {missing}. Do not proceed until stakeholders choose them."
        )


def _is_empty(value: Any) -> bool:
    if isinstance(value, str):
        return value.strip() in EMPTY_VALUES
    return value in EMPTY_VALUES


def _write(path: Path, content: str) -> Path:
    path.write_text(content, encoding="utf-8")
    return path


def _resolve(root: Path, path: str | Path) -> Path:
    candidate = Path(path)
    return candidate if candidate.is_absolute() else root / candidate


def _display_path(path: Path) -> str:
    try:
        return str(path.resolve().relative_to(Path.cwd().resolve()))
    except ValueError:
        return str(path)


def _target_options() -> str:
    return """# Target Definition Options

This report explains configurable target-definition options. It does not choose one and does not introduce any churn threshold.

## Available Inputs

- Six feature-month scan values in each rolling sample.
- The immediately following three-month horizon totals and helper fields already generated in the unlabeled window datasets.
- Recent-status segment for reporting only.

## Configurable Patterns

- `explicit_column`: use a stakeholder-provided binary target column.
- `future_total_rule`: define target from `future_3m_total` only after an explicit threshold is provided.
- `decline_rule`: compare future horizon behavior with recent feature-window behavior only after an explicit decline rule is provided.
- `custom_sql_or_python_rule`: use a reviewed project-specific rule, documented in config.

## Required Decision

The project cannot train until `business_rules.target_definition` is filled in `configs/business_rules.yaml`.
"""


def _potential_options() -> str:
    return """# Potential Definition Options

This report explains configurable potential-definition options. It does not choose one and does not create default potential bands.

## Configurable Patterns

- `explicit_column`: use a stakeholder-provided potential field.
- `recent_scan_volume`: define potential from scan values only after explicit bands are provided.
- `historical_window_summary`: use six-month feature summaries only after explicit band logic is provided.
- `none`: explicitly disable potential-based prioritization if stakeholders choose not to use it.

## Required Decision

Potential enrichment cannot proceed until potential logic is explicitly configured or a reviewed lookup is available.
Core churn scoring does not require `business_rules.potential_definition`.
"""


def _risk_prioritization_options() -> str:
    return """# Risk And Prioritization Options

This report explains configurable prioritization options and historical risk-band options. Current core churn scoring uses the fixed probability-based risk mapping documented in `reports/RISK_LOGIC_CHANGE.md`.

## Risk Band Options

- `fixed_probability_bands`: current scoring output rule. `Churn probability < 0.50` => `LOW RISK`; `0.50 <= Churn probability < 0.85` => `MEDIUM RISK`; `Churn probability >= 0.85` => `HIGH RISK`.
- `explicit_thresholds`: historical option for configurable score cutoffs after stakeholders provide exact thresholds.
- `quantile_bands`: define quantile cutoffs only after exact quantile choices are provided.
- `none`: explicitly disable risk bands if stakeholders choose score-only outputs.

## Prioritization Strategy Options

- `within_recent_status`: rank separately inside `recently_scanning` and `recently_inactive`. This keeps recently inactive users as their own operational segment instead of letting them dominate a single global high-risk list.
- `recently_scanning_first`: create an operational ordering that places `recently_scanning` before `recently_inactive`, then ranks by raw model probability within each segment.
- `custom_segment_order`: require an explicit `segment_order` list in `business_rules.yaml`; valid segment values are `recently_scanning` and `recently_inactive`.
- `score_only`: keep raw model probability and recent-status segment, but do not create a cross-segment operational rank.
- `potential_adjusted`: combine risk and configured potential only after explicit combination logic is provided. This is intentionally blocked unless that logic is configured.

## Recent Status Contract

- `recently_inactive` means scans are zero across months 4-6 of the six-month feature window.
- `recently_scanning` means there is some scan activity across months 4-6 of the six-month feature window.
- Recent status must be derived from the latest three months of the six-month input, not from future months and not from older history.
- Raw model probability remains available as `risk_score` and `raw_model_probability`.
- Operational prioritization fields are separate: `operational_priority_segment`, `rank_within_recent_status`, and, when configured, `operational_rank`.

## Model Selection Strategy Options

- `fixed_candidate`: promote a reviewed model artifact by path.
- `metric_gate`: choose a model only after exact metrics and acceptance criteria are configured.
- `manual_review`: require a human approval checkpoint before finalization.

## Required Decision

Core production scoring does not require `business_rules.risk_bands`; it applies the fixed probability-based mapping in scoring code.
"""
