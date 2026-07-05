"""Handler pack loader.

Which handler packs a worker carries is deployment configuration, not code:

    HANDLER_MODULES=app.handlers.builtin,acme.billing_handlers

Each module registers its handlers with @handler on import. The default
includes the demo pack (lifecycle showcases) and the builtin pack (real
HTTP + email execution).
"""
import importlib
import logging
import os

from app.handler_sdk import REGISTRY, catalog, get_handler  # re-export

logger = logging.getLogger("scheduler.handlers")

DEFAULT_MODULES = "app.handlers.demo,app.handlers.builtin"

_loaded = False


def load_handler_packs() -> None:
    global _loaded
    if _loaded:
        return
    modules = os.environ.get("HANDLER_MODULES", DEFAULT_MODULES)
    for module_path in [m.strip() for m in modules.split(",") if m.strip()]:
        importlib.import_module(module_path)
        logger.info("Loaded handler pack %s", module_path)
    _loaded = True


load_handler_packs()
