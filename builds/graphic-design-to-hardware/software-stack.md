# Software stack — graphic design to hardware

Every one of these already exists. Clone or install them.

## design to toolpath (SVG/raster to G-code)
- **svg2gcode** — Convert paths in SVG files to GCode for a pen plotter, laser engraver, or other machine. _(crates)_
  - https://github.com/sameer/svg2gcode
- **svg2gcode** — Convert SVG to Gcode _(npm, MIT)_
  - https://github.com/em/svg2gcode
- **svg-to-gcode** — Convert SVG files to G-code for plotter _(npm, ISC)_
  - git+https://github.com/MidlajN/Svg2gCode-converter.git
- **svgcode** — A minimal SVG to GCODE converter for 2d operations _(npm, MIT)_
  - git+https://github.com/piLeoni/svgcode.git
  - _built from 8+ existing packages (crates:svg2gcode dependency graph, depth 1)_

## motion-controller firmware (runs G-code, drives steppers)
- **GRBL** — The classic open-source G-code parser and CNC motion controller written in optimized C, generating up to 30 kHz jitter-free step pulses with look-ahead acceleration. _(github, GPL-3.0)_
  - https://github.com/gnea/grbl
- **FluidNC** — The next-generation ESP32 CNC firmware from the grbl/grblESP32 lineage, configured via runtime YAML (no recompile) with a built-in WiFi web UI. _(github, GPL-3.0)_
  - https://github.com/bdring/FluidNC
- **grblHAL** — A hardware-abstraction-layer rewrite of grbl 1.1f that runs the same core on 32-bit MCUs with a plugin architecture, driven by separate per-chip driver repos. _(github, GPL-3.0)_
  - https://github.com/grblHAL/core
- **Marlin** — The dominant open-source RepRap 3D-printer firmware for 8- and 32-bit MCUs, which also ships built-in laser and CNC spindle (G-code) control for those machine types. _(github, GPL-3.0)_
  - https://github.com/MarlinFirmware/Marlin

## host / G-code sender (streams G-code over USB)
- **Universal Gcode Sender (UGS)** — Java-based cross-platform G-code sender for GRBL/FluidNC (plus TinyG, g2core, Smoothieware) with a dedicated jog controller panel, DRO, and 3D visualizer. _(github, GPL-3.0)_
  - https://github.com/winder/Universal-G-Code-Sender
- **CNCjs** — Node.js web-based CNC controller/G-code sender for GRBL, Marlin, Smoothieware, and TinyG, with a browser jog UI, 6-axis DRO, keyboard shortcuts, pendant support, and 3D toolpath view. _(github, MIT)_
  - https://github.com/cncjs/cncjs
- **OpenBuilds CONTROL** — Electron-based GRBL host/interface and G-code sender for CNC machines (GRBL and GRBL-compatible like FluidNC) with jogging, probing wizards, and job streaming. _(github, GPL-3.0)_
  - https://github.com/OpenBuilds/OpenBuilds-CONTROL
- **bCNC** — Advanced Python/Tkinter G-code sender for GRBL/grblHAL with jogging, auto-leveling (probe height map), a G-code editor, and CAM tools, runs well on low-power hardware like Raspberry Pi. _(github, GPL-2.0)_
  - https://github.com/vlachoudis/bCNC

