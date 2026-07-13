"""Broker-neutral domain layer: models and the ``MarketDataSource``/``Broker`` boundary.

Nothing here imports a vendor SDK. See ADR-0002 for the abstraction boundary and
ADR-0004 for bar timestamp semantics.
"""

from qrp.domain.enums import WhatToShow
from qrp.domain.models import Bar
from qrp.domain.protocols import Broker, MarketDataSource

__all__ = ["Bar", "Broker", "MarketDataSource", "WhatToShow"]
