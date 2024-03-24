from construct import *
from construct.debug import Probe
from constructutils import *


class Lines(ConstructClass):
    subcon = Struct(
        Const(1, Int16ul),
        "LineCount" / Int16ul,
        "LineOffset" / Array(this.LineCount, Int32ul),
        "LineNumbers" / Array(this.LineCount, Int16ul),
    )

class File(ConstructClass):
    subcon = Struct(
        "SubrangeCount" / Int32ul,
        "Children" / Array(this.SubrangeCount,
            FocusedSeq("Lines",
                "Offset" / Int32ul,
                "Lines" / Pointer(this.Offset, Lines),
            )
        ),
        "ChildrenSubranges" / Array(this.SubrangeCount, Struct(
            "Start" / Hex(Int32ul),
            "End" / Hex(Int32ul),
        )),
        Probe(lookahead=10),
        "SourceFile" / PascalString(Int8ul, "ascii"),

    )

class LinesSection(ConstructClass):
    subcon = Struct(
        "FileCount" / Int16ul,
        Const(1, Int16ul),
        "Files" / Array(this.FileCount,
            FocusedSeq("File",
                "Offset" / Int32ul,
                "File" / Pointer(this.Offset, File),
            )
        ),
        "StartAddr" / Int32ul,
        "EndAddr" / Int32ul,
        "Flags" / Int16ul,
    )
