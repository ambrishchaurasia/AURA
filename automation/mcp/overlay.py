"""On-screen feedback for voice control: a soft coloured glow around the screen edge and a caption
pill at the top centre. The window is click-through and never takes focus.

    overlay = Overlay()
    overlay.caption("Listening…")            # glow + text, stays
    overlay.caption("Volume set to 30", 4)   # hides itself after 4 seconds
    overlay.hide()

Run `python -m automation.mcp.overlay` to see it.
"""
import ctypes as ct
import math
import queue
import threading
import time

import numpy as np
from PIL import Image, ImageDraw, ImageFont

# Corner colours of the glow, clockwise from top-left.
PALETTE = np.array([[255, 94, 135], [255, 176, 92], [84, 190, 255], [150, 110, 255]], dtype="float32")


class _BitmapInfo(ct.Structure):
    _fields_ = [("size", ct.c_uint32), ("width", ct.c_int32), ("height", ct.c_int32), ("planes", ct.c_uint16),
                ("bits", ct.c_uint16), ("compression", ct.c_uint32), ("image_size", ct.c_uint32),
                ("xppm", ct.c_int32), ("yppm", ct.c_int32), ("used", ct.c_uint32), ("important", ct.c_uint32)]


class _Blend(ct.Structure):
    _fields_ = [("op", ct.c_ubyte), ("flags", ct.c_ubyte), ("alpha", ct.c_ubyte), ("format", ct.c_ubyte)]


def glow(width, height):
    """RGBA edge glow, drawn at quarter size and scaled up so it stays smooth and cheap."""
    w, h = width // 4, height // 4
    y, x = np.mgrid[0:h, 0:w].astype("float32")
    fx, fy = (x / (w - 1))[..., None], (y / (h - 1))[..., None]
    top = PALETTE[0] * (1 - fx) + PALETTE[1] * fx
    bottom = PALETTE[3] * (1 - fx) + PALETTE[2] * fx
    colour = top * (1 - fy) + bottom * fy
    edge = np.minimum(np.minimum(x, w - 1 - x), np.minimum(y, h - 1 - y))  # distance to the nearest screen edge
    alpha = 235 * np.exp(-edge / (h * 0.022)) + 40 * np.exp(-edge / (h * 0.06))
    rgba = np.dstack([colour, np.clip(alpha, 0, 255)]).astype("uint8")
    return Image.fromarray(rgba, "RGBA").resize((width, height), Image.BICUBIC)


def with_caption(base, text):
    """`base` with `text` in a translucent pill at the top centre (at most two lines)."""
    image = base.copy()
    if not text:
        return image
    scale = image.height / 1080
    try:
        font = ImageFont.truetype("segoeui.ttf", round(26 * scale))
    except OSError:
        font = ImageFont.load_default()
    draw = ImageDraw.Draw(image)
    limit = image.width * 0.6
    lines, line = [], ""
    for word in text.split():
        if line and draw.textlength(f"{line} {word}", font=font) > limit:
            lines.append(line)
            line = word
        else:
            line = f"{line} {word}".strip()
    lines.append(line)
    if len(lines) > 2:
        lines = [lines[0], lines[1].rstrip(".,") + "…"]
    line_height = round(36 * scale)
    pad_x, pad_y = round(30 * scale), round(16 * scale)
    box_w = max(draw.textlength(row, font=font) for row in lines) + 2 * pad_x
    box_h = line_height * len(lines) + 2 * pad_y
    left, top = (image.width - box_w) / 2, round(46 * scale)
    draw.rounded_rectangle((left, top, left + box_w, top + box_h), radius=round(26 * scale),
                           fill=(18, 18, 26, 215), outline=(255, 255, 255, 60), width=max(1, round(scale)))
    for i, row in enumerate(lines):
        draw.text((image.width / 2, top + pad_y + line_height * i + line_height / 2), row, font=font,
                  fill=(255, 255, 255, 255), anchor="mm")
    return image


