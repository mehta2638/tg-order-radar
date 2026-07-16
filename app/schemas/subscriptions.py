from __future__ import annotations

from datetime import datetime
from decimal import Decimal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator


class SubscriptionBase(BaseModel):
    name: str = Field(min_length=1, max_length=128)
    enabled: bool = True
    min_relevance_score: int | None = Field(default=None, ge=0, le=100)
    project_types: list[str] = Field(default_factory=list)
    budget_min: Decimal | None = None
    budget_max: Decimal | None = None
    currencies: list[str] = Field(default_factory=list)
    source_ids: list[UUID] = Field(default_factory=list)
    positive_keywords: list[str] = Field(default_factory=list)
    negative_keywords: list[str] = Field(default_factory=list)
    quiet_hours_start: str | None = Field(default=None, pattern=r"^([01]\d|2[0-3]):[0-5]\d$")
    quiet_hours_end: str | None = Field(default=None, pattern=r"^([01]\d|2[0-3]):[0-5]\d$")
    timezone: str = Field(default="UTC", min_length=1, max_length=64)
    freshness_days: int | None = Field(default=None, ge=1, le=365)
    max_notifications_per_period: int | None = Field(default=None, ge=1, le=10000)
    rate_limit_period_minutes: int = Field(default=60, ge=1, le=10080)
    similar_cooldown_minutes: int | None = Field(default=None, ge=1, le=10080)

    @model_validator(mode="after")
    def validate_ranges(self) -> SubscriptionBase:
        if self.budget_min is not None and self.budget_max is not None:
            if self.budget_min > self.budget_max:
                raise ValueError("budget_min must be <= budget_max")
        if (self.quiet_hours_start is None) != (self.quiet_hours_end is None):
            raise ValueError("quiet_hours_start and quiet_hours_end must be set together")
        return self


class SubscriptionCreateRequest(SubscriptionBase):
    user_id: UUID | None = None
    tg_chat_id: int | None = None


class SubscriptionUpdateRequest(BaseModel):
    name: str | None = Field(default=None, min_length=1, max_length=128)
    enabled: bool | None = None
    min_relevance_score: int | None = Field(default=None, ge=0, le=100)
    project_types: list[str] | None = None
    budget_min: Decimal | None = None
    budget_max: Decimal | None = None
    currencies: list[str] | None = None
    source_ids: list[UUID] | None = None
    positive_keywords: list[str] | None = None
    negative_keywords: list[str] | None = None
    quiet_hours_start: str | None = Field(default=None, pattern=r"^([01]\d|2[0-3]):[0-5]\d$")
    quiet_hours_end: str | None = Field(default=None, pattern=r"^([01]\d|2[0-3]):[0-5]\d$")
    timezone: str | None = Field(default=None, min_length=1, max_length=64)
    freshness_days: int | None = Field(default=None, ge=1, le=365)
    max_notifications_per_period: int | None = Field(default=None, ge=1, le=10000)
    rate_limit_period_minutes: int | None = Field(default=None, ge=1, le=10080)
    similar_cooldown_minutes: int | None = Field(default=None, ge=1, le=10080)

    @model_validator(mode="after")
    def validate_ranges(self) -> SubscriptionUpdateRequest:
        if self.budget_min is not None and self.budget_max is not None:
            if self.budget_min > self.budget_max:
                raise ValueError("budget_min must be <= budget_max")
        if (self.quiet_hours_start is not None or self.quiet_hours_end is not None) and (
            self.quiet_hours_start is None or self.quiet_hours_end is None
        ):
            # Partial quiet-hours update is invalid.
            if (
                "quiet_hours_start" in self.model_fields_set
                or "quiet_hours_end" in self.model_fields_set
            ):
                if bool(self.quiet_hours_start) != bool(self.quiet_hours_end):
                    raise ValueError("quiet_hours_start and quiet_hours_end must be set together")
        return self


class SubscriptionResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    user_id: UUID
    name: str
    enabled: bool
    min_relevance_score: int | None
    project_types: list[str]
    budget_min: Decimal | None
    budget_max: Decimal | None
    currencies: list[str]
    source_ids: list[str]
    positive_keywords: list[str]
    negative_keywords: list[str]
    quiet_hours_start: str | None
    quiet_hours_end: str | None
    timezone: str
    freshness_days: int | None
    max_notifications_per_period: int | None
    rate_limit_period_minutes: int
    similar_cooldown_minutes: int | None
    created_at: datetime
    updated_at: datetime

    @field_validator("source_ids", mode="before")
    @classmethod
    def coerce_source_ids(cls, value: object) -> list[str]:
        if value is None:
            return []
        if not isinstance(value, list):
            return [str(value)]
        return [str(item) for item in value]

    @field_validator(
        "project_types",
        "currencies",
        "positive_keywords",
        "negative_keywords",
        mode="before",
    )
    @classmethod
    def coerce_lists(cls, value: object) -> list[str]:
        if value is None:
            return []
        if not isinstance(value, list):
            return [str(value)]
        return [str(item) for item in value]


class SubscriptionListResponse(BaseModel):
    items: list[SubscriptionResponse]
    total: int
