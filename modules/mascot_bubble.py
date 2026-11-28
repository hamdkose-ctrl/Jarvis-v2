"""Position and draw the mascot’s desktop speech bubble."""
from PIL import Image, ImageChops, ImageDraw, ImageFilter, ImageOps

from modules.mascot_window import KEY_RGB, clamp_position


def place(bounds, body_width, body_height, monitors):
    """Anchor the glass above the hood, with a side placement near the top edge."""
    x, y, w, h = bounds
    head_x = x + round(w * .55)
    hood_y = y + round(h * .09)
    height = body_height + 25
    left, top = clamp_position(head_x - round(body_width * .60), hood_y - height - 3,
                               body_width, height, monitors)
    if top + height < hood_y:
        anchor = max(20, min(body_width - 20, head_x - left))
        return left, top, "down", anchor

    face_y = y + round(h * .33)
    width = body_width + 25
    left_edge = x + round(w * .19)
    right_edge = x + round(w * .81)
    left, top = clamp_position(left_edge - width, face_y - body_height // 2,
                               width, body_height, monitors)
    if left + width <= left_edge:
        return left, top, "right", body_height // 2
    left, top = clamp_position(right_edge, face_y - body_height // 2,
                               width, body_height, monitors)
    return left, top, "left", body_height // 2


def artwork(body_width, body_height, trail, anchor):
    """Render the curved glass, edge reflections and short light trail at 3×."""
    scale = 3
    pad = 25
    offset = pad if trail == "left" else 0
    width = body_width + (pad if trail != "down" else 0)
    height = body_height + (pad if trail == "down" else 0)
    dimensions = (body_width * scale, body_height * scale)
    mask = Image.new("L", dimensions)
    radius = min(21, body_height // 2 - 2)
    ImageDraw.Draw(mask).rounded_rectangle(
        (scale, scale, dimensions[0] - scale - 1, dimensions[1] - scale - 1),
        radius * scale, fill=255,
    )

    gradient = Image.linear_gradient("L").resize(dimensions)
    glass = ImageOps.colorize(gradient, "#173044", "#0a1522", mid="#102336")
    rim = ImageChops.subtract(mask, mask.filter(ImageFilter.MinFilter(7)))
    edge = ImageOps.colorize(gradient, "#83a8b5", "#2d6878", mid="#304758")
    glass.paste(edge, mask=rim)

    # A local reflection at the lower edge reads as glass without adding chrome behind the text.
    reflection = Image.new("L", dimensions)
    pencil = ImageDraw.Draw(reflection)
    if trail == "down":
        light_x = anchor * scale
        pencil.ellipse((light_x - 29*scale, dimensions[1] - 7*scale,
                        light_x + 29*scale, dimensions[1] + 2*scale), fill=150)
    else:
        light_x = 0 if trail == "left" else dimensions[0]
        pencil.ellipse((light_x - 7*scale, (anchor - 20)*scale,
                        light_x + 7*scale, (anchor + 20)*scale), fill=140)
    reflection = reflection.filter(ImageFilter.GaussianBlur(2.7 * scale))
    glass.paste("#91f1f3", mask=ImageChops.multiply(rim, reflection))

    layer = Image.new("RGBA", (width * scale, height * scale))
    layer.paste(glass, (offset * scale, 0), mask)
    pencil = ImageDraw.Draw(layer)

    if trail == "down":
        origin = (anchor, body_height)
        forward, across = (0, 1), (1, 0)
    else:
        origin = (offset if trail == "left" else body_width, anchor)
        forward, across = ((-1, 0) if trail == "left" else (1, 0)), (0, 1)

    def point(distance, sideways):
        return tuple(round((origin[i] + forward[i] * distance + across[i] * sideways) * scale)
                     for i in (0, 1))

    for distance, half_width, color in ((3, 11, "#81d8e5"), (9, 7, "#4e9cac"), (15, 4, "#34677a")):
        pencil.line([point(distance, -half_width), point(distance + 2, 0), point(distance, half_width)],
                    fill=color, width=scale, joint="curve")
    cx, cy = point(21, 0)
    pencil.ellipse((cx-scale, cy-scale, cx+scale, cy+scale), fill="#78d4e6")

    layer = layer.resize((width, height), Image.Resampling.LANCZOS)
    background = Image.new("RGB", layer.size, KEY_RGB)
    background.paste(layer.convert("RGB"), mask=layer.getchannel("A").point(lambda a: 255 if a >= 120 else 0))
    return background, offset
