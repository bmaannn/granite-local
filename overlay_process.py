"""
overlay_process.py — Siri-style animated orb overlay.

A glowing, pulsing orb rendered via Core Animation CAGradientLayer.
Sits at the bottom-center of the screen, always on top, never steals focus.

States:
  recording    → pulsing orange/amber orb  (breathing scale animation)
  transcribing → fast ripple animation
  polishing    → slow swirling animation
  done         → brief green flash, then fade out
  hidden       → invisible

Reads state commands from stdin (one per line).
"""

import sys
import threading
import time
import math

import AppKit
import objc
import Quartz


# ── Dimensions ────────────────────────────────────────────────────────────────

W       = 160
H       = 160
BOTTOM  = 55   # px from bottom

# ── NSApplication setup ───────────────────────────────────────────────────────

app = AppKit.NSApplication.sharedApplication()
app.setActivationPolicy_(AppKit.NSApplicationActivationPolicyAccessory)

screen = AppKit.NSScreen.mainScreen().frame()
sw     = screen.size.width
x      = (sw - W) / 2
y      = BOTTOM
rect   = AppKit.NSMakeRect(x, y, W, H)

# Borderless, non-activating panel
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

# ── Transparent content view ──────────────────────────────────────────────────

content = AppKit.NSView.alloc().initWithFrame_(AppKit.NSMakeRect(0, 0, W, H))
content.setWantsLayer_(True)
content.layer().setBackgroundColor_(Quartz.CGColorGetConstantColor(Quartz.kCGColorClear))
panel.setContentView_(content)

# ── Orb layer stack ───────────────────────────────────────────────────────────
# Layer order (bottom to top):
#   glow_layer   — large soft radial outer glow
#   orb_layer    — main gradient circle
#   shine_layer  — small highlight highlight top-left for depth

CX, CY = W / 2, H / 2
R  = 46   # orb radius (smaller)
GR = 75   # glow radius

# ── Outer glow layer ──────────────────────────────────────────────────────────

glow_layer = Quartz.CAGradientLayer.layer()
glow_layer.setType_(Quartz.kCAGradientLayerRadial)
glow_layer.setFrame_(Quartz.CGRectMake(CX - GR, CY - GR, GR * 2, GR * 2))
glow_layer.setCornerRadius_(GR)

# Orange glow: center opaque → edge transparent
glow_layer.setColors_([
    Quartz.CGColorCreateGenericRGB(1.0, 0.45, 0.0, 0.55),  # deep orange centre
    Quartz.CGColorCreateGenericRGB(1.0, 0.35, 0.0, 0.18),  # mid fade
    Quartz.CGColorCreateGenericRGB(1.0, 0.25, 0.0, 0.0),   # transparent edge
])
glow_layer.setLocations_([0.0, 0.5, 1.0])
glow_layer.setStartPoint_(Quartz.CGPointMake(0.5, 0.5))
glow_layer.setEndPoint_(Quartz.CGPointMake(1.0, 1.0))
content.layer().addSublayer_(glow_layer)

# ── Main orb layer ────────────────────────────────────────────────────────────

orb_layer = Quartz.CAGradientLayer.layer()
orb_layer.setType_(Quartz.kCAGradientLayerRadial)
orb_layer.setFrame_(Quartz.CGRectMake(CX - R, CY - R, R * 2, R * 2))
orb_layer.setCornerRadius_(R)

# Gradient: bright amber centre → deep orange → burnt orange edge
orb_layer.setColors_([
    Quartz.CGColorCreateGenericRGB(1.0, 0.82, 0.20, 1.0),  # bright amber
    Quartz.CGColorCreateGenericRGB(1.0, 0.50, 0.05, 1.0),  # orange
    Quartz.CGColorCreateGenericRGB(0.85, 0.22, 0.0,  1.0), # deep burnt orange
])
orb_layer.setLocations_([0.0, 0.55, 1.0])
orb_layer.setStartPoint_(Quartz.CGPointMake(0.5, 0.5))
orb_layer.setEndPoint_(Quartz.CGPointMake(1.0, 1.0))
content.layer().addSublayer_(orb_layer)

# ── Shine highlight (small white circle top-left for depth) ───────────────────

shine_layer = Quartz.CAGradientLayer.layer()
shine_layer.setType_(Quartz.kCAGradientLayerRadial)
shine_layer.setFrame_(Quartz.CGRectMake(CX - R * 0.55, CY + R * 0.15, R * 0.7, R * 0.7))
shine_layer.setCornerRadius_(R * 0.35)
shine_layer.setColors_([
    Quartz.CGColorCreateGenericRGB(1.0, 1.0, 1.0, 0.45),
    Quartz.CGColorCreateGenericRGB(1.0, 1.0, 1.0, 0.0),
])
shine_layer.setLocations_([0.0, 1.0])
shine_layer.setStartPoint_(Quartz.CGPointMake(0.5, 0.5))
shine_layer.setEndPoint_(Quartz.CGPointMake(1.0, 1.0))
content.layer().addSublayer_(shine_layer)

