from __future__ import annotations

from ...models.market_data import AdapterCapability
from .authorized_rest_adapter import AuthorizedRestMarketDataAdapter


class IFindAdapter(AuthorizedRestMarketDataAdapter):
    adapter_id = "ifind"
    provider_name = "ifind"
    label = "同花顺 iFinD"
    priority = 4
    env_prefix = "IFIND"
    requires_token = True
    capabilities = {
        AdapterCapability.REALTIME_QUOTE,
        AdapterCapability.HISTORICAL_QUOTE,
        AdapterCapability.FUNDAMENTALS,
        AdapterCapability.ANNOUNCEMENTS,
        AdapterCapability.MONEYFLOW,
        AdapterCapability.CHIP,
        AdapterCapability.MACRO,
        AdapterCapability.INDEX,
        AdapterCapability.BOND,
        AdapterCapability.FUTURES,
    }
    timeout_seconds = 15
