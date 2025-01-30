#!/usr/bin/env python3

# --------------------------------------------------------------------------------
#  Import Required Packages
# --------------------------------------------------------------------------------

import my_configuration as config
from flask import Flask, render_template, Response, request, send_from_directory, jsonify
import logging
import sys
import threading
import time
from collections import deque
import cv2
import numpy as np
import pan_tilt_control  # Must be your existing file: "pan_tilt_control.py"
from functools import lru_cache
from picamera2 import MappedArray, Picamera2
from picamera2.devices import IMX500
from picamera2.devices.imx500 import (NetworkIntrinsics,
                                      postprocess_nanodet_detection)
from libcamera import Transform
import RPi.GPIO as GPIO

import os
import subprocess
import math
import psutil
import platform
import importlib.metadata

# --------------------------------------------------------------------------------
#  TUNING PARAMETERS (SET FROM my_confgiuration.py)
# --------------------------------------------------------------------------------

PAN_DEG_PER_PIXEL = config.PAN_DEG_PER_PIXEL
TILT_DEG_PER_PIXEL = config.TILT_DEG_PER_PIXEL
PAN_INVERT = config.PAN_INVERT
TILT_INVERT = config.TILT_INVERT
DEAD_ZONE = config.DEAD_ZONE
HOME_PAN  = config.HOME_PAN
HOME_TILT = config.HOME_TILT
MOVE_STEPS = config.MOVE_STEPS
MOVE_STEP_DELAY = config.MOVE_STEP_DELAY
SHOW_PREVIEW = config.SHOW_PREVIEW
SAVE_DIRECTORY = config.SAVE_DIRECTORY_NAME
DELETE_CONVERTED_FILES = config.DELETE_CONVERTED_FILES

# -----------------------------------------------------------------------------
#  LOGGING SETUP
# -----------------------------------------------------------------------------

logger = logging.getLogger("my_app_logger")
numeric_level = getattr(logging, config.LOG_LEVEL.upper(), logging.INFO)
logger.setLevel(numeric_level)
console_handler = logging.StreamHandler(sys.stdout)
console_handler.setLevel(numeric_level)

formatter = logging.Formatter(
    fmt="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S"
)
console_handler.setFormatter(formatter)
logger.addHandler(console_handler)

# If we also want to log to a file
if config.LOG_FILE:
    file_handler = logging.FileHandler(config.LOG_FILE)
    file_handler.setLevel(numeric_level)
    file_handler.setFormatter(formatter)
    logger.addHandler(file_handler)




# Added for manual control and settgins
auto_mode = True  # starts in auto mode
manual_home_pan = HOME_PAN
manual_home_tilt = HOME_TILT

# -----------------------------------------------------------------------------
#  Auto detection of Platform
# -----------------------------------------------------------------------------
def detect_platform():
    """
    Reads /proc/device-tree/model and sets config.RASPBERRY_PI_ZERO_2W
    to True if it's a Raspberry Pi Zero 2 W, otherwise False.
    Logs the detected platform via logger.info.
    """
    model_str = "Unknown Platform"
    model_path = "/proc/device-tree/model"

    if os.path.exists(model_path):
        with open(model_path, "r") as f:
            model_str = f.read().strip()

    logger.info(f"Detected Platform - {model_str}")

    # Set config.RASPBERRY_PI_ZERO_2W based on substring match
    config.RASPBERRY_PI_ZERO_2W = ("Raspberry Pi Zero 2 W" in model_str)

detect_platform()
if config.RASPBERRY_PI_ZERO_2W:
    logger.info("This is a Raspberry Pi Zero 2 W, enabling Pi Zero optimizations...")
else:
    logger.info("Not a Pi Zero 2 W, using normal behavior.")


# -----------------------------------------------------------------------------
#  Web Server settings, Functions and Routes
# -----------------------------------------------------------------------------
app = Flask(__name__)
latest_frame = None  # We'll store the latest camera frame in memory

def get_cpu_temperature():
    """Return CPU temperature in °C if available, otherwise None."""
    temp_path = "/sys/class/thermal/thermal_zone0/temp"
    if os.path.exists(temp_path):
        try:
            with open(temp_path, "r") as f:
                millideg = f.read().strip()
                return float(millideg) / 1000.0  # convert from millideg to °C
        except Exception:
            pass
    return None

def get_platform_name():
    """
    Return the platform name from /proc/device-tree/model if available,
    else a fallback to platform.platform().
    """
    model_path = "/proc/device-tree/model"
    if os.path.exists(model_path):
        try:
            with open(model_path, "r") as f:
                return f.read().strip()
        except Exception:
            pass
    # Fallback for non-Raspberry Pi or missing file
    return platform.platform()

