

from construct import *
from construct.debug import Debugger

from constructutils import *


from utils import *
from msf import *

from codeview import *
from lines import *
from tpi import *


StreamNumT = Int16ul

class DebugInfomationHeader(ConstructClass):
    subcon = Struct(
        "GlobalSymbolStream" / StreamNumT,
        "PublicSymbolStream" / StreamNumT,
        "SymbolRecordStream" / StreamNumT,
        Padding(2),
        "ModuleInfoSize" / Int32ul,
        "SectionContributionSize" / Int32ul,
        "SectionMapSize" / Int32ul,
        "SourceInfoSize" / Int32ul,
    )

class SectionContrib(ConstructClass):
    subcon = Struct(
        "Section" / Int16ul,
        "Unknown1" / Int16ul, # Always 0xcbf for valid entries
        "Offset" / Int32ul,
        "Size" / Hex(Int32ul),
        "Characteristics" / Hex(Int32ul),
        "ModuleIndex" / Int16ul,
        "Pad2" / Int16ul,
    )

class SectionMapEntry(ConstructClass):
    subcon = Struct(
        "Flags" / Int16ul,
        "Overlay" / Int16ul, # Logical overlay number
        "Group" / Int16ul, # Group index
        "Frame" / Int16ul, # Frame index
        "SectionName" / Int16ul, # byte index of name in string table (or 0xffff)
        "ClassName" / Int16ul,
        "Offset" / Int32ul,
        "SectionLength" / Int32ul,
    )

class SectionMap(ConstructClass):
    subcon = Struct(
        "Count" / Int16ul,
        "LogicalCount" / Int16ul,
        "Entries" / Array(this.Count, SectionMapEntry),
    )

class SourceInfo(ConstructClass):
    subcon = Struct(
        "NumModules" / Int16ul,
        "NumSourceFiles" / Int16ul,

        "ModuleIndices" / Array(this.NumModules, Int16ul),
        "ModuleFileCounts" / Array(this.NumModules, Int16ul),
        # later version of the format ignore the 16bit NumSourceFiles and use this instead
        "ComputedNumSourceFiles" / Computed(lambda ctx: sum(ctx.ModuleFileCounts)),
        "FilenameOffsets" / Array(this.ComputedNumSourceFiles, Int32ul),
        #"Names" / GreedyRange(PascalString(Int8ub, "ascii")),
        # Names are indexed by offset, so we can't parse them until later
        "NamesBuffer" / HexDump(GreedyBytes),
    )

    NameString = PascalString(Int8ub, "ascii")

    def getName(self, idx):
        return self.NameString.parse(self.NamesBuffer[self.FilenameOffsets[idx]:])

    def parsed(self, ctx):
        # parse to a
        self.Modules = []
        for idx, count in zip(self.ModuleIndices, self.ModuleFileCounts):
            num = len(self.Modules)
            files = [self.getName(i) for i in range(idx, idx + count)]
            self.Modules.append(files)

        # Discard raw data
        del self.ModuleIndices
        del self.ModuleFileCounts
        del self.FilenameOffsets
        del self.NamesBuffer

class ModuleInfo(ConstructClass):
    # immediately follows header
    subcon = Aligned(4, Struct(
        "Unused" / Int32ul, # Currently open module?
        "SectionContrib" / SectionContrib,
        "Flags" / Int16ul,
        "Stream" / StreamNumT,
        "SymbolsSize" / Int32ul,
        "LinesSize" / Int32ul,
        "FramePointerOptSize" / Int32ul,
        "SourceFileCount" / Int16ul,
        Padding(2),
        #"pad" / Int16ul,
        "SourceFilenameIndex" / Int32ul,
        "ModuleName" / CString("ascii"),
        "ObjFilename" / CString("ascii"),
    ))

    def parsed(self, ctx):
        pass
        #print(f"ModuleInfo: {self.ModuleName} {self.ObjFilename} {self.Stream} {self.SymbolsSize} {self.LinesSize} {self.FramePointerOptSize} {self.SourceFileCount} {self.SourceFilenameIndex} {self.SectionContrib}")


class DebugInfomation(ConstructClass):
    subcon = Struct(
        "Header" / DebugInfomationHeader,
        "ModuleInfo" / FixedSized(this.Header.ModuleInfoSize,
           RepeatUntil(lambda x, lst, ctx: x._io.tell() == DebugInfomationHeader.sizeof() + ctx.Header.ModuleInfoSize,
           ModuleInfo
        )),
        "SectionContribution" / FixedSized(this.Header.SectionContributionSize,
            RepeatUntil(lambda x, lst, ctx: x._io.tell() == DebugInfomationHeader.sizeof() + ctx.Header.ModuleInfoSize + ctx.Header.SectionContributionSize,
            SectionContrib)
        ),
        "SectionMap" / FixedSized(this.Header.SectionMapSize, SectionMap),
        "SourceInfo" / FixedSized(this.Header.SourceInfoSize, SourceInfo),
    )

    def parsed(self, ctx):
        # contents of substreams should fill the stream
        dbi = self.Header
        size = dbi.ModuleInfoSize + dbi.SectionContributionSize + dbi.SectionMapSize + dbi.SourceInfoSize
        assert size + DebugInfomationHeader.sizeof() == self._stream.size


if __name__ == "__main__":
    import sys
    filename = sys.argv[1]

    f = open(filename, "rb")
    msf = MsfFile.parse_stream(f)
    # print(msf)

    if len(sys.argv) > 2:
        stream_idx = int(sys.argv[2])
        stream = msf.getStream(stream_idx)
        #stream.seek(0)
        data = stream.read(stream.size)
        chexdump(data)
        exit(0)

    # for i in range(len(msf)):
    #     stream = msf.getStream(i)
    #     data = stream.read(stream.size)

    #     if b"StationDirectoryNameArray" in data:
    #         print(f"Stream {i}\n\n")
    #         chexdump(data)


    #msf.getStream(0x3)

    tpi_stream = msf.getStream(2)
    dbi_stream = msf.getStream(3)

    #tpi = TypeInfomation.parse_stream(tpi_stream)
    #print(tpi)

    #exit(0)

    dbi = DebugInfomation.parse_stream(dbi_stream)

    print(dbi.Header)

    pub = GreedyRange(Aligned(4, CodeviewRecord)).parse_stream(msf.getStream(dbi.Header.SymbolRecordStream))
    print(pub)

    exit(0)

    if len(sys.argv) == 2:
        for i, (modi, source) in enumerate(zip(dbi.ModuleInfo, dbi.SourceInfo.Modules)):
            print(f"Module {i} {modi.ModuleName} {modi.Stream} {source}")

        exit()

    modi = dbi.ModuleInfo[int(sys.argv[2])]

    print(modi)

    print(dbi.SourceInfo.Modules[int(sys.argv[2])])

    if modi.Stream == 0xffff:
        print("No debug symbols")
    else:
        mod_stream = msf.getStream(modi.Stream)
        moduleStream = Struct(
            "Symbols" / If(modi.SymbolsSize, (RestreamData(FixedSized(modi.SymbolsSize, GreedyBytes),
                Struct(
                    "Signature" / Int32ul,
                    "Records" / RepeatUntil(lambda x, lst, ctx: x._io.tell() == modi.SymbolsSize, CodeviewRecord)
                )
            ))),
            "Lines" / If(modi.LinesSize, (RestreamData(FixedSized(modi.LinesSize, GreedyBytes),
                LinesSection
            ))),
        )
        symbols = moduleStream.parse_stream(mod_stream)
        print(symbols)

