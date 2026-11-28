"""Position and draw the mascot’s desktop speech bubble."""
from PIL import Image, ImageDraw

from modules.mascot_window import KEY_RGB, clamp_position


def place(bounds, body_width, body_height, monitors):
    """Anchor the caption above the hood, with a side placement near the top edge."""
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
    """Draw a small aqua reflection beneath the type, with no enclosing shape."""
    scale = 3
    pad = 25
    offset = pad if trail == "left" else 0
    width = body_width + (pad if trail != "down" else 0)
    height = body_height + (pad if trail == "down" else 0)
    layer = Image.new("RGBA", (width * scale, height * scale))
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

    pencil.line([point(4 + .008 * x*x, x) for x in range(-22, 23)],
                fill="#2b596b", width=3 * scale)
    pencil.line([point(4 + .008 * x*x, x) for x in range(-16, 17)],
                fill="#66c7d6", width=scale)
    pencil.line([point(4 + .008 * x*x, x) for x in range(-7, 8)],
                fill="#a8f1f2", width=scale)
    for distance, sideways, radius in ((12, -2, 1.5), (19, 3, 1)):
        cx, cy = point(distance, sideways)
        r = round(radius * scale)
        pencil.ellipse((cx-r, cy-r, cx+r, cy+r), fill="#72cfdd")

    layer = layer.resize((width, height), Image.Resampling.LANCZOS)
    background = Image.new("RGB", layer.size, KEY_RGB)
    background.paste(layer.convert("RGB"), mask=layer.getchannel("A").point(lambda a: 255 if a >= 120 else 0))
    return background, offset
