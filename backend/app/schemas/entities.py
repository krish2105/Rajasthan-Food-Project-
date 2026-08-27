"""Request and response models for the Phase 1 API surface."""

from __future__ import annotations

import uuid
from datetime import date, datetime

from pydantic import BaseModel, ConfigDict, Field

from app.core.principal import Role


class AWCOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    awc_code: str
    name_en: str
    name_hi: str
    centre_type: str
    district: str
    district_hi: str
    block: str
    block_hi: str
    latitude: float | None = None
    longitude: float | None = None
    is_active: bool


class BeneficiaryOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    poshan_tracker_id: str | None
    awc_code: str
    district: str
    block: str
    name: str
    dob: date
    gender: str
    age_months: int | None = None


class GrowthEntryOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    beneficiary_id: uuid.UUID
    recorded_at: date
    height_cm: float
    weight_kg: float
    age_months: int
    standard_used: str
    waz_score: float | None
    haz_score: float | None
    whz_score: float | None
    baz_score: float | None
    bmi: float | None
    classification: str
    classification_detail: dict
    data_quality_flags: list[str] = []


class GrowthEntryIn(BaseModel):
    """A new measurement. z-scores are never accepted from the client -- they
    are computed server-side by app/growth/assess.py (Section 6.4)."""

    beneficiary_id: uuid.UUID
    recorded_at: date | None = Field(default=None, description="Defaults to today when omitted")
    height_cm: float = Field(gt=0, lt=250)
    weight_kg: float = Field(gt=0, lt=150)


class GrowthEntryCreated(BaseModel):
    entry: GrowthEntryOut
    #: Explains any index WHO does not define at this age, e.g. why whz is NULL
    #: for a nine-year-old. Surfaced so the field worker sees a reason, not a gap.
    notes: list[str] = Field(default_factory=list)


class PlateCaptureOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    beneficiary_id: uuid.UUID
    awc_code: str
    meal_type: str
    captured_at: datetime
    sync_status: str
    photo_url: str
    #: Short-lived signed URL. Absent when Storage is not configured.
    photo_signed_url: str | None = None
    ai_food_items: list | dict | None = None
    ai_calories: float | None = None
    ai_protein_g: float | None = None
    ai_carbs_g: float | None = None
    ai_model_version: str | None = None


class MenuItemOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    code: str
    name_en: str
    name_hi: str
    category: str
    ifct_code: str | None


class MeOut(BaseModel):
    worker_id: str
    name: str
    role: Role
    awc_code: str | None
    district: str | None
    scope_description_en: str
    scope_description_hi: str


class DevTokenIn(BaseModel):
    phone: str


class TokenOut(BaseModel):
    access_token: str
    token_type: str = "bearer"
    expires_in: int
    role: Role
    awc_code: str | None
    district: str | None
