Keep each visual element's source type unchanged in elements. The source type
can be an observation error: explicitly spoken editable behavior may differ.
Add top-level semantic_input_overrides: a list of objects with exactly
vision_id, target_type (only "input"), evidence_quote. Propose only for a unique
existing visual text object explicitly identified as an editable text entry by
the original User Intent. Quote an exact contiguous substring (<=400 chars)
containing its literal visible label and an explicit statement that text can
be entered. A mention of a label, input icon, a message display, or a read-only
field is insufficient. Do not infer missing identities or rename labels. Never
change elements types directly to implement these proposals. Empty list when
unsupported. Code will independently check and compile these proposals before
rendering; evidence extraction is not ground truth. No extra nodes or geometry
edits for this field. Do not use evaluation labels or read/create HTML.
