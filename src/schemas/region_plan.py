"""Single structural definition for planning, repair and validation."""
from typing import Literal
from pydantic import BaseModel, ConfigDict, Field


class Contract(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)


class Viewport(Contract):
    width: int = Field(gt=0)
    height: int = Field(gt=0)


class PageMeta(Contract):
    viewport: Viewport


class Requirement(Contract):
    sources: list[str] = Field(min_length=1)
    intent: str = Field(min_length=1)
    certainty: Literal["explicit", "inferred", "conflicting"]
    status: Literal["bound", "unknown"]
    scope: str | None
    targets: list[str]
    references: list[str]


class Element(Contract):
    id: str = Field(min_length=1)
    type: str = Field(min_length=1)
    origin: Literal["speech", "vision", "both", "request"]
    text: str = ""
    rpa_action: str = ""
    placeholder: str | None = None
    input_type: str | None = None
    items: list[dict] = Field(default_factory=list)


class Placement(Contract):
    id: str = Field(min_length=1)
    slot: Literal["bottom"] | None = None
    cross_align: Literal["start", "end", "center", "stretch"] | None = None
    grow: bool = False


class Leaf(Placement):
    pass


class Region(Placement):
    axis: Literal["row", "column"]
    children: list["Region | Leaf"] = Field(min_length=1)


class RegionPlan(Contract):
    page_meta: PageMeta
    requirements: list[Requirement]
    elements: list[Element] = Field(min_length=1)
    region_tree: Region
