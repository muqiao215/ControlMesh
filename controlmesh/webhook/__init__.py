"""Webhook system: HTTP ingress for external event triggers."""

from controlmesh.webhook.manager import WebhookManager
from controlmesh.webhook.models import WebhookEntry, WebhookResult

__all__ = ["WebhookEntry", "WebhookManager", "WebhookResult"]
