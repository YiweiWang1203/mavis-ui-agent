# Native control generation contract v1
These additional rules specialize the implementation of the supplied UI-State.
They do not add user requirements or change the element list or geometry.

1. Preserve each nonempty element `id` exactly once on its corresponding DOM control. For compound components put the id on the operative control, not an outer wrapper. Do not duplicate controls or ids. Keep noninteractive text and images noninteractive unless the contract explicitly says otherwise.
2. Implement `input`, `text_input`, `search_input`, and `search_bar` as editable native `<input>` controls; use `type="search"` for search types. Implement `textarea` as native `<textarea>`. Use native password/email/number inputs for `password_input`, `email_input`, and `number_input`. Preserve an explicitly supplied input type and placeholder. Do not infer new placeholder content from evaluation answers. An empty div, a drawn rectangle, a label, or an onclick handler is not an editable input.
3. Preserve native focus, typing, selection and editing. Input-related rpa_action bindings must not clear values, prevent typing, steal focus, or replace editing with a click notice. Do not disable or make inputs readonly unless explicitly requested. Keep labels separate from entered values.
4. Keep the supplied geometry, locale, content and specified behaviors. Do not add a backend, extra pages or invented requirements. For other controls follow the base prompt; this change targets native text entry only.
5. Before returning the complete HTML, check internally that each input-type element has its own native editable control with the same id. Return only HTML, no check report or Markdown.
