from Adafruit_PCA9685 import PCA9685
import threading
import time


# Get the configuration from the config file or if that is not available set some defaults
try:
    import my_configuration
    # Use the values from the configuration file
    PWM_FREQUENCY = my_configuration.PWM_FREQUENCY
    MIN_PULSE = my_configuration.MIN_PULSE
    MAX_PULSE = my_configuration.MAX_PULSE
    CENTER_PULSE = my_configuration.CENTER_PULSE
    ANGLE_RANGE = my_configuration.ANGLE_RANGE
    I2C_ADDRESS = my_configuration.I2C_ADDRESS
    I2C_BUS = my_configuration.I2C_BUS
    PAN_SERVO_CHANNEL = my_configuration.PAN_SERVO_CHANNEL
    TILT_SERVO_CHANNEL = my_configuration.TILT_SERVO_CHANNEL
except ImportError:
    # Default values if the configuration module cannot be imported
    print("configuration module not found. Using default values.")
    # Servo Settings
    PWM_FREQUENCY = 50
    MIN_PULSE = 150  # Pulse length for -90 degrees
    MAX_PULSE = 565  # Pulse length for +90 degrees
    CENTER_PULSE = (MIN_PULSE + MAX_PULSE) // 2
    ANGLE_RANGE = 90  # Range of motion in degrees (-90 to +90)
    # PCA9685 I2C settings and servo channels
    I2C_ADDRESS = 0x40
    I2C_BUS = 1
    PAN_SERVO_CHANNEL = 0
    TILT_SERVO_CHANNEL = 1

# Global variables to track current angles
current_pan = 0.0
current_tilt = 0.0
lock = threading.Lock()

# Initialize the PCA9685
pwm = PCA9685(address=I2C_ADDRESS, busnum=I2C_BUS )
pwm.set_pwm_freq(PWM_FREQUENCY)

def angle_to_pulse(angle):
    """
    Convert an angle (-90 to 90 degrees) to a pulse width.
    :param angle: The desired angle (-90 to +90 degrees)
    :return: Corresponding pulse width
    """
    if angle < -ANGLE_RANGE or angle > ANGLE_RANGE:
        raise ValueError(f"Angle must be between -{ANGLE_RANGE} and {ANGLE_RANGE} degrees.")
    return int(CENTER_PULSE + (angle / ANGLE_RANGE) * (MAX_PULSE - CENTER_PULSE))

def move_to(pan_angle, tilt_angle, steps=10, step_delay=0.05):
    """
    Move the pan and tilt servos to specified angles.
    :param pan_angle: Target pan angle (-90 to 90 degrees)
    :param tilt_angle: Target tilt angle (-90 to 90 degrees)
    :param steps: Number of steps for smooth movement
    :param step_delay: Delay between steps in seconds
    """
    global current_pan, current_tilt

    with lock:
        # Validate angles
        pan_angle = max(-ANGLE_RANGE, min(ANGLE_RANGE, pan_angle))
        tilt_angle = max(-ANGLE_RANGE, min(ANGLE_RANGE, tilt_angle))

        # Calculate pulse values
        pan_start = angle_to_pulse(current_pan)
        pan_end = angle_to_pulse(pan_angle)
        tilt_start = angle_to_pulse(current_tilt)
        tilt_end = angle_to_pulse(tilt_angle)

        # Smoothly interpolate between current and target positions
        for step in range(1, steps + 1):
            pan_pulse = pan_start + (pan_end - pan_start) * step // steps
            tilt_pulse = tilt_start + (tilt_end - tilt_start) * step // steps
            pwm.set_pwm(PAN_SERVO_CHANNEL, 0, pan_pulse)
            pwm.set_pwm(TILT_SERVO_CHANNEL, 0, tilt_pulse)
            time.sleep(step_delay)

        # Update current angles
        current_pan = pan_angle
        current_tilt = tilt_angle

def get_current_angles():
    """
    Get the current pan and tilt angles.
    :return: Tuple (current_pan, current_tilt)
    """
    with lock:
        return current_pan, current_tilt

if __name__ == "__main__":
    # If you run this on its own then just do a little test movement
    stepping_steps = 2
    stepping_delay = 0.05
    while True:
        try:
            # Move to center position initially
            move_to(0, 0)
            time.sleep(1)

            move_to(90, 90, steps=stepping_steps, step_delay=stepping_delay)
            time.sleep(1)

            move_to(45, -45, steps=stepping_steps, step_delay=stepping_delay)
            time.sleep(1)

            move_to(-90, -90, steps=stepping_steps, step_delay=stepping_delay)
            time.sleep(1)

            move_to(-45, 45, steps=stepping_steps, step_delay=stepping_delay)
            time.sleep(1)

            move_to(-90, 90, steps=stepping_steps, step_delay=stepping_delay)
            time.sleep(1)

            move_to(90, -90, steps=stepping_steps, step_delay=stepping_delay)
            time.sleep(1)


            print("Test completed.")
        except KeyboardInterrupt:
            print("Test interrupted by user.")
        except Exception as e:
            print(f"An error occurred during testing: {e}")




