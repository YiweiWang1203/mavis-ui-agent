Organize the supplied immutable objects into a sourced symbolic layout tree. Do not write coordinates.
Use the complete sketch and spoken organization, not the photograph's paper/background positions.
You decide grouping, order and relative flexibility; code owns all geometric coordinates.
Return exactly {"version":"symbolic-flow-v1","root":NODE}. JSON only, no extra fields.

NODE is exactly one of:
{"kind":"split","id":"UNIQUE_GROUP","axis":"row","weights":[1,2],"children":[NODE,NODE],
 "evidence_refs":["SUPPLIED_REF"],"reason":"Evidence for grouping/order and uncertainty"}
or
{"kind":"entity","entity_id":"EXISTING_ID","evidence_refs":["SUPPLIED_REF"],"reason":"Supported membership"}.
axis=row places children left to right, column places them top to bottom.
weights must be finite nonnegative numbers, one per child, with positive total. These are
UNCALIBRATED relative shares of remaining space after child minimum sizes and gaps, not measured
screen ratios. Zero requests only the child's minimum along that split axis. Code gives every
leaf at least 24x24 pixels and sibling gaps of 8px; groups inherit their children's minima.
Do not create unnecessary deep groups. Logical groups do not add visible content or UI objects.

Every immutable entity must appear in exactly one leaf, including passive content and controls.
Do not add/omit/rename/retype/reparent objects or change actions. Do not substitute an existing
object for content missing upstream. Preserve actual meaning; missing semantics remain unresolved.
Choose actual supported major groups and order from the sketch and speech. A content object and
editing controls should not cover each other. A wide content area should have more flexible space
than a small control group when supported. Avoid assuming a desktop/mobile template without evidence.
Known semantic parent relationships remain immutable and must be compatible with grouping; code
reports conflicts rather than squeezing children or changing parents. No invented containers.

Use supplied text-span refs, vision:<observed ID>, or spoken_intent:<spoken-only entity ID>.
Never fabricate quotations or offsets. A reference is evidence to review, not proof of accuracy.
Group IDs cannot start with leaf__. All IDs must be unique. No bbox, width, height, positions,
requirements acceptance tables, entity declarations or prose outside JSON.
