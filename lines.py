from construct import *
from construct.debug import Probe
from constructutils import *

from intervaltree import Interval, IntervalTree

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
        "SourceFile" / PascalString(Int8ul, "ascii"),
    )

    def parsed(self, ctx):
        self.children = IntervalTree()
        for lines, subrange in zip(self.Children, self.ChildrenSubranges):
            lines = { k: v for k, v in zip(lines.LineOffset, lines.LineNumbers) }
            self.children[int(subrange.Start) : subrange.End + 1] = (self.SourceFile, lines)

        del self.SubrangeCount
        del self.Children
        del self.ChildrenSubranges

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

