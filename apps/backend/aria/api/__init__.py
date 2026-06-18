"""aria.api — V2 HTTP surface (Week 33). Localhost pilot only."""
from aria.api.v2 import build_v2_app, reset_components, v2_router

__all__ = ["v2_router", "build_v2_app", "reset_components"]