def start_web_server():
    # Run Flask dev server on port 5000 (or any port you want)
    app.run(host="0.0.0.0", port=5000, debug=False, threaded=True)

def gen_frames():
    """
    Generator function that captures the latest_frame,
    encodes it as JPEG, and yields it as an HTTP response chunk (MJPEG).
    """
    global latest_frame
    while True:
        if latest_frame is not None:
            # Encode as JPEG
            ret, buffer = cv2.imencode('.jpg', latest_frame)
            if not ret:
                continue  # skip if encoding failed

            # Convert to bytes
            frame_bytes = buffer.tobytes()

            # MJPEG framing
            yield (b'--frame\r\n'
                   b'Content-Type: image/jpeg\r\n\r\n' + frame_bytes + b'\r\n')
        else:
            # If no frame yet, just sleep briefly
            time.sleep(0.05)

@app.route("/system_info")
def system_info():
    # 1) Temperature
    temperature = get_cpu_temperature()

    # 2) CPU usage (percentage)
    cpu_usage = psutil.cpu_percent(interval=0.1)

    # 3) Memory info
    mem = psutil.virtual_memory()
    mem_total_mb = mem.total / (1024 * 1024)
    mem_used_mb  = mem.used  / (1024 * 1024)
    mem_free_mb  = mem.available / (1024 * 1024)

    # 4) Swap info
    swap = psutil.swap_memory()
    swap_total_mb = swap.total / (1024 * 1024)
    swap_used_mb  = swap.used  / (1024 * 1024)

    # 5) Root filesystem disk usage
    disk = psutil.disk_usage('/')
    disk_total_mb = disk.total / (1024 * 1024)
    disk_used_mb  = disk.used  / (1024 * 1024)
    disk_free_mb  = disk.free  / (1024 * 1024)

    # 6) Platform name (Pi model or fallback)
    platform_name = get_platform_name()

    # 7) OS version (e.g. "Linux-6.1.21-v7+-armv7l-with-glibc2.31")
    os_version = platform.platform()

    # 8) Python version (e.g. "3.9.2")
    python_version = platform.python_version()

    data = {
        "temperature": temperature,      # float or None
        "cpu_usage": cpu_usage,          # float
        "memory": {
            "total_mb": round(mem_total_mb, 2),
            "used_mb":  round(mem_used_mb,  2),
            "free_mb":  round(mem_free_mb,  2),
        },
        "swap": {
            "total_mb": round(swap_total_mb, 2),
            "used_mb":  round(swap_used_mb,  2),
        },
        "disk": {
            "total_mb": round(disk_total_mb, 2),
            "used_mb":  round(disk_used_mb,  2),
            "free_mb":  round(disk_free_mb, 2),
        },
        "platform_name": platform_name,
        "os_version": os_version,
        "python_version": python_version,
    }

    return jsonify(data)


@app.route("/packages")
def list_packages():
    """
    Returns a JSON mapping of {package_name: version} for all installed packages
    in the current Python environment, using importlib.metadata.
    """
    # Retrieve all distributions
    distributions = importlib.metadata.distributions()

    installed = {}
    for dist in distributions:
        # dist.metadata is an email.message.Message object
        # dist.metadata["Name"] and dist.metadata["Version"] are standard fields
        name = dist.metadata["Name"]
        version = dist.metadata["Version"]
        installed[name] = version

    # Sort by package name (case-insensitive) for cleaner output
    sorted_installed = dict(sorted(installed.items(), key=lambda x: x[0].lower()))

    return jsonify(sorted_installed)

@app.route("/system")
def system_page():
    """
    Renders the 'system.html' template which shows CPU/Memory/Disk stats,
    Raspberry Pi info, etc.
    """
    return render_template("system.html")

@app.route("/status")
def status():
    """
    Returns a JSON response containing the current status of the system:
    - auto_mode: boolean (True for auto, False for manual)
    - is_recording: boolean (current recording state)
    - water_pistol_active: boolean (whether the water pistol is firing)
    - current_pan_angle: float
    - current_tilt_angle: float
    """
    current_pan, current_tilt = pan_tilt_control.get_current_angles()

    data = {
        "auto_mode": auto_mode,                          # True/False
        "is_recording": recording_manager.recording,     # True/False
        "water_pistol_active": water_pistol.active,      # True/False
        "current_pan_angle": current_pan,                # numeric value
        "current_tilt_angle": current_tilt,              # numeric value
    }
    return jsonify(data)


