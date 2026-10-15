"""The storefront blueprint object.

Kept in its own module so both the package initialiser and the route modules
can import it without a circular import.
"""

from flask import Blueprint

shop = Blueprint(
    "shop",
    __name__,
    url_prefix="/shop",
    template_folder="templates",
    static_folder="static",
)
