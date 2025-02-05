from gpiozero import LED
import time

class WaterPistolController:
    def __init__(self, pin=14, active_high=True):
        # For a typical relay that activates on HIGH:
        self.relay = LED(pin, active_high=active_high)
        self.active = False

    def start(self):
        if not self.active:
            self.active = True
            # Turn relay ON
            self.relay.on()
            print("[WaterPistol] Started firing.")

    def stop(self):
        if self.active:
            self.active = False
            # Turn relay OFF
            self.relay.off()
            print("[WaterPistol] Stopped firing.")

    def cleanup(self):
        """
        gpiozero does automatic cleanup on exit,
        but you can explicitly close devices if you wish.
        """
        self.relay.close()

if __name__ == "__main__":
    GPIO_RELAY_PIN = 14
    waterpistol = WaterPistolController(pin=GPIO_RELAY_PIN)
    waterpistol.start()
    time.sleep(5)
    waterpistol.stop()
    waterpistol.cleanup()
