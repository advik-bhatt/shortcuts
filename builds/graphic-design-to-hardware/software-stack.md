# Software stack — graphic design to hardware

Every one of these already exists. Clone or install them.

## design to toolpath (SVG/raster to G-code)
- **juicy-gcode** — Command-line SVG-to-G-code converter with good Bezier handling and a configurable flavor for pen plotters. _(github, BSD-3-Clause)_
  - https://github.com/domoszlai/juicy-gcode
- **svg2gcode** — Convert paths in SVG files to GCode for a pen plotter, laser engraver, or other machine. _(crates)_
  - https://github.com/sameer/svg2gcode
- **svg2gcode** — Convert SVG to Gcode _(npm, MIT)_
  - https://github.com/em/svg2gcode
- **svg-to-gcode** — Convert SVG files to G-code for plotter _(npm, ISC)_
  - git+https://github.com/MidlajN/Svg2gCode-converter.git
  - _built from 8+ existing packages (crates:svg2gcode dependency graph, depth 1)_

## motion-controller firmware (runs G-code, drives steppers)
- **grbl** — The classic G-code motion controller firmware for the ATmega328 (Arduino Uno). Runs a small CNC/plotter/laser from G-code. _(github, GPL-3.0)_
  - https://github.com/gnea/grbl
- **Marlin** — The dominant 3D-printer/CNC firmware; also drives plotters and laser rigs. Heavier than GRBL but very capable. _(github, GPL-3.0)_
  - https://github.com/MarlinFirmware/Marlin
- **FluidNC** — Modern GRBL-style firmware for the ESP32 with Wi-Fi, a web UI, and config.yaml. Great if you want wireless control. _(github, GPL-3.0)_
  - https://github.com/bdring/FluidNC

## host / G-code sender (streams G-code over USB)
- **Universal Gcode Sender (UGS)** — Cross-platform Java host that streams G-code to GRBL/TinyG/FluidNC over USB, with jogging, visualizer, and macros. _(github, GPL-3.0)_
  - https://github.com/winder/Universal-G-Code-Sender
- **CNCjs** — A web-based G-code sender/controller (Node.js) for GRBL/Smoothie/TinyG; runs in the browser, great on a Raspberry Pi. _(github, MIT)_
  - https://github.com/cncjs/cncjs
- **bCNC** — Python/Tk GRBL sender with a strong toolpath editor, autoleveling, and G-code utilities. _(github, GPL-2.0)_
  - https://github.com/vlachoudis/bCNC
- **gcode-preview** — Preview a 3d print from a gcode file _(npm, MIT)_
  - git+ssh://git@github.com/remcoder/gcode-preview.git
  - _built from 2+ existing packages (npm:gcode-preview dependency graph, depth 1)_

