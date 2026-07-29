from __future__ import annotations

import json
from pathlib import Path

from conftest import make_config

from labctl.config import WorkloadConfig
from labctl.tfvars import TFVARS_FILENAME, build_tfvars, write_tfvars


def _config(tmp_path: Path):
    return make_config(
        tmp_path,
        workload=WorkloadConfig(
            alert_notification_email="ops@example.com", alert_threshold_5xx=5, log_retention_days=45
        ),
    )


def test_build_tfvars_maps_every_field(tmp_path: Path) -> None:
    config = _config(tmp_path)

    tfvars = build_tfvars(config)

    assert tfvars["region"] == "swedencentral"
    assert tfvars["subscription_id"] == "sub-1"
    assert tfvars["tenant_id"] == "tenant-1"
    assert tfvars["agent_resource_group_name"] == "rg-agent"
    assert tfvars["workload_resource_group_name"] == "rg-workload"
    assert tfvars["tags"] == {
        "repository": "azure-sre-agent",
        "environment": "demo",
        "owner": "me",
        "deployment_id": "local",
    }
    assert tfvars["alert_notification_email"] == "ops@example.com"
    assert tfvars["log_retention_days"] == 45
    assert tfvars["alert_threshold_5xx"] == 5
    assert tfvars["agent_name"] == "sre-agent-demo"
    assert tfvars["agent_upgrade_channel"] == "Preview"
    assert tfvars["agent_monthly_aau_allocation"] == 3000
    assert tfvars["agent_model_provider"] == "Anthropic"
    assert tfvars["agent_model_name"] == "Automatic"
    assert tfvars["agent_workload_access_level"] == "narrow"


def test_write_tfvars_creates_json_file_under_state_dir(tmp_path: Path) -> None:
    config = _config(tmp_path)

    path = write_tfvars(config)

    assert path == tmp_path / ".state" / TFVARS_FILENAME
    assert path.is_file()
    written = json.loads(path.read_text(encoding="utf-8"))
    assert written["region"] == "swedencentral"


def test_write_tfvars_is_idempotent_and_overwrites(tmp_path: Path) -> None:
    config = _config(tmp_path)

    write_tfvars(config)
    path = write_tfvars(config)

    assert path.is_file()
    written = json.loads(path.read_text(encoding="utf-8"))
    assert written["workload_resource_group_name"] == "rg-workload"
