# Bioyond S4 Slide-Handling Application Context Pack

This package contains the authoritative robot manuals, TCP protocol, controller
Lua sources, and reference Python clients needed to design a custom autonomous
slide-handling application for the Bioyond LabGenius S4.

Start with `01_Project_Context/AGENT_CONTEXT.md`.

## Package contents

- `01_Project_Context/` - concise project brief and known constraints.
- `02_Protocol/` - raw BRCAPI TCP/JSON protocol specification.
- `03_Integration/` - host/Lua automation integration examples.
- `04_Manuals/` - Bioyond Works and S4 hardware/safety manuals.
- `05_Controller_Lua/user/` - complete controller Lua sample project.
- `06_Python_Reference/` - vendor reference clients; these require hardening.
- `07_Cell_Photos_and_Fixture_Drawings/` - placeholder for cell imagery/CAD.
- `08_Arducam_Model_Documentation/` - placeholder for the exact camera manual.

## Important warning

This software controls physical machinery. Keep the hardware E-stop available,
validate motion at low speed with dummy slides, and do not automatically retry
an uncertain motion command.

