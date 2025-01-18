# from Adafruit_PCA9685 import PCA9685
from time import sleep
from Adafruit_PCA9685 import PCA9685

# Constants
PWM_FREQUENCY = 50
MIN_PULSE = 150  # Pulse length for -90 degrees
MAX_PULSE = 565  # Pulse length for +90 degrees
CENTER_PULSE = (MIN_PULSE + MAX_PULSE) // 2  # Pulse length for 0 degrees
ANGLE_RANGE = 90  # Range of motion in degrees (-90 to +90)

# Initialize the PCA9685
pwm = PCA9685(address=0x40, busnum=1)
pwm.set_pwm_freq(PWM_FREQUENCY)

def angle_to_pulse(angle):
    """
    Convert an angle (-90 to 90 degrees) to a pulse width.
    :param angle: The desired angle (-90 to +90 degrees)
    :return: Corresponding pulse width
    """
    if angle < -ANGLE_RANGE or angle > ANGLE_RANGE:
        raise ValueError(f"Angle must be between -{ANGLE_RANGE} and {ANGLE_RANGE} degrees.")
    # Map angle to pulse width
    pulse_width = int(CENTER_PULSE + (angle / ANGLE_RANGE) * (MAX_PULSE - CENTER_PULSE))
    return pulse_width

def set_servo_angle(channel, angle):
    """
    Set the servo to a specified angle.
    :param channel: The PWM channel for the servo (0 for pan, 1 for tilt)
    :param angle: The desired angle (-90 to +90 degrees)
    """
    pulse = angle_to_pulse(angle)
    pwm.set_pwm(channel, 0, pulse)

# Example usage
if __name__ == "__main__":
    import time

    channel_pan = 0
    channel_tilt = 1

    set_servo_angle(channel_pan, 0)
    set_servo_angle(channel_tilt, 0)

    try:
        while True:
            # Test angles: move to -90, 0, and +90 degrees
            for angle in [-90, 0, 90, 0]:
                print(f"Moving pan to {angle} degrees")
                set_servo_angle(channel_pan, angle)

                print(f"Moving tilt to {angle} degrees")
                set_servo_angle(channel_tilt, angle)
                time.sleep(1)

    except KeyboardInterrupt:
        print("Exiting...")