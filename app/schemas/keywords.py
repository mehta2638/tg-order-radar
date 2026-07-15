from __future__ import annotations

from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field


class KeywordCreateRequest(BaseModel):
    phrase: str = Field(min_length=1, max_length=256)
    lang: str = Field(default="ru", min_length=2, max_length=8)
    weight: int = Field(default=1, ge=1, le=10)
    category: str = Field(default="general", min_length=1, max_length=64)
    is_regex: bool = False
    enabled: bool = True


class KeywordUpdateRequest(BaseModel):
    phrase: str | None = Field(default=None, min_length=1, max_length=256)
    lang: str | None = Field(default=None, min_length=2, max_length=8)
    weight: int | None = Field(default=None, ge=1, le=10)
    category: str | None = Field(default=None, min_length=1, max_length=64)
    is_regex: bool | None = None
    enabled: bool | None = None


class NegativeKeywordCreateRequest(BaseModel):
    phrase: str = Field(min_length=1, max_length=256)
    lang: str = Field(default="ru", min_length=2, max_length=8)
    weight: int = Field(default=1, ge=1, le=10)
    is_regex: bool = False
    enabled: bool = True


class NegativeKeywordUpdateRequest(BaseModel):
    phrase: str | None = Field(default=None, min_length=1, max_length=256)
    lang: str | None = Field(default=None, min_length=2, max_length=8)
    weight: int | None = Field(default=None, ge=1, le=10)
    is_regex: bool | None = None
    enabled: bool | None = None


class KeywordResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    phrase: str
    lang: str
    weight: int
    category: str
    is_regex: bool
    enabled: bool


class NegativeKeywordResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    phrase: str
    lang: str
    weight: int
    is_regex: bool
    enabled: bool


class KeywordListResponse(BaseModel):
    items: list[KeywordResponse]
    total: int


class NegativeKeywordListResponse(BaseModel):
    items: list[NegativeKeywordResponse]
    total: int
