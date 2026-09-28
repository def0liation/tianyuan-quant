from collections.abc import Callable, Iterable, MutableMapping
from typing import Any

RunStore = MutableMapping[str, dict[str, Any]]
RunStoreProvider = Callable[[], RunStore]
LegacyRunPredicate = Callable[[str, dict[str, Any] | None], bool]

_run_store_provider: RunStoreProvider | None = None
_legacy_run_predicate: LegacyRunPredicate | None = None


def bind_analysis_run_store(
    provider: RunStoreProvider,
    legacy_run_predicate: LegacyRunPredicate,
) -> None:
    global _run_store_provider, _legacy_run_predicate
    _run_store_provider = provider
    _legacy_run_predicate = legacy_run_predicate


def run_store() -> RunStore:
    if _run_store_provider is None:
        return {}
    return _run_store_provider()


def is_legacy_run(run_id: str, run: dict[str, Any] | None) -> bool:
    if _legacy_run_predicate is None:
        return False
    return _legacy_run_predicate(run_id, run)


def get_run(run_id: str, *, include_legacy: bool = False) -> dict[str, Any] | None:
    run = run_store().get(run_id)
    if not isinstance(run, dict):
        return None
    if not include_legacy and is_legacy_run(run_id, run):
        return None
    return run


def iter_runs(*, include_legacy: bool = False) -> Iterable[tuple[str, dict[str, Any]]]:
    for run_id, run in list(run_store().items()):
        if not isinstance(run, dict):
            continue
        normalized_run_id = str(run_id)
        if not include_legacy and is_legacy_run(normalized_run_id, run):
            continue
        yield normalized_run_id, run


def contains_run(run_id: str, *, include_legacy: bool = False) -> bool:
    return get_run(run_id, include_legacy=include_legacy) is not None
