from typing import Any, Dict, List, Optional

from pydantic import BaseModel, Field


class AgentLLMProfile(BaseModel):
    id: str
    label: str
    provider: str = "openai_compatible"
    base_url: str = ""
    model: str = ""
    api_key: str = ""
    egress_confirmed: bool = False
    temperature: float = Field(default=0.2, ge=0, le=2)
    max_tokens: int = Field(default=4096, ge=1, le=200000)
    timeout_seconds: int = Field(default=60, ge=5, le=600)
    enabled: bool = True
    extra_headers: Dict[str, str] = Field(default_factory=dict)


class LLMProfileConfig(BaseModel):
    """Configuration for validating LLM profile without saving."""
    provider: str
    base_url: str
    model: str
    api_key: str
    egress_confirmed: bool = False
    enabled: bool = True


class RuntimeBaseUrlSecurity(BaseModel):
    status: str = "NOT_EVALUATED"
    allowed: bool = False
    strict_mode_required: bool = False
    message: str = ""
    code: str = ""
    host: str = ""
    reason: str = ""
    allowed_hosts: List[str] = Field(default_factory=list)
    confirmed_at: Optional[str] = None
    confirmed_by: Optional[str] = None


class AgentLLMProfilePublic(BaseModel):
    id: str
    label: str
    provider: str
    base_url: str
    model: str
    configured: bool = False
    auth_available: bool = False
    api_key_set: bool
    api_key_mask: Optional[str] = None
    egress_confirmed: bool = False
    egress_policy_status: str = "NOT_EVALUATED"
    egress_policy_message: str = ""
    health_status: str = "INCOMPLETE"
    health_warnings: List[str] = Field(default_factory=list)
    base_url_security: RuntimeBaseUrlSecurity = Field(default_factory=RuntimeBaseUrlSecurity)
    last_call_success: Optional[bool] = None
    last_error: str = ""
    last_checked_at: str = ""
    last_test_status: str = ""
    last_test_message: str = ""
    last_live_call_at: str = ""
    last_latency_ms: Optional[int] = None
    last_usage: Dict[str, Any] = Field(default_factory=dict)
    temperature: float
    max_tokens: int
    timeout_seconds: int
    enabled: bool
    extra_headers: Dict[str, str] = Field(default_factory=dict)


class MarketDataProfile(BaseModel):
    id: str
    label: str
    provider: str = "generic_rest"
    base_url: str = ""
    quote_path: str = ""
    symbol_query_param: str = "symbol"
    auth_mode: str = "query"
    api_key: str = ""
    egress_confirmed: bool = False
    api_key_header: str = "Authorization"
    api_key_query_param: str = "apikey"
    timeout_seconds: int = Field(default=15, ge=3, le=120)
    enabled: bool = False
    extra_headers: Dict[str, str] = Field(default_factory=dict)
    extra_query_params: Dict[str, str] = Field(default_factory=dict)
    price_path: str = ""
    name_path: str = ""
    change_percent_path: str = ""
    volume_path: str = ""
    timestamp_path: str = ""


class MarketDataProfilePublic(BaseModel):
    id: str
    label: str
    provider: str
    base_url: str
    quote_path: str
    symbol_query_param: str
    auth_mode: str
    api_key_set: bool
    api_key_mask: Optional[str] = None
    egress_confirmed: bool = False
    egress_policy_status: str = "NOT_EVALUATED"
    egress_policy_message: str = ""
    health_status: str = "INCOMPLETE"
    health_warnings: List[str] = Field(default_factory=list)
    base_url_security: RuntimeBaseUrlSecurity = Field(default_factory=RuntimeBaseUrlSecurity)
    last_call_success: Optional[bool] = None
    last_error: str = ""
    last_checked_at: str = ""
    last_test_status: str = ""
    last_test_message: str = ""
    last_live_call_at: str = ""
    last_latency_ms: Optional[int] = None
    api_key_header: str
    api_key_query_param: str
    timeout_seconds: int
    enabled: bool
    extra_headers: Dict[str, str] = Field(default_factory=dict)
    extra_query_params: Dict[str, str] = Field(default_factory=dict)
    price_path: str
    name_path: str
    change_percent_path: str
    volume_path: str
    timestamp_path: str


class AgentDeployment(BaseModel):
    id: str
    name: str
    stage: str
    role: str
    system_prompt_ref: str
    prompt_file: str
    node_type: str
    tool_scope: List[str] = Field(default_factory=list)
    next_nodes: List[str] = Field(default_factory=list)
    run_modes: List[str] = Field(default_factory=list)
    allow_trade_action: bool = False
    final_decision_cap: str = "NO_DIRECT_TRADE_ACTION"
    enabled: bool = True
    status: str = "READY"
    llm_profile_id: str = ""
    prompt_source: str = ""
    prompt_hash: str = ""
    system_prompt_excerpt: str = ""
    framework_version: str = "10.2"


