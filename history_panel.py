"""
history_panel.py — Floating dictation-history panel (Cocoa subprocess).

A dark rounded panel above the waveform pill listing recent dictations,
newest first. Clicking an entry pastes it at the cursor — the panel is
non-activating, so the app you're typing in never loses focus.

Reads commands from stdin (one per line):
  toggle → show (reloading history from disk) or hide
  hide   → hide

Launched and managed by history_ui.py.
"""

import os
import sys
import threading
import time

import AppKit
import objc
import pyperclip
import Quartz

import history
import inject

# ── Dimensions ────────────────────────────────────────────────────────────────

PANEL_W   = 460
ROW_H     = 64
HEADER_H  = 44
MAX_ROWS_VISIBLE = 6          # panel grows up to this many rows, then scrolls
BOTTOM    = 118               # sits above the waveform pill
MAX_SHOW  = 50                # entries listed per open

ORANGE = AppKit.NSColor.colorWithCalibratedRed_green_blue_alpha_(1.00, 0.55, 0.10, 1.0)
GREY   = AppKit.NSColor.colorWithCalibratedWhite_alpha_(1.0, 0.45)
WHITE  = AppKit.NSColor.colorWithCalibratedWhite_alpha_(1.0, 0.92)

# ── App / panel setup ────────────────────────────────────────────────────────

app = AppKit.NSApplication.sharedApplication()
app.setActivationPolicy_(AppKit.NSApplicationActivationPolicyAccessory)

screen = AppKit.NSScreen.mainScreen().frame()

panel = AppKit.NSPanel.alloc().initWithContentRect_styleMask_backing_defer_(
    AppKit.NSMakeRect(0, 0, PANEL_W, 200),
    AppKit.NSWindowStyleMaskBorderless | 0x0080,   # non-activating
    AppKit.NSBackingStoreBuffered,
    False,
)
panel.setLevel_(AppKit.NSStatusWindowLevel)        # pill sits one level above
panel.setOpaque_(False)
panel.setHasShadow_(True)
panel.setBackgroundColor_(AppKit.NSColor.clearColor())
panel.setBecomesKeyOnlyIfNeeded_(True)
panel.setCollectionBehavior_(
    AppKit.NSWindowCollectionBehaviorCanJoinAllSpaces |
    AppKit.NSWindowCollectionBehaviorStationary |
    AppKit.NSWindowCollectionBehaviorIgnoresCycle
)

_visible = [False]


class FlippedView(AppKit.NSView):
    """Document view with (0,0) top-left so newest rows stack from the top."""
    def isFlipped(self):
        return True


class RowButton(AppKit.NSButton):
    """Transparent click-catcher that works in a non-activating panel."""
    def acceptsFirstMouse_(self, event):
        return True


class ClickTarget(AppKit.NSObject):
    def clickRow_(self, sender):
        idx = sender.tag()
        if 0 <= idx < len(_entries[0]):
            text = _entries[0][idx]["text"]
            _hide()
            # Paste in a worker thread: inject sleeps internally and must not
            # block the Cocoa run loop. The panel never took focus, so the
            # user's app is still frontmost and receives the Cmd+V.
            threading.Thread(target=_paste_later, args=(text,), daemon=True).start()

    def copyRow_(self, sender):
        idx = sender.tag()
        if not (0 <= idx < len(_entries[0])):
            return
        try:
            pyperclip.copy(_entries[0][idx]["text"])
        except Exception:
            return
        # Brief "✓" feedback, then restore the label. Panel stays open so
        # multiple entries can be copied in a row.
        sender.setAttributedTitle_(_copy_title("✓"))
        def _restore():
            time.sleep(0.9)
            AppKit.NSOperationQueue.mainQueue().addOperationWithBlock_(
                lambda: sender.setAttributedTitle_(_copy_title("Copy"))
            )
        threading.Thread(target=_restore, daemon=True).start()


def _paste_later(text: str):
    time.sleep(0.12)   # let the click event settle
    inject.paste(text)


_entries: list[list[dict]] = [[]]
_target = ClickTarget.alloc().init()