@app.route("/recordings")
def show_recordings():
    page = request.args.get("page", 1, type=int)  # Get ?page=<int>, default to 1
    page_size = 5  # Show 5 recordings per page

    # Get all MP4s
    all_files = [
        f for f in os.listdir(SAVE_DIRECTORY)
        if f.lower().endswith(".mp4")
    ]
    # Sort by modification time descending (newest first)
    all_files.sort(
        key=lambda x: os.path.getmtime(os.path.join(SAVE_DIRECTORY, x)),
        reverse=True
    )

    # Convert to a list of dicts: {filename, datetime_str}
    # so the template can show the date/time easily.
    all_file_info = []
    for f in all_files:
        file_path = os.path.join(SAVE_DIRECTORY, f)
        mtime = os.path.getmtime(file_path)
        # Format the mtime as "YYYY-MM-DD HH:MM:SS"
        datetime_str = time.strftime("%Y-%m-%d %H:%M:%S", time.localtime(mtime))
        all_file_info.append({
            "filename": f,
            "datetime_str": datetime_str
        })

    # Pagination logic
    total_files = len(all_file_info)
    total_pages = math.ceil(total_files / page_size)

    # Slice out the files for this page
    start_idx = (page - 1) * page_size
    end_idx = start_idx + page_size
    page_files = all_file_info[start_idx:end_idx]

    return render_template("recordings.html",
                           files=page_files,    # the 5 (or fewer) items for this page
                           page=page,
                           total_pages=total_pages)


@app.route("/video/<path:filename>")
def serve_video(filename):
    """
    Serve an MP4 file from SAVE_DIRECTORY.
    """
    return send_from_directory(SAVE_DIRECTORY, filename)


@app.route("/delete_recording", methods=["POST"])
def delete_recording():
    """
    Delete a recording file specified by JSON data: {"filename": "..."}
    Returns JSON {"status": "ok"} on success, or {"status": "error"} on failure.
    """
    data = request.get_json()
    if not data or "filename" not in data:
        return jsonify({"status": "error", "message": "No filename provided"}), 400

    filename = data["filename"]
    file_path = os.path.join(SAVE_DIRECTORY, filename)

    if not os.path.exists(file_path):
        return jsonify({"status": "error", "message": "File not found"}), 404

    try:
        os.remove(file_path)
        return jsonify({"status": "ok"})
    except Exception as e:
        logger.error(f"Error deleting file {filename}: {e}")
        return jsonify({"status": "error", "message": str(e)}), 500

@app.route("/set_mode")
def set_mode():
    """
    Handles the HTTP route for setting the mode of operation between
    "auto" and "manual". The mode is determined from the query
    parameter 'mode'.
    """
    # e.g. /set_mode?mode=auto or /set_mode?mode=manual
    global auto_mode
    mode = request.args.get("mode", "auto")
    if mode.lower() == "auto":
        water_pistol.stop()
        pan_tilt_control.move_to(HOME_PAN, HOME_TILT, steps=config.MOVE_STEPS, step_delay=config.MOVE_STEP_DELAY)
        auto_mode = True
        logger.info("Switched to AUTO mode")
    else:
        auto_mode = False
        logger.info("Switched to MANUAL mode")
    return "OK"


@app.route("/move")
def move():
    """
    Handles the movement of a pan-tilt mechanism in response to HTTP requests. Movement
    is performed based on the direction parameter provided (e.g., up, down, left, right)
    and changes angles incrementally. The function does not allow movement if the system
    is in AUTO mode and performs necessary validations before attempting movement.

    """
    # e.g. /move?direction=up or left or right or down
    direction = request.args.get("direction", None)
    if auto_mode:
        return "Cannot move while in AUTO mode", 400

    if not direction:
        return "No direction provided", 400

    # Basic approach: small increments in angles
    step_degrees = 5.0

    current_pan, current_tilt = pan_tilt_control.get_current_angles()
    if direction == "down":
        new_tilt = current_tilt - step_degrees  # tilt decreases as you go up
        pan_tilt_control.move_to(current_pan, new_tilt, steps=config.MOVE_STEPS, step_delay=config.MOVE_STEP_DELAY)
    elif direction == "up":
        new_tilt = current_tilt + step_degrees
        pan_tilt_control.move_to(current_pan, new_tilt, steps=config.MOVE_STEPS, step_delay=config.MOVE_STEP_DELAY)
    elif direction == "right":
        new_pan = current_pan - step_degrees
        pan_tilt_control.move_to(new_pan, current_tilt, steps=config.MOVE_STEPS, step_delay=config.MOVE_STEP_DELAY)
    elif direction == "left":
        new_pan = current_pan + step_degrees
        pan_tilt_control.move_to(new_pan, current_tilt, steps=config.MOVE_STEPS, step_delay=config.MOVE_STEP_DELAY)
    else:
        return f"Unknown direction: {direction}", 400

    return "OK"
