"""Receipt renderer — a thin adapter over the declarative layout engine.

Visual DNA per receipt format now lives in config/layouts/receipts.yml as a
`body:` tree of layout primitives; this module only sets up the page, delegates
to the DSL, and crops the result. The values a receipt draws that exist nowhere
in ground truth — POS time/register/staff, the receipt number, the sixteen
EFTPOS terminal-slip values and the ex-GST subtotal — come from the
`receipt_pos`, `receipt_payment` and `computed_totals` field providers
(generators/layout_dsl/field_providers.py), which each layout declares under
`field_providers:`; the line items come from the `receipt_line_items` row
provider (generators/layout_dsl/providers.py).
"""

from PIL import Image, ImageDraw

from generators.exporters.geometry import BoxRecorder, rescale_vertical
from generators.layout_dsl.context import Region
from generators.layout_dsl.engine import render_body

_LAYOUT_PATH = "config/layouts/receipts.yml"


def render_receipt(entry: dict, layout: dict, *, geometry_out: dict | None = None) -> Image.Image:
    """Render a receipt image from ground truth entry and layout config.

    Receipts are variable-height: the body is drawn onto a canvas
    `canvas_ceiling` tall, then cropped to the y the engine returns plus the
    bottom margin, and the recorder's boxes are rescaled to that final height.
    `render_body` is canvas-agnostic, so this needs no engine support.

    Args:
        entry: Ground truth YAML entry with 'fields', 'case_id' and 'layout'.
        layout: Layout registry entry carrying a `body:` tree, `width`,
            `margin`, `content_width` and `canvas_ceiling`.
        geometry_out: Optional dict (opt-in); when given, populated in place
            with {"width", "height", "boxes"} describing each captured
            field's normalised bounding box on the rendered page.

    Returns:
        PIL Image of the rendered receipt, cropped to its content.
    """
    layout_id = str(entry.get("layout", ""))
    width = int(layout["width"])
    ceiling = int(layout["canvas_ceiling"])
    margin = int(layout["margin"])

    image = Image.new("RGB", (width, ceiling), "white")
    draw = ImageDraw.Draw(image)
    recorder = BoxRecorder(width, ceiling) if geometry_out is not None else None

    end_y = render_body(
        layout,
        entry,
        layout_id=layout_id,
        layout_path=_LAYOUT_PATH,
        draw=draw,
        region=Region(x=margin, width=int(layout["content_width"])),
        y=margin,
        recorder=recorder,
    )

    height = min(end_y + margin, ceiling)
    image = image.crop((0, 0, width, height))

    if recorder is not None and geometry_out is not None:
        geometry_out["width"] = width
        geometry_out["height"] = height
        geometry_out["boxes"] = rescale_vertical(recorder.as_dict(), old_height=ceiling, new_height=height)
    return image
