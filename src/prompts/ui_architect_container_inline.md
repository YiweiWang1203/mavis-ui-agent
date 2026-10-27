
There is ONE authoritative node table: elements. Declare every visual object,
including containers, exactly once in elements with its exact vision_id.
Do not output a separate containers array. Local code derives its container
registry from your elements; do not duplicate an existing region under a u_ id.
Every relationships endpoint must refer to a node actually declared in elements.

When a container genuinely absent from Vision Elements is explicitly described
by User Intent, declare it in elements with vision_id:null, origin:"spoken", a
u_ id, and an exact contiguous evidence_quote naming its container type from User
Intent. Its bbox must be valid page-global target PIXELS, never normalized units.
Use empty text if no visible title. Do not invent a missing parent or claim a
visual counterpart. If a source does not support a container or relation, omit
that unsupported proposal. The existing source/identity checks still apply.