@app.route("/water_pistol")
def water_pistol_control():
    """
    Handles control of the water pistol via HTTP requests.

    This endpoint allows starting or stopping the water pistol
    based on the action sent as a query parameter in the request.
    Supported actions are "start" and "stop". If no action is
    specified or if an invalid action is provided, an appropriate
    error message is returned with an HTTP 400 status code.

    """
    # e.g. /water_pistol?action=start or stop
    action = request.args.get("action", None)
    if not action:
        return "No action specified", 400

    if action == "start":
        water_pistol.start()
    elif action == "stop":
        water_pistol.stop()
    else:
        return f"Unknown action: {action}", 400

    return "OK"


@app.route("/set_home")
def set_home():
    """
    Sets the current pan and tilt angles as the new AUTO home position.

    """
    global manual_home_pan, manual_home_tilt
    global HOME_PAN, HOME_TILT
    if auto_mode:
        return "Cannot set home in AUTO mode", 400

    # Read current angles
    current_pan, current_tilt = pan_tilt_control.get_current_angles()

    # Update the global home angles
    manual_home_pan = current_pan
    manual_home_tilt = current_tilt
    HOME_PAN = manual_home_pan
    HOME_TILT = manual_home_tilt

    logger.info(f"Set new manual home to Pan={manual_home_pan}, Tilt={manual_home_tilt}")
    return "OK"

@app.route('/')
def index():
    """Serve the main HTML page from the templates folder."""
    return render_template('index.html')

@app.route('/video_feed')
def video_feed():
    """Route that streams frames in MJPEG format."""
    return Response(gen_frames(),
                    mimetype='multipart/x-mixed-replace; boundary=frame')


# -----------------------------------------------------------------------------
#  Main Classes and Functions
# -----------------------------------------------------------------------------

def convert_saved_video(filename):
    """
    Convert the file passed in to MP4 format using ffmpeg (ensuring no quality is lost).
    The converted MP4 is saved into SAVE_DIRECTORY. If SAVE_DIRECTORY does not exist,
    it will be created.

    If DELETE_CONVERTED_FILES is True, the original file is deleted after conversion.

    :param filename: The path to the original video file (e.g., .h264) to convert
    """
    # Ensure save directory exists
    if not os.path.exists(SAVE_DIRECTORY):
        os.makedirs(SAVE_DIRECTORY)

    # Construct output filename with .mp4 extension inside SAVE_DIRECTORY
    base_name = os.path.splitext(os.path.basename(filename))[0]  # e.g., "capture_01_01_22_12_00_00"
    mp4_filename = os.path.join(SAVE_DIRECTORY, base_name + ".mp4")

    try:
        # Call ffmpeg to do a container copy (no re-encode) to avoid quality loss
        subprocess.run([
            "ffmpeg", "-i", filename,
            "-c:v", "copy",
            "-c:a", "copy",
            mp4_filename
        ], check=True)

        # If configured to delete original file, remove it
        if DELETE_CONVERTED_FILES:
            os.remove(filename)

        # Optionally log success if you have a logger
        logger.info(f"Converted {filename} to {mp4_filename} (DELETE_CONVERTED_FILES={DELETE_CONVERTED_FILES}).")

    except subprocess.CalledProcessError as e:
        logger.error(f"ffmpeg failed to convert {filename} to {mp4_filename}. Error: {e}")
        # If needed, handle the error more gracefully here





class PanTiltControllerWrapper:
    """
    A thin wrapper around pan_tilt_control.py that:
      - Maintains a lock or flag (is_moving) so we do not queue multiple moves.
      - Converts pixel offsets into angles and inverts direction if needed.
    """
    def __init__(self, move_steps, move_step_delay):
        self.is_moving = False
        self.move_steps = move_steps
        self.move_step_delay = move_step_delay

        # Home on initialization
        self.home()

    def home(self):
        """ Move to HOME_PAN, HOME_TILT immediately. """
        # You can do a blocking move here if you want:
        pan_tilt_control.move_to(
            HOME_PAN, HOME_TILT,
            steps=self.move_steps,
            step_delay=self.move_step_delay
        )

    def set_target_by_pixels(self, offset_x, offset_y):
        """
        offset_x, offset_y = difference in pixels from image center.
        If the rig is currently moving, skip any new commands.
        Otherwise, convert offsets to degrees and move.
        """
        if self.is_moving:
            # Skip if still moving
            return

        # Check dead zone
        if abs(offset_x) < DEAD_ZONE and abs(offset_y) < DEAD_ZONE:
            return  # No movement needed

        # Get current angles from pan_tilt_control
        current_pan, current_tilt = pan_tilt_control.get_current_angles()

        # Convert pixel offset to angle offset
        delta_pan = offset_x * PAN_DEG_PER_PIXEL
        delta_tilt = offset_y * TILT_DEG_PER_PIXEL

        # Invert if needed
        if PAN_INVERT:
            delta_pan = -delta_pan
        if TILT_INVERT:
            delta_tilt = -delta_tilt

        new_pan_angle = current_pan + delta_pan
        new_tilt_angle = current_tilt + delta_tilt

        # Now we actually move in a separate thread so we don't block.
        def do_move():
            self.is_moving = True
            pan_tilt_control.move_to(
                new_pan_angle,
                new_tilt_angle,
                steps=self.move_steps,
                step_delay=self.move_step_delay
            )
            self.is_moving = False

        t = threading.Thread(target=do_move, daemon=True)
        t.start()

    def move_home_async(self):
        """Non-blocking home call."""
        if self.is_moving:
            return
        def do_home():
            self.is_moving = True
            pan_tilt_control.move_to(
                HOME_PAN, HOME_TILT,
                #steps=self.move_steps,
                #step_delay=self.move_step_delay
                steps=config.MOVE_STEPS,
                step_delay=config.MOVE_STEP_DELAY
            )
            self.is_moving = False
        t = threading.Thread(target=do_home, daemon=True)
        t.start()


