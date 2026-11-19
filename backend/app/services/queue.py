"""AWS SQS adapter. No credential fields or untrusted endpoint overrides."""

import json
import time
import uuid
from dataclasses import dataclass

from botocore.config import Config
from pydantic import BaseModel, ConfigDict, ValidationError
from sqlalchemy import select, update

from app.core.config import Settings
from app.models.entities import CheckJob, utcnow
from app.services.jobs import backoff


class JobMessage(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)
    schema_version: int
    job_id: str
    region: str

    @classmethod
    def decode(cls, body: str, expected_region: str) -> uuid.UUID:
        if len(body.encode("utf-8")) > 1024:
            raise ValueError("Oversized job envelope")
        item = cls.model_validate_json(body)
        if item.schema_version != 1 or item.region != expected_region:
            raise ValueError("Unsupported or misrouted job envelope")
        return uuid.UUID(item.job_id)


@dataclass(frozen=True)
class Delivery:
    receipt: str
    job_id: uuid.UUID | None
    attempts: int


class SQSQueue:
    def __init__(self, settings: Settings, region: str, *, client=None, long_poll: bool = False):
        if region not in settings.monitor_regions or region not in settings.sqs_queue_urls:
            raise ValueError("Queue region not configured")
        self.url = settings.sqs_queue_urls[region]
        self.region = region
        self.visibility = settings.job_lease_seconds
        if client is None:
            import boto3

            client = boto3.client(
                "sqs",
                region_name=region,
                config=Config(
                    connect_timeout=3,
                    read_timeout=25 if long_poll else 5,
                    ignore_configured_endpoint_urls=True,
                    retries={"mode": "standard", "total_max_attempts": 2},
                ),
            )
        self.client = client

    def publish(self, job_id: uuid.UUID) -> None:
        self.client.send_message(
            QueueUrl=self.url,
            MessageBody=json.dumps(
                {
                    "schema_version": 1,
                    "job_id": str(job_id),
                    "region": self.region,
                }
            ),
        )

    def receive(self) -> Delivery | None:
        messages = self.client.receive_message(
            QueueUrl=self.url,
            MaxNumberOfMessages=1,
            WaitTimeSeconds=20,
            VisibilityTimeout=self.visibility,
            MessageSystemAttributeNames=["ApproximateReceiveCount"],
        ).get("Messages", [])
        if not messages:
            return None
        message = messages[0]
        try:
            job_id = JobMessage.decode(message.get("Body", ""), self.region)
        except (ValueError, ValidationError):
            job_id = None  # Poison envelopes are never acknowledged; SQS redrives to DLQ.
        return Delivery(
            message["ReceiptHandle"],
            job_id,
            int(message.get("Attributes", {}).get("ApproximateReceiveCount", "1")),
        )

    def acknowledge(self, delivery: Delivery) -> None:
        self.client.delete_message(QueueUrl=self.url, ReceiptHandle=delivery.receipt)

    def retry(self, delivery: Delivery) -> None:
        self.client.change_message_visibility(
            QueueUrl=self.url,
            ReceiptHandle=delivery.receipt,
            VisibilityTimeout=backoff(delivery.attempts),
        )


def publish_outbox(session_factory, settings: Settings, *, queue_factory=SQSQueue) -> int:
    from datetime import timedelta

    count = 0
    with session_factory() as db:
        pending = list(
            db.execute(
                select(CheckJob.id, CheckJob.region)
                .where(
                    CheckJob.state == "PUBLISH_PENDING",
                    CheckJob.available_at <= utcnow(),
                )
                .order_by(CheckJob.scheduled_at)
                .limit(100)
            )
        )
    deadline = time.monotonic() + 30
    failed_regions: set[str] = set()
    for job_id, region in pending:
        if time.monotonic() >= deadline:
            break
        if region in failed_regions:
            continue
        try:
            queue_factory(settings, region).publish(job_id)
        except Exception:
            failed_regions.add(region)
            # Retain the outbox record on publish failure; don't silently drop work.
            # A bounded delay avoids a hot retry loop; lag is surfaced operationally.
            with session_factory() as db:
                db.execute(
                    update(CheckJob)
                    .where(CheckJob.id == job_id, CheckJob.state == "PUBLISH_PENDING")
                    .values(
                        last_error="PUBLISH_FAILED",
                        available_at=utcnow() + timedelta(seconds=30),
                    )
                )
                db.commit()
            continue
        with session_factory() as db:
            db.execute(
                update(CheckJob)
                .where(CheckJob.id == job_id, CheckJob.state == "PUBLISH_PENDING")
                .values(
                    state="QUEUED",
                    last_error=None,
                )
            )
            db.commit()
        count += 1
    return count