# ── Label (state text below orb) ─────────────────────────────────────────────

label = AppKit.NSTextField.alloc().initWithFrame_(
    AppKit.NSMakeRect(0, 2, W, 24)
)
label.setEditable_(False)
label.setSelectable_(False)
label.setBezeled_(False)
label.setDrawsBackground_(False)
label.setAlignment_(AppKit.NSTextAlignmentCenter)
label.setFont_(AppKit.NSFont.systemFontOfSize_weight_(13, AppKit.NSFontWeightSemibold))
# White text with a dark shadow so it's legible on any background
label.setTextColor_(AppKit.NSColor.whiteColor())
shadow = AppKit.NSShadow.alloc().init()
shadow.setShadowColor_(AppKit.NSColor.colorWithCalibratedRed_green_blue_alpha_(0, 0, 0, 0.8))
shadow.setShadowBlurRadius_(4)
shadow.setShadowOffset_(AppKit.NSMakeSize(0, -1))
label.setShadow_(shadow)
label.setStringValue_("")
content.addSubview_(label)

panel.orderFrontRegardless()

# ── Animation helpers ─────────────────────────────────────────────────────────

def _make_pulse_anim(from_scale, to_scale, duration, repeat=True):
    anim = Quartz.CABasicAnimation.animationWithKeyPath_("transform.scale")
    anim.setFromValue_(from_scale)
    anim.setToValue_(to_scale)
    anim.setDuration_(duration)
    anim.setTimingFunction_(
        Quartz.CAMediaTimingFunction.functionWithName_(Quartz.kCAMediaTimingFunctionEaseInEaseOut)
    )
    if repeat:
        anim.setRepeatCount_(float("inf"))
        anim.setAutoreverses_(True)
    return anim


def _make_blob_axis_anim(key_path, values, duration):
    """Organic blob motion: independent X/Y squash-stretch keyframes."""
    anim = Quartz.CAKeyframeAnimation.animationWithKeyPath_(key_path)
    anim.setValues_(values)
    anim.setKeyTimes_([0.0, 0.14, 0.30, 0.48, 0.66, 0.84, 1.0])
    anim.setDuration_(duration)
    anim.setRepeatCount_(float("inf"))
    anim.setCalculationMode_(Quartz.kCAAnimationCubic)
    return anim


def _make_blob_position_anim(duration):
    """Tiny vertical wobble so the splat feels alive instead of mechanical."""
    anim = Quartz.CAKeyframeAnimation.animationWithKeyPath_("transform.translation.y")
    anim.setValues_([0.0, -1.5, 1.0, -0.8, 0.6, -0.2, 0.0])
    anim.setKeyTimes_([0.0, 0.14, 0.30, 0.48, 0.66, 0.84, 1.0])
    anim.setDuration_(duration)
    anim.setRepeatCount_(float("inf"))
    anim.setCalculationMode_(Quartz.kCAAnimationCubic)
    return anim


def _make_blob_opacity_anim(duration):
    anim = Quartz.CAKeyframeAnimation.animationWithKeyPath_("opacity")
    anim.setValues_([0.72, 0.98, 0.84, 0.94, 0.88, 0.96, 0.90])
    anim.setKeyTimes_([0.0, 0.14, 0.30, 0.48, 0.66, 0.84, 1.0])
    anim.setDuration_(duration)
    anim.setRepeatCount_(float("inf"))
    anim.setCalculationMode_(Quartz.kCAAnimationCubic)
    return anim


def _make_opacity_anim(from_val, to_val, duration, repeat=True):
    anim = Quartz.CABasicAnimation.animationWithKeyPath_("opacity")
    anim.setFromValue_(from_val)
    anim.setToValue_(to_val)
    anim.setDuration_(duration)
    anim.setTimingFunction_(
        Quartz.CAMediaTimingFunction.functionWithName_(Quartz.kCAMediaTimingFunctionEaseInEaseOut)
    )
    if repeat:
        anim.setRepeatCount_(float("inf"))
        anim.setAutoreverses_(True)
    return anim


def _stop_anims():
    orb_layer.removeAllAnimations()
    glow_layer.removeAllAnimations()
    shine_layer.removeAllAnimations()


# ── State machine ─────────────────────────────────────────────────────────────

_hide_at   = [None]
_cur_state = [None]

# Smoothed level value for the voice-reactive scale (0.0 – 1.0)
_smooth_level = [0.0]


