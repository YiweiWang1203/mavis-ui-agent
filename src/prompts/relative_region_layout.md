Plan a relative UI layout for the immutable source objects on the existing target canvas.
Use the full image and original spoken transcript to decide local groups, order and relative size.
The objects' IDs, types, text and actions cannot be changed. Never invent missing UI objects.
Do not output coordinates, HTML or a new canvas. Do not assume that the photograph boundary is the UI page.

Return only {"tree": NODE}. Every NODE has exactly:
{"id":string,"axis":"row"|"column"|null,"weight":positive_number,"quote":string|null,"children":[NODE,...]}.

- The root has id "page", axis row or column, weight 1, quote null.
- Every source object ID must occur exactly once in the entire tree. A leaf uses an existing source ID, axis null, quote null and children [].
- A branch may reuse an existing container/card/navigation/toolbar/header/footer/list/modal object ID. An image, avatar, text, button or input may NEVER become a container.
- A layout-only branch may instead use a new "layout_..." ID. It is only an invisible grouping operation, not a new detected UI object or drawn frame.
- Every non-root branch needs one unique verbatim substring of the supplied transcript as quote supporting that grouping. Do not paraphrase or correct ASR in the quote.
- Row lays out children left to right; column lays out children top to bottom. Each sibling's positive weight gives its share of the parent's width or height. Weights must be at most 100.
- Existing container objects should enclose their supported children rather than occupy an empty separate slot. Do not put unrelated objects inside a group just to make the tree complete.
- Preserve all observed source objects, including separators and passive areas. An unobserved element cannot be supplied from an assumed template.
- Use at most 20 layout-only branches and depth at most 12. Return a complete tree, without extra fields or explanation.

This is a testable proposed layout, not semantic proof. Source quotes will be checked against the original transcript and the grouping will be reviewed with the image.
