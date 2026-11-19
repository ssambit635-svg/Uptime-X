import json
import uuid
from datetime import timedelta

import boto3
import pytest
from botocore.stub import Stubber
from pydantic import ValidationError
from sqlalchemy import select, update

from app.core.config import Settings
from app.models.entities import CheckJob, utcnow
from app.services.jobs import enqueue_monitor
from app.services.queue import JobMessage, SQSQueue, publish_outbox


@pytest.fixture
def cloud_settings():
    regions = ["ap-south-1", "eu-west-1"]
    return Settings(
        queue_backend="sqs",
        database_url="postgresql+psycopg://test@db/uptimex",
        worker_region=regions[0],
        monitor_regions=regions,
        sqs_queue_urls={
            r: f"https://sqs.{r}.amazonaws.com/123456789012/uptimex-checks" for r in regions
        },
        _env_file=None,
    )


@pytest.fixture
def cloud_queue(cloud_settings):
    client = boto3.client(
        "sqs",
        region_name="ap-south-1",
        aws_access_key_id="testing",
        aws_secret_access_key="testing",
    )
    with Stubber(client) as stub:
        yield SQSQueue(cloud_settings, "ap-south-1", client=client), stub
        stub.assert_no_pending_responses()


def test_sqs_publish_receive_ack_contract(cloud_queue):
    queue, stub = cloud_queue
    job_id = uuid.uuid4()
    envelope = json.dumps({"schema_version": 1, "job_id": str(job_id), "region": "ap-south-1"})
    stub.add_response(
        "send_message", {"MessageId": "one"}, {"QueueUrl": queue.url, "MessageBody": envelope}
    )
    queue.publish(job_id)
    stub.add_response(
        "receive_message",
        {
            "Messages": [
                {
                    "ReceiptHandle": "receipt",
                    "Body": envelope,
                    "Attributes": {"ApproximateReceiveCount": "2"},
                }
            ]
        },
        {
            "QueueUrl": queue.url,
            "MaxNumberOfMessages": 1,
            "WaitTimeSeconds": 20,
            "VisibilityTimeout": 90,
            "MessageSystemAttributeNames": ["ApproximateReceiveCount"],
        },
    )
    delivery = queue.receive()
    assert delivery.job_id == job_id and delivery.attempts == 2
    stub.add_response("delete_message", {}, {"QueueUrl": queue.url, "ReceiptHandle": "receipt"})
    queue.acknowledge(delivery)


def test_poison_message_retries_without_delete_and_empty_queue_is_normal(cloud_queue, monkeypatch):
    queue, stub = cloud_queue
    expected = {
        "QueueUrl": queue.url,
        "MaxNumberOfMessages": 1,
        "WaitTimeSeconds": 20,
        "VisibilityTimeout": 90,
        "MessageSystemAttributeNames": ["ApproximateReceiveCount"],
    }
    stub.add_response(
        "receive_message", {"Messages": [{"ReceiptHandle": "bad", "Body": "not-json"}]}, expected
    )
    delivery = queue.receive()
    assert delivery.job_id is None
    monkeypatch.setattr("app.services.queue.backoff", lambda _: 42)
    stub.add_response(
        "change_message_visibility",
        {},
        {"QueueUrl": queue.url, "ReceiptHandle": "bad", "VisibilityTimeout": 42},
    )
    queue.retry(delivery)
    stub.add_response("receive_message", {}, expected)
    assert queue.receive() is None


@pytest.mark.parametrize(
    "payload",
    [
        "x" * 1025,
        "{}",
        '{"schema_version":true,"job_id":"x","region":"ap-south-1"}',
        json.dumps({"schema_version": 2, "job_id": str(uuid.uuid4()), "region": "ap-south-1"}),
        json.dumps({"schema_version": 1, "job_id": str(uuid.uuid4()), "region": "eu-west-1"}),
        json.dumps({"schema_version": 1, "job_id": "bad", "region": "ap-south-1"}),
        json.dumps(
            {
                "schema_version": 1,
                "job_id": str(uuid.uuid4()),
                "region": "ap-south-1",
                "target_url": "http://127.0.0.1",
            }
        ),
    ],
)
def test_envelopes_never_accept_urls_other_regions_or_unknown_versions(payload):
    with pytest.raises((ValueError, ValidationError)):
        JobMessage.decode(payload, "ap-south-1")


def test_transactional_outbox_is_retained_when_sqs_fails(
    db, monitor, cloud_settings, session_factory
):
    monitor.regions = cloud_settings.monitor_regions
    jobs = enqueue_monitor(db, monitor, cloud_settings, utcnow())
    db.commit()

    class Broken:
        def __init__(self, *_):
            pass

        def publish(self, _):
            raise OSError("unavailable")

    assert publish_outbox(session_factory, cloud_settings, queue_factory=Broken) == 0
    db.expire_all()
    for job in jobs:
        refreshed = db.get(CheckJob, job.id)
        assert refreshed.state == "PUBLISH_PENDING" and refreshed.last_error == "PUBLISH_FAILED"
        assert refreshed.available_at > utcnow()
        refreshed.available_at = utcnow() - timedelta(seconds=1)
    db.commit()
    sent = []

    class Working:
        def __init__(self, _, region):
            self.region = region

        def publish(self, job_id):
            sent.append((job_id, self.region))

    assert publish_outbox(session_factory, cloud_settings, queue_factory=Working) == 2
    assert {region for _, region in sent} == set(cloud_settings.monitor_regions)
    assert publish_outbox(session_factory, cloud_settings, queue_factory=Working) == 0


def test_send_before_mark_published_race_cannot_overwrite_completed_job(
    db, monitor, cloud_settings, session_factory
):
    monitor.regions = ["ap-south-1"]
    enqueue_monitor(db, monitor, cloud_settings, utcnow())
    db.commit()

    class FastConsumer:
        def __init__(self, *_):
            pass

        def publish(self, job_id):
            with session_factory() as other:
                other.execute(
                    update(CheckJob).where(CheckJob.id == job_id).values(state="COMPLETE")
                )
                other.commit()

    assert publish_outbox(session_factory, cloud_settings, queue_factory=FastConsumer) == 1
    db.expire_all()
    assert db.scalar(select(CheckJob.state)) == "COMPLETE"


@pytest.mark.parametrize(
    "changes",
    [
        {"monitor_regions": ["ap-south-1"]},
        {"worker_region": "ap-south-1"},
        {"queue_backend": "sqs"},
        {"monitor_regions": ["local", "local"]},
        {"preview_session_minutes": 121},
        {"max_job_attempts": 0},
        {"job_lease_seconds": 20},
    ],
)
def test_monitoring_settings_fail_closed(changes):
    with pytest.raises(ValidationError):
        Settings(**changes, _env_file=None)


def test_cloud_queue_refuses_unconfigured_region(cloud_settings):
    with pytest.raises(ValueError):
        SQSQueue(cloud_settings, "local")


def test_sdk_ignores_endpoint_overrides_and_bounds_aws_calls(cloud_settings, monkeypatch):
    from unittest.mock import Mock

    factory = Mock()
    monkeypatch.setattr(boto3, "client", factory)
    SQSQueue(cloud_settings, "ap-south-1")
    config = factory.call_args.kwargs["config"]
    assert config.ignore_configured_endpoint_urls is True
    assert config.connect_timeout == 3 and config.read_timeout == 5
    SQSQueue(cloud_settings, "ap-south-1", long_poll=True)
    assert factory.call_args.kwargs["config"].read_timeout == 25
