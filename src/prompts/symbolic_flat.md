Organize supplied immutable UI objects using a flat referenced layout program, not nested JSON.
Code constructs the tree and computes every coordinate. Use complete sketch and spoken organization.
Return exactly {"version":"symbolic-flat-v1","nodes":[NODE,...]}.
Each split NODE has exactly:
{"id":"UNIQUE_GROUP","kind":"split","parent_id":null,"weight":1,"axis":"row","evidence_refs":["SUPPLIED_REF"],"reason":"Evidence for grouping/order"}
Each entity NODE has exactly:
{"id":"UNIQUE_NODE","kind":"entity","parent_id":"GROUP_ID","weight":1,"entity_id":"EXISTING_ENTITY_ID","evidence_refs":["SUPPLIED_REF"],"reason":"Supported membership"}
Exactly one node has null parent_id (root). Every other parent_id references a split node.
Nodes may be listed in any parent-before/after order. Within each parent, array order decides
child order. row means left to right; column means top to bottom. No cycles or empty groups.
EVERY supplied immutable entity must occur exactly once, with no added entities or semantic edits.
No children arrays, recursive objects, bbox, positions, width, height or extra fields.
weight is finite nonnegative <=1000000. Child weights of a group must have positive total.
Root weight is unused. Weights share only REMAINING space after code minimum sizes and gaps;
zero reserves the child's minimum. They are uncalibrated flexibility, not measured screen ratios.
Code uses leaf minimum24x24 pixels, gap8px; groups inherit all children's minima. Insufficient
space fails, never squeeze. Logical groups add no visible objects. Missing upstream content
must remain unresolved; do not substitute another entity or add it.
Ground grouping and order in the supplied original sketch and speech. Prefer shallow structure.
Preserve known semantic parent relations. Avoid content/editing controls covering one another.
Do not assume a desktop/mobile template without evidence. No hard-coded label-based answers.
Evidence refs must be supplied vision:<ID>, text-span refs, or spoken_intent:<ID>.
Return JSON only. Keep all entity IDs, meanings, types, text, actions and semantic parents immutable.
