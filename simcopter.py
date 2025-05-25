

# These are includes mentioned by assert statements.
# But don't show up in LineInfo at all.

extra_includes = [
    "C:\\Copter\\source\\sparkal\\memory.hpp",
    "C:\\Copter\\source\\game\\S3MOBILE.H",
    "C:\\Copter\\Source\\Game\\S3WMOBIL.H",
    "C:\\Copter\\Source\\Game\\S3MOBILE.H",
    "c:\\copter\\source\\x\\Array2d.h",
]

source_prefix = "c:/copter/source/"
source_prefix2 = "/copter/source/"


libs = {
    "COPTER_D": "",
    "wcommon.lib": "common/",
    "vrengine.lib": "engine/",
    "game.lib": "game/",
    "x.lib": "x/",
}

unknowns = {

}

source_override = {
    # We don't have a source filename for these, probably because they have no functions
    # Or all the functions were inlined and/or garbage collected.
    "fixed.obj": "fixed.asm",
    "io.obj": "io.c",
    "s2global.obj": "s2global.c",
}