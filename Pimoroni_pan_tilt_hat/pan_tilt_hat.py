"""
pan_tilt_control.py

A small library for controlling a Pan-Tilt rig whose wiring is reversed:
- 'pantilthat.pan(x)' physically moves the TILT servo
- 'pantilthat.tilt(x)' physically moves the PAN servo

Logical angles (pan, tilt):
- 'pan' = left/right (negative => left, positive => right)
- 'tilt' = up/down   (negative => down, positive => up)

Exposes functions:
  left(deg, steps=10, step_delay=0.05)
  right(deg, steps=10, step_delay=0.05)
  up(deg, steps=10, step_delay=0.05)
  down(deg, steps=10, step_delay=0.05)
  home(pan_angle, tilt_angle, steps=10, step_delay=0.05)
  get_current_angles()
"""

import pantilthat
import time


# Track our "logical" angles:
#   current_pan: left/right  (negative=left, positive=right)
#   current_tilt: up/down   (negative=down, positive=up)
current_pan = 0.0
current_tilt = 0.0

# We define servo's valid range in degrees:
PAN_MIN, PAN_MAX = -90.0, 90.0
TILT_MIN, TILT_MAX = -90.0, 90.0

def clamp_angle(angle, min_val=-90.0, max_val=90.0):
    """Clamp 'angle' within [min_val, max_val]."""
    if angle < min_val:
        return min_val
    elif angle > max_val:
        return max_val
    return angle

def move_to(pan_target, tilt_target, steps=10, step_delay=0.05):
    """
    Smoothly move from the *logical* angles (current_pan, current_tilt)
    to the *logical* angles (pan_target, tilt_target).

    Because of reversed wiring:
      - pantilthat.pan(...) physically controls the TILT servo.
      - pantilthat.tilt(...) physically controls the PAN servo.
    So we swap them when we send commands.

    We also clamp angles to [-90, +90] so we never pass an invalid value to pantilhat.
    """
    global current_pan, current_tilt

    # Clamp the final targets to safe range
    pan_target = clamp_angle(pan_target, PAN_MIN, PAN_MAX)
    tilt_target = clamp_angle(tilt_target, TILT_MIN, TILT_MAX)

    # Calculate total distance to move
    pan_delta = pan_target - current_pan
    tilt_delta = tilt_target - current_tilt

    for i in range(1, steps + 1):
        # Interpolate for smooth movement
        new_pan = current_pan + (pan_delta * i / steps)
        new_tilt = current_tilt + (tilt_delta * i / steps)

        # Also clamp the intermediate angles so we never exceed [-90, +90] mid-way
        new_pan = clamp_angle(new_pan, PAN_MIN, PAN_MAX)
        new_tilt = clamp_angle(new_tilt, TILT_MIN, TILT_MAX)

        # REVERSED LOGIC:
        #   pantilthat.pan(...) => physically TILT
        #   pantilthat.tilt(...) => physically PAN
        pantilthat.pan(new_tilt)  # physically up/down
        pantilthat.tilt(new_pan)  # physically left/right

        time.sleep(step_delay)

    # Update stored angles
    current_pan = pan_target
    current_tilt = tilt_target

def get_current_angles():
    """
    Return the logical (pan, tilt) in degrees.
    """
    return (current_pan, current_tilt)

def left(deg, steps=10, step_delay=0.05):
    """
    Move left by 'deg' degrees.
    Negative pan is left, so pan_target = current_pan - deg.
    """
    global current_pan, current_tilt
    pan_target = current_pan - deg
    tilt_target = current_tilt
    move_to(pan_target, tilt_target, steps=steps, step_delay=step_delay)

def right(deg, steps=10, step_delay=0.05):
    """
    Move right by 'deg' degrees.
    Positive pan is right, so pan_target = current_pan + deg.
    """
    global current_pan, current_tilt
    pan_target = current_pan + deg
    tilt_target = current_tilt
    move_to(pan_target, tilt_target, steps=steps, step_delay=step_delay)

def up(deg, steps=10, step_delay=0.05):
    """
    Move up by 'deg' degrees.
    If physically reversed, we do tilt_target = current_tilt - deg.
    """
    global current_pan, current_tilt
    tilt_target = current_tilt - deg  # physically goes up
    pan_target = current_pan
    move_to(pan_target, tilt_target, steps=steps, step_delay=step_delay)

def down(deg, steps=10, step_delay=0.05):
    """
    Move down by 'deg' degrees.
    If physically reversed, we do tilt_target = current_tilt + deg.
    """
    global current_pan, current_tilt
    tilt_target = current_tilt + deg  # physically goes down
    pan_target = current_pan
    move_to(pan_target, tilt_target, steps=steps, step_delay=step_delay)

def home(pan_angle, tilt_angle, steps=10, step_delay=0.05):
    """
    Move directly to logical (pan_angle, tilt_angle).
    e.g. home(0, -60) => pan=0°, tilt=-60° logically.
    """
    move_to(pan_angle, tilt_angle, steps=steps, step_delay=step_delay)