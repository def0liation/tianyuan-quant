from __future__ import annotations

from ...models.market_data import AdapterCapability
from .authorized_rest_adapter import AuthorizedRestMarketDataAdapter


class TongdaxinAdapter(AuthorizedRestMarketDataAdapter):
    adapter_id = "tongdaxin"
    provider_name = "tongdaxin"
    label = "通达信"
    priority = 3
    env_prefix = "TONGDAXIN"
    requires_token = True
    capabilities = {
        AdapterCapability.REALTIME_QUOTE,
        AdapterCapability.HISTORICAL_QUOTE,
        AdapterCapability.FUNDAMENTALS,
        AdapterCapability.MONEYFLOW,
        AdapterCapability.CHIP,
        AdapterCapability.INDEX,
    }
    timeout_seconds = 12
