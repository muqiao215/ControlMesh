"""Project-level exception hierarchy."""


class ControlMeshError(Exception):
    """Base for all controlmesh exceptions."""


class CLIError(ControlMeshError):
    """CLI execution failed."""


class WorkspaceError(ControlMeshError):
    """Workspace initialization or access failed."""


class SessionError(ControlMeshError):
    """Session persistence or lifecycle failed."""


class CronError(ControlMeshError):
    """Cron job scheduling or execution failed."""


class StreamError(ControlMeshError):
    """Streaming output failed."""


class SecurityError(ControlMeshError):
    """Security violation detected."""


class PathValidationError(SecurityError):
    """File path failed validation."""


class WebhookError(ControlMeshError):
    """Webhook server or dispatch failed."""
