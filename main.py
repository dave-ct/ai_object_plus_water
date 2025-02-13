#!/usr/bin/env python3
# main.py

# --------------------------------------------------------------------------------
#  Import Required Packages
# --------------------------------------------------------------------------------
# import my_configuration as config
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
from gpiozero import LED  # So it works across all Pi types
import os
import subprocess
import math
import psutil
import platform
import importlib.metadata
import json


def load_configuration():
   """
   Loads configuration from my_configuration.py and optionally overrides
   with values from config.json if it exists
   """
   import my_configuration as config
   print("Loading all configuration settings from my_configuration.py and config.json.")

   json_path = "config.json"
   if os.path.exists(json_path):
       try:
           with open(json_path, 'r') as f:
               json_config = json.load(f)

           for key, value in json_config.items():
               if hasattr(config, key):
                   original_value = getattr(config, key)
                   if isinstance(original_value, tuple):
                       value = tuple(value)  # Convert JSON array back to tuple
                   setattr(config, key, value)
                   print(f"Overriding {key} from JSON config with value: {value}")
               else:
                   print(f"Unknown configuration key in JSON: {key}")

       except Exception as e:
           print(f"Error loading JSON configuration: {e}")
   else:
       print("No JSON configuration file found, using default values from my_configuration.py")

   return config


# Load configuration
config = load_configuration()


# --------------------------------------------------------------------------------
#  TUNING PARAMETERS (FROM my_configuration.py)
# --------------------------------------------------------------------------------
PAN_DEG_PER_PIXEL    = config.PAN_DEG_PER_PIXEL
TILT_DEG_PER_PIXEL   = config.TILT_DEG_PER_PIXEL
PAN_INVERT           = config.PAN_INVERT
TILT_INVERT          = config.TILT_INVERT
DEAD_ZONE            = config.DEAD_ZONE
HOME_PAN             = config.HOME_PAN
HOME_TILT            = config.HOME_TILT
MOVE_STEPS           = config.MOVE_STEPS
MOVE_STEP_DELAY      = config.MOVE_STEP_DELAY
SHOW_PREVIEW         = config.SHOW_PREVIEW
SAVE_DIRECTORY       = config.SAVE_DIRECTORY_NAME
DELETE_CONVERTED_FILES = config.DELETE_CONVERTED_FILES
ALPHA                = config.ALPHA
FADE_FRAMES          = config.FADE_FRAMES
DISPLAY_BOXES_VIDEO  = config.DISPLAY_BOXES_VIDEO
DISPLAY_BOXES_PREVIEW = config.DISPLAY_BOXES_PREVIEW
WATER_PISTOL_ARMED    = config.WATER_PISTOL_ARMED


#Variable for smoothed boxes
smoothed_boxes = {}  # { category_id: { "box": (x, y, w, h), "no_update_count": 0 } }




def blend_boxes(old_box, new_box, alpha):
    """
    Weighted average of old_box and new_box coords.
    old_box, new_box = (x, y, w, h)
    alpha in [0..1], where higher alpha = more weight on new data.
    """
    (xo, yo, wo, ho) = old_box
    (xn, yn, wn, hn) = new_box
    x = int((1 - alpha) * xo + alpha * xn)
    y = int((1 - alpha) * yo + alpha * yn)
    w = int((1 - alpha) * wo + alpha * wn)
    h = int((1 - alpha) * ho + alpha * hn)
    return (x, y, w, h)

def update_smoothed_detections(new_detections, alpha=0.5, fade_frames=3):
    """
    new_detections: list of real Detection objects => each has .category, .box, .conf
    alpha: how strongly we blend new boxes (but we use the latest conf).
    fade_frames: remove old boxes if they don't appear again after these frames.
    """
    global smoothed_boxes

    # Mark all existing boxes to increment no_update_count
    for cat_id in smoothed_boxes:
        smoothed_boxes[cat_id]["no_update_count"] += 1

    for det in new_detections:
        cat_id  = int(det.category)
        new_box = det.box     # (x, y, w, h)
        new_conf = det.conf   # real confidence from detection

        if cat_id in smoothed_boxes:
            old_box  = smoothed_boxes[cat_id]["box"]
            old_conf = smoothed_boxes[cat_id]["conf"]

            # 1) Blend the bounding boxes
            blended_box = blend_boxes(old_box, new_box, alpha)
            smoothed_boxes[cat_id]["box"] = blended_box

            # 2) Use the NEW (latest) confidence directly
            smoothed_boxes[cat_id]["conf"] = new_conf

            smoothed_boxes[cat_id]["no_update_count"] = 0
        else:
            # Initialize with new detection’s box + conf
            smoothed_boxes[cat_id] = {
                "box":  new_box,
                "conf": new_conf,
                "no_update_count": 0
            }

    # Remove entries that didn't appear for fade_frames
    to_remove = []
    for cat_id, data in smoothed_boxes.items():
        if data["no_update_count"] > fade_frames:
            to_remove.append(cat_id)
    for cat_id in to_remove:
        del smoothed_boxes[cat_id]