class WaterPistolController:
    """
    Controls a water pistol by toggling a relay module using GPIO pins.

    This class provides methods to start and stop the water pistol by activating and
    deactivating the relay pin. It also ensures proper GPIO configuration as well as
    cleanup.

    """
    def __init__(self, pin=config.REPLAY_PIN):
        self.active = False
        self.relay_pin = pin

        # Set up GPIO
        GPIO.setmode(GPIO.BCM)
        GPIO.setup(self.relay_pin, GPIO.OUT)

        # Ensure relay starts in OFF state
        GPIO.output(self.relay_pin, GPIO.LOW)

    def start(self):
        if not self.active:
            self.active = True
            # Turn relay ON
            GPIO.output(self.relay_pin, GPIO.HIGH)
            logger.info("WaterPistol - Started firing!!.")

    def stop(self):
        if self.active:
            self.active = False
            # Turn relay OFF
            GPIO.output(self.relay_pin, GPIO.LOW)
            logger.info("WaterPistol - Stopped firing.")

    def cleanup(self):
        """Clean up GPIO settings - should be called when program exits"""
        GPIO.cleanup()

def convert_saved_video_async(filename):
    """
        Converts the saved video to a different format asynchronously.

        The function initiates a background thread to convert a saved video
        file to the desired format without blocking the main thread's execution.
        It is helpful for Raspberry PI zero2w which doe snot have alot of resources

        Args:
            filename (str): The path of the video file to be converted.

        Returns:
            None
    """
    def convert():
        convert_saved_video(filename)
    threading.Thread(target=convert, daemon=True).start()



class RecordingManager:
    """
    Provides functionality to manage video recording via a Picamera2 instance.

    The RecordingManager class serves as a utility to handle video recordings, including
    configuring encoders, defining file outputs with timestamped filenames, and managing
    the recording state. Its primary purpose is to integrate and simplify the recording
    capabilities afforded by the Picamera2 library.

    """
    def __init__(self, picam2):
        from picamera2.encoders import H264Encoder
        from picamera2.outputs import FileOutput
        self.picam2 = picam2
        self.recording = False
        self.encoder = H264Encoder()
        self.output_class = FileOutput
        self.filename = None  # Will set each time we start recording

    def start_recording(self):
        if not self.recording:
            timestamp = time.strftime("%d_%m_%y_%H_%M_%S")
            self.filename = f"capture_{timestamp}.h264"
            logger.info(f"[RecordingManager] Starting recording to {self.filename}...")
            self.output = self.output_class(self.filename)
            self.picam2.start_recording(self.encoder, self.output)
            self.recording = True

    def stop_recording(self):
        if self.recording:
            logger.info("[RecordingManager] Stopping recording...")
            self.picam2.stop_recording()
            self.recording = False

            #Now convert the file
            if config.RASPBERRY_PI_ZERO_2W == False:
                convert_saved_video(self.filename)
            else:
                convert_saved_video_async(self.filename)



class TargetTracker:
    """
    Tracks the presence of a target based on detection timestamps within a defined time
    window. The tracker uses a threshold of detections within the time window to activate,
    and a timeout period to deactivate when no detections occur. This class is designed
    for scenarios where real-time activation and deactivation based on detection events
    are required.

    """
    def __init__(self, activation_detections, activation_time_window, no_detection_timeout):
        self.activation_detections = activation_detections
        self.activation_time_window = activation_time_window
        self.no_detection_timeout = no_detection_timeout
        self.detection_timestamps = deque()
        self.target_acquired = False
        self.last_detection_time = None

    def update_detections(self, has_detections):
        now = time.time()
        if has_detections:
            self.detection_timestamps.append(now)
            self.last_detection_time = now
            # Remove old timestamps
            while self.detection_timestamps and (now - self.detection_timestamps[0]) > self.activation_time_window:
                self.detection_timestamps.popleft()

            # Check activation threshold
            if (not self.target_acquired) and (len(self.detection_timestamps) >= self.activation_detections):
                self.target_acquired = True
                logger.info("[TargetTracker] Target acquired!")
        else:
            if self.target_acquired and self.last_detection_time is not None:
                if (now - self.last_detection_time) > self.no_detection_timeout:
                    self.target_acquired = False
                    self.detection_timestamps.clear()
                    logger.info("[TargetTracker] Target lost due to no detections.")
        return self.target_acquired

    def is_target_acquired(self):
        return self.target_acquired


