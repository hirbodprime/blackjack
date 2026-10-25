"""Callback-data routing for inline keyboard handlers."""


class CallbackRouter:
    """Ordered callback-data routes; the first registered match wins."""

    def __init__(self):
        self._routes = []

    def on(self, *values):
        """Route callback data equal to any of ``values``."""
        values = frozenset(values)
        return self._register(lambda data: data in values)

    def on_prefix(self, *prefixes):
        """Route callback data starting with any of ``prefixes``."""
        return self._register(lambda data: data.startswith(prefixes))

    def _register(self, matches):
        def decorator(handler):
            self._routes.append((matches, handler))
            return handler

        return decorator

    def resolve(self, data):
        for matches, handler in self._routes:
            if matches(data):
                return handler
        return None
