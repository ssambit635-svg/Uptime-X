"""CloudWatch Embedded Metric Format over stdout; no sensitive request contents."""

import json
import logging
import time

logger = logging.getLogger("uptimex.monitoring")


def metric(
    role: str, region: str, name: str, value: float = 1, *, unit: str = "Count", **safe_fields
) -> None:
    logger.info(
        json.dumps(
            {
                "_aws": {
                    "Timestamp": int(time.time() * 1000),
                    "CloudWatchMetrics": [
                        {
                            "Namespace": "UptimeX/Monitoring",
                            "Dimensions": [["Role", "Region"]],
                            "Metrics": [{"Name": name, "Unit": unit}],
                        }
                    ],
                },
                "Role": role,
                "Region": region,
                name: value,
                **safe_fields,
            }
        )
    )
