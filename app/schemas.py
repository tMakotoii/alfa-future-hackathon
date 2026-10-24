from typing import Literal

from pydantic import BaseModel


class Factor(BaseModel):
    name: str
    direction: Literal["up", "down", "flat", "unknown"] = "unknown"


class NewsFact(BaseModel):
    text: str
    confirmed: bool = False


class Classification(BaseModel):
    is_business: bool = False
    topics: list[str] = []
    okved2: list[str] = []
    factors: list[Factor] = []
    regions: list[str] = []
    entities: list[str] = []
    facts: list[NewsFact] = []
    sentiment: Literal["negative", "neutral", "positive"] = "neutral"