def _apply_level(raw: float):
    """Scale the orb in real time to match mic RMS level while recording."""
    if _cur_state[0] != "recording":
        return

    # Smooth: 65% new value, 35% previous — snappier response to voice peaks
    _smooth_level[0] = _smooth_level[0] * 0.35 + raw * 0.65
    lvl = _smooth_level[0]

    # Map 0–1 → scale 0.70–1.45  (much wider range = more dramatic)
    orb_scale  = 0.70 + lvl * 0.75
    glow_scale = 0.55 + lvl * 0.95

    # CATransaction with 0 animation duration = instant, no implicit animation
    Quartz.CATransaction.begin()
    Quartz.CATransaction.setDisableActions_(True)

    # Remove the preset pulse so voice takes over
    orb_layer.removeAnimationForKey_("pulse")
    glow_layer.removeAnimationForKey_("glow_pulse")

    # Set scale via CATransform3DMakeScale — the correct API for CALayer
    orb_layer.setTransform_(Quartz.CATransform3DMakeScale(orb_scale, orb_scale, 1.0))
    glow_layer.setTransform_(Quartz.CATransform3DMakeScale(glow_scale, glow_scale, 1.0))

    Quartz.CATransaction.commit()


def _apply(state: str):
    _hide_at[0]   = None
    _cur_state[0] = state
    _smooth_level[0] = 0.0
    _stop_anims()

    if state == "hidden":
        panel.setAlphaValue_(0.0)
        label.setStringValue_("")
        return

    # Show panel
    panel.setAlphaValue_(1.0)

    # Reset any transform left over from voice-reactive scaling
    Quartz.CATransaction.begin()
    Quartz.CATransaction.setDisableActions_(True)
    orb_layer.setTransform_(Quartz.CATransform3DIdentity)
    glow_layer.setTransform_(Quartz.CATransform3DIdentity)
    Quartz.CATransaction.commit()

    if state == "recording":
        label.setStringValue_("Recording")

        # Claude-like blob/splat motion:
        # - orb squashes horizontally while stretching vertically
        # - then reverses with slight overshoot
        # - glow lags behind with larger deformation
        duration = 1.08

        orb_layer.addAnimation_forKey_(
            _make_blob_axis_anim("transform.scale.x", [1.00, 0.86, 1.12, 0.94, 1.08, 0.98, 1.00], duration),
            "blob_x"
        )
        orb_layer.addAnimation_forKey_(
            _make_blob_axis_anim("transform.scale.y", [1.00, 1.16, 0.90, 1.08, 0.96, 1.02, 1.00], duration),
            "blob_y"
        )
        orb_layer.addAnimation_forKey_(_make_blob_position_anim(duration), "blob_pos")

        glow_layer.addAnimation_forKey_(
            _make_blob_axis_anim("transform.scale.x", [1.00, 0.78, 1.22, 0.90, 1.14, 0.96, 1.00], duration),
            "glow_blob_x"
        )
        glow_layer.addAnimation_forKey_(
            _make_blob_axis_anim("transform.scale.y", [1.00, 1.26, 0.84, 1.14, 0.92, 1.04, 1.00], duration),
            "glow_blob_y"
        )
        glow_layer.addAnimation_forKey_(_make_blob_opacity_anim(duration), "glow_fade")

    elif state == "transcribing":
        label.setStringValue_("Transcribing…")
        # Faster flicker — 0.6s
        orb_layer.addAnimation_forKey_(_make_pulse_anim(0.95, 1.05, 0.6), "pulse")
        glow_layer.addAnimation_forKey_(_make_pulse_anim(0.9, 1.1, 0.6), "glow_pulse")
        glow_layer.addAnimation_forKey_(_make_opacity_anim(0.5, 1.0, 0.4), "glow_fade")

    elif state == "polishing":
        label.setStringValue_("Polishing…")
        # Medium swirl — 1.1s
        orb_layer.addAnimation_forKey_(_make_pulse_anim(0.93, 1.07, 1.1), "pulse")
        glow_layer.addAnimation_forKey_(_make_pulse_anim(0.88, 1.12, 1.1), "glow_pulse")
        glow_layer.addAnimation_forKey_(_make_opacity_anim(0.6, 1.0, 1.1), "glow_fade")

    elif state == "done":
        label.setStringValue_("Done ✓")
        # Brief expand then settle
        orb_layer.addAnimation_forKey_(_make_pulse_anim(1.0, 1.12, 0.3, repeat=False), "pop")
        # Schedule hide after 1.8s
        _hide_at[0] = time.monotonic() + 1.8


# ── Timer — runs in run loop, handles auto-hide ───────────────────────────────

class TimerTarget(AppKit.NSObject):
    def tick_(self, _timer):
        if _hide_at[0] and time.monotonic() >= _hide_at[0]:
            _hide_at[0] = None
            _stop_anims()
            panel.setAlphaValue_(0.0)
            label.setStringValue_("")


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

threading.Thread(target=_stdin_reader, daemon=True).start()

# ── Run ───────────────────────────────────────────────────────────────────────

app.run()
