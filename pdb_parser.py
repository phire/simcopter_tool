

import time, sys
from construct import *
from construct.debug import Debugger

from constructutils import *

from utils import *
from msf import *

from codeview import *
from lines import *
from tpi import *
from gsi import Gsi, Pgsi, LoadSymbols, Visablity
from pathlib import Path
from intervaltree import Interval, IntervalTree

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
    # Appears to be struct SC40:
    # https://github.com/microsoft/microsoft-pdb/blob/master/PDB/include/dbicommon.h#L19
    subcon = Struct(
        "Section" / Int16ul,
        "Unknown1" / Int16ul, # Always 0xcbf for valid entries
        "Offset" / Int32ul,
        "Size" / Int32ul,
        # https://learn.microsoft.com/en-us/windows/win32/api/winnt/ns-winnt-image_section_header
        "Characteristics" / Hex(Int32ul),
        "ModuleIndex" / Int16ul,
        "Pad2" / Int16ul,
    )

    def parsed(self, ctx):
        self.symbols = []
        self.things = {}

    def alignment(self) -> int:
        align = (self.Characteristics & 0x00f00000) >> 20
        if align == 0:
            return 0
        return 2 ** (align - 1)

    def characteristicsString(self):
        s = ""
        align = self.alignment()
        if align:
            s += f"{align} byte alignment, "
        if self.Characteristics & 0x00000020:
            s += "code, "
        if self.Characteristics & 0x00000040:
            s += "initialized_data, "
        if self.Characteristics & 0x00000080:
            s += "uninitialized_data, "
        if self.Characteristics & 0x00001000:
            # I'm pretty this marks functions that were defined in header files (and therefore
            # might have been included in multiple .obj files (before linking eliminated duplicates)
            s += "(comdat), "
        if self.Characteristics & 0x10000000:
            s += "shared, "
        if self.Characteristics & 0x20000000:
            s += "execute, "
        if self.Characteristics & 0x40000000:
            s += "read, "
        if self.Characteristics & 0x80000000:
            s += "write, "
        return s

    def is_code(self):
        return self.Characteristics & 0x00000020

    def is_data(self):
        return self.Characteristics & 0x00000040

    def is_bss(self):
        return self.Characteristics & 0x00000080

    def is_readonly(self):
        return self.Characteristics & 0x80000000 == 0

    def __str__(self):
        return f"{self.Section}:{self.Offset:08x}-{self.Offset+self.Size-1:08x} Module: {self.ModuleIndex}, {self.characteristicsString()}"

    def register(self, thing, offset, length):
        self.things[offset] = thing



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
        # Appears to be a copy of the last Section Contribution for this module.
        # which makes it kind of useless
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
        "ModuleName" / CString("ascii"), # name of the .obj file
        # When the .obj file was directly linked into the exe: ObjFilename == ModuleName
        # Otherwise, ObjFilename is the library it was previously linked into
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
        assert len(self.SectionContribution * SectionContrib.sizeof()) == dbi.SectionContributionSize
        assert size + DebugInfomationHeader.sizeof() == self._stream.size


class Section:
    def __init__(self, idx, section):
        self.idx = idx
        if section:
            self.name = section.Name
            self.va = 0x400000 + section.VirtualAddress
            self.data = section.Data
        else:
            self.va = None
        self.contribs = IntervalTree()

