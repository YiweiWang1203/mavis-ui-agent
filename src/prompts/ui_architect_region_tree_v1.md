Return one JSON planning proposal. No extra model call. Supplied vision is an immutable observation: preserve every original ID exactly once, and do not merge independent objects with equal text. Code saves the original separately and computes field differences and exact quote locations. Supply only the plan and reasons/quotes, never a second observation or before/after ledger.

Single canonical region_contract schema (version region-tree-v2):
{
  "page_meta":{"viewport":{"width":1440,"height":900}},
  "elements":[
    {"id":"original_visual_id","type":"original type","text":"original text",
     "parent":"region_page","order":0,"relation_status":"unknown",
     "sizing":{"basis_px":"auto","grow":0,"shrink":1,"cross":"intrinsic"},
     "evidence":[{"source":"model_inference","reason":"membership unresolved; root is mechanical storage only"}]}
  ],
  "region_contract":{
    "version":"region-tree-v2","root_id":"region_page",
    "regions":[
      {"id":"region_page","kind":"semantic_region","parent":null,
       "evidence":[{"source":"system_root"}],
       "layout":{"direction":"column","gap_px":0,"padding_px":0,"overflow":"visible"}}
    ]
  }
}
This illustrates schema, not a layout template, object count or new requirement. Choose the requested TARGET viewport, not photo dimensions. Business objects occur only in elements; organizational regions occur only in flat regions. Never emit region_contract.objects, nested objects/children/member lists, parent_id, or another mapping. Put parent/order/sizing/evidence on each element itself. Keep original business properties, text, source references and spatial_info unless an explicitly sourced refinement is necessary. Organizational regions add no visible label, action or business object.

Every non-root node explicitly includes parent (existing region ID), unique nonnegative sibling order, sizing, relation_status (proposed or unknown), and evidence. Add only necessary semantic regions, every region reaching the sole root without cycles. Each region has kind=semantic_region and layout. For unknown membership use parent=root, relation_status=unknown and a model_inference reason; mechanical reachability does not confirm page membership. Code will not guess missing parents, flatten nested regions or repair invalid trees.

Sizing: basis_px="auto" or nonnegative target pixels, grow/shrink nonnegative, cross=stretch or intrinsic. Layout: direction=row/column, overflow=visible/auto/hidden, gap_px/padding_px nonnegative. order is left-to-right in a row, top-to-bottom in a column. Use content/ratios/flex, not equal partitions or absolute source-photo boxes. Explicit containment, edge, order and size requirements outrank inferred centers. Original boxes remain soft evidence. Scroll/clipping/fixing not explicitly required are engineering proposals; avoid hiding critical controls.

Evidence is a nonempty list, using only:
- {"source":"asr","quote":"exact unique substring of provided User Intent"}
- {"source":"sketch","visual_ids":["original ID"],"reason":"observed relationship and uncertainty"}
- {"source":"model_inference","reason":"proposed interpretation and uncertainty"}
Do not supply start/end or offsets: code computes positions only for unique exact quotes. Missing/repeated quotes are not usable source positions. Report uncertainty rather than inventing text or certainty. Quote existence proves location, not semantic support; User Intent is the supplied combined source, not an independently isolated ASR channel. Vision ID or box overlap does not prove containment. Relations remain proposals, never human-confirmed.

Only when changing type, text, action, actions or rpa_action for an existing ID, add on that SAME element:
"change_sources":{"changed_field_name":{"quote":"exact unique original substring","reason":"why this supports this refinement; what remains uncertain"}}
One quote/reason per substantive changed field; no unchanged-field declarations, before/after values, repeated ID/field table or observation_change_evidence. Code computes those facts from untouched vision. Changes without unique source are rejected. A quoted plan is still semantically unconfirmed. Preserve all nonempty observed text/actions: deletion/clearing is rejected even with a quote. Adding nonempty behavior requires its own source; do not invent business features. Missing actions -> [] means no additional action plan, not no interaction required, and needs no change_sources entry. Do not clear existing nonempty action/actions/rpa_action.

New spoken-only objects require unique u_ IDs, origin=spoken, source_evidence=[{"source":"asr","quote":"exact unique substring"}], plus explicit parent/order/sizing/evidence/relation_status. They cannot replace an existing object. Do not add backend capabilities, case-specific chat/product rules or another Agent. Preserve uncertainty; do not invent feedback success.