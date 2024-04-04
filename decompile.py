
from pdb_parser import *
from gsi import *

from intervaltree import Interval, IntervalTree
from coff import Executable

def ext(filename : str):
    try:
        return filename.split('.')[-1].lower()
    except IndexError:
        return ''

includes = {}

class Include:
    def __init__(self, filename):
        self.filename = filename
        self.modules = []
        self.functions = []
        includes[filename] = self

    def get(filename):
        return includes.get(filename) or Include(filename)

class Function:
    def __init__(self, program, module, symbols, lines, contrib):
        self.module = module
        self.source_file = module.sourceFile
        self.symbols = symbols
        self.lines = lines
        self.name = symbols.Name
        self.contrib = contrib

        self.length = symbols.Len
        segment = program.sections[symbols.Segment]
        self.address = segment.va + symbols.Offset


class Module:
    # Modules are (typically) .obj files that were linked into the exe
    def __init__(self, program, library, idx, name, symbols, sources, linesInfo, contribs, globs):
        self.idx = idx
        self.library = library

        self.locals = []
        self.globals = globs
        self.functions = {}
        try:
            self.sourceFile = [s for s in sources if ext(s) in ('cpp', 'c', 'asm') ].pop()
        except IndexError:
            if ext(name) in ("res", "dll"):
                self.sourceFile = name
            elif ext(name) in ("obj"):
                self.sourceFile = name + ".c"
            else:
                raise Exception(f"don't know source name for {name}, {sources}")
        self.includes = {p: Include.get(p) for p in sources if ext(p) in ('h', 'hpp')}
        self.name = name
        self.sectionContribs = contribs

        for contrib in self.sectionContribs:
            contrib.module = self

        for inc in self.includes.values():
            inc.modules.append(self)

        lines_map = IntervalTree()

        if linesInfo:
            self.start = linesInfo.StartAddr
            self.end = linesInfo.EndAddr
            self.flags = linesInfo.Flags

            for file in linesInfo.Files:
                lines_map.update(file.children)

        for sym in symbols or []:
            if isinstance(sym, (ObjName, CompileFlags)):
                continue

            if isinstance(sym, (LocalProcedureStart, GlobalProcedureStart)):
                start, end = sym.Offset, sym.Offset + sym.Len
                try:
                    contrib = program.sections[sym.Segment].contribs[start:end].pop().data
                    contrib = (contrib, start - contrib.Offset)
                except KeyError:
                    # TODO: We should probally create a new contrib when this happens
                    contrib = None

                try:
                    source_file, lines = lines_map[sym.Offset].pop().data
                except KeyError:
                    source_file, lines = None, {}

                # trim lines, convert to relative offsets
                lines = {off - start: ln for off, ln in lines.items() if off >= start and off < end}

                fn = Function(program, self, sym, lines, contrib)

                self.functions[fn.name] = fn

                if source_file != self.sourceFile:
                    fn.source_file = source_file
                    try:
                        self.includes[source_file].functions.append(fn)
                    except KeyError:
                        pass
            elif isinstance(sym, Thunk):
                self.functions[sym.Name] = sym
            elif isinstance(sym, CodeLabel):
                # These only show up in libc, so just ignore those
                if self.library.name in ("LIBCMTD.lib"):
                    continue
                else:
                    raise Exception(f"unexpected CodeLabel {sym} in {self.name}")
            else:
                raise Exception(f"Unknown root symbol type {sym} in {self.name}")


class Library:
    # multiple .obj files might be pre-linked into a library
    def __init__(self, name, path):
        self.name = path.split('\\')[-1]
        self.path = path
        self.commonPath = None
        self.modules = {}

    def __str__(self):
        s = f"Library: {self.name} @ {self.path}"

        for m in self.modules:
            s += f"\n    {m.sourceFile or m.name }"
            for sc in m.sectionContribs:
                s += f"\n        {sc.Section}:{sc.Offset:08x} {sc.Size:x} {sc.characteristicsString()}"

        return s

    def is_dll(self):
        return all([ext(m.name) == 'dll' for m in self.modules.values()])

    def addModule(self, m):
        fullpath = m.sourceFile.lower()
        filename = fullpath.split('\\')[-1]
        path = fullpath[:-len(filename)]
        if not self.commonPath:
            # Start by assuming everything but the filename is common
            self.commonPath = path
        else:
            if self.commonPath == path:
                pass
            elif self.commonPath == path[:len(self.commonPath)]:
                filename = path[len(self.commonPath):] + filename
            else:
                # Find the common path
                path_parts = path.split('\\')
                common_parts = self.commonPath.split('\\')
                for i, (a, b) in enumerate(zip(path_parts, common_parts)):
                    if a != b:
                        break
                self.commonPath = '\\'.join(common_parts[:i]) + '\\'
                extra = '\\'.join(common_parts[i:])
                filename = fullpath[len(self.commonPath):]

                # update all existing keys
                self.modules = {extra + k: v for k, v in self.modules.items()}

        self.modules[filename] = m

