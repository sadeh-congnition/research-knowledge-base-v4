from __future__ import annotations

from collections.abc import Callable
import inspect

from django.utils.module_loading import import_string

SearchEngine = Callable[[str, int], list[dict]]


def _assert_search_engine_contract(search_engine: Callable[..., object]) -> None:
    if not callable(search_engine):
        raise TypeError("Search engine path must resolve to a callable.")

    signature = inspect.signature(search_engine)
    parameters = list(signature.parameters.values())
    if len(parameters) != 2:
        raise TypeError(
            "Search engine callable must accept exactly two parameters: "
            "query and n_results."
        )

    query_param, n_results_param = parameters
    if query_param.name != "query" or n_results_param.name != "n_results":
        raise TypeError(
            "Search engine callable parameters must be named 'query' and 'n_results'."
        )

    valid_kinds = {
        inspect.Parameter.POSITIONAL_ONLY,
        inspect.Parameter.POSITIONAL_OR_KEYWORD,
        inspect.Parameter.KEYWORD_ONLY,
    }
    if query_param.kind not in valid_kinds or n_results_param.kind not in valid_kinds:
        raise TypeError(
            "Search engine callable parameters must accept named arguments."
        )


def load_search_engine(package_path: str) -> SearchEngine:
    search_engine = import_string(package_path)
    _assert_search_engine_contract(search_engine)
    return search_engine


def validate_search_engine(package_path: str) -> None:
    load_search_engine(package_path)
