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

## Out Of Scope

Manual visual annotations must not label business semantics:

- `semantic_role`
- `page_kind`
- `rpa_action`
- `component_role`

This stage creates visual-layer ground truth only. Business semantic interpretation belongs to a later Semantic Layer.