# Store the last set of detections globally (like original code)
last_detections = []


class Detection:
    def __init__(self, coords, category, conf, metadata, picam2, imx500):
        """
        Create a Detection object, recording the bounding box, category, and confidence.
        """
        self.category = category
        self.conf = conf
        self.box = imx500.convert_inference_coords(coords, metadata, picam2)


def parse_detections(metadata: dict, imx500, intrinsics, picam2):
    """
    Parses and processes the detection metadata produced by an image sensor.
    This function applies postprocessing to detection metadata, converts bounding
    box formats, scales bounding boxes according to the input resolution, and
    filters the results based on confidence scores and maximum allowed detections.
    It returns a list containing the processed detections.

    """
    global last_detections
    bbox_normalization = intrinsics.bbox_normalization
    bbox_order = intrinsics.bbox_order
    threshold = config.THRESHOLD
    iou = config.IOU
    max_detections = config.MAX_DETECTIONS

    np_outputs = imx500.get_outputs(metadata, add_batch=True)
    input_w, input_h = imx500.get_input_size()
    if np_outputs is None:
        return last_detections

    if intrinsics.postprocess == "nanodet":
        boxes, scores, classes = postprocess_nanodet_detection(
            outputs=np_outputs[0],
            conf=threshold,
            iou_thres=iou,
            max_out_dets=max_detections
        )[0]
        from picamera2.devices.imx500.postprocess import scale_boxes
        boxes = scale_boxes(boxes, 1, 1, input_h, input_w, False, False)
    else:
        boxes, scores, classes = np_outputs[0][0], np_outputs[1][0], np_outputs[2][0]
        if bbox_normalization:
            boxes = boxes / input_h
        if bbox_order == "xy":
            # switch from (y0, x0, y1, x1) => (x0, y0, x1, y1)
            boxes = boxes[:, [1, 0, 3, 2]]
        boxes = np.array_split(boxes, 4, axis=1)
        boxes = zip(*boxes)

    new_detections = [
        Detection(box, category, score, metadata, picam2, imx500)
        for box, score, category in zip(boxes, scores, classes)
        if score > threshold
    ]
    last_detections = new_detections
    return last_detections


@lru_cache
def get_labels(intrinsics):
    labels = intrinsics.labels
    if intrinsics.ignore_dash_labels:
        labels = [label for label in labels if label and label != "-"]
    return labels


