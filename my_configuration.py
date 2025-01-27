# Setup all the configurable aspects in this file

#Setup the logging
LOG_LEVEL = "INFO"     # or "DEBUG", "WARNING", "ERROR", "CRITICAL"
LOG_FILE = None        # If set to a filename (e.g. "my_log.log"), logs to a file; if None, logs to console

# Servo Settings (assumes both servos are the sme type)  By default set for servo of type MG996R which can do 180 degrees
PWM_FREQUENCY = 50
MIN_PULSE = 103  # Pulse length for -90 degrees
MAX_PULSE = 512  # Pulse length for +90 degrees
CENTER_PULSE = (MIN_PULSE + MAX_PULSE) // 2
ANGLE_RANGE = 90  # Range of motion in degrees 90 = (-90 to +90)
#Todo - Make is possible ot have two different types of servos with different degree settings.

# Note: MG996R Servro PWM_FREQUENCY = 50 MIN_PULSE = 150 MAX_PULSE = 565
# Note: GXservo 43Kg PWM_FREQUENCY = 50 MIN_PULSE = 103 MAX_PULSE = 512

#PCA9685 i2c settings and servo channels
I2C_ADDRESS = 0x40
I2C_BUS = 1
PAN_SERVO_CHANNEL = 0
TILT_SERVO_CHANNEL = 1

#Relay GPIO pin
REPLAY_PIN = 14

# How many degrees to move per pixel offset when tracking an object
PAN_DEG_PER_PIXEL = 0.03
TILT_DEG_PER_PIXEL = 0.03

# Reverse directions if needed (if you go up instead of down and left instead of right)
PAN_INVERT = True  # If True, pan movement is inverted
TILT_INVERT = True  # If True, tilt movement is inverted

# Zone around center in which we do NOT move (pixels) when tracking, so if the we are within dead_zone (in the centre of the image) we wont move any further
DEAD_ZONE = 20

# Set the default PanTilt home angles when it starts up
HOME_PAN  = 0.0
HOME_TILT = 0.0

# Move smoothing, adjust to make the movement smoother or more aggressive
MOVE_STEPS = 15
MOVE_STEP_DELAY = 0.02

#Picamera settings

SHOW_PREVIEW = False # Set to false in headless mode, if running locally on PI setting to True will show the live preview in a window

#Set the resolution to use, MAIN_STREAM for video recording / preview and LOW_RES for web interface
#Note settgina high resolution on the LOW_RES can cause performance issues.
MAIN_STREAM_RESOLUTION = (1920, 1080)
LOW_RES_STREAM_RESOLUTION = (640, 360)

#If the camera is mounted upside down set to True
FLIP_VERTICALLY = False
FLIP_HORIZONTALLY = False

SAVE_DIRECTORY_NAME = "./saved_videos/"
DELETE_CONVERTED_FILES = True #If True Delete the .h264 version once converted to MP4



MODEL = "models/train_all_yolov8n_150_32/network.rpk"
# Path to the AI inference model (an .rpk file) used by the IMX500 for object detection.

LABELS = "models/train_all_yolov8n_150_32/labels.txt"
# Path to the file containing the label names (one label per line).

FPS = 25
# The desired frames per second (FPS) for the camera to capture/stream.

BBOX_NORMALIZATION = True
# Whether the bounding box coordinates produced by the model are normalized (0.0–1.0).
# If True, box coordinates need to be multiplied by the actual frame size.

BBOX_ORDER = "xy"
# Order of coordinates in each bounding box.
# "xy" => (x0, y0, x1, y1)
# "yx" => (y0, x0, y1, x1)

THRESHOLD = 0.50
# Minimum detection confidence (0.0–1.0) required for a detection to be valid.

IOU = 0.65
# Intersection-over-Union threshold for non-max suppression (NMS).
# Higher value => stricter overlap requirement for discarding overlapping boxes.

MAX_DETECTIONS = 2
# Maximum number of detection boxes to keep after NMS.

IGNORE_DASH_LABELS = True
# If True, ignore labels that are just "-" in the model's label set.

POSTPROCESS = "" # or "nanodet" if needed
# Type of postprocessing to apply to raw model outputs.
# e.g., "nanodet" if your model is a NanoDet-based architecture; otherwise None.

PRESERVE_ASPECT_RATIO = False
# Whether to preserve the aspect ratio when scaling image input to the model.
# If True, will draw an ROI box on the preview indicating the cropped region.

ACTIVATION_DETECTIONS = 5
# Number of detections within a given time window required to declare "target acquired."

ACTIVATION_TIME_WINDOW = 1.0
# Time window (in seconds) for counting up detections toward ACTIVATION_DETECTIONS.

NO_DETECTION_TIMEOUT = 2.0
# If no detections occur within this many seconds, we consider the target "lost" and stop recording and squirting

PRINT_INTRINSICS = False
# If True, print the IMX500 network intrinsics (details about the loaded model)
# and exit before the main program loop, for debugging only.




