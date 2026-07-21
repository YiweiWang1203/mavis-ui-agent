# UI Element Annotation Spec v0.1

This document defines the manual annotation convention for building visual-layer ground truth from diagrams.net / drawio files.

## Element Types

The visual element ontology has only five element types:

- `region`
- `text`
- `image`
- `icon`
- `divider`

`interactive` is an element property, not an element type.

## Recommended drawio Label Format

Use semicolon-separated key/value labels in the drawio cell value:

```text
type=region;interactive=true;shape=rectangle
```

Text example:

```text
type=text;text_content=用户名;interactive=false
```

Supported `shape` values:

- `rectangle`
- `rounded_rectangle`
- `circle`
- `line`
- `unknown`

## Chinese Fallback Labels

Chinese fallback labels are supported only for compatibility with older manual annotations. They are not the long-term authoring convention.

Examples:

- `可交互商品卡片`
- `头像`
- `ID信息`
- `分割线`

## Current drawio Style Fallbacks

These style fallbacks exist to support current manual drawio samples. Prefer the standard key/value label format for new annotations.

- Green stroke `strokeColor=#00CC00`: `text`
- Red circular cell `strokeColor=#FF0000` plus `ellipse`: `icon`, `shape=circle`, `interactive=true`
- Red circular cell with `头像`: `image`, `shape=circle`
- Blue stroke `strokeColor=#0000FF`: `image` fallback
- Blue stroke with `卡片`, `区域`, `内容展示`, `商品卡片`, or `可交互商品卡片`: keyword fallback wins, so the element remains `region`
- Large blank phone/screen background rectangles are treated as canvas cells, not UI elements
- Cells outside the detected canvas are treated as legends or annotation examples and are not parsed
- `style=group` cells are drawio structure only and are not parsed as UI elements

## OCR Preservation Principle

The Vision layer does not assign `semantic_role`, but it must preserve OCR and handwritten text as completely as possible.

For `type=text` elements, `text_content` is a core field and should not be ignored during annotation, parsing, prediction export, or evaluation.

OCR confidence may be used only as a diagnostic signal or as a weighting feature in later stages. It must not be used to delete or suppress `text_content` in the visual-layer ontology.

When OCR confidence is low, keep the original recognized text. The later Semantic Layer can decide whether and how to use it.

User voice intent may be incomplete, while handwritten or on-screen text is often the key source of page intent. OCR preservation is therefore a required v0.1 principle for visual-layer ground truth.

Future evaluators should add text preservation and OCR similarity metrics in addition to geometry, type, interactivity, and shape metrics.

## Out Of Scope

Manual visual annotations must not label business semantics:

- `semantic_role`
- `page_kind`
- `rpa_action`
- `component_role`

This stage creates visual-layer ground truth only. Business semantic interpretation belongs to a later Semantic Layer.