def _copy_title(text: str) -> AppKit.NSAttributedString:
    """Orange, centered attributed title for the per-row Copy button."""
    para = AppKit.NSMutableParagraphStyle.alloc().init()
    para.setAlignment_(AppKit.NSTextAlignmentCenter)
    return AppKit.NSAttributedString.alloc().initWithString_attributes_(
        text,
        {
            AppKit.NSFontAttributeName:
                AppKit.NSFont.systemFontOfSize_weight_(11, AppKit.NSFontWeightSemibold),
            AppKit.NSForegroundColorAttributeName: ORANGE,
            AppKit.NSParagraphStyleAttributeName: para,
        },
    )


def _label(text, size, color, weight=AppKit.NSFontWeightRegular):
    lbl = AppKit.NSTextField.alloc().init()
    lbl.setEditable_(False)
    lbl.setSelectable_(False)
    lbl.setBezeled_(False)
    lbl.setDrawsBackground_(False)
    lbl.setFont_(AppKit.NSFont.systemFontOfSize_weight_(size, weight))
    lbl.setTextColor_(color)
    lbl.setStringValue_(text)
    return lbl


def _build_content():
    """(Re)build the panel contents from the history file."""
    _entries[0] = list(reversed(history.load(limit=MAX_SHOW)))   # newest first
    entries = _entries[0]

    n_rows = max(1, min(len(entries), MAX_ROWS_VISIBLE)) if entries else 2
    panel_h = HEADER_H + n_rows * ROW_H + 12

    x = (screen.size.width - PANEL_W) / 2
    panel.setFrame_display_(AppKit.NSMakeRect(x, BOTTOM, PANEL_W, panel_h), True)

    content = AppKit.NSView.alloc().initWithFrame_(AppKit.NSMakeRect(0, 0, PANEL_W, panel_h))
    content.setWantsLayer_(True)
    layer = content.layer()
    layer.setBackgroundColor_(Quartz.CGColorCreateGenericRGB(0.07, 0.07, 0.08, 0.96))
    layer.setCornerRadius_(16.0)
    layer.setBorderWidth_(1.0)
    layer.setBorderColor_(Quartz.CGColorCreateGenericRGB(1, 1, 1, 0.10))

    # ── Header ──
    dot = AppKit.NSView.alloc().initWithFrame_(AppKit.NSMakeRect(18, panel_h - 27, 8, 8))
    dot.setWantsLayer_(True)
    dot.layer().setBackgroundColor_(Quartz.CGColorCreateGenericRGB(1.00, 0.55, 0.10, 1.0))
    dot.layer().setCornerRadius_(4.0)
    content.addSubview_(dot)

    title = _label("Dictation History", 13, WHITE, AppKit.NSFontWeightSemibold)
    title.setFrame_(AppKit.NSMakeRect(32, panel_h - 34, 200, 20))
    content.addSubview_(title)

    hint = _label("click to paste  ·  Copy to clipboard  ·  ⌥ to close", 10, GREY)
    hint.setAlignment_(AppKit.NSTextAlignmentRight)
    hint.setFrame_(AppKit.NSMakeRect(PANEL_W - 300, panel_h - 32, 282, 16))
    content.addSubview_(hint)

    # ── Rows (scrollable) ──
    scroll_h = panel_h - HEADER_H - 8
    scroll = AppKit.NSScrollView.alloc().initWithFrame_(
        AppKit.NSMakeRect(6, 6, PANEL_W - 12, scroll_h))
    scroll.setDrawsBackground_(False)
    scroll.setHasVerticalScroller_(True)
    scroll.setBorderType_(AppKit.NSNoBorder)

    doc_h = max(len(entries) * ROW_H, scroll_h)
    doc = FlippedView.alloc().initWithFrame_(AppKit.NSMakeRect(0, 0, PANEL_W - 12, doc_h))

    if not entries:
        empty = _label("No dictations yet — hold Right-⌘ and speak.", 12, GREY)
        empty.setAlignment_(AppKit.NSTextAlignmentCenter)
        empty.setFrame_(AppKit.NSMakeRect(0, scroll_h / 2 - 10, PANEL_W - 12, 20))
        doc.addSubview_(empty)

    for i, e in enumerate(entries):
        row = AppKit.NSView.alloc().initWithFrame_(
            AppKit.NSMakeRect(0, i * ROW_H, PANEL_W - 12, ROW_H))

        ts = _label(history.format_ts(e["ts"]), 10, GREY, AppKit.NSFontWeightMedium)
        ts.setFrame_(AppKit.NSMakeRect(14, ROW_H - 22, PANEL_W - 40, 14))
        row.addSubview_(ts)

        preview = _label(" ".join(e["text"].split()), 12, WHITE)
        cell = preview.cell()
        cell.setWraps_(True)
        cell.setLineBreakMode_(AppKit.NSLineBreakByTruncatingTail)
        preview.setMaximumNumberOfLines_(2)
        preview.setFrame_(AppKit.NSMakeRect(14, 8, PANEL_W - 40 - 66, 34))
        row.addSubview_(preview)

        if i < len(entries) - 1:
            sep = AppKit.NSView.alloc().initWithFrame_(
                AppKit.NSMakeRect(14, 0, PANEL_W - 40, 1))
            sep.setWantsLayer_(True)
            sep.layer().setBackgroundColor_(Quartz.CGColorCreateGenericRGB(1, 1, 1, 0.06))
            row.addSubview_(sep)

        btn = RowButton.alloc().initWithFrame_(
            AppKit.NSMakeRect(0, 0, PANEL_W - 12, ROW_H))
        btn.setTitle_("")
        btn.setBordered_(False)
        btn.setTransparent_(True)
        btn.setTag_(i)
        btn.setTarget_(_target)
        btn.setAction_(objc.selector(_target.clickRow_, signature=b"v@:@"))
        row.addSubview_(btn)

        # Copy button — added after the row overlay so it sits on top and
        # receives its own clicks (copies to clipboard, panel stays open).
        copy_btn = RowButton.alloc().initWithFrame_(
            AppKit.NSMakeRect(PANEL_W - 12 - 62, ROW_H / 2 - 12, 50, 24))
        copy_btn.setTitle_("Copy")
        copy_btn.setBordered_(False)
        copy_btn.setWantsLayer_(True)
        copy_btn.layer().setBackgroundColor_(
            Quartz.CGColorCreateGenericRGB(1.00, 0.55, 0.10, 0.16))
        copy_btn.layer().setCornerRadius_(6.0)
        copy_btn.setAttributedTitle_(_copy_title("Copy"))
        copy_btn.setTag_(i)
        copy_btn.setTarget_(_target)
        copy_btn.setAction_(objc.selector(_target.copyRow_, signature=b"v@:@"))
        row.addSubview_(copy_btn)

        doc.addSubview_(row)

    scroll.setDocumentView_(doc)
    content.addSubview_(scroll)
    panel.setContentView_(content)

    # Debug hook: render the panel to a PNG for visual verification.
    out = os.environ.get("WISPR_PANEL_RENDER")
    if out:
        _render_png(content, out)


def _render_png(view, path):
    rep = view.bitmapImageRepForCachingDisplayInRect_(view.bounds())
    view.cacheDisplayInRect_toBitmapImageRep_(view.bounds(), rep)
    png = rep.representationUsingType_properties_(AppKit.NSBitmapImageFileTypePNG, None)
    png.writeToFile_atomically_(path, True)


def _show():
    _build_content()
    panel.orderFrontRegardless()
    _visible[0] = True


def _hide():
    panel.orderOut_(None)
    _visible[0] = False


def _handle(cmd: str):
    if cmd == "toggle":
        _hide() if _visible[0] else _show()
    elif cmd == "hide":
        _hide()


# ── stdin reader ──────────────────────────────────────────────────────────────

def _stdin_reader():
    for line in sys.stdin:
        msg = line.strip()
        if msg:
            AppKit.NSOperationQueue.mainQueue().addOperationWithBlock_(
                lambda m=msg: _handle(m)
            )
    AppKit.NSOperationQueue.mainQueue().addOperationWithBlock_(
        lambda: app.terminate_(None)
    )

threading.Thread(target=_stdin_reader, daemon=True).start()

app.run()
