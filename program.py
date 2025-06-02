
from pdb_parser import *
from gsi import *
import tpi
from collections import defaultdict


from function import Function, TypeUsage
from classes import parse_classes

def ext(filename : str):
    try:
        return filename.split('.')[-1].lower()
    except IndexError:
        return ''

class Include:
    def __init__(self, filename):
        self.filename = filename
        self.modules = []
        self.functions = []

class Item:
    def __init__(self, sym, address):
        self.sym = sym
        self.address = address
        self.length = sym.Len
        self.name = sym.Name

    def post_process(self):
        # This is called after the module has been fully processed
        # and all symbols have been linked to types
        pass

    def data(self):
        try:
            contrib = self.sym.contrib
            offset = self.sym.contribOffset
            length = self.length
            return contrib._data[offset: offset+length]
        except AttributeError:
            return None

class Data(Item):
    def __init__(self, sym, address, ty):
        self.sym = sym
        self.address = address
        try:
            self.length = ty.type_size()
        except:
            self.length = 1
        self.ty = ty
        self.name = sym.Name

    def initializer(self):
        if self.ty.getCon() is None:
            # If there is no construct, we cannot initialize it
            return "{ 0 /* todo */ }"
        if (data := self.data()) is None:
            return "{ 0 /* error */ }"

        parsed = self.ty.getCon().parse(data)

        return self.ty.initializer(parsed)

    def as_code(self):
        cls = getattr(self.ty, '_class', None)
        cls = getattr(self.ty, '_def_class', cls)
        s = self.ty.typestr(self.name)

        if isinstance(self.sym, LocalData):
            s = f"static {s}"

        if self.sym.visablity == Visablity.Public:
            s = f"extern {s}"

        try:
            is_bss = self.sym.contrib.is_bss()
        except AttributeError:
            s += "; // Contrib missing\n"
            return s
        if not is_bss:
            s += f" = {self.initializer()};\n"
        else:
            s += ";\n"

        return s



class Usage:
    def __init__(self, ty, other, mode: TypeUsage):
        while True:
            match ty:
                case tpi.LfPointer():
                    ty = ty.Type.Type
                    mode = self.Ptr(ty, mode)
                case tpi.LfModifier():
                    ty = ty.Type.Type
                    mode = self.Modifier(ty, mode)
                case tpi.LfArray():
                    ty = ty.Type.Type
                    mode = self.Array(ty, mode)
                case _:
                    break
        self.ty = ty
        self.other = other
        self.mode = mode



    class Modifier:
        def __init__(self, modifier_ty, mode):
            self.modifier_ty = modifier_ty
            self.mode = mode

        def __repr__(self):
            return f"Modifier({self.modifier_ty.typestr()}, {self.mode!r})"

    class Ptr:
        def __init__(self, ptr_ty, mode):
            self.ptr_ty = ptr_ty
            self.mode = mode

        def __repr__(self):
            return f"Ptr({self.ptr_ty.typestr()}, {self.mode!r})"

    class Array:
        def __init__(self, array_ty, mode):
            self.array_ty = array_ty
            self.mode = mode

        def __repr__(self):
            return f"Array({self.array_ty.typestr()}, {self.mode!r})"


    def __repr__(self):
        return f"Usage({self.ty.typestr()}, {self.other!r} {self.mode!r})"



class Module:
    # Modules are (typically) .obj files that were linked into the exe
    def __init__(self, program, library, idx, name, symbols, sources, linesInfo, contribs, globs):
        self.idx = idx
        self.library = library

        self.locals = []
        self.globals = globs
        self.functions = {}
        self.all_items = []
        self.unknowns = []
        self.used_types = defaultdict(set)

        try:
            self.sourceFile = [s for s in sources if ext(s) in ('cpp', 'c', 'asm') ].pop()
        except IndexError:
            if ext(name) in ("res", "dll"):
                self.sourceFile = name
            elif ext(name) in ("obj"):
                self.sourceFile = name
            else:
                raise Exception(f"don't know source name for {name}, {sources}")
        self.includes = {p: program.getInclude(p) for p in sources if ext(p) in ('h', 'hpp')}
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

        for g in self.globals:
            try:
                g.contrib.register(g, g.Offset - g.contrib.Offset, 0)
            except AttributeError:
                continue
            ty = program.types.types[g.Type]
            item = Data(g, program.getAddr(g.Segment, g.Offset), ty)
            if item.length:
                program.items[item.address: item.address + item.length] = item
            self.use_type(ty, item, TypeUsage.GlobalData)

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
                self.all_items += [fn]

                if fn.length:
                    program.items[fn.address: fn.address + fn.length] = fn

                if source_file != self.sourceFile:
                    fn.source_file = source_file
                    try:
                        self.includes[source_file].functions.append(fn)
                    except KeyError:
                        pass
            elif isinstance(sym, Thunk):
                self.functions[sym.Name] = Item(sym, program.getAddr(sym.Segment, sym.Offset))
            elif isinstance(sym, CodeLabel):
                # These only show up in libc, so just ignore those
                if self.library.name in ("LIBCMTD.lib"):
                    continue
                else:
                    raise Exception(f"unexpected CodeLabel {sym} in {self.name}")
            else:
                raise Exception(f"Unknown root symbol type {sym} in {self.name}")

    def use_type(self, ty, other, mode):
        if ty.TI == 0:
            return

        usage = Usage(ty, other, mode)
        self.used_types[usage.ty].add(usage)

    def __repr__(self):
        return f"Module({self.name!r}, {self.sourceFile!r}, ...)"


