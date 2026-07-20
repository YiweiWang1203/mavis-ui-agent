from typing import Literal, Optional

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator


class BBox(BaseModel):
    model_config = ConfigDict(extra="forbid")

    x_min: float
    y_min: float
    x_max: float
    y_max: float

    @field_validator("*")
    def check_range(cls, value: float) -> float:
        if not 0.0 <= value <= 1.0:
            raise ValueError("bbox coordinates must be normalized between 0 and 1")
        return value

    @model_validator(mode="after")
    def check_order(self):
        if not (self.x_min < self.x_max and self.y_min < self.y_max):
            raise ValueError("bbox must satisfy x_min < x_max and y_min < y_max")
        return self


class UIElementOntologyElement(BaseModel):
    model_config = ConfigDict(extra="forbid")

    id: str
    type: Literal["region", "text", "image", "icon", "divider"]
    bbox: BBox
    interactive: bool
    shape: Literal["rectangle", "rounded_rectangle", "circle", "line", "unknown"]
    text_content: Optional[str] = None
    parent_id: Optional[str] = None
    children_ids: list[str] = Field(default_factory=list)


class UIElementOntologyPayload(BaseModel):
    model_config = ConfigDict(extra="forbid")

    schema_version: Literal["ui_element_ontology_v0.1"] = "ui_element_ontology_v0.1"
    metadata: dict = Field(default_factory=dict)
    elements: list[UIElementOntologyElement]
