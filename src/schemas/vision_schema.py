from typing import Literal, List, Optional
from pydantic import BaseModel, Field, ConfigDict, field_validator, model_validator


class BBox(BaseModel):
    model_config = ConfigDict(extra='forbid')
    x_min: float
    y_min: float
    x_max: float
    y_max: float

    @field_validator('*')
    def check_range(cls, v):
        if not (0.0 <= v <= 1.0):
            raise ValueError('bbox coordinates must be normalized between 0 and 1')
        return v

    @model_validator(mode='after')
    def check_order(self):
        if not (self.x_min < self.x_max and self.y_min < self.y_max):
            raise ValueError('bbox must satisfy x_min < x_max and y_min < y_max')
        return self


class CanvasInfo(BaseModel):
    model_config = ConfigDict(extra='forbid')
    width: int
    height: int
    orientation: Literal['portrait', 'landscape', 'square']

    @model_validator(mode='after')
    def check_dims(self):
        if self.width <= 0 or self.height <= 0:
            raise ValueError('canvas width and height must be > 0')
        return self


class UIElement(BaseModel):
    model_config = ConfigDict(extra='forbid')
    id: str
    type: Literal[
        'page', 'container', 'header', 'footer', 'navigation', 'text', 'button', 'input', 'textarea',
        'checkbox', 'radio', 'switch', 'icon', 'image', 'avatar', 'card', 'list', 'list_item', 'divider',
        'tab', 'badge', 'unknown', 'select', 'search_input', 'modal', 'toolbar'
    ]
    text: Optional[str] = None
    description: Optional[str] = None
    bbox: BBox
    parent_id: Optional[str] = None
    children_ids: List[str] = Field(default_factory=list)
    confidence: float = Field(0.5, ge=0.0, le=1.0)
    visible: bool = True
    source: Literal['vision', 'inferred'] = 'vision'


class VisionValidation(BaseModel):
    model_config = ConfigDict(extra='forbid')
    valid: bool
    completeness_score: float = Field(0.0, ge=0.0, le=1.0)
    element_count: int
    errors: List[str] = Field(default_factory=list)
    warnings: List[str] = Field(default_factory=list)


class VisionLayoutPayload(BaseModel):
    model_config = ConfigDict(extra='forbid')
    schema_version: Literal['1.0'] = '1.0'
    canvas: CanvasInfo
    elements: List[UIElement]
    reading_order: List[str] = Field(default_factory=list)


class VisionLayoutResult(VisionLayoutPayload):
    model_config = ConfigDict(extra='forbid')
    validation: VisionValidation

    @model_validator(mode='after')
    def ensure_consistency(self):
        # ensure element_count matches
        if self.validation.element_count != len(self.elements):
            raise ValueError('validation.element_count must equal number of elements')
        return self