class Overlay:
    def __init__(self):
        self._commands = queue.Queue()
        threading.Thread(target=self._run, daemon=True).start()

    def caption(self, text, seconds=None):
        self._commands.put((text, seconds))

    def hide(self):
        self._commands.put((None, None))

    def _run(self):
        import win32con
        import win32gui
        user32, gdi32 = ct.windll.user32, ct.windll.gdi32
        gdi32.CreateDIBSection.restype = gdi32.CreateCompatibleDC.restype = gdi32.SelectObject.restype = ct.c_void_p
        gdi32.CreateCompatibleDC.argtypes = [ct.c_void_p]
        gdi32.CreateDIBSection.argtypes = [ct.c_void_p, ct.c_void_p, ct.c_uint32, ct.c_void_p, ct.c_void_p, ct.c_uint32]
        gdi32.SelectObject.argtypes = [ct.c_void_p, ct.c_void_p]
        user32.UpdateLayeredWindow.argtypes = [ct.c_void_p, ct.c_void_p, ct.c_void_p, ct.c_void_p, ct.c_void_p,
                                               ct.c_void_p, ct.c_uint32, ct.c_void_p, ct.c_uint32]
        try:
            ct.windll.shcore.SetProcessDpiAwareness(2)
        except OSError:
            pass  # already set by the host process
        width, height = user32.GetSystemMetrics(0), user32.GetSystemMetrics(1)
        window_class = win32gui.WNDCLASS()
        window_class.lpszClassName = "AuraOverlay"
        window_class.lpfnWndProc = win32gui.DefWindowProc
        try:
            win32gui.RegisterClass(window_class)
        except win32gui.error:
            pass  # registered by an earlier Overlay
        hwnd = win32gui.CreateWindowEx(
            win32con.WS_EX_LAYERED | win32con.WS_EX_TRANSPARENT | win32con.WS_EX_TOPMOST | win32con.WS_EX_TOOLWINDOW
            | win32con.WS_EX_NOACTIVATE, "AuraOverlay", "", win32con.WS_POPUP, 0, 0, width, height, 0, 0, 0, None)
        dc = gdi32.CreateCompatibleDC(None)
        info = _BitmapInfo(ct.sizeof(_BitmapInfo), width, -height, 1, 32, 0, 0, 0, 0, 0, 0)
        pixels = ct.c_void_p()
        bitmap = gdi32.CreateDIBSection(dc, ct.byref(info), 0, ct.byref(pixels), None, 0)
        gdi32.SelectObject(dc, bitmap)
        size, origin = (ct.c_long * 2)(width, height), (ct.c_long * 2)(0, 0)
        base = glow(width, height)

        def paint(text):
            rgba = np.asarray(with_caption(base, text)).astype("float32")
            alpha = rgba[..., 3:4] / 255
            bgra = np.dstack([rgba[..., 2::-1] * alpha, rgba[..., 3:4]]).astype("uint8")  # premultiplied, as Windows wants
            ct.memmove(pixels, bgra.tobytes(), width * height * 4)

        shown, level, hide_at, visible = False, 0.0, None, False
        while True:
            win32gui.PumpWaitingMessages()
            try:
                text, seconds = self._commands.get(timeout=0.03 if (shown or level) else 0.25)
                shown = text is not None
                hide_at = time.monotonic() + seconds if shown and seconds else None
                if shown:
                    paint(text)
            except queue.Empty:
                pass
            if hide_at and time.monotonic() > hide_at:
                shown, hide_at = False, None
            level = min(1.0, level + 0.12) if shown else max(0.0, level - 0.08)  # fade in and out
            if level and not visible:
                win32gui.ShowWindow(hwnd, win32con.SW_SHOWNOACTIVATE)
            elif not level and visible:
                win32gui.ShowWindow(hwnd, win32con.SW_HIDE)
            visible = bool(level)
            if visible:
                breathe = 0.88 + 0.12 * math.sin(time.monotonic() * 2.2)
                blend = _Blend(0, 0, int(255 * level * breathe), 1)
                user32.UpdateLayeredWindow(hwnd, None, None, ct.byref(size), dc, ct.byref(origin), 0, ct.byref(blend), 2)


if __name__ == "__main__":
    demo = Overlay()
    demo.caption("Listening…")
    time.sleep(2)
    demo.caption("Turn the volume down in Brave and open my downloads folder")
    time.sleep(3)
    demo.caption("Brave volume is now 20", 2.5)
    time.sleep(4)
