#!/usr/bin/env python3
"""
calibrate_web.py

A web-based calibration tool for adjusting the degree movement per pixel.
It uses Picamera2 to capture images, a Flask web server to serve a web page,
and allows you to click on the image to specify a target point.
The script then calculates the required pan/tilt adjustments (using the same
calculation as in your main program) and moves the camera.
After the move, a new image is shown for comparison.

On startup, the camera is moved to its home position (as defined in your configuration).
"""

import time
import cv2
from flask import Flask, render_template, Response, request, jsonify
from picamera2 import Picamera2
import pan_tilt_control  # Your pan/tilt control module
import my_configuration as config  # Your configuration file

# Calibration parameters from configuration
PAN_DEG_PER_PIXEL = config.PAN_DEG_PER_PIXEL
TILT_DEG_PER_PIXEL = config.TILT_DEG_PER_PIXEL
PAN_INVERT = config.PAN_INVERT
TILT_INVERT = config.TILT_INVERT

app = Flask(__name__)

# Initialize and configure Picamera2 using the resolution from your config.
# (Your main program uses config.MAIN_STREAM_RESOLUTION for configuration.)
picam2 = Picamera2()
preview_config = picam2.create_preview_configuration(main={"size": config.MAIN_STREAM_RESOLUTION})
picam2.configure(preview_config)
picam2.start()
time.sleep(1)  # Allow time for auto exposure/white balance to settle

# Get the actual main stream resolution (this should match what your main program uses)
main_resolution = picam2.stream_configuration("main")["size"]


@app.route("/")
def index():
    # Render the calibration page, passing the actual main resolution and a timestamp.
    return render_template("index_calibrate.html",
                           timestamp=time.time(),
                           main_resolution=main_resolution)


@app.route("/capture_image")
def capture_image():
    """
    Capture an image from the camera and return it as a JPEG.
    This endpoint is used by the web page to populate the canvases.
    """
    try:
        img = picam2.capture_array("main")
    except Exception as e:
        return f"Error capturing image: {e}", 500

    ret, jpeg = cv2.imencode('.jpg', img)
    if not ret:
        return "Failed to encode image", 500
    return Response(jpeg.tobytes(), mimetype="image/jpeg")


@app.route("/calibrate", methods=["POST"])
def calibrate():
    """
    Receives JSON data with the clicked (x, y) coordinates (in full-resolution pixels),
    calculates the offset from the center of the main stream (as computed by the camera),
    applies the degrees-per-pixel conversion (with inversion if needed), and commands
    the camera to move.

    Returns:
      - The current angles,
      - The pixel offset (x and y),
      - The calculated delta (in degrees),
      - The new angles,
      - And a message.
    """
    data = request.get_json()
    if not data or "x" not in data or "y" not in data:
        return jsonify({"error": "Missing coordinates"}), 400

    try:
        x = float(data["x"])
        y = float(data["y"])
    except Exception:
        return jsonify({"error": "Invalid coordinates"}), 400

    main_w, main_h = main_resolution
    center_x = main_w / 2.0
    center_y = main_h / 2.0

    # Compute the pixel offset from the center (exactly as in your main code)
    offset_x = x - center_x
    offset_y = y - center_y

    # Calculate the required angle adjustments (in degrees)
    delta_pan = offset_x * PAN_DEG_PER_PIXEL
    delta_tilt = offset_y * TILT_DEG_PER_PIXEL
    if PAN_INVERT:
        delta_pan = -delta_pan
    if TILT_INVERT:
        delta_tilt = -delta_tilt

    # Get current angles from your pan_tilt_control module
    current_pan, current_tilt = pan_tilt_control.get_current_angles()
    new_pan = current_pan + delta_pan
    new_tilt = current_tilt + delta_tilt

    # Command the camera to move to the new angles (using your existing move_to function)
    pan_tilt_control.move_to(new_pan, new_tilt)
    time.sleep(2)  # Allow time for the move to complete

    response = {
        "current_angles": {"pan": current_pan, "tilt": current_tilt},
        "pixel_offset": {"x": offset_x, "y": offset_y},
        "delta": {"pan": delta_pan, "tilt": delta_tilt},
        "new_angles": {"pan": new_pan, "tilt": new_tilt},
        "message": "Camera moved. See the updated view below."
    }
    return jsonify(response)


if __name__ == "__main__":
    # On startup, move the camera to its home position as specified in your config.
    # If HOME_PAN or HOME_TILT are not defined, default to 0.
    home_pan = getattr(config, "HOME_PAN", 0)
    home_tilt = getattr(config, "HOME_TILT", 0)
    print(f"Moving camera to home position: pan {home_pan}, tilt {home_tilt}")
    pan_tilt_control.move_to(home_pan, home_tilt)

    # Run the Flask app with the reloader disabled to prevent double initialization.
    app.run(host="0.0.0.0", port=5000, debug=True, use_reloader=False)
