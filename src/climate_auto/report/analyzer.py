"""Chart image analyzers for report generation."""

from abc import ABC, abstractmethod
from pathlib import Path

from climate_auto.report.models import ChartImage


class BaseAnalyzer(ABC):
    """Abstract base class for chart image analyzers."""

    @abstractmethod
    async def analyze(self, chart: ChartImage, image_path: Path) -> str:
        """Analyze a chart image and return descriptive text.

        Args:
            chart: Chart metadata.
            image_path: Absolute path to the image file.

        Returns:
            Analysis text for the chart.
        """

    async def analyze_batch(
        self,
        charts: list[tuple[ChartImage, Path]],
        section_context: str = "",
    ) -> dict[str, str]:
        """Batch analyze multiple charts. Default: per-chart calls.

        Args:
            charts: List of (chart metadata, image absolute path) tuples.
            section_context: Optional section title for context.

        Returns:
            Mapping of chart relative_path to analysis text.
        """
        results: dict[str, str] = {}
        for chart, image_path in charts:
            results[chart.relative_path] = await self.analyze(chart, image_path)
        return results


class PlaceholderAnalyzer(BaseAnalyzer):
    """Placeholder analyzer that returns empty analysis (template shows '待分析')."""

    async def analyze(self, chart: ChartImage, image_path: Path) -> str:
        """Return empty string; template will display placeholder text.

        Args:
            chart: Chart metadata.
            image_path: Absolute path to the image file.

        Returns:
            Empty string.
        """
        return ""
