"""Horizontal geometry and per-render state for the layout engine.

`Region` is the only place nesting arithmetic lives: a container narrows or
divides its own region and hands the result to its children, so no primitive
needs to know how deeply it is nested.
"""

from collections.abc import Callable
from dataclasses import dataclass

from PIL import ImageDraw

from generators.exporters.geometry import BoxRecorder


@dataclass(frozen=True)
class Region:
    """A horizontal slice of the page available to a block.

    Attributes:
        x: Absolute left edge in pixels.
        width: Usable content width in pixels.
    """

    x: int
    width: int

    @property
    def right(self) -> int:
        """Absolute right edge in pixels."""
        return self.x + self.width

    def indent(self, left: int, right: int = 0) -> "Region":
        """Return a narrowed region inset from this one.

        Args:
            left: Pixels to inset from the left edge.
            right: Pixels to inset from the right edge.

        Returns:
            A new Region shifted right by `left` and narrowed by `left + right`.

        Raises:
            ValueError: If the insets consume the whole region.
        """
        width = self.width - left - right
        if width < 1:
            msg = (
                f"Region.indent({left}, {right}) leaves width {width} from {self.width}. "
                f"Remediation: reduce the container's padding."
            )
            raise ValueError(msg)
        return Region(x=self.x + left, width=width)

    def divide(self, n: int, gap: int) -> list["Region"]:
        """Split this region into `n` equal columns separated by `gap` px.

        Args:
            n: Number of columns; must be at least 1.
            gap: Pixels between adjacent columns.

        Returns:
            `n` Regions, left to right.

        Raises:
            ValueError: If `n` < 1, or the gaps leave no usable column width.
        """
        if n < 1:
            msg = f"Region.divide needs n >= 1, got {n}. Remediation: pass a positive column count."
            raise ValueError(msg)
        total_gap = gap * (n - 1)
        column = (self.width - total_gap) // n
        if column < 1:
            msg = (
                f"Region.divide({n}, gap={gap}) leaves column width {column} "
                f"from {self.width}. Remediation: reduce the gap or the column count."
            )
            raise ValueError(msg)
        return [Region(x=self.x + i * (column + gap), width=column) for i in range(n)]


@dataclass
class RenderContext:
    """Everything a primitive needs besides its own block dict and the y-cursor.

    Attributes:
        draw: The PIL drawing surface.
        entry: The ground-truth entry being rendered.
        layout: The resolved layout dict.
        layout_id: Layout id, used in diagnostics.
        layout_path: Path to the layout YAML, used in diagnostics.
        region: The horizontal slice this block may draw into.
        recorder: Optional draw-time bounding-box capture.
        render_children: The walker, injected by the engine so containers can
            render nested blocks without importing the engine — which would be
            a circular import, since the engine's dispatch table imports them.
    """

    draw: ImageDraw.ImageDraw
    entry: dict
    layout: dict
    layout_id: str
    layout_path: str
    region: Region
    recorder: BoxRecorder | None = None
    render_children: "Callable[[list, RenderContext, int], int] | None" = None

    def within(self, region: Region) -> "RenderContext":
        """Return a copy of this context scoped to a different region.

        Args:
            region: The child region.

        Returns:
            A new RenderContext sharing all state but the region.
        """
        return RenderContext(
            draw=self.draw,
            entry=self.entry,
            layout=self.layout,
            layout_id=self.layout_id,
            layout_path=self.layout_path,
            region=region,
            recorder=self.recorder,
            render_children=self.render_children,
        )
