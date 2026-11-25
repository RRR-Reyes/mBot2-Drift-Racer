# mbot2-drift-racer

Drive an mBot2 like an RC race car from your phone, with a drift mode.

The CyberPi hosts its own Wi-Fi hotspot and a web app. Open the page on your phone, turn it sideways and use two touch sticks. Engine sound, exhaust pops and horn play on the phone.

## Features

- Left stick for throttle, right stick for steering, plus BRAKE, BOOST and HORN buttons
- **DRIFT mode**: steer hard while moving forward and the inner wheel kicks back, then the robot holds a slide. A gyro assist keeps the spin rate steady
- After each drift the phone shows gyro rotation against what the wheels predicted, which gives a slip %
- Auto-brake using the ultrasonic sensor (brakes earlier at higher speed)
- Car-style lights on the CyberPi: headlights, turn signals, brake, reverse, parking
- Optional "evil eyes" on the ultrasonic sensor LEDs
- Failsafe stop if the phone goes quiet

## Setup

1. Edit `ROBOT_WIFI_PASS` at the top of `mbot2_drift_racer.py` (8+ characters).
2. In mBlock 5, open the Python editor, switch to Upload mode and upload the file. Power-cycle the robot afterwards.
3. Join the Wi-Fi shown on the CyberPi screen.
4. Open `192.168.4.1` in Safari, turn the phone sideways, tap to start. On iPhone, use Share > Add to Home Screen for full screen.

## Tuning

If it spins in circles, set `FLIP_RIGHT = False`. If it drives backwards, set `FLIP_LEFT = True`. Drift settings (`DRIFT_ENTER`, `FLICK_MS`, `TARGET_YAW`, ...) are in the settings block. Smooth tape on the tires and a smooth floor help it slide.

## License

MIT
