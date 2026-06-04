"""Tests for the web API pydantic schemas."""

import pytest
from pydantic import ValidationError

from climate_auto.web.schemas import (
    ExtractionBlock,
    RunRequest,
    SaveExtractionsRequest,
)


def test_run_request_defaults_numeric_false_and_sources_none() -> None:
    req = RunRequest(date="2026-06-04")

    assert req.numeric is False
    assert req.sources is None


def test_run_request_requires_date() -> None:
    with pytest.raises(ValidationError):
        RunRequest()


def test_extraction_block_image_url_optional() -> None:
    block = ExtractionBlock(key="numeric/foo", text="bar", exists=False)

    assert block.image_url is None


def test_save_request_preserves_block_order() -> None:
    req = SaveExtractionsRequest(
        date="2026-06-04",
        blocks=[
            ExtractionBlock(key="a.gif", text="A", exists=True),
            ExtractionBlock(key="b.gif", text="B", exists=True),
        ],
    )

    assert [b.key for b in req.blocks] == ["a.gif", "b.gif"]
