# AI Object Detection with Pan/Tilt and Water Pistol

**This is work in progress, documentation will get better!!**

This is still a work in progress and is shared to allow others to create their own personal devices to use. 
If you are beginner with a raspberry PI you may wish to try other projects first and get familiar with them. 
We will be releasing a kit to purchase that will make it easier and a fully assembled product. 

Currently, it has only been tested on a Raspberry Pi 4b with an AI Camera, but I plan to do the following variations

* Raspberry Pi 5 with AI camera
* Raspberry Pi 5 or 4b any camera
* Raspberry Pi 5 with any camera plus AI accelerator 
* Raspberry Pi Zero 2w with AI camera (a compact version)
***
# Main Part list
![Parts](docs/images/parts_list3.png)

You will need parts similar to these:
* Raspberry Pi (4b or 5)
* Raspberry Pi AI Camera
* PCA9685 servo controller
* None latching relay
* Electric water pistol
* Pan / Tilt Mechanism
* 2 x Servos
* Power Supply
* Cables for connecting it up
* Tubing for water pistol
* Case for Components

### Links to parts
You can use these or similair, the links give you an idea of what you might 
need but can be sourced from any supplier :-)  Will add other links later

| Description             | Links                                                                                |
|-------------------------|--------------------------------------------------------------------------------------|
| Raspberry Pi 4b         | [Pimornoi](https://shop.pimoroni.com/products/raspberry-pi-4?variant=29157087412307) |
| Raspberry Pi 5b         | [Pimoroni](https://shop.pimoroni.com/products/raspberry-pi-5?variant=42119790428243) |
| Raspberry Pi AI Camera  | [Pimoroni](https://shop.pimoroni.com/products/raspberry-pi-ai-camera)                |
| PCA9685 Servo Contoller | [Amazon](https://www.amazon.co.uk/dp/B0BKZC1XWR)                                     |
| None Lataching Relay    | [Adafruit](https://www.adafruit.com/product/4409)                                    |
| Electric Water Pistol   | [Amazon](https://www.amazon.co.uk/dp/B0BWNDTKFJ)                                     |
| Pantilt Mechanism       | [Ali Express](https://www.aliexpress.com/item/1406199345.html)                       |
| 2 x Servos              | [Ali Express](https://www.aliexpress.com/item/1005007208312977.html)                 |
| Power Supply            | Work In Prgress, will update soon                                                    |
| Cables                  | TBC                                                                                  |
| Tubing for water pistol | [Amazon](https://www.amazon.co.uk/dp/B07PNQ5BXD)                                     |
| Case fro Compnents      | Whatever fits, will add 3d printed one later                                         |

***
# Connecting the parts together

### Water Pistol and Relay (plus connections)
You will need to disiasbmle the water pistol and take out the pump mechanism
shown below, the link to the part above is simple to take apart with a screw driver.
Once you have that make sure you keep the connector for the tubing which you put in the
water source.
![Water Pistol](docs/images/water_pistol3.png)

The Relay I used is shown below, this is used to turn the water pistol mechanism on and off
![Relay](docs/images/relay.png)

Connect the DC Motor, Power Source for Motor, Relay and Raspberry Pi as in the below diagram.  For the power supply for the
DC motor you can use the battery as the power source that cam with it for now (I am working on a power supply design).  
**DO NOT try to power the DC motor directly from the raspberry Pi**
![relay_wiring](docs/images/Pump_and_relay_wiring.png)

### Pan/Tilt withe servos and PCA9685
The pan/tilt mechanism is used to move the camera and the water pistol together. 
The pan/tilt mechanism is driven by two servos, int he exmaple it is using MG996R 180 degree servos.
The servos are power and contolled by a PCA9685.

You can use whatever pan/tilt mechanism that suits you needs, below is an example pan/tilt with servo connected.
![pan_tilit](docs/images/pan_tilt.png)

The PCA9685, shown below is used to control the servos.  Due to the stall current
of the servos you need to supply a power source for these direct to the PCA9685.
Also, due to the control signals the grnd ot the raspberry pi must be connected to 
the ground (-ve) of the power supply for the servos so they have a common ground.
![PCA9685](docs/images/pca_image.png)

To connect this up the interface pins are connected to the raspberry pi and then the pan servo and 
tilt servo are connected the first two channels (on the left in the above diagram the first two sets of three pins).  
Finally connect the power supply for ther servos the PCA9685.
![Servo Wiring](docs/images/servo_wiring.png)

### Overall Wiring Diagram
The below diagram shows the overall circuit wiring for the servos and the water pump dc motor.
Note that the batteries in the image are just for illustration purposes
![wiring](docs/images/Wiring.png)


### AI Camera
You simply connect the AI camera to the raspberry pi camera porton the Raspberry PI 4b.
Make sure you use the correct cable that comes with it.
![AI Camera](docs/images/ai_camera.png)

## Assembly Guide
TBC to completed, will contain how to put it all togther.  But breifly make sure 
the camera and water pump are mounted on the pan/tilt device.


***
# Getting it running
Once all the components are wired up (suggest you dont put it in a box until after you test it) 
you need to make sure the Raspberry PI is installed with the latest version of the Raspberry PI OS.
The install the software which is detailed below.




## Raspberry PI Installation
On the raspberry pi pmake sure it is up to date with the latest packages installed and install the Raspberry Pi AI camera packages `imx500-all` and some extra packages needed to run (they may already be installed but thats ok)

From the terminal run
```
sudo apt update
sudo apt upgrade
sudo apt install imx500-all
sudo apt install python3-opencv python3-munkres
sudo apt install python3 python3-venv python3-pip
```

Enable I2C port on the raspberry pi and reboot (this will be needed for the PCA9685)
```
sudo raspi-config nonint do_i2c 0
sudo reboot
```


## PCA9685 i2c address
When the PCA9685 is connected to the pi you can check you can see it ands it address by running the command `i2cdetect -y 1`.  If you dont have ic2detect already installed you can install it with `sudo apt install -y i2c-tools`

The output of `i2cdetect -y 1` should look something like this
```
     0  1  2  3  4  5  6  7  8  9  a  b  c  d  e  f
00:                         -- -- -- -- -- -- -- -- 
10: -- -- -- -- -- -- -- -- -- -- -- -- -- -- -- -- 
20: -- -- -- -- -- -- -- -- -- -- -- -- -- -- -- -- 
30: -- -- -- -- -- -- -- -- -- -- -- -- -- -- -- -- 
40: 40 -- -- -- -- -- -- -- -- -- -- -- -- -- -- -- 
50: -- -- -- -- -- -- -- -- -- -- -- -- -- -- -- -- 
60: -- -- -- -- -- -- -- -- -- -- -- -- -- -- -- -- 
70: 70 -- -- -- -- -- -- -- 
```
This shows the Device Address of the PCA9685 module is `0x40` and its all-call address is `0x70`.  If this is different you will need to adjust the configuration by 
changing the `I2C_ADDRESS ` in the `my_configuration.py` file
.

## Get software and setup venv


First clone the software from Github (This needs updating) 
```
cd
git -c http.sslVerify=false clone https://gitlab.v2d.co.uk:743/v2d/ai_object_plus_water.git

```
Create a new `venv` that inherits the site packages, activate it and make sure all packages are installed
```
cd ai_object_plus_water
python3 -m venv --system-site-packages myenv
source myenv/bin/activate
pip install -r requirements.txt 
```
## Testing the Relay and Servos
Before you use the main software there are a couple of test scripts
so you can check the relay works and the servo works, you may need to edit them.
Make sure you run them from the `venv` you have setup.

The scripts are:

`test_scripts/pca9685_test.py` for the servo/PCA9685 testing

`test_scripts/relay_test.py` for the relay


## Software Configuration
The configurable parameters are set in the file `my_configuration.py`.  This will be moved to a JSON file in the future 
but to for now use this.  Before you run the `main.py` edit this file to suit your needs.  There are comments in the file to explain it.


## Running the program



Run the `main.py` from within you `venv`
```
python -u main.py
```
If successful you should see something like this in your terminal

```
[0:22:30.207928494] [12234]  INFO Camera camera_manager.cpp:325 libcamera v0.3.2+99-1230f78d
[0:22:30.224500745] [12238]  WARN CameraSensorProperties camera_sensor_properties.cpp:305 No static properties available for 'imx500'
[0:22:30.224554986] [12238]  WARN CameraSensorProperties camera_sensor_properties.cpp:307 Please consider updating the camera sensor properties database
[0:22:30.235821534] [12238]  WARN RPiSdn sdn.cpp:40 Using legacy SDN tuning - please consider moving SDN inside rpi.denoise
[0:22:30.238001426] [12238]  INFO RPI vc4.cpp:447 Registered camera /base/soc/i2c0mux/i2c@1/imx500@1a to Unicam device /dev/media3 and ISP device /dev/media0
[0:22:30.238108888] [12238]  INFO RPI pipeline_base.cpp:1120 Using configuration file '/usr/share/libcamera/pipeline/rpi/vc4/rpi_apps.yaml'

------------------------------------------------------------------------------------------------------------------
NOTE: Loading network firmware onto the IMX500 can take several minutes, please do not close down the application.
------------------------------------------------------------------------------------------------------------------

[0:22:30.319423044] [12234]  INFO Camera camera.cpp:1197 configuring streams: (0) 1920x1080-XBGR8888 (1) 640x360-YUV420 (2) 2028x1520-SRGGB10_CSI2P
[0:22:30.319876392] [12238]  INFO RPI vc4.cpp:622 Sensor: /base/soc/i2c0mux/i2c@1/imx500@1a - Selected sensor format: 2028x1520-SRGGB10_1X10 - Selected unicam format: 2028x1520-pRAA
/home/pi/ai_object_plus_water/main.py:330: RuntimeWarning: This channel is already in use, continuing anyway.  Use GPIO.setwarnings(False) to disable warnings.
  GPIO.setup(self.relay_pin, GPIO.OUT)
2025-01-17 12:50:53 [INFO] my_app_logger: Starting main loop...
 * Serving Flask app 'main'
 * Debug mode: off
WARNING: This is a development server. Do not use it in a production deployment. Use a production WSGI server instead.
 * Running on all addresses (0.0.0.0)
 * Running on http://127.0.0.1:5000
 * Running on http://192.168.0.175:5000
Press CTRL+C to quit

```
Note that the ip address `192.168.0.175` in the above output should appear as the IP address of the raspberry pi you have setup.

You can now access the web interface.  If you are running locally on your raspberry pi with a local display you can go to http://127.0.0.1:5000 in your browser.

If you are accessing the raspberry pi remotely use the IP address of your raspberry pi to connect to it, in the example above this would be http://192.168.0.175:5000 replacing `192.168.0.175` with the IP address of your raspberry PI 

The web interface is currently not secure and anyone on the network your raspberry pi is connected to can access it.





***
## Useful Links
[Raspberry Pi AI Camera Documentation](https://www.raspberrypi.com/documentation/accessories/ai-camera.html) - How to install and setup the Raspberry PI Camera

[Sony IMX500 Export for Ultralytics YOLOv8 Documentation](https://docs.ultralytics.com/integrations/sony-imx500/) - How to create your own models using YoloV8n for the Raspberry Pi AI Camera

[PCA9685 Servo Driver guide from Kevs Robots](https://www.kevsrobots.com/learn/pca9685/04_introduction_to_pca9685.html) - Useful resource on working with Servos. 

***
## License
Software is Licensed under Apache 2 with a common clause so it cannot be used for commercial purposes at this time.  See the [LICENSE](LICENSE) file for details.
Basically this is just for personal use for people who want to build their own device.

***
## Common Issues
To Be Updated