class Library:
    # multiple .obj files might be pre-linked into a library
    def __init__(self, name, path):
        self.name = name
        self.path = path
        self.commonPath = None
        self.modules = {}

    def __str__(self):
        s = f"Library: {self.name} @ {self.path}"

        for m in self.modules.values():
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
        self.modules[filename] = m

        if fullpath.endswith('.res'):
            return

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
                #self.modules = {extra + k: v for k, v in self.modules.items()}


    def __repr__(self):
        return f"Library({self.name!r}, {self.path!r}, {len(self.modules)} modules)"




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
    def __init__(self, data):

        # dummy library to hold modules not in a library, directly linked into the executable
        self.exename = data.exename
        top = Library(data.exename, "C:\\Copter\\source\\")

        self.libraries = { data.exename : top }
        self.modules = []
        self.extra_globals = []
        self.includes = {}
        self.sections = data.sections
        self.unknownContribs = UnknownContribs()
        self.types = data.types

        # The symbol record stream contains all globals (and public globals)
        self.globals = Symbols(data.symbols, self.types)

        self.classes = parse_classes(self)

        # the only thing we really care about from GSI and PSGI is what visibility they apply to global symbols.
        # Though in theory it might be possible to learn something about the ordering

        data.gsi.apply_visablity(Visablity.Global, self.globals)
        data.pgsi.gsi.apply_visablity(Visablity.Public, self.globals)

        self.items = IntervalTree()

        module_globals = [[] for _ in data.modules]
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

        for g in self.extra_globals:
            if g.Segment == 7:
                continue
            # Todo: These are globals that are not in any module... for some reason

            item = Data(g, self.getAddr(g.Segment, g.Offset), self.types.types[g.Type])
            if item.length:
                self.items[item.address: item.address + item.length] = item

        # process all modules
        for i, (modi, sources, contribs, symbols, lines) in enumerate(data.modules):

            library = top
            name = modi.ModuleName.split('\\')[-1]
            globs = module_globals[i]

            if modi.ModuleName != modi.ObjFilename:
                lib_name = modi.ObjFilename.split('\\')[-1]
                library = self.libraries.get(lib_name)
                if not library:
                    library = Library(lib_name, modi.ObjFilename)
                    self.libraries[lib_name] = library

            m = Module(self, library, i, name, symbols, sources, lines, contribs, globs)

            self.modules.append(m)
            library.addModule(m)


        for m in self.modules:

            for item in m.all_items:
                item.post_process()



    def getInclude(self, filename):
        try:
            return self.includes[filename]
        except KeyError:
            self.includes[filename] = include = Include(filename)
            return include

    def getAddr(self, segment, offset):
        return self.sections[segment].va + offset

    def getItem(self, addr):
        item = self.items[addr]

        if item:
            return item.pop().data
        return None


class Symbols:
    def __init__(self, symbols, types):
        self.symbols = []
        self.byRecOffset = {}
        self.bySegOffset = defaultdict(list)

        for i, rec in enumerate(symbols):
            offset = rec._addr

            # Strip the record wrapper
            rec = rec.Data

            rec.index = i
            rec.visablity = Visablity.Unknown
            rec.refcount = 0

            self.symbols.append(rec)
            self.byRecOffset[offset] = rec

            try:
                self.bySegOffset[(rec.Segment, rec.Offset)].append(rec)
            except AttributeError:
                if isinstance(rec, UserDefinedType):
                    pass
                elif not isinstance(rec, (Constant, ProcRef, LocalProcRef)):
                    # Todo: work out what these proc refs are
                    print(rec)
                    breakpoint()

            # Link symbol with type
            try:
                ty = rec.Type
                types.types[ty].symbols.append(rec)
            except AttributeError:
                pass




    def fromOffset(self, offset):
        try:
            return self.byRecOffset[offset]
        except KeyError:
            return None

    def fromSegmentOffset(self, segment, offset):
        try:
            return self.bySegOffset[(segment, offset)]
        except KeyError:
            return None

    def __getitem__(self, index):
        return self.symbols[index]

    def __len__(self):
        return len(self.symbols)
