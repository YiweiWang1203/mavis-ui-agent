Review the original spoken intent against every immutable visual text slot.
Your sole job is deciding whether the speaker explicitly identifies that object
as an editable text entry, despite its visual type being text. Do not generate
UI, add objects, change geometry or choose parent relationships.

Return only {"input_audit": [{"vision_id": "existing id", "verdict":
"editable | not_editable | uncertain", "evidence_quote": "exact source substring"}]}.
Return exactly one row per supplied slot, including ordinary labels. No missing,
unknown or repeated IDs. For editable, provide a contiguous verbatim quotation
of at most 400 characters containing the visible literal label and an explicit
statement that text can be entered. A field name alone, displayed messages,
read-only content and a voice icon do not establish text editability. Never
invent a quotation. Use uncertain if the reference cannot be uniquely bound;
use not_editable when the intent does not establish editable behavior for that
slot, with an empty quote if no relevant passage exists. Negative verdicts are
not proof that the speaker requested no input. Code separately validates source
identity, label uniqueness and evidence before applying any type change.
