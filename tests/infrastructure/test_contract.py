"""Offline configuration contracts; these do NOT replace terraform validate/plan."""

from pathlib import Path

import hcl2
import pytest

ROOT = Path(__file__).resolve().parents[2] / "infrastructure" / "terraform"
OPTIONS = hcl2.SerializationOptions(strip_string_quotes=True)


def load(relative):
    with (ROOT / relative).open() as file:
        return hcl2.load(file, serialization_options=OPTIONS)


def blocks(document, kind):
    return {
        (resource, name): attributes
        for item in document.get(kind, [])
        for resource, definitions in item.items()
        for name, attributes in definitions.items()
    }


@pytest.mark.parametrize("path", sorted(ROOT.rglob("*.tf")))
def test_all_terraform_files_parse_as_hcl(path):
    assert load(path.relative_to(ROOT))


def test_queue_visibility_retention_encryption_and_bounded_regional_redrive():
    resources = blocks(load("queues.tf"), "resource")
    env = {
        entry["name"]: entry["value"]
        for entry in load("modules/worker_pool/main.tf")["locals"][0]["environment"]
    }
    assert env["QUEUE_BACKEND"] == "sqs"
    for region in ("primary", "secondary"):
        queue = resources[("aws_sqs_queue", region)]
        dlq = resources[("aws_sqs_queue", f"{region}_dlq")]
        assert queue["visibility_timeout_seconds"] >= int(env["JOB_LEASE_SECONDS"])
        assert queue["sqs_managed_sse_enabled"] and dlq["sqs_managed_sse_enabled"]
        assert queue["message_retention_seconds"] < dlq["message_retention_seconds"] <= 1209600
        assert "maxReceiveCount = 5" in queue["redrive_policy"]
        assert (
            "byQueue"
            in resources[("aws_sqs_queue_redrive_allow_policy", region)]["redrive_allow_policy"]
        )


def test_api_has_no_queue_permissions_and_workers_cannot_change_aws_resources():
    api = blocks(load("api.tf"), "resource")
    assert ("aws_iam_role_policy", "api") not in api
    worker = blocks(load("modules/worker_pool/main.tf"), "resource")
    policy = worker[("aws_iam_role_policy", "consume")]["policy"]
    assert "sqs:ReceiveMessage" in policy and "sqs:DeleteMessage" in policy
    assert "sqs:SendMessage" not in policy and 'Action = "*"' not in policy
    assert "ecs:" not in policy and "iam:" not in policy
    assert (
        worker[("aws_ecs_service", "worker")]["network_configuration"][0]["assign_public_ip"]
        is False
    )


def test_private_http_deny_rules_are_separate_from_inline_acl_rules():
    network = blocks(load("modules/network/main.tf"), "resource")
    acl = network[("aws_network_acl", "private")]
    assert "ingress" not in acl and "egress" not in acl
    deny = network[("aws_network_acl_rule", "no_private_http")]
    assert deny["rule_action"] == "deny" and deny["egress"] is True
    assert network[("aws_subnet", "private")]["map_public_ip_on_launch"] is False


def test_provider_is_locked_and_ci_does_not_authenticate_or_deploy_to_aws():
    lock = load(".terraform.lock.hcl")
    provider = lock["provider"][0]["registry.terraform.io/hashicorp/aws"]
    assert provider["version"].startswith("6.") and provider["constraints"] == "~> 6.0"
    assert any(value.startswith("h1:") for value in provider["hashes"])
    assert any(value.startswith("zh:") for value in provider["hashes"])
    workflow = (ROOT.parents[1] / ".github" / "workflows" / "ci.yml").read_text()
    assert "terraform init -backend=false -input=false -lockfile=readonly" in workflow
    assert "terraform apply" not in workflow and "configure-aws-credentials" not in workflow
    assert "id-token: write" not in workflow


def test_staging_disabled_by_default_and_database_is_private_encrypted_backed_up():
    variables = {
        name: value for item in load("versions.tf")["variable"] for name, value in item.items()
    }
    assert variables["enable_services"]["default"] is False
    assert variables["app_image"]["default"] == ""
    assert 'var.environment == "staging"' in variables["environment"]["validation"][0]["condition"]
    database = blocks(load("network.tf"), "resource")[("aws_db_instance", "database")]
    assert database["publicly_accessible"] is False
    assert database["storage_encrypted"] and database["manage_master_user_password"]
    assert database["deletion_protection"] and database["skip_final_snapshot"] is False
    assert database["backup_retention_period"] >= 7
