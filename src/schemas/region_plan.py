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
    scope: str | None = Field(description="Existing region ID, including page, or null. Never the literal word region unless that ID exists.")
    targets: list[str] = Field(description="Existing tree IDs; nonempty for bound, empty for unknown.")
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
    asset_content: str | None = None


class Action(Contract):
    sources: list[str] = Field(min_length=1)
    target: str = Field(description="Top-level elements inventory ID. For repeated rows target the list control, describing row behavior in trigger; nested items IDs alone are not action targets.")
    trigger: str = Field(min_length=1)
    state_change: str = Field(min_length=1)
    observable_result: str = Field(min_length=1)


class Placement(Contract):
    id: str = Field(min_length=1)
    slot: Literal["bottom"] | None = Field(default=None, description="Only on the final child of a column parent. Never on the root or under a row.")
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
    actions: list[Action]
