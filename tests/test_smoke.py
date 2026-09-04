"""Phase 0 checkpoint as a test.

Asserts the dependency set actually resolves on this interpreter. Python 3.14 is
bleeding edge and `pydantic-core` is a compiled extension, so "pip said ok" is not
the same as "it imports".
"""

import sys


def test_python_is_at_least_3_10():
    # the MCP SDK requires >= 3.10
    assert sys.version_info >= (3, 10), f"got {sys.version}"


def test_core_dependencies_import():
    import httpx
    import mcp
    import pydantic

    assert pydantic.VERSION.startswith("2."), f"expected pydantic v2, got {pydantic.VERSION}"
    assert httpx.__version__
    assert mcp is not None


def test_test_tooling_imports():
    import pytest_asyncio
    import respx

    assert pytest_asyncio is not None
    assert respx is not None