class ProgramData:
    """
    This class holds all the data parsed from a PDB file, including type information,
    global and public symbols, and module information.
    Since construct takes a long time to parse, this data is cached between runs.
    """
    def __init__(self, filename, exe, timeit=True):
        if timeit:
            now = None
            def timeit(desc):
                nonlocal now
                now = time.time()
                print(f"{desc}...    ", file=sys.stderr, end='', flush=True)

            def done():
                nonlocal now
                elapsed = int((time.time() - now) * 1000)
                print(f"done, {elapsed} ms", file=sys.stderr)
        else:
            def timeit(desc): pass
            def done(): pass

        self.exename = Path(filename).stem.upper()

        f = open(filename, "rb")
        msf = MsfFile.parse_stream(f)

        # debug information is always in stream 0x3
        dbi = DebugInfomation.parse_stream(msf.getStream(0x3))

        self.sections = [ Section(0, None) ] + [ Section(i + 1, s) for i, s in enumerate(exe.Sections) ] + [ Section(7, None) ]

        for e in dbi.SectionMap.Entries:
            self.sections[e.Frame].size = e.SectionLength
            #print(e)

        module_contribs = [[] for _ in dbi.ModuleInfo]
        for sc in dbi.SectionContribution:
            # put section contributions into the correct modules
            module_contribs[sc.ModuleIndex].append(sc)

            # add to interval trees for quick lookup
            section = self.sections[sc.Section]

            section.contribs[sc.Offset : sc.Offset + max(1, sc.Size)] = sc
            sc._data = section.data[sc.Offset : sc.Offset + sc.Size]

        timeit("parsing types")

        self.types = parse_tpi(msf)

        done()
        timeit("parsing GSI/PGSI")

        self.gsi = Gsi.parse_stream(msf.getStream(dbi.Header.GlobalSymbolStream))
        self.pgsi = Pgsi.parse_stream(msf.getStream(dbi.Header.PublicSymbolStream))

        done()
        timeit(f"parsing symbols")

        # The symbol record stream contains all globals (and public globals)
        self.symbols = LoadSymbols(msf.getStream(dbi.Header.SymbolRecordStream), self.types)

        done()
        timeit(f"parsing modules")

        # parse all modules
        self.modules = []
        for i, (modi, sources, contribs) in enumerate(zip(dbi.ModuleInfo, dbi.SourceInfo.Modules, module_contribs)):

            if modi.Stream != 0xffff:
                mod_stream = msf.getStream(modi.Stream)
                moduleStream = Struct(
                    "Symbols" / If(modi.SymbolsSize, (RestreamData(FixedSized(modi.SymbolsSize, GreedyBytes),
                        Struct(
                            "Signature" / Int32ul,
                            "Records" / RepeatUntil(lambda x, lst, ctx: x._io.tell() == modi.SymbolsSize, CodeviewRecord),
                            #"Records" / HexDump(GreedyBytes),
                        )
                    ))),
                    "Lines" / If(modi.LinesSize, (RestreamData(FixedSized(modi.LinesSize, GreedyBytes),
                        LinesSection
                        #HexDump(GreedyBytes),
                    ))))

                mod_details = moduleStream.parse_stream(mod_stream, types=self.types)

                symbols = toTree(list(mod_details.Symbols.Records)) if mod_details.Symbols else None
                lines = mod_details.Lines
            else:
                symbols = None
                lines = None

            self.modules.append((modi, sources, contribs, symbols, lines))

        done()

        f.close()

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

    #tpi = parse_tpi(tpi_stream)
    #print(tpi)

    dbi = DebugInfomation.parse_stream(dbi_stream)

    print(dbi.Header)

    symbolRecordStream = msf.getStream(dbi.Header.SymbolRecordStream)

    symbols = LoadSymbols(msf.getStream(dbi.Header.SymbolRecordStream))

    gsi_stream = msf.getStream(dbi.Header.GlobalSymbolStream)
    pgsi_stream = msf.getStream(dbi.Header.PublicSymbolStream)

    gsi = Gsi.parse_stream(gsi_stream)
    pgsi = Pgsi.parse_stream(pgsi_stream)

    for sym in gsi.all_hashes:
        rec = symbols.fromOffset(sym.offset - 1)
        if rec:
            rec.visablity = Visablity.Global
            rec.refcount = sym.refcount
        else:
            print(f"Global symbol {sym.offset-1:x} not found")


    for sym in pgsi.gsi.all_hashes:
        rec = symbols.fromOffset(sym.offset - 1)
        if rec:
            rec.visablity = Visablity.Public
            rec.refcount = sym.refcount
        else:
            print(f"Public symbol {sym.offset-1:x} not found")

    SymByAddress = {}

    # Put global/public symbols with known addresses in a map
    for sym in symbols.symbols:
        #print(f"{sym}")
        if isinstance(sym, (PublicData, GlobalData, LocalData)):
            SymByAddress[(sym.Segment, sym.Offset)] = sym
        elif isinstance(sym, ProcRef):
            module = sym.ModuleId
            offset = sym.SymbolOffset
        elif isinstance(sym, LocalProcRef):
            # I suspect these are functions from a module that have been re-exported into global visibility?
            pass
        elif isinstance(sym, Constant):
            # these appear to be enum values
            pass
        elif isinstance(sym, UserDefinedType):
            # I think these are typedefs?
            pass
        else:
           print(f"{sym}, {sym.__class__}")

    for sc in dbi.SectionContribution:
        module = dbi.ModuleInfo[sc.ModuleIndex]
        sources = dbi.SourceInfo.Modules[sc.ModuleIndex]
        source = "?"
        try:
            source = [s for s in sources if ".h" not in s][0]
        except IndexError:
            pass

        name = "?"
        ty = 0
        sym = None
        try:
            sym = SymByAddress[(sc.Section, sc.Offset)]
            name = sym.Name
            ty = sym.Type
        except KeyError:
            pass

        # todo: each section contribution might contain multiple symbols
        # todo: non-global symbols

        print(f"{sc.Section}:{sc.Offset:08x}-{sc.Offset+sc.Size-1:08x} {sc.ModuleIndex} {module.ModuleName} {source} {name} {ty}")

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

