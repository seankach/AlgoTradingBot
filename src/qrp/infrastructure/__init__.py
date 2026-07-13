"""Infrastructure layer: concrete adapters for external systems.

Vendor SDKs (e.g. ``ib_async``) may be imported only within this layer, and only within
the specific adapter package that owns them (ADR-0002).
"""
