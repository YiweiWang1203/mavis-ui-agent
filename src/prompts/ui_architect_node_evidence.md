# One authoritative containment declaration per child node
Return page_meta and elements, with each source object exactly once. Do not
output a separate relationships ledger. Each element has parent_id and
parent_evidence_quote. A page-level node has parent_id:null and no parent quote.
For every supported containment relation, set the child's parent_id to the
actually declared container ID and put its exact contiguous User Intent quote
in that SAME child's parent_evidence_quote. Local code compiles the ledger.

The quote must include the child's literal text label and the parent's label or
container description in the original language. Include the pronoun antecedent
when necessary, at most 400 characters. An area containing controls, or a
navigation area whose left/center/right items are named, can support containment.
Below/next to alone does not. Do not rewrite ASR or invent source quotations.
If an alias prevents a literal quote, retain an explicit uncertain parent proposal
only when supported by context, but leave its quote null: it will be unresolved,
not automatically accepted. If the parent itself is uncertain leave parent_id
null. Include all supported explicit relations; do not omit a named containment
requirement merely to avoid validation. Parent types must be containers, nav_bar
is a navigation_bar alias, and every referenced ID must exist. Never turn a
button/image into a container to satisfy a relation. No cycles or duplicated
source objects. Geometry and source validation remain local responsibilities.
