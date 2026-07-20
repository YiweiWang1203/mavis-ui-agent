import pytest
from pydantic import ValidationError

from src.schemas.ui_element_ontology import (
    BBox,
    UIElementOntologyElement,
    UIElementOntologyPayload,
)


def test_ui_element_ontology_payload_accepts_valid_element():
    payload = UIElementOntologyPayload(
        elements=[
            UIElementOntologyElement(
                id="e1",
                type="text",
                bbox=BBox(x_min=0.1, y_min=0.2, x_max=0.8, y_max=0.3),
                interactive=False,
                shape="rectangle",
                text_content="Title",
            )
        ]
    )

    assert payload.schema_version == "ui_element_ontology_v0.1"
    assert payload.elements[0].children_ids == []


def test_ui_element_ontology_rejects_invalid_type():
    with pytest.raises(ValidationError):
        UIElementOntologyElement(
            id="e1",
            type="button",
            bbox={"x_min": 0.1, "y_min": 0.1, "x_max": 0.2, "y_max": 0.2},
            interactive=True,
            shape="rounded_rectangle",
        )


def test_ui_element_ontology_rejects_invalid_bbox():
    with pytest.raises(ValidationError):
        UIElementOntologyElement(
            id="e1",
            type="region",
            bbox={"x_min": 0.5, "y_min": 0.1, "x_max": 0.2, "y_max": 0.2},
            interactive=False,
            shape="rectangle",
        )
