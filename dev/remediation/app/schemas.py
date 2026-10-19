"""Interface (a) : signal d'anomalie envoyé par le détecteur (voir doc/ARCHITECTURE.md)."""
from datetime import datetime
from typing import Literal

from pydantic import BaseModel, Field, field_validator


class Suspect(BaseModel):
    kind: Literal["ip"]
    value: str = Field(max_length=64)
    share: float = Field(ge=0, le=1)


class Signal(BaseModel):
    schema_version: str
    anomaly_id: str = Field(min_length=1, max_length=64)   # rend l'appel idempotent
    detected_at: datetime
    detector: dict
    score: float = Field(ge=0, le=1)
    consecutive_windows: int = Field(ge=1)
    # Liste fermée : le moteur ne redémarre jamais autre chose que ces services, quoi que dise le signal.
    target_service: Literal["api", "auth", "frontend"]
    window_s: int = Field(ge=1)
    features: dict[str, float] = {}
    suspects: list[Suspect] = Field(default=[], max_length=50)

    @field_validator("schema_version")
    @classmethod
    def major_version(cls, v: str) -> str:
        if not v.startswith("1."):
            raise ValueError("schema_version non supportée (attendu 1.x)")
        return v
