Bind each supplied original requirement to its unique visual object, if supported.
Requirements are exact source sentences owned by code, never generated quotes.
Use the complete original intent for context. A visual type may be mistaken:
a text object can represent an explicitly spoken editable field. Do not confuse
displayed chat messages, avatars or buttons with the field used to enter text.
Only choose an existing eligible visual ID; use null if no unique correspondence
is supported. Do not create an object or infer a missing region.

Return exactly {"bindings": [{"requirement_id": "supplied id", "vision_id":
"supplied visual id or null"}]}. Every supplied requirement must appear exactly
once. No extra fields, quotations, labels, geometry, types or parents. Existing
input objects must still be bound if they match: their type is not an improvement.
Source identity, literal unique label and type eligibility are checked separately
by code; your choice is a hypothesis requiring semantic review, not ground truth.
