from __future__ import annotations

from pathlib import Path

from conftest import make_config

from labctl.state import (
    DEPLOYMENT_STATE_FILENAME,
    DeploymentState,
    ScenarioState,
    load_deployment_state,
    load_scenario_state,
    save_deployment_state,
    save_scenario_state,
)


def test_load_deployment_state_returns_defaults_when_missing(tmp_path: Path) -> None:
    config = make_config(tmp_path)

    state = load_deployment_state(config)

    assert state == DeploymentState()


def test_save_and_load_deployment_state_roundtrips(tmp_path: Path) -> None:
    config = make_config(tmp_path)
    original = DeploymentState(
        image_tag="abc123-def456",
        image_ref="myregistry.azurecr.io/pulsemart:abc123-def456",
        baseline_revision_suffix="baseline-abc123-def456",
        baseline_revision_name="ca-pulsemart-demo--baseline-abc123-def456",
        deployed_at="2026-01-01T00:00:00+00:00",
        git_commit="abc123def456",
        terraform_outputs={"container_app_name": "ca-pulsemart-demo"},
    )

    path = save_deployment_state(config, original)
    loaded = load_deployment_state(config)

    assert path == tmp_path / ".state" / DEPLOYMENT_STATE_FILENAME
    assert loaded == original


def test_load_deployment_state_ignores_corrupt_json(tmp_path: Path) -> None:
    config = make_config(tmp_path)
    state_dir = tmp_path / ".state"
    state_dir.mkdir(parents=True)
    (state_dir / DEPLOYMENT_STATE_FILENAME).write_text("not valid json", encoding="utf-8")

    assert load_deployment_state(config) == DeploymentState()


def test_load_deployment_state_ignores_unknown_fields(tmp_path: Path) -> None:
    config = make_config(tmp_path)
    state_dir = tmp_path / ".state"
    state_dir.mkdir(parents=True)
    (state_dir / DEPLOYMENT_STATE_FILENAME).write_text(
        '{"image_tag": "x", "totally_unknown_field": "y"}', encoding="utf-8"
    )

    state = load_deployment_state(config)

    assert state.image_tag == "x"


def test_load_scenario_state_returns_defaults_with_slug_when_missing(tmp_path: Path) -> None:
    config = make_config(tmp_path)

    state = load_scenario_state(config, "bad-deployment")

    assert state == ScenarioState(slug="bad-deployment")


def test_save_and_load_scenario_state_roundtrips(tmp_path: Path) -> None:
    config = make_config(tmp_path)
    original = ScenarioState(
        slug="bad-deployment",
        fault_active=True,
        fault_revision_name="ca-pulsemart-demo--fault-abc-123",
        baseline_revision_name="ca-pulsemart-demo--baseline-abc",
        triggered_at="2026-01-01T00:00:00+00:00",
        run_count=2,
    )

    path = save_scenario_state(config, original)
    loaded = load_scenario_state(config, "bad-deployment")

    assert path == tmp_path / ".state" / "scenario-bad-deployment.json"
    assert loaded == original


def test_scenario_states_for_different_slugs_do_not_collide(tmp_path: Path) -> None:
    config = make_config(tmp_path)
    save_scenario_state(config, ScenarioState(slug="a", fault_active=True))
    save_scenario_state(config, ScenarioState(slug="b", fault_active=False))

    assert load_scenario_state(config, "a").fault_active is True
    assert load_scenario_state(config, "b").fault_active is False


def test_load_scenario_state_ignores_corrupt_json(tmp_path: Path) -> None:
    config = make_config(tmp_path)
    state_dir = tmp_path / ".state"
    state_dir.mkdir(parents=True)
    (state_dir / "scenario-bad-deployment.json").write_text("not valid json", encoding="utf-8")

    assert load_scenario_state(config, "bad-deployment") == ScenarioState(slug="bad-deployment")
