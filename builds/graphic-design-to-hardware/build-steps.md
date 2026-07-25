# Build steps — graphic design to hardware

## 1. Order the parts

Use bill-of-materials.md / order-list.csv. The base build is an Arduino Uno + CNC Shield V3 with two A4988 (or DRV8825) drivers, two NEMA17 steppers, GT2 belts and pulleys, linear motion (rods+LM8UU or MGN12 rails), a frame (2020 extrusion or laser-cut/printed), a 12V/24V power supply, endstops, and a tool head (SG90 servo pen lift to start; a diode laser module later).

Uses: electronics, motion + frame, tool head + sensors

## 2. Flash the controller firmware

Flash GRBL to the Arduino Uno (grbl for ATmega328), or FluidNC to an ESP32 board if you want Wi-Fi and a web UI. Set steps/mm, max rate, and acceleration for your steppers and pulley/belt pitch. GRBL config is the $$ settings; FluidNC uses a config.yaml.

Uses: motion-controller firmware

## 3. Assemble the machine

Build the frame, mount the two axes (X carriage on Y gantry, or a CoreXY layout), fit belts and pulleys, wire the steppers to the drivers on the CNC shield, wire the endstops, and mount the tool head. Set the A4988 driver current (Vref) before powering the motors.

Uses: motion + frame, electronics, tool head + sensors

## 4. Convert your design to G-code

For vector art, run svg2gcode (or vpype + vpype-gcode) to turn your SVG paths into G-code with pen-up/pen-down (or laser on/off) moves. For a raster image, use an image-to-gcode tool. Set travel/feed rates and the pen-lift servo angles (or laser PWM S-values).

Uses: design to toolpath

## 5. Stream and run

Open the G-code in a host sender (Universal Gcode Sender, CNCjs, or bCNC), connect over USB serial, home the machine, jog to the work origin, and run the job. Watch the first run closely and keep the power switch in reach.

Uses: host / G-code sender, design to toolpath

## Safety

If you fit a diode laser: it can permanently blind you and start fires. Wear laser-safety goggles rated for the exact wavelength (usually 445nm blue), never run it unattended, enclose the beam, add a fume extractor for cut materials, and keep a fire extinguisher nearby. For the mechanical build, set stepper-driver current correctly to avoid overheating, and disconnect power before touching wiring.

