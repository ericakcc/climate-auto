"""Chart image analyzers for report generation."""

from abc import ABC, abstractmethod
from pathlib import Path

from climate_auto.report.models import ChartImage


class BaseAnalyzer(ABC):
    """Abstract base class for chart image analyzers."""

    @abstractmethod
    async def extract_info(self, chart: ChartImage, image_path: Path) -> str:
        """Extract concise, precise information from a single chart image.

        Args:
            chart: Chart metadata.
            image_path: Absolute path to the image file.

        Returns:
            Extracted information text for the chart.
        """

    @abstractmethod
    async def synthesize(
        self,
        extractions: dict[str, str],
        charts: list[tuple[ChartImage, Path]],
    ) -> str:
        """Synthesize all extracted chart information into a unified diagnosis.

        Args:
            extractions: Mapping of chart relative_path to extracted info text.
            charts: All chart metadata with paths for reference.

        Returns:
            Unified weather diagnosis text.
        """

    async def extract_all(
        self,
        charts: list[tuple[ChartImage, Path]],
    ) -> dict[str, str]:
        """Extract information from all charts. Default: sequential per-chart calls.

        Args:
            charts: List of (chart metadata, image absolute path) tuples.

        Returns:
            Mapping of chart relative_path to extracted info text.
        """
        results: dict[str, str] = {}
        for chart, image_path in charts:
            info = await self.extract_info(chart, image_path)
            if info:
                results[chart.relative_path] = info
        return results


class PlaceholderAnalyzer(BaseAnalyzer):
    """Placeholder analyzer that returns empty analysis."""

    async def extract_info(self, chart: ChartImage, image_path: Path) -> str:
        """Return empty string.

        Args:
            chart: Chart metadata.
            image_path: Absolute path to the image file.

        Returns:
            Empty string.
        """
        return ""

    async def synthesize(
        self,
        extractions: dict[str, str],
        charts: list[tuple[ChartImage, Path]],
    ) -> str:
        """Return empty string.

        Args:
            extractions: Mapping of chart relative_path to extracted info.
            charts: All chart metadata with paths.

        Returns:
            Empty string.
        """
        return ""
