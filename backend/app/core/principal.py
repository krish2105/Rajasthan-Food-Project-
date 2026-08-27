"""The authenticated caller, and the JWT claims that carry their scope.

One dataclass is the single source of truth for "who is asking", and it feeds
two consumers that must never disagree:

  * `app/db/session.py`, which stamps these claims onto the Postgres session so
    RLS policies can enforce scope in the database;
  * `app/storage/`, which passes the same signed token to Supabase Storage.

Section 10's rule -- never trust a client-side role check -- is satisfied
because the claims come from a signature-verified token and are then enforced by
Postgres, not by the route handler.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from enum import StrEnum


class Role(StrEnum):
    FIELD_WORKER = "field_worker"
    DISTRICT_OFFICIAL = "district_official"
    STATE_ADMIN = "state_admin"


@dataclass(frozen=True, slots=True)
class Principal:
    worker_id: str
    role: Role
    awc_code: str | None
    district: str | None
    name: str = ""
    token: str = ""

    def claims(self) -> dict[str, str | None]:
        """The claim set stamped onto the Postgres session and signed into JWTs.

        `role: authenticated` is Supabase's own Postgres role name -- distinct
        from `app_role`, which is our three-role model from Section 10. Keeping
        them separate avoids a collision that would either break Supabase's
        conventions or silently widen access.
        """
        return {
            "sub": self.worker_id,
            "role": "authenticated",
            "app_role": self.role.value,
            "awc_code": self.awc_code,
            "district": self.district,
        }

    def claims_json(self) -> str:
        return json.dumps(self.claims(), separators=(",", ":"))
