from __future__ import annotations

from typing import Any


class BridgeError(Exception):
    code = "BRIDGE_ERROR"
    retryable = False

    def __init__(self, message: str, *, details: dict[str, Any] | None = None, code: str | None = None):
        super().__init__(message)
        self.message = message
        self.details = details or {}
        if code:
            self.code = code

    def as_dict(self) -> dict[str, Any]:
        return {"ok": False, "error": {"code": self.code, "message": self.message, "retryable": self.retryable, "details": self.details}}


class NotFound(BridgeError):
    code = "NOT_FOUND"


class ValidationFailed(BridgeError):
    code = "VALIDATION_FAILED"


class InvalidTransition(BridgeError):
    code = "INVALID_TRANSITION"


class LimitExceeded(BridgeError):
    code = "LIMIT_EXCEEDED"


class PolicyDenied(BridgeError):
    code = "POLICY_DENIED"


class ApprovalError(BridgeError):
    code = "APPROVAL_REJECTED"


class Conflict(BridgeError):
    code = "CONFLICT"


class ResourcePressure(BridgeError):
    code = "RESOURCE_PRESSURE"
    retryable = True


class Unavailable(BridgeError):
    code = "CAPABILITY_UNAVAILABLE"