class Section:
    def __init__(self, idx, section):
        self.idx = idx
        if section:
            self.name = section.Name
            self.va = 0x400000 + section.VirtualAddress
            self.data = section.Data
        self.contribs = IntervalTree()

class UnknownContribs:
    def __init__(self):
        self.symbols = []
        self.ModuleIndex = None
        self.module = None

    def __str__(self):
        return f"Unknown contribs: {len(self.symbols)}"

    def __getitem__(self, index):
        return self.symbols[index]


class Program:
    def __init__(self, filename, exe):
        f = open(filename, "rb")
        msf = MsfFile.parse_stream(f)

        dbi = DebugInfomation.parse_stream(msf.getStream(0x3))

        # For any modules not in a library, directly linked into the executable
        top = Library("", "")

        self.libraries = { "" : top }
        self.modules = []
        self.extra_globals = []

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
            section.contribs[sc.Offset : sc.Offset + sc.Size + 1] = sc
            sc._data = section.data[sc.Offset : sc.Offset + sc.Size]

        self.unknownContribs = UnknownContribs()

        # The symbol record stream contains all globals (and public globals)
        self.globals = LoadSymbols(msf.getStream(dbi.Header.SymbolRecordStream))

        # the only thing we really care about from GSI and PSGI is what visibility they apply to global symbols.
        # Though in theory it might be possible to
        gsi = Gsi.parse_stream(msf.getStream(dbi.Header.GlobalSymbolStream))
        gsi.apply_visablity(Visablity.Global, self.globals)

        pgsi = Pgsi.parse_stream(msf.getStream(dbi.Header.PublicSymbolStream))
        pgsi.gsi.apply_visablity(Visablity.Public, self.globals)

        module_globals = [[] for _ in dbi.ModuleInfo]
        for sym in self.globals:
            try:
                getModuleId = sym.getModuleId
            except AttributeError:
                # TODO: These are enum constants (CONSTANT) AND typedefs (UserDefinedType)
                #       We need to deal with them
                continue

            idx = getModuleId(self)
            if idx:
                module_globals[idx].append(sym)
            else:
                self.extra_globals.append(sym)

        # process all modules
        for i, (modi, sources, contribs, globs) in enumerate(zip(dbi.ModuleInfo, dbi.SourceInfo.Modules, module_contribs, module_globals)):

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

                mod_details = moduleStream.parse_stream(mod_stream)

                symbols = toTree(list(mod_details.Symbols.Records)) if mod_details.Symbols else None
                lines = mod_details.Lines

            m = Module(self, library, i, name, symbols, sources, lines, contribs, globs)

            self.modules.append(m)
            library.addModule(m)


if __name__ == "__main__":
    import sys

    pdb_file = "../debug_build_beta/COPTER_D.PDB"
    exe_file = "../debug_build_beta/COPTER_D.EXE"

    exe = Executable(exe_file)

    p = Program(pdb_file, exe)
    for lib in p.libraries.values():
        if lib.is_dll() or lib.name in ["OLDNAMES.lib", "LIBCMTD.lib"]:
            continue
        #print(lib)

    game = p.libraries["game.lib"]
    police = game.modules["s3police.cpp"]
    createfn = police.functions["PoliceCarClass::CreateInstance"]



    # for sym in p.unknownContribs:
    #     print(sym)
    #     for idx in range(sym.index - 1, 0, -1):
    #         try:
    #             contrib = p.globals[idx].contrib
    #             if contrib.module:
    #                 print(f"After {contrib.module.sourceFile}")
    #                 break
    #         except:
    #             try:
    #                 moduleId = p.globals[idx].getModuleId(p)
    #                 if moduleId:
    #                     print(f"After {p.modules[moduleId].sourceFile}")
    #                     break
    #             except AttributeError:
    #                 continue
    #     for idx in range(sym.index, len(p.globals)):
    #         try:
    #             contrib = p.globals[idx].contrib
    #             if contrib.module:
    #                 print(f"Before {contrib.module.sourceFile}\n")
    #                 break
    #         except:
    #             try:
    #                 moduleId = p.globals[idx].getModuleId(p)
    #                 if moduleId:
    #                     print(f"Before {p.modules[moduleId].sourceFile}\n")
    #                     break
    #             except AttributeError:
    #                 continue


    # for inc in includes.values():q
    #     print(inc.filename)
    #     for m in inc.modules:
    #         print(f"    {m.sourceFile or m.name }")
