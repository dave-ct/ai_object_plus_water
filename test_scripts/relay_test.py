import RPi.GPIO as GPIO
import time

class WaterPistolController:
    def __init__(self, pin=14):  # Using TX pin (GPIO14) by default
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
            print("[WaterPistol] Started firing.")

    def stop(self):
        if self.active:
            self.active = False
            # Turn relay OFF
            GPIO.output(self.relay_pin, GPIO.LOW)
            print("[WaterPistol] Stopped firing.")

    def cleanup(self):
        """Clean up GPIO settings - should be called when program exits"""
        GPIO.cleanup()


if __name__ == "__main__":
    #Set the pin the relay is connected to
    GPIO_RELAY_PIN = 14
    waterpistol = WaterPistolController(pin=GPIO_RELAY_PIN)
    waterpistol.start()
    time.sleep(5)
    waterpistol.stop()
    waterpistol.cleanup()