def draw_detections(request, stream, intrinsics, recording_manager, imx500, last_results):
    """
    Draws detection annotations and indicators on an image using OpenCV based on
    input detection results and the state of a recording session.

    This function modifies the visual representation of a frame, drawing bounding
    boxes, labels, and crosshairs based on whether a recording session is active
    and whether a specific crosshair intersects an object detection. It also adapts
    its drawing logic according to certain conditions such as the results of object
    detection, recording state, and the position of the camera intrinsics.

    """
    if last_results is None:
        return
    labels = get_labels(intrinsics)
    recording = recording_manager.recording

    with MappedArray(request, stream) as m:
        height, width, _ = m.array.shape
        center_x = width // 2
        center_y = height // 2

        # Check if crosshair is inside any bounding box
        inside_box = False
        if recording and len(last_results) > 0:
            for det in last_results:
                x, y, w, h = det.box
                if x <= center_x <= x + w and y <= center_y <= y + h:
                    inside_box = True
                    break

        # Drawing logic depending on "recording" and "inside_box"
        if not recording:
            # Not recording => green boxes, label text in top-right
            box_color = (0, 255, 0)
            label_bg_color = (0, 255, 0)
            label_text_color = (255, 255, 255)

            # Draw bounding boxes
            for det in last_results:
                x, y, w, h = det.box
                cv2.rectangle(m.array, (x, y), (x + w, y + h), box_color, 2)

            # Draw labels near top-right
            label_x = width - 10
            label_y = 30
            for det in last_results:
                label_text = f"{labels[int(det.category)]} ({det.conf:.2f})"
                logger.debug(label_text)
                (text_width, text_height), baseline = cv2.getTextSize(
                    label_text, cv2.FONT_HERSHEY_SIMPLEX, 0.5, 1
                )
                text_start_x = label_x - text_width
                text_start_y = label_y

                cv2.rectangle(
                    m.array,
                    (text_start_x, text_start_y - text_height - baseline),
                    (text_start_x + text_width, text_start_y + baseline),
                    label_bg_color,
                    cv2.FILLED
                )
                cv2.putText(
                    m.array, label_text,
                    (text_start_x, text_start_y),
                    cv2.FONT_HERSHEY_SIMPLEX,
                    0.5, label_text_color, 1
                )
                label_y += text_height + baseline + 10

        else:
            # Recording => crosshair, color depends on inside_box
            if inside_box:
                crosshair_color = (255, 0, 0)  # red
                box_color = (255, 0, 0)        # red
                label_bg_color = (255, 0, 0)   # red
                bottom_text = "AQUIRED"
                bottom_bg_color = (255, 0, 0)
            else:
                crosshair_color = (0, 255, 0)  # green
                box_color = (0, 255, 0)        # green
                label_bg_color = (0, 255, 0)   # green
                bottom_text = "TRACKING"
                bottom_bg_color = (0, 255, 0)

            label_text_color = (255, 255, 255)

            # Draw bounding boxes + labels at top-left of each box
            for det in last_results:
                x, y, w, h = det.box
                cv2.rectangle(m.array, (x, y), (x + w, y + h), box_color, 2)

                label_text = f"{labels[int(det.category)]} ({det.conf:.2f})"
                logger.debug(label_text)
                (text_width, text_height), baseline = cv2.getTextSize(
                    label_text, cv2.FONT_HERSHEY_SIMPLEX, 1.0, 1
                )
                label_x = x + 5
                label_y = y + text_height + 5

                cv2.rectangle(
                    m.array,
                    (label_x, label_y - text_height - baseline),
                    (label_x + text_width, label_y + baseline),
                    label_bg_color,
                    cv2.FILLED
                )
                cv2.putText(
                    m.array, label_text,
                    (label_x, label_y),
                    cv2.FONT_HERSHEY_SIMPLEX,
                    1.0, label_text_color, 1
                )

            # Draw crosshair
            line_length = 30
            thickness = 4
            cv2.line(
                m.array,
                (center_x - line_length, center_y),
                (center_x + line_length, center_y),
                crosshair_color, thickness
            )
            cv2.line(
                m.array,
                (center_x, center_y - line_length),
                (center_x, center_y + line_length),
                crosshair_color, thickness
            )

            # Bottom text
            (bt_text_width, bt_text_height), bt_baseline = cv2.getTextSize(
                bottom_text, cv2.FONT_HERSHEY_SIMPLEX, 2.0, 2
            )
            text_x = (width - bt_text_width) // 2
            text_y = height - 20
            cv2.rectangle(
                m.array,
                (text_x, text_y - bt_text_height - bt_baseline),
                (text_x + bt_text_width, text_y + bt_baseline),
                bottom_bg_color,
                cv2.FILLED
            )
            cv2.putText(
                m.array, bottom_text,
                (text_x, text_y),
                cv2.FONT_HERSHEY_SIMPLEX,
                2.0, (255, 255, 255), 2
            )

        # If preserve_aspect_ratio => draw ROI
        if intrinsics.preserve_aspect_ratio:
            b_x, b_y, b_w, b_h = imx500.get_roi_scaled(request)
            color = (255, 0, 0)  # red
            cv2.putText(
                m.array, "ROI",
                (b_x + 5, b_y + 15),
                cv2.FONT_HERSHEY_SIMPLEX, 0.5, color, 1
            )
            cv2.rectangle(
                m.array, (b_x, b_y), (b_x + b_w, b_y + b_h),
                color, 2
            )

# -----------------------------------------------------------------------------
#  Main Program logic
# -----------------------------------------------------------------------------

