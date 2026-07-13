"""
overlay_process.py — Wispr-Flow-style waveform pill overlay.

A small dark capsule at the bottom-center of the screen with live orange
waveform bars. Always on top, never steals focus, ignores the mouse.

States (read from stdin, one per line):
  recording    → bars scroll live with mic level (voice-reactive waveform)
  transcribing → fast traveling-wave animation across the bars
  polishing    → slower traveling-wave animation
  done         → bars pop to a symmetric peak, then fade out
  hidden       → invisible
  level:0.42   → mic RMS level update (only used while recording)
"""

import os
import sys
import threading
import time
from collections import deque

import AppKit
import objc
import Quartz

# ── Dimensions ────────────────────────────────────────────────────────────────

# Panel is larger than the pill so the drop shadow and the status label fit.
W, H     = 220, 92
PILL_W   = 158
PILL_H   = 36
PILL_Y   = 48          # pill sits in the upper part; status label below it
BOTTOM   = 20          # px from bottom of screen to panel

BAR_W     = 3.0        # bar width
BAR_GAP   = 3.0        # gap between bars
BAR_MIN_H = 3.0        # bar height at silence
BAR_MAX_H = 22.0       # bar height at full level
PAD_X     = 16.0       # horizontal padding inside the pill

N_BARS = int((PILL_W - 2 * PAD_X + BAR_GAP) // (BAR_W + BAR_GAP))

# Wispr-orange bar colour
BAR_COLOR = Quartz.CGColorCreateGenericRGB(1.00, 0.55, 0.10, 1.0)

# ── NSApplication setup ───────────────────────────────────────────────────────

app = AppKit.NSApplication.sharedApplication()
app.setActivationPolicy_(AppKit.NSApplicationActivationPolicyAccessory)

screen = AppKit.NSScreen.mainScreen().frame()
x = (screen.size.width - W) / 2
rect = AppKit.NSMakeRect(x, BOTTOM, W, H)

# Borderless, non-activating panel (0x0080 = NSWindowStyleMaskNonactivatingPanel)
panel = AppKit.NSPanel.alloc().initWithContentRect_styleMask_backing_defer_(
    rect,
    AppKit.NSWindowStyleMaskBorderless | 0x0080,
    AppKit.NSBackingStoreBuffered,
    False,
)
panel.setLevel_(AppKit.NSStatusWindowLevel + 1)
panel.setAlphaValue_(0.0)
panel.setOpaque_(False)
panel.setHasShadow_(False)
panel.setIgnoresMouseEvents_(True)
panel.setBackgroundColor_(AppKit.NSColor.clearColor())
panel.setCollectionBehavior_(
    AppKit.NSWindowCollectionBehaviorCanJoinAllSpaces |
    AppKit.NSWindowCollectionBehaviorStationary |
    AppKit.NSWindowCollectionBehaviorIgnoresCycle
)

content = AppKit.NSView.alloc().initWithFrame_(AppKit.NSMakeRect(0, 0, W, H))
content.setWantsLayer_(True)
content.layer().setBackgroundColor_(Quartz.CGColorGetConstantColor(Quartz.kCGColorClear))
panel.setContentView_(content)

# ── Pill capsule ──────────────────────────────────────────────────────────────

pill = Quartz.CALayer.layer()
pill.setFrame_(Quartz.CGRectMake((W - PILL_W) / 2, PILL_Y, PILL_W, PILL_H))
pill.setCornerRadius_(PILL_H / 2)
pill.setBackgroundColor_(Quartz.CGColorCreateGenericRGB(0.07, 0.07, 0.08, 0.94))
pill.setBorderWidth_(1.0)
pill.setBorderColor_(Quartz.CGColorCreateGenericRGB(1, 1, 1, 0.10))
# Soft drop shadow so the pill floats over any background
pill.setShadowColor_(Quartz.CGColorCreateGenericRGB(0, 0, 0, 1.0))
pill.setShadowOpacity_(0.45)
pill.setShadowRadius_(10.0)
pill.setShadowOffset_(Quartz.CGSizeMake(0, -2))
content.layer().addSublayer_(pill)

# ── Waveform bars ─────────────────────────────────────────────────────────────

bars = []
_total_bars_w = N_BARS * BAR_W + (N_BARS - 1) * BAR_GAP
_bars_x0 = (PILL_W - _total_bars_w) / 2

for i in range(N_BARS):
    bar = Quartz.CALayer.layer()
    bx = _bars_x0 + i * (BAR_W + BAR_GAP)
    bar.setFrame_(Quartz.CGRectMake(bx, (PILL_H - BAR_MIN_H) / 2, BAR_W, BAR_MIN_H))
    bar.setCornerRadius_(BAR_W / 2)
    bar.setBackgroundColor_(BAR_COLOR)
    pill.addSublayer_(bar)
    bars.append(bar)

# ── Status label (below the pill) ────────────────────────────────────────────

label = AppKit.NSTextField.alloc().initWithFrame_(
    AppKit.NSMakeRect(0, PILL_Y - 28, W, 20)
)
label.setEditable_(False)
label.setSelectable_(False)
label.setBezeled_(False)
label.setDrawsBackground_(False)
label.setAlignment_(AppKit.NSTextAlignmentCenter)
label.setFont_(AppKit.NSFont.systemFontOfSize_weight_(12.5, AppKit.NSFontWeightSemibold))
# White text with a dark shadow so it's legible on any background
label.setTextColor_(AppKit.NSColor.whiteColor())
_shadow = AppKit.NSShadow.alloc().init()
_shadow.setShadowColor_(AppKit.NSColor.colorWithCalibratedRed_green_blue_alpha_(0, 0, 0, 0.85))
_shadow.setShadowBlurRadius_(4)
_shadow.setShadowOffset_(AppKit.NSMakeSize(0, -1))
label.setShadow_(_shadow)
label.setStringValue_("")
content.addSubview_(label)

panel.orderFrontRegardless()

# ── State ─────────────────────────────────────────────────────────────────────

_hide_at   = [None]
_cur_state = [None]

# Rolling mic-level history: newest sample = rightmost bar.
_levels = deque([0.0] * N_BARS, maxlen=N_BARS)


def _set_bar_heights(heights):
    """Set bar frames instantly (no implicit animation)."""
    Quartz.CATransaction.begin()
    Quartz.CATransaction.setDisableActions_(True)
    for bar, h in zip(bars, heights):
        f = bar.frame()
        bar.setFrame_(Quartz.CGRectMake(
            f.origin.x, (PILL_H - h) / 2, BAR_W, h
        ))
    Quartz.CATransaction.commit()


def _stop_anims():
    for bar in bars:
        bar.removeAllAnimations()


def _apply_level(raw: float):
    """Scroll the waveform: push new level, redraw all bars."""
    if _cur_state[0] != "recording":
        return
    _levels.append(min(1.0, max(0.0, raw)))
    heights = [BAR_MIN_H + lvl * (BAR_MAX_H - BAR_MIN_H) for lvl in _levels]
    _set_bar_heights(heights)


def _wave_animation(duration_per_bar: float, phase_step: float):
    """Traveling sine wave across the bars — the 'processing' look."""
    now = Quartz.CACurrentMediaTime()
    for i, bar in enumerate(bars):
        anim = Quartz.CABasicAnimation.animationWithKeyPath_("transform.scale.y")
        anim.setFromValue_(0.30)
        anim.setToValue_(1.0)
        anim.setDuration_(duration_per_bar)
        anim.setAutoreverses_(True)
        anim.setRepeatCount_(float("inf"))
        anim.setTimingFunction_(
            Quartz.CAMediaTimingFunction.functionWithName_(
                Quartz.kCAMediaTimingFunctionEaseInEaseOut)
        )
        anim.setBeginTime_(now + i * phase_step)
        bar.addAnimation_forKey_(anim, "wave")


def _fade_panel(to_alpha: float, duration: float):
    AppKit.NSAnimationContext.beginGrouping()
    AppKit.NSAnimationContext.currentContext().setDuration_(duration)
    panel.animator().setAlphaValue_(to_alpha)
    AppKit.NSAnimationContext.endGrouping()


def _apply(state: str):
    _hide_at[0]   = None
    _cur_state[0] = state
    _stop_anims()

    if state == "hidden":
        label.setStringValue_("")
        _fade_panel(0.0, 0.20)
        return

    if state == "recording":
        label.setStringValue_("Recording")
        # Reset waveform history and fade the pill in.
        for _ in range(N_BARS):
            _levels.append(0.0)
        _set_bar_heights([BAR_MIN_H] * N_BARS)
        _fade_panel(1.0, 0.12)

    elif state == "transcribing":
        label.setStringValue_("Transcribing…")
        _set_bar_heights([BAR_MAX_H * 0.75] * N_BARS)
        _wave_animation(0.40, 0.045)

    elif state == "polishing":
        label.setStringValue_("Polishing…")
        _set_bar_heights([BAR_MAX_H * 0.75] * N_BARS)
        _wave_animation(0.65, 0.07)

    elif state == "done":
        label.setStringValue_("Done ✓")
        # Bars pop into a symmetric peak, then the pill fades out.
        mid = (N_BARS - 1) / 2
        heights = [
            BAR_MIN_H + (BAR_MAX_H - BAR_MIN_H) * (1.0 - abs(i - mid) / mid) ** 1.5
            for i in range(N_BARS)
        ]
        _set_bar_heights(heights)
        _hide_at[0] = time.monotonic() + 0.9

    # Debug hook: render each state to a PNG for visual verification.
    out = os.environ.get("WISPR_OVERLAY_RENDER")
    if out:
        rep = content.bitmapImageRepForCachingDisplayInRect_(content.bounds())
        content.cacheDisplayInRect_toBitmapImageRep_(content.bounds(), rep)
        png = rep.representationUsingType_properties_(AppKit.NSBitmapImageFileTypePNG, None)
        png.writeToFile_atomically_(f"{out}_{state}.png", True)


# ── Timer — runs in run loop, handles auto-hide ───────────────────────────────

class TimerTarget(AppKit.NSObject):
    def tick_(self, _timer):
        if _hide_at[0] and time.monotonic() >= _hide_at[0]:
            _hide_at[0] = None
            _stop_anims()
            label.setStringValue_("")
            _fade_panel(0.0, 0.30)


timer_target = TimerTarget.alloc().init()
ns_timer = AppKit.NSTimer.scheduledTimerWithTimeInterval_target_selector_userInfo_repeats_(
    0.05,
    timer_target,
    objc.selector(timer_target.tick_, signature=b"v@:@"),
    None,
    True,
)
AppKit.NSRunLoop.mainRunLoop().addTimer_forMode_(
    ns_timer, AppKit.NSRunLoopCommonModes
)

# ── stdin reader ──────────────────────────────────────────────────────────────

def _stdin_reader():
    for line in sys.stdin:
        msg = line.strip()
        if not msg:
            continue
        if msg.startswith("level:"):
            try:
                val = float(msg[6:])
                AppKit.NSOperationQueue.mainQueue().addOperationWithBlock_(
                    lambda v=val: _apply_level(v)
                )
            except ValueError:
                pass
        else:
            AppKit.NSOperationQueue.mainQueue().addOperationWithBlock_(
                lambda s=msg: _apply(s)
            )
    # stdin closed → parent exited → quit so we don't linger as a zombie.
    AppKit.NSOperationQueue.mainQueue().addOperationWithBlock_(
        lambda: app.terminate_(None)
    )

threading.Thread(target=_stdin_reader, daemon=True).start()

# ── Run ───────────────────────────────────────────────────────────────────────

app.run()
