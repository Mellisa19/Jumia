"""Socratic Shop — a Jumia-style storefront with an AI shopping assistant.

The storefront is a self-contained Flask blueprint mounted at ``/shop``. It
shares the application's brand system (see ``brand.css``) but keeps its own
templates, static assets, catalog and recommendation engine, so it can be
lifted into another Flask app without dragging the analytics dashboard along.
"""

from .blueprint import shop

# Imported last: route modules register their views on the blueprint above.
from . import routes  # noqa: E402,F401

__all__ = ["shop"]