if __name__ == "__main__":

    # Initialize IMX500
    imx500 = IMX500(config.MODEL)
    intrinsics = imx500.network_intrinsics
    if not intrinsics:
        intrinsics = NetworkIntrinsics()
        intrinsics.task = "object detection"
    elif intrinsics.task != "object detection":
        logger.info("Network is not an object detection task")
        sys.exit(1)

    # 1) Set intrinsics.labels from config.LABELS if available;
    #    otherwise, use "assets/coco_labels.txt".
    if config.LABELS:
        with open(config.LABELS, "r") as f:
            intrinsics.labels = f.read().splitlines()
    else:
        with open("assets/coco_labels.txt", "r") as f:
            intrinsics.labels = f.read().splitlines()

    # 2) Assign other recognized intrinsics fields from config
    if hasattr(intrinsics, "ignore_dash_labels"):
        intrinsics.ignore_dash_labels = config.IGNORE_DASH_LABELS

    if hasattr(intrinsics, "postprocess"):
        intrinsics.postprocess = config.POSTPROCESS

    if hasattr(intrinsics, "bbox_normalization"):
        intrinsics.bbox_normalization = config.BBOX_NORMALIZATION

    if hasattr(intrinsics, "bbox_order"):
        intrinsics.bbox_order = config.BBOX_ORDER

    if hasattr(intrinsics, "preserve_aspect_ratio"):
        intrinsics.preserve_aspect_ratio = config.PRESERVE_ASPECT_RATIO


    # 3) Finalize intrinsics with any missing defaults
    intrinsics.update_with_defaults()

    # 4) If we want to print intrinsics and exit
    if config.PRINT_INTRINSICS:
        logger.info(intrinsics)
        print(intrinsics)
        sys.exit(0)

    # Picamera2 setup
    picam2 = Picamera2(imx500.camera_num)
    video_config = picam2.create_video_configuration(
        main={"size": config.MAIN_STREAM_RESOLUTION},
        lores={"size": config.LOW_RES_STREAM_RESOLUTION, "format": "YUV420"},  # low-res for web streaming
        controls={"FrameRate": intrinsics.inference_rate},
        buffer_count=12,
        transform=Transform(hflip=config.FLIP_HORIZONTALLY, vflip=config.FLIP_VERTICALLY)
    )
    picam2.configure(video_config)
    picam2.start(show_preview=SHOW_PREVIEW)

    if intrinsics.preserve_aspect_ratio:
        imx500.set_auto_aspect_ratio()

    last_results = None

    # Instantiate controllers
    pan_tilt = PanTiltControllerWrapper(MOVE_STEPS, MOVE_STEP_DELAY)
    water_pistol = WaterPistolController()
    recording_manager = RecordingManager(picam2)

    # Target tracking
    activation_detections = config.ACTIVATION_DETECTIONS
    activation_time_window = config.ACTIVATION_TIME_WINDOW
    no_detection_timeout = config.NO_DETECTION_TIMEOUT
    target_tracker = TargetTracker(activation_detections, activation_time_window, no_detection_timeout)

    #Set frame fro web streaming
    latest_frame = None

    def pre_callback(request):
        global latest_frame
        draw_detections(
            request, stream="main",
            intrinsics=intrinsics,
            recording_manager=recording_manager,
            imx500=imx500,
            last_results=last_results
        )
        #Capture the low res frame
        with MappedArray(request, "lores") as lores_m:
            # Convert YUV to BGR so we can serve it with OpenCV
            lores_frame = cv2.cvtColor(lores_m.array, cv2.COLOR_YUV2BGR_I420)
            latest_frame = lores_frame.copy()

    picam2.pre_callback = pre_callback

    logger.info("Starting main loop...")

    flask_thread = threading.Thread(target=start_web_server, daemon=True)
    flask_thread.start()

    while True:
        # Retrieve metadata => parse detections => update last_results
        metadata = picam2.capture_metadata()
        current_detections = parse_detections(metadata, imx500, intrinsics, picam2)
        last_results = current_detections

        if auto_mode:
            # Check if we have any detections
            has_detections = len(current_detections) > 0
            was_target_acquired = target_tracker.is_target_acquired()
            target_tracker.update_detections(has_detections)
            is_target_acquired = target_tracker.is_target_acquired()

            # Transition: target just acquired
            if is_target_acquired and not was_target_acquired:
                recording_manager.start_recording()
                water_pistol.start()

            # If target is acquired, track the first detection
            if is_target_acquired:
                if current_detections:
                    # Example: track first detection bounding box
                    det = current_detections[0]
                    x, y, w, h = det.box
                    center_x = x + w // 2
                    center_y = y + h // 2

                    # Grab frame dimensions
                    frame_width, frame_height = picam2.stream_configuration("main")["size"]
                    offset_x = center_x - (frame_width / 2)
                    offset_y = center_y - (frame_height / 2)

                    # PanTilt tries to align if outside dead zone
                    pan_tilt.set_target_by_pixels(offset_x, offset_y)

            # Transition: target just lost
            else:
                if was_target_acquired and not is_target_acquired:
                    water_pistol.stop()
                    if recording_manager.recording:
                        recording_manager.stop_recording()
                        # Reconfigure + restart preview to avoid freeze issues
                        picam2.configure(video_config)
                        picam2.start(show_preview=SHOW_PREVIEW)
                        logger.info("Preview re-started after stopping recording.")
                    # Move to home if desired
                    pan_tilt.move_home_async()
                    logger.info("Ready for next detection sequence...")
        else:
            pass
        # Optional: small delay to reduce CPU usage
        # time.sleep(0.05)