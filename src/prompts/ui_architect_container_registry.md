
Use a typed container registry for this response. Return top-level containers:[]
as well as elements:[] and relationships:[]. Declare every container exactly ONCE
in containers, and all non-container controls in elements. Never repeat a container
in elements. Relationships may reference only IDs declared in these two arrays.
Do not emit an undeclared parent such as u_card; declare it with its source first.

Container declarations use the same element fields (id, vision_id, origin, type,
text, parent_id, spatial_info, rpa_action). A visual container retains its exact
vision_id and source geometry. A container genuinely absent from Vision Elements
may be added only when User Intent explicitly describes that region: use a u_ id,
vision_id:null, origin:"spoken", an exact contiguous evidence_quote from User
Intent naming its container type, and a valid page-global target bbox. Keep its
text empty if the region has no visible title. Do not invent a visual counterpart,
change an image into a container, or add a second copy of an existing region.

The local compiler materializes these declarations before checking relationships.
Source quotes are required, but lexical matches alone do not establish semantics;
when uncertain omit the unsupported relation instead of guessing a source.
