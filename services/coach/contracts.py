"""Internal Lila-to-worker contract; never trust a browser snapshot."""

from typing import Annotated, Literal

from pydantic import BaseModel, ConfigDict, Field

Color = Literal["white", "black"]
SchemaVersion = Annotated[int, Field(ge=1, le=1)]
San = Annotated[str, Field(min_length=1, max_length=16)]
GameStatus = Literal[
    "created", "started", "aborted", "mate", "resign", "stalemate", "timeout",
    "draw", "outoftime", "cheat", "noStart", "unknownFinish", "insufficientMaterialClaim",
]


class Contract(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True, frozen=True)


class Snapshot(Contract):
    schemaVersion: SchemaVersion
    variant: Literal["standard"]
    initialFen: str = Field(min_length=15, max_length=120)
    sanHistory: list[San] = Field(max_length=2000)
    ply: int = Field(ge=0, le=2000)
    fen: str = Field(min_length=15, max_length=120)
    status: GameStatus
    winner: Color | None = None


class AnalyseMove(Contract):
    schemaVersion: SchemaVersion
    requestId: str = Field(pattern=r"^[a-zA-Z0-9_-]{1,80}$")
    kind: Literal["analyseMove"]
    positionRevision: str = Field(pattern=r"^[a-f0-9]{64}$")
    learnerColor: Color
    snapshot: Snapshot
    proactive: bool = False


class QuestionJob(Contract):
    schemaVersion: SchemaVersion
    requestId: str = Field(pattern=r"^[a-zA-Z0-9_-]{1,80}$")
    kind: Literal["hint", "explain", "threat"]
    positionRevision: str = Field(pattern=r"^[a-f0-9]{64}$")
    learnerColor: Color
    hintLevel: int = Field(ge=0, le=3)
    snapshot: Snapshot
