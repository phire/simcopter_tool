
from pdb_parser import *

from intervaltree import Interval, IntervalTree

def ext(filename : str):
    try:
        return filename.split('.')[-1]
    except IndexError:
        return ''


class Module:
    # Modules are (typically) .obj files that were linked into the exe
    def __init__(self, idx, name, symbols, sources, linesInfo):
        self.idx = idx
        self.symbols = symbols
        self.globalSymbols = {}
        try:
            self.sourceFile = [s for s in sources if ext(s) in ('cpp', 'c', 'asm') ].pop()
        except IndexError:
            self.sourceFile = None
        self.includes = [s for s in sources if ext(s) in ('h', 'hpp')]
        self.name = name
        self.sectionContribs = []

        if linesInfo:
            self.start = linesInfo.StartAddr
            self.end = linesInfo.EndAddr
            self.flags = linesInfo.Flags

            for file in linesInfo.Files:
                pass

class Library:
    # multiple .ojb files might be pre-linked into a library
    def __init__(self, name, path):
        self.name = path.split('\\')[-1]
        self.path = path
        self.modules = []

    def __str__(self):
        s = f"Library: {self.name} @ {self.path}"

        for m in self.modules:
            s += f"\n    {m.sourceFile or m.name }"
            for sc in m.sectionContribs:
                s += f"\n        {sc.Section}:{sc.Offset:08x} {sc.Size:x}"

        return s

class Section:
    def __init__(self, name, idx):
        self.name = name
        self.idx = idx
        self.contribs = IntervalTree()


class Program:
    def __init__(self, filename):
        f = open(filename, "rb")
        msf = MsfFile.parse_stream(f)

        dbi = DebugInfomation.parse_stream(msf.getStream(0x3))

        # For any modules not in a library, directly linked into the executable
        top = Library("", "")

        self.libraries = { "" : top }
        self.modules = []

        # process all modules
        for i, (modi, sources) in enumerate(zip(dbi.ModuleInfo, dbi.SourceInfo.Modules)):

            library = top
            name = modi.ModuleName.split('\\')[-1]
            symbols = None
            lines = None

            if modi.ModuleName != modi.ObjFilename:
                lib_name = modi.ObjFilename.split('\\')[-1]
                library = self.libraries.get(lib_name)
                if not library:
                    library = Library(lib_name, modi.ObjFilename)
                    self.libraries[lib_name] = library

                if lib_name in self.libraries:
                    lib = self.libraries[lib_name]

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

                try:
                    mod_details = moduleStream.parse_stream(mod_stream)

                    symbols = mod_details.Symbols
                    lines = mod_details.Lines
                except:
                    print(f"Error parsing module {sources}")


            m = Module(i, name, symbols, sources, lines)

            self.modules.append(m)
            library.modules.append(m)
            m.library = library

        # Just hardcode these names now
        self.sections = [
            Section("Headers", 0),
            Section(".text", 1),
            Section(".rdata", 2),
            Section(".data", 3),
            Section(".idata", 4), # import descriptors
            Section(".rsrc", 5), # resources
            Section(".reloc" , 6), # relocation table
        ]

        for e in dbi.SectionMap.Entries:
            self.sections[e.Frame].size = e.SectionLength
            #print(e)

        for sc in dbi.SectionContribution:
            # put section contributions into the correct modules
            m = self.modules[sc.ModuleIndex]
            m.sectionContribs.append(sc)

            # add to interval trees for quick lookup
            section = self.sections[sc.Section]
            section.contribs[sc.Offset : sc.Offset + sc.Size] = sc




    def from_file(filename):
        pdb = ProgramDatabase()

if __name__ == "__main__":
    import sys

    pdb_file = "../debug_build_beta/COPTER_D.PDB"
    exe_file = "../debug_build_beta/COPTER_D.EXE"

    p = Program(pdb_file)
    for lib in p.libraries.values():
        print(lib)