class AgentRuntimeSummary(BaseModel):
    workflowName: str = ""
    workflowVersion: str = ""
    runMode: str = ""
    enabledNodeOrder: List[str] = Field(default_factory=list)
    toolBudget: Dict[str, Any] = Field(default_factory=dict)
    agents: List[Dict[str, Any]] = Field(default_factory=list)
    model: str = ""
    provider: str = ""
    profileId: str = ""


class AgentRuntimeConfig(BaseModel):
    default_llm_profile_id: str = ""
    default_market_data_profile_id: str = ""
    max_parallel_agents: int = 5
    llm_profiles: List[Any] = Field(default_factory=list)
    market_data_profiles: List[Any] = Field(default_factory=list)
    agents: List[Any] = Field(default_factory=list)
    updated_at: str = ""


class UpdateAgentLLMRequest(BaseModel):
    llm_profile_id: Optional[str] = None
    enabled: Optional[bool] = None


class UpsertLLMProfileRequest(BaseModel):
    label: Optional[str] = None
    provider: Optional[str] = None
    base_url: Optional[str] = None
    model: Optional[str] = None
    api_key: Optional[str] = None
    clear_api_key: bool = False
    egress_confirmed: Optional[bool] = None
    temperature: Optional[float] = Field(default=None, ge=0, le=2)
    max_tokens: Optional[int] = Field(default=None, ge=1, le=200000)
    timeout_seconds: Optional[int] = Field(default=None, ge=5, le=600)
    enabled: Optional[bool] = None
    extra_headers: Optional[Dict[str, str]] = None


class UpdateRuntimeSettingsRequest(BaseModel):
    default_llm_profile_id: Optional[str] = None
    default_market_data_profile_id: Optional[str] = None
    max_parallel_agents: Optional[int] = None
    apply_default_to_all_agents: bool = False


class UpsertMarketDataProfileRequest(BaseModel):
    label: Optional[str] = None
    provider: Optional[str] = None
    base_url: Optional[str] = None
    quote_path: Optional[str] = None
    symbol_query_param: Optional[str] = None
    auth_mode: Optional[str] = None
    api_key: Optional[str] = None
    clear_api_key: bool = False
    egress_confirmed: Optional[bool] = None
    api_key_header: Optional[str] = None
    api_key_query_param: Optional[str] = None
    timeout_seconds: Optional[int] = Field(default=None, ge=3, le=120)
    enabled: Optional[bool] = None
    extra_headers: Optional[Dict[str, str]] = None
    extra_query_params: Optional[Dict[str, str]] = None
    price_path: Optional[str] = None
    name_path: Optional[str] = None
    change_percent_path: Optional[str] = None
    volume_path: Optional[str] = None
    timestamp_path: Optional[str] = None


class MarketDataAdapterConfig(BaseModel):
    adapter_id: str
    provider: str = ""
    label: str = ""
    enabled: bool = True
    priority: int = Field(default=10, ge=1, le=99)
    timeout_seconds: int = Field(default=15, ge=3, le=120)
    requires_token: bool = False
    capabilities: List[str] = Field(default_factory=list)
    note: str = ""


class UpdateMarketDataAdapterConfigRequest(BaseModel):
    enabled: Optional[bool] = None
    priority: Optional[int] = Field(default=None, ge=1, le=99)
    timeout_seconds: Optional[int] = Field(default=None, ge=3, le=120)


class LLMConfigTestResult(BaseModel):
    profile_id: str
    status: str
    message: str
    details: Optional[Dict[str, Any]] = None


class MarketDataConfigTestResult(BaseModel):
    profile_id: str
    status: str
    message: str = ""
    details: Optional[Dict[str, Any]] = None


class DataSourceItem(BaseModel):
    key: str
    name: str
    tushare_api: str = ""
    enabled: bool = False
    description: str = ""
    required_credits: Optional[int] = None
    tier_label: Optional[str] = None
    provider_apis: Dict[str, str] = Field(default_factory=dict)
    providers: List[str] = Field(default_factory=list)


class DataSourcesConfig(BaseModel):
    tushare_token: str = ""
    tushare_token_set: bool = False
    tushare_token_mask: Optional[str] = None
    sources: List[DataSourceItem] = Field(default_factory=list)


class UpdateDataSourcesRequest(BaseModel):
    tushare_token: Optional[str] = None
    sources: Optional[List[DataSourceItem]] = None


class LLMConfigTestRequest(BaseModel):
    profile_id: str
    live_call: bool = False
    test_prompt: Optional[str] = None


class MarketDataConfigTestRequest(BaseModel):
    profile_id: str
    live_call: bool = False
    symbol: Optional[str] = None
