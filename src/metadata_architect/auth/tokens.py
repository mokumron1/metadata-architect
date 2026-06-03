"""
JWT one-time tokens for SME review portal links.

Each Verification Pulse email embeds a signed token containing:
  - workflow_id  — the specific workflow the SME must act on
  - sub          — the SME's email address
  - exp          — set to the SLA deadline so the link auto-expires

The token is validated on every workflow action endpoint so that:
  1. Only the designated SME can approve/edit/reject
  2. The link stops working after the SLA window closes
  3. No separate session store is needed
"""

import uuid
from dataclasses import dataclass
from datetime import datetime, timezone

from jose import JWTError, jwt

from metadata_architect.config import ALLOWED_JWT_ALGORITHMS, get_settings


class TokenError(Exception):
    pass


@dataclass
class SMETokenPayload:
    workflow_id: uuid.UUID
    sme_email: str
    expires_at: datetime


class TokenService:
    def __init__(self) -> None:
        settings = get_settings()
        self._secret = settings.jwt_secret_key
        algorithm = settings.jwt_algorithm
        # Guard against algorithm-confusion attacks: reject any algorithm not in
        # the explicit allowlist (e.g. "none", RS*, ES*).
        if algorithm not in ALLOWED_JWT_ALGORITHMS:
            raise ValueError(
                f"JWT_ALGORITHM '{algorithm}' is not in the allowed set "
                f"{ALLOWED_JWT_ALGORITHMS}. Update your configuration."
            )
        self._algorithm = algorithm

    def create_review_token(
        self,
        workflow_id: uuid.UUID,
        sme_email: str,
        sla_deadline: datetime,
    ) -> str:
        """
        Create a signed JWT for the SME review link.
        Expires at the SLA deadline so the link self-destructs on breach.
        """
        payload = {
            "sub": sme_email,
            "workflow_id": str(workflow_id),
            "exp": sla_deadline,
            "iat": datetime.now(timezone.utc),
            "type": "sme_review",
        }
        return jwt.encode(payload, self._secret, algorithm=self._algorithm)

    def verify_review_token(self, token: str) -> SMETokenPayload:
        """
        Decode and validate a review token.
        Raises TokenError on expiry, tampering, or wrong type.

        The algorithms list is a fixed allowlist — it is NOT driven by the
        token header, preventing algorithm-confusion / "alg:none" attacks.
        """
        try:
            data = jwt.decode(
                token,
                self._secret,
                algorithms=list(ALLOWED_JWT_ALGORITHMS),  # fixed allowlist, not from token
            )
        except JWTError as exc:
            raise TokenError(f"Invalid or expired review token: {exc}") from exc

        if data.get("type") != "sme_review":
            raise TokenError("Token is not an SME review token.")

        return SMETokenPayload(
            workflow_id=uuid.UUID(data["workflow_id"]),
            sme_email=data["sub"],
            expires_at=datetime.fromtimestamp(data["exp"], tz=timezone.utc),
        )

    def create_api_key_header(self) -> dict[str, str]:
        """Returns the auth header dict for internal service-to-service calls."""
        settings = get_settings()
        return {"X-API-Key": settings.gate_api_key}
