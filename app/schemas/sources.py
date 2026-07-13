from datetime import datetime
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field


class SourceCreateRequest(BaseModel):
    link: str = Field(min_length=1, max_length=256)


class SourceUpdateRequest(BaseModel):
    enabled: bool


class SourceResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    tg_peer_id: int | None
    username: str | None
    normalized_username: str | None
    title: str | None
    type: str
    is_public: bool
    enabled: bool
    access_status: str
    activity_score: int
    activity_status: str
    poll_mode: str
    participants_count: int | None
    last_seen_message_id: int
    last_checked_at: datetime | None
    pause_until: datetime | None
    created_at: datetime
    updated_at: datetime


class SourceListResponse(BaseModel):
    items: list[SourceResponse]
    total: int
    page: int
    size: int