def get_smoothed_detections():
    results = []
    for cat_id, data in smoothed_boxes.items():
        (x, y, w, h) = data["box"]
        c = data["conf"]  # This is the latest confidence from update_smoothed_detections
        results.append({
            "category": cat_id,
            "conf": c,
            "box": (x, y, w, h)
        })
    return results

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

# Added for manual control and settings
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
    """
    model_str = "Unknown Platform"
    model_path = "/proc/device-tree/model"

    if os.path.exists(model_path):
        with open(model_path, "r") as f:
            model_str = f.read().strip()

    logger.info(f"Detected Platform - {model_str}")

    config.RASPBERRY_PI_ZERO_2W = ("Raspberry Pi Zero 2 W" in model_str)

detect_platform()
if config.RASPBERRY_PI_ZERO_2W:
    logger.info("This is a Raspberry Pi Zero 2 W, enabling Pi Zero optimizations...")
else:
    logger.info("Not a Pi Zero 2 W, using normal behavior.")

# -----------------------------------------------------------------------------
#  Web Server: Flask App
# -----------------------------------------------------------------------------
app = Flask(__name__)
latest_frame = None  # We'll store the latest "lores" frame (annotated) for MJPEG streaming

# -----------------------------------------------------------------------------
#  Global Flags to Defer Recording Start/Stop
# -----------------------------------------------------------------------------
recording_requested = False
recording_stop_requested = False

# -----------------------------------------------------------------------------
#  System Info Utilities
# -----------------------------------------------------------------------------
def get_cpu_temperature():
    temp_path = "/sys/class/thermal/thermal_zone0/temp"
    if os.path.exists(temp_path):
        try:
            with open(temp_path, "r") as f:
                millideg = f.read().strip()
                return float(millideg) / 1000.0
        except Exception:
            pass
    return None

def get_platform_name():
    model_path = "/proc/device-tree/model"
    if os.path.exists(model_path):
        try:
            with open(model_path, "r") as f:
                return f.read().strip()
        except Exception:
            pass
    return platform.platform()

# -----------------------------------------------------------------------------
#  Start Flask in a separate thread
# -----------------------------------------------------------------------------
def start_web_server():
    app.run(host="0.0.0.0", port=5000, debug=False, threaded=True)

def gen_frames():
    """
    Generator for MJPEG streaming from 'latest_frame'.
    """
    global latest_frame
    while True:
        if latest_frame is not None:
            ret, buffer = cv2.imencode('.jpg', latest_frame)
            if not ret:
                continue
            frame_bytes = buffer.tobytes()
            yield (b'--frame\r\n'
                   b'Content-Type: image/jpeg\r\n\r\n' + frame_bytes + b'\r\n')
        else:
            time.sleep(0.05)

# -----------------------------------------------------------------------------
#  Flask Routes
# -----------------------------------------------------------------------------

@app.route("/configuration", methods=['GET', 'POST'])
def configuration():
    if request.method == 'POST':
        # Handle form submission
        config_updates = {}
        for key, value in request.form.items():
            # Convert string values to appropriate types
            try:
                current_value = getattr(config, key)
                if isinstance(current_value, bool):
                    value = value.lower() == 'true'
                elif isinstance(current_value, int):
                    value = int(value)
                elif isinstance(current_value, float):
                    value = float(value)
                elif isinstance(current_value, tuple):
                    # Convert string "(1920, 1080)" to tuple
                    value = tuple(map(int, value.strip('()').split(',')))
                config_updates[key] = value
            except (ValueError, AttributeError):
                logger.warning(f"Skipping invalid configuration value for {key}")
                continue

        # Save to config.json
        try:
            with open('config.json', 'w') as f:
                json.dump(config_updates, f, indent=4)
            logger.info("Configuration saved. Restart required for changes to take effect.")
            return jsonify(
                {"status": "success", "message": "Configuration saved. Restart required for changes to take effect."})
        except Exception as e:
            logger.error(f"Error saving configuration: {e}")
            return jsonify({"status": "error", "message": str(e)}), 500

    # GET request - show current configuration
    config_items = []
    for key in dir(config):
        if not key.startswith('__'):
            value = getattr(config, key)
            # Add tuple to accepted types and handle conversion
            if isinstance(value, (str, int, float, bool, tuple)):
                config_items.append({
                    'name': key,
                    'value': str(value) if isinstance(value, tuple) else value,
                    'type': 'tuple' if isinstance(value, tuple) else type(value).__name__
                })

    return render_template('configuration.html', config_items=config_items)


@app.route("/manual_recording")
def manual_recording():
    global auto_mode, recording_requested, recording_stop_requested
    if auto_mode:
        return "Cannot record manually while in AUTO mode", 400

    action = request.args.get("action", None)
    if not action:
        return "No action specified", 400

    if action == "start":
        if not recording_manager.recording:
            # Instead of direct start, we can still do the same "recording_requested" approach:
            recording_requested = True
            return "Recording start requested."
        else:
            return "Already recording.", 200

    elif action == "stop":
        if recording_manager.recording:
            # Instead of direct stop, set the flag:
            recording_stop_requested = True
            return "Recording stop requested."
        else:
            return "Was not recording.", 200

    else:
        return f"Unknown action: {action}", 400

@app.route("/system_info")
def system_info():
    temperature = get_cpu_temperature()
    cpu_usage = psutil.cpu_percent(interval=0.1)
    mem = psutil.virtual_memory()
    mem_total_mb = mem.total / (1024 * 1024)
    mem_used_mb = mem.used / (1024 * 1024)
    mem_free_mb = mem.available / (1024 * 1024)
    swap = psutil.swap_memory()
    swap_total_mb = swap.total / (1024 * 1024)
    swap_used_mb  = swap.used / (1024 * 1024)
    disk = psutil.disk_usage('/')
    disk_total_mb = disk.total / (1024 * 1024)
    disk_used_mb  = disk.used / (1024 * 1024)
    disk_free_mb  = disk.free / (1024 * 1024)
    platform_name = get_platform_name()
    os_version = platform.platform()
    python_version = platform.python_version()

    data = {
        "temperature": temperature,
        "cpu_usage": cpu_usage,
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
    distributions = importlib.metadata.distributions()
    installed = {}
    for dist in distributions:
        name = dist.metadata["Name"]
        version = dist.metadata["Version"]
        installed[name] = version
    sorted_installed = dict(sorted(installed.items(), key=lambda x: x[0].lower()))
    return jsonify(sorted_installed)

@app.route("/system")
def system_page():
    return render_template("system.html")

@app.route("/status")
def status():
    current_pan, current_tilt = pan_tilt_control.get_current_angles()
    data = {
        "auto_mode": auto_mode,
        "is_recording": recording_manager.recording,
        "water_pistol_active": water_pistol.active,
        "current_pan_angle": current_pan,
        "current_tilt_angle": current_tilt,
    }
    return jsonify(data)

@app.route("/recordings")
def show_recordings():
    page = request.args.get("page", 1, type=int)
    page_size = 5

    all_files = [
        f for f in os.listdir(SAVE_DIRECTORY)
        if f.lower().endswith(".mp4")
    ]
    all_files.sort(key=lambda x: os.path.getmtime(os.path.join(SAVE_DIRECTORY, x)), reverse=True)
    all_file_info = []
    for f in all_files:
        file_path = os.path.join(SAVE_DIRECTORY, f)
        mtime = os.path.getmtime(file_path)
        datetime_str = time.strftime("%Y-%m-%d %H:%M:%S", time.localtime(mtime))
        all_file_info.append({
            "filename": f,
            "datetime_str": datetime_str
        })
    total_files = len(all_file_info)
    total_pages = math.ceil(total_files / page_size)
    start_idx = (page - 1) * page_size
    end_idx = start_idx + page_size
    page_files = all_file_info[start_idx:end_idx]

    return render_template("recordings.html",
                           files=page_files,
                           page=page,
                           total_pages=total_pages)

@app.route("/video/<path:filename>")
def serve_video(filename):
    return send_from_directory(SAVE_DIRECTORY, filename)

@app.route("/delete_recording", methods=["POST"])
def delete_recording():
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
    global auto_mode
    mode = request.args.get("mode", "auto")
    if mode.lower() == "auto":
        water_pistol.stop()
        target_tracker.reset()
        pan_tilt_control.move_to(HOME_PAN, HOME_TILT, steps=MOVE_STEPS, step_delay=MOVE_STEP_DELAY)
        auto_mode = True
        logger.info("Switched to AUTO mode")
    else:
        auto_mode = False
        logger.info("Switched to MANUAL mode")
    return "OK"

@app.route("/move")
def move():
    direction = request.args.get("direction", None)
    if auto_mode:
        return "Cannot move while in AUTO mode", 400
    if not direction:
        return "No direction provided", 400

    step_degrees = 5.0
    current_pan, current_tilt = pan_tilt_control.get_current_angles()
    if direction == "down":
        new_tilt = current_tilt - step_degrees
        pan_tilt_control.move_to(current_pan, new_tilt, steps=MOVE_STEPS, step_delay=MOVE_STEP_DELAY)
    elif direction == "up":
        new_tilt = current_tilt + step_degrees
        pan_tilt_control.move_to(current_pan, new_tilt, steps=MOVE_STEPS, step_delay=MOVE_STEP_DELAY)
    elif direction == "right":
        new_pan = current_pan - step_degrees
        pan_tilt_control.move_to(new_pan, current_tilt, steps=MOVE_STEPS, step_delay=MOVE_STEP_DELAY)
    elif direction == "left":
        new_pan = current_pan + step_degrees
        pan_tilt_control.move_to(new_pan, current_tilt, steps=MOVE_STEPS, step_delay=MOVE_STEP_DELAY)
    else:
        return f"Unknown direction: {direction}", 400
    return "OK"

@app.route("/water_pistol")
def water_pistol_control():
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
    global manual_home_pan, manual_home_tilt
    global HOME_PAN, HOME_TILT
    if auto_mode:
        return "Cannot set home in AUTO mode", 400
    current_pan, current_tilt = pan_tilt_control.get_current_angles()
    manual_home_pan = current_pan
    manual_home_tilt = current_tilt
    HOME_PAN = manual_home_pan
    HOME_TILT = manual_home_tilt
    logger.info(f"Set new manual home to Pan={manual_home_pan}, Tilt={manual_home_tilt}")
    return "OK"

@app.route('/')
def index():
    return render_template('index.html')

@app.route('/video_feed')
def video_feed():
    return Response(gen_frames(),
                    mimetype='multipart/x-mixed-replace; boundary=frame')

# -----------------------------------------------------------------------------
#  Utility Functions for Video Conversion
# -----------------------------------------------------------------------------
def convert_saved_video(filename):
    if not os.path.exists(SAVE_DIRECTORY):
        os.makedirs(SAVE_DIRECTORY)
    base_name = os.path.splitext(os.path.basename(filename))[0]
    mp4_filename = os.path.join(SAVE_DIRECTORY, base_name + ".mp4")
    try:
        subprocess.run([
            "ffmpeg", "-i", filename,
            "-c:v", "copy",
            "-c:a", "copy",
            mp4_filename
        ], check=True)
        if DELETE_CONVERTED_FILES:
            os.remove(filename)
        logger.info(f"Converted {filename} to {mp4_filename}. (DELETE_CONVERTED_FILES={DELETE_CONVERTED_FILES})")
    except subprocess.CalledProcessError as e:
        logger.error(f"ffmpeg failed to convert {filename}: {e}")

def convert_saved_video_async(filename):
    def convert():
        convert_saved_video(filename)
    threading.Thread(target=convert, daemon=True).start()

# -----------------------------------------------------------------------------
#  Classes
# -----------------------------------------------------------------------------
class PanTiltControllerWrapper:
    def __init__(self, move_steps, move_step_delay):
        self.is_moving = False
        self.move_steps = move_steps
        self.move_step_delay = move_step_delay
        # Move to home on init
        time.sleep(1.0)
        self.home()

    def home(self):
        pan_tilt_control.move_to(
            HOME_PAN, HOME_TILT,
            # steps=self.move_steps,
            # step_delay=self.move_step_delay
            steps=10,
            step_delay=0.1
        )

    def set_target_by_pixels(self, offset_x, offset_y):
        if self.is_moving:
            return
        if abs(offset_x) < DEAD_ZONE and abs(offset_y) < DEAD_ZONE:
            return
        current_pan, current_tilt = pan_tilt_control.get_current_angles()
        delta_pan = offset_x * PAN_DEG_PER_PIXEL
        delta_tilt = offset_y * TILT_DEG_PER_PIXEL
        if PAN_INVERT:
            delta_pan = -delta_pan
        if TILT_INVERT:
            delta_tilt = -delta_tilt
        new_pan_angle = current_pan + delta_pan
        new_tilt_angle = current_tilt + delta_tilt

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
        if self.is_moving:
            return
        def do_home():
            self.is_moving = True
            pan_tilt_control.move_to(
                HOME_PAN, HOME_TILT,
                # steps=self.move_steps,
                # step_delay=self.move_step_delay
                steps=10,
                step_delay=0.1
            )
            self.is_moving = False
        threading.Thread(target=do_home, daemon=True).start()

class WaterPistolController:
    def __init__(self, pin=config.REPLAY_PIN):
        self.active = False
        self.relay_pin = pin
        self.relay = LED(self.relay_pin, active_high=True)
        self.relay.off()

    def start(self):
        if not self.active:
            self.active = True
            self.relay.on()
            logger.info("WaterPistol - Started firing!!")

    def stop(self):
        if self.active:
            self.active = False
            self.relay.off()
            logger.info("WaterPistol - Stopped firing.")

    def cleanup(self):
        self.relay.close()

class RecordingManager:
    def __init__(self, picam2):
        from picamera2.encoders import H264Encoder
        from picamera2.outputs import FileOutput
        self.picam2 = picam2
        self.encoder = H264Encoder()
        self.output_class = FileOutput
        self.recording = False
        self.filename = None

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
            # Now convert the file
            if not config.RASPBERRY_PI_ZERO_2W:
                convert_saved_video(self.filename)
            else:
                convert_saved_video_async(self.filename)

class TargetTracker:
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
            while (self.detection_timestamps and
                   (now - self.detection_timestamps[0]) > self.activation_time_window):
                self.detection_timestamps.popleft()

            # Check if we cross the activation threshold
            if (not self.target_acquired) and (len(self.detection_timestamps) >= self.activation_detections):
                self.target_acquired = True
                logger.info("[TargetTracker] Target acquired!")
        else:
            # If no detections for too long => lose target
            if self.target_acquired and self.last_detection_time is not None:
                if (now - self.last_detection_time) > self.no_detection_timeout:
                    self.target_acquired = False
                    self.detection_timestamps.clear()
                    logger.info("[TargetTracker] Target lost due to no detections.")
        return self.target_acquired

    def is_target_acquired(self):
        return self.target_acquired

    def reset(self):
        # Force a fresh
        self.detection_timestamps.clear()
        self.target_acquired = False
        self.last_detection_time = None

        logger.info("[TargetTracker] State has been reset.")

# Simple detection container
class Detection:
    def __init__(self, coords, category, conf, metadata, picam2, imx500):
        self.category = category
        self.conf = conf
        # Convert from IMX500's inference coords to pixel coords
        self.box = imx500.convert_inference_coords(coords, metadata, picam2)
        logger.debug(f"[Detection] Raw coords: {coords} converted to pixel box: {self.box}")

def parse_detections(metadata: dict, imx500, intrinsics, picam2):
    threshold      = config.THRESHOLD
    iou            = config.IOU
    max_detections = config.MAX_DETECTIONS

    np_outputs = imx500.get_outputs(metadata, add_batch=True)
    if np_outputs is None:
        return []

    input_w, input_h = imx500.get_input_size()

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
        bbox_normalization = intrinsics.bbox_normalization
        bbox_order = intrinsics.bbox_order
        boxes, scores, classes = np_outputs[0][0], np_outputs[1][0], np_outputs[2][0]
        if bbox_normalization:
            boxes = boxes / input_h
        if bbox_order == "xy":
            # Convert from (y0, x0, y1, x1) => (x0, y0, x1, y1)
            boxes = boxes[:, [1, 0, 3, 2]]

    new_detections = []
    for i in range(len(scores)):
        score = scores[i]
        if score < threshold:
            continue
        category = classes[i]
        box = boxes[i]
        det = Detection(box, category, score, metadata, picam2, imx500)
        new_detections.append(det)

    return new_detections

@lru_cache
def get_labels(intrinsics):
    labels = intrinsics.labels
    if hasattr(intrinsics, "ignore_dash_labels") and intrinsics.ignore_dash_labels:
        labels = [label for label in labels if label and label != "-"]
    return labels


def draw_detections_on_frame(
    array,
    detections,
    intrinsics,
    recording,
    inside_box,
    scale_x=1.0,
    scale_y=1.0
):
    labels = get_labels(intrinsics)
    height, width, _ = array.shape
    center_x = width // 2
    center_y = height // 2

    if not recording:
        box_color      = (0, 255, 0)
        label_bg_color = (0, 255, 0)
        label_text_color = (255, 255, 255)

        # 1) Draw bounding boxes
        for det in detections:
            # -- CHANGED HERE --
            x, y, w, h = det["box"]  # dictionary style
            x = int(x * scale_x)
            y = int(y * scale_y)
            w = int(w * scale_x)
            h = int(h * scale_y)
            cv2.rectangle(array, (x, y), (x + w, y + h), box_color, 2)

        # 2) Draw label text near top-right corner
        label_x = width - 10
        label_y = 30
        for det in detections:
            # -- CHANGED HERE --
            category = det["category"]
            conf     = det["conf"]
            label_text = f"{labels[category]} ({conf:.2f})"

            (text_width, text_height), baseline = cv2.getTextSize(
                label_text, cv2.FONT_HERSHEY_SIMPLEX, 0.5, 1
            )
            text_start_x = label_x - text_width
            text_start_y = label_y

            cv2.rectangle(
                array,
                (text_start_x, text_start_y - text_height - baseline),
                (text_start_x + text_width, text_start_y + baseline),
                label_bg_color,
                cv2.FILLED
            )
            cv2.putText(
                array, label_text,
                (text_start_x, text_start_y),
                cv2.FONT_HERSHEY_SIMPLEX,
                0.5, label_text_color, 1
            )
            label_y += text_height + baseline + 10

    else:
        # Recording => crosshair, color depends on inside_box
        if inside_box:
            crosshair_color = (255, 0, 0)
            box_color       = (255, 0, 0)
            label_bg_color  = (255, 0, 0)
            bottom_text     = "ACQUIRED"
            bottom_bg_color = (255, 0, 0)
        else:
            crosshair_color = (0, 255, 0)
            box_color       = (0, 255, 0)
            label_bg_color  = (0, 255, 0)
            bottom_text     = "TRACKING"
            bottom_bg_color = (0, 255, 0)

        label_text_color = (255, 255, 255)

        # Draw bounding boxes
        for det in detections:
            # -- CHANGED HERE --
            x, y, w, h = det["box"]
            x = int(x * scale_x)
            y = int(y * scale_y)
            w = int(w * scale_x)
            h = int(h * scale_y)

            cv2.rectangle(array, (x, y), (x + w, y + h), box_color, 2)

            category = det["category"]
            conf     = det["conf"]
            label_text = f"{labels[category]} ({conf:.2f})"

            (text_width, text_height), baseline = cv2.getTextSize(
                label_text, cv2.FONT_HERSHEY_SIMPLEX, 1.0, 1
            )
            label_x = x + 5
            label_y = y + text_height + 5
            cv2.rectangle(
                array,
                (label_x, label_y - text_height - baseline),
                (label_x + text_width, label_y + baseline),
                label_bg_color,
                cv2.FILLED
            )
            cv2.putText(
                array, label_text,
                (label_x, label_y),
                cv2.FONT_HERSHEY_SIMPLEX,
                1.0, label_text_color, 1
            )

        # Crosshair
        line_length = 30
        thickness   = 4
        cv2.line(
            array,
            (center_x - line_length, center_y),
            (center_x + line_length, center_y),
            crosshair_color, thickness
        )
        cv2.line(
            array,
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
            array,
            (text_x, text_y - bt_text_height - bt_baseline),
            (text_x + bt_text_width, text_y + bt_baseline),
            bottom_bg_color,
            cv2.FILLED
        )
        cv2.putText(
            array, bottom_text,
            (text_x, text_y),
            cv2.FONT_HERSHEY_SIMPLEX,
            2.0, (255, 255, 255), 2
        )


# -----------------------------------------------------------------------------
#  The Camera Callback - DO NOT start/stop recording here
# -----------------------------------------------------------------------------
def do_frame_callback(request):
    global latest_frame
    global recording_requested, recording_stop_requested

    metadata = request.get_metadata()
    raw_detections = parse_detections(metadata, imx500, intrinsics, picam2)

    if logger.isEnabledFor(logging.DEBUG):
        labels_list = get_labels(intrinsics)  # or intrinsics.labels if you prefer
        for d in raw_detections:
            cat_id = d.category
            label_text = labels_list[int(cat_id)]
            logger.debug(f"Detection: {label_text} {d.conf:.2f}")

    # 1) Update the smoothing store
    update_smoothed_detections(raw_detections, alpha=ALPHA, fade_frames=FADE_FRAMES)

    # 2) Retrieve the smoothed bounding boxes
    #    Here we create "Detection-like" objects or simple dicts
    #    so the draw function can be fed them.
    smoothed_dets = get_smoothed_detections()

    # 3) (Optional) If you still do TargetTracker, you might pass raw_detections
    #    or the smoothed_dets. Some prefer raw for immediate logic, or a partial approach.
    has_detections = (len(smoothed_dets) > 0)
    was_acquired = target_tracker.is_target_acquired()
    target_tracker.update_detections(has_detections)
    is_acquired = target_tracker.is_target_acquired()

    if is_acquired and not was_acquired and auto_mode:
        recording_requested = True
        if WATER_PISTOL_ARMED:
            water_pistol.start()

    elif was_acquired and not is_acquired and auto_mode:
        recording_stop_requested = True
        water_pistol.stop()
        if auto_mode:
            pan_tilt.move_home_async()

    # 4) Pan/tilt: maybe track the first smoothed box if you want
    # if is_acquired and smoothed_dets and auto_mode:
    #     first_box = smoothed_dets[0]["box"]  # (x, y, w, h)
    #     (x, y, w, h) = first_box
    #     main_w, main_h = picam2.stream_configuration("main")["size"]
    #     offset_x = (x + w/2) - (main_w / 2)
    #     offset_y = (y + h/2) - (main_h / 2)
    #     pan_tilt.set_target_by_pixels(offset_x, offset_y)

    if is_acquired and raw_detections and auto_mode:
        # Option A: Just pick the first detection
        # first_det = raw_detections[0]

        # Option B: Pick the detection with the highest confidence
        best_det = max(raw_detections, key=lambda d: d.conf)

        (x, y, w, h) = best_det.box  # (x, y, w, h)
        main_w, main_h = picam2.stream_configuration("main")["size"]
        offset_x = (x + w / 2) - (main_w / 2)
        offset_y = (y + h / 2) - (main_h / 2)
        pan_tilt.set_target_by_pixels(offset_x, offset_y)


    # 5) Draw bounding boxes on main (1:1)
    inside_box = False

    if recording_manager.recording and len(smoothed_dets) > 0:
        main_w, main_h = picam2.stream_configuration("main")["size"]
        cx = main_w // 2
        cy = main_h // 2
        for d in smoothed_dets:
            (bx, by, bw, bh) = d["box"]
            if bx <= cx <= (bx + bw) and by <= cy <= (by + bh):
                inside_box = True
                break
    if DISPLAY_BOXES_VIDEO:
        with MappedArray(request, "main") as m:
            main_array = m.array
            draw_detections_on_frame(
                main_array,
                smoothed_dets,     # pass the "smoothed" list
                intrinsics,
                recording_manager.recording,
                inside_box,
                scale_x=1.0,
                scale_y=1.0
            )
    # 6) Draw bounding boxes on lowres (scaled)

    with MappedArray(request, "lores") as lores_m:
        lores_frame = cv2.cvtColor(lores_m.array, cv2.COLOR_YUV2BGR_I420)
        lores_w, lores_h = picam2.stream_configuration("lores")["size"]
        main_w, main_h   = picam2.stream_configuration("main")["size"]

        sx = lores_w / float(main_w)
        sy = lores_h / float(main_h)

        if DISPLAY_BOXES_PREVIEW:
            draw_detections_on_frame(
                lores_frame,
                smoothed_dets,     # pass the smoothed list
                intrinsics,
                recording_manager.recording,
                inside_box,
                scale_x=sx,
                scale_y=sy
            )
        latest_frame = lores_frame.copy()



# -----------------------------------------------------------------------------
#  Main Loop to Actually Start/Stop Recording
# -----------------------------------------------------------------------------
def main_loop():
    """
    Periodically checks if we need to start or stop recording, to avoid deadlock
    in the camera callback.
    """
    while True:
        global recording_requested, recording_stop_requested

        # Start recording if requested, but only if not already recording
        if recording_requested and not recording_manager.recording:
            recording_manager.start_recording()
            recording_requested = False

        # Stop recording if requested, but only if we are currently recording
        if recording_stop_requested and recording_manager.recording:
            recording_manager.stop_recording()
            recording_stop_requested = False
            picam2.configure(video_config)
            picam2.start(show_preview=SHOW_PREVIEW)
            logger.info("Preview re-started after stopping recording.")
            # If you want to reconfigure picam2 or do something else, do it here
            # (not inside the callback)

        time.sleep(0.05)

# -----------------------------------------------------------------------------
#  Main Program
# -----------------------------------------------------------------------------
if __name__ == "__main__":
    # 1) Initialize IMX500
    imx500 = IMX500(config.MODEL)
    intrinsics = imx500.network_intrinsics
    if not intrinsics:
        intrinsics = NetworkIntrinsics()
        intrinsics.task = "object detection"
    elif intrinsics.task != "object detection":
        logger.info("Network is not an object detection task.")
        sys.exit(1)

    # 2) Set intrinsics.labels from config.LABELS, else "assets/coco_labels.txt"
    if config.LABELS:
        with open(config.LABELS, "r") as f:
            intrinsics.labels = f.read().splitlines()
    else:
        with open("assets/coco_labels.txt", "r") as f:
            intrinsics.labels = f.read().splitlines()

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
    intrinsics.update_with_defaults()

    if config.PRINT_INTRINSICS:
        logger.info(intrinsics)
        print(intrinsics)
        sys.exit(0)

    # 3) Set up Picamera2
    picam2 = Picamera2(imx500.camera_num)
    video_config = picam2.create_video_configuration(
        main={"size": config.MAIN_STREAM_RESOLUTION},
        lores={"size": config.LOW_RES_STREAM_RESOLUTION, "format": "YUV420"},
        controls={"FrameRate": intrinsics.inference_rate},
        buffer_count=12,
        transform=Transform(
            hflip=config.FLIP_HORIZONTALLY,
            vflip=config.FLIP_VERTICALLY
        )
    )
    picam2.configure(video_config)
    picam2.start(show_preview=SHOW_PREVIEW)
    if hasattr(intrinsics, "preserve_aspect_ratio") and intrinsics.preserve_aspect_ratio:
        imx500.set_auto_aspect_ratio()

    # 4) Create global controllers
    pan_tilt = PanTiltControllerWrapper(MOVE_STEPS, MOVE_STEP_DELAY)
    water_pistol = WaterPistolController()
    recording_manager = RecordingManager(picam2)
    target_tracker = TargetTracker(
        config.ACTIVATION_DETECTIONS,
        config.ACTIVATION_TIME_WINDOW,
        config.NO_DETECTION_TIMEOUT
    )

    # 5) Assign the pre_callback to handle detection + overlay (but no direct record calls)
    picam2.pre_callback = do_frame_callback

    # 6) Start the Flask server in a background thread
    flask_thread = threading.Thread(target=start_web_server, daemon=True)
    flask_thread.start()

    # 7) Run main loop to actually start/stop recording outside callback
    try:
        main_loop()
    except KeyboardInterrupt:
        logger.info("Shutting down...")
        water_pistol.stop()
        sys.exit(0)
