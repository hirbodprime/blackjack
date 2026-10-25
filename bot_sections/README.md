# Bot handler modules

Ordinary Python modules with explicit imports. Importing the package runs
`django.setup()`, so handlers can import models at module level.

`application.py` builds the `telegram.ext.Application` and registers handlers.
Registration order matters: within a handler group only the first matching
handler runs, and the unfiltered `handle_menu_callback` receives every callback
not claimed earlier and dispatches internally.

Keep game rules in `game/services/` and keep these modules to parsing updates,
calling services, and rendering replies.
