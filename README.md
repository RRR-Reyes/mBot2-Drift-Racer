# mBot2 Drift Racer

Drive an mBot2 like an RC race car from your phone, with a drift mode. Works on iPhone and Android.

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
3. Join the Wi-Fi shown on the CyberPi screen (default name `Mbot-Racer`).
4. Open `http://192.168.4.1` in your phone's browser, turn the phone sideways and tap to start.

### iPhone

- Use **Safari**.
- For full screen: Share > **Add to Home Screen**, then open it from your home screen.
- Sound plays even with the silent switch on.

### Android

- Use **Chrome** (or another Chromium-based browser).
- Type the address as `http://192.168.4.1`. Chrome may try `https` and fail, since the robot only serves plain `http`.
- The robot has no internet, so Android may say "No internet, connection may not work" or offer to switch networks. Choose to **stay connected**. If it keeps dropping to mobile data, turn mobile data off while driving.
- For full screen: Chrome menu (three dots) > **Add to Home screen** (or **Install app**), then open it from your home screen.
- Turn auto-rotate on, or the page will ask you to turn the phone sideways.
- Raise the media volume. Android may keep sound muted until you tap **TAP TO START ENGINE**.

## Tuning

If it spins in circles, set `FLIP_RIGHT = False`. If it drives backwards, set `FLIP_LEFT = True`. Drift settings (`DRIFT_ENTER`, `FLICK_MS`, `TARGET_YAW`, ...) are in the settings block. Smooth tape on the tires and a smooth floor help it slide.

## Troubleshooting

- **Page won't load:** check you are on the robot's Wi-Fi, use `http://` not `https://`, and turn off any VPN or private DNS.
- **Shows "offline" at the top:** the phone lost the Wi-Fi link. Move closer and make sure the phone didn't switch back to mobile data.
- **Robot stops by itself:** the failsafe triggers if the phone is silent for 700 ms. Keep the screen on and the browser in the foreground.
- **Port busy after re-upload:** power-cycle the robot.

## License

MIT
