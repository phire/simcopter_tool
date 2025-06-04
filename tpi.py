
from construct import *
from access import Access, ArrayAccess
from base_types import cast_access, ScaleExpr
from constructutils import *

from codeview import VarInt
from collections import defaultdict

class TypeLeaf(ConstructClass):
    con = None  # Construct class for this type, if applicable

    def parsed(self, ctx):
        self.symbols = []

    def linkTIs(self, other, tpi, history=set()):
        if id(self) in history:
            return
        history.add(id(self))
        for k, lf in self.items():
            if k.startswith("_"):
                continue
            if isinstance(lf, TypeIndex):
                lf.link(self, tpi)
            elif isinstance(lf, ListContainer) or isinstance(lf, list):
                for item in lf:
                    if isinstance(item, TypeLeaf):
                        item.TI = self.TI
                        item.linkTIs(other, tpi, history)

    def addRef(self, ref):
        if not ref:
            return
        if isinstance(ref, TypeIndex):
            TI = ref.value
        else:
            TI = ref.TI
        try:
            self._refs.add(TI)
        except AttributeError:
            self._refs = set()
            self._refs.add(TI)

    def shortstr(self):
        return self.__str__()

    def typestr(self, name=None):
        if name:
            return f"{self.shortstr()} {name}"
        return self.shortstr()

    def fullstr(self):
        return self.__str__()

    def type_size(self):
        raise NotImplementedError(f"{self.__class__.__name__} does not implement type_size()")

    def access(self, prefix, offset, size):
        if offset == 0 and not size or size == self.type_size():
            return Access(size, prefix, self)

        return cast_access(self, prefix, offset, size)

    def __hash__(self):
        return hash(self.TI)

    def is_fwdref(self):
        return False

    def getCon(self):
        return self.con

class TypeIndex(ConstructValueClass):
    subcon = Int16ul

    def link(self, other, tpi):
        self.Type = tpi.types[self.value]
        self.Type.addRef(other)

    def __str__(self):
        ty = getattr(self, "Type", None)
        if ty:
            return f"{ty}"
        if self.value == 0:
            return "Nil"
        return f"TI(0x{self.value:04x})"

    def __hash__(self):
        try:
            return hash(self.value)
        except AttributeError:
            return 0

    def parsed(self, ctx):
        self.Type = None
        self.ViaForwardsRef = None

    def shortstr(self):
        return self.Type.shortstr()

    def typestr(self, name=None):
        return self.Type.typestr(name)

    def fullstr(self):
        return self.Type.fullstr()

    def type_size(self):
        return self.Type.type_size()

    def access(self, prefix, offset, size):
        return self.Type.access(prefix, offset, size)

    def initializer(self, parsed):
        return self.Type.initializer(parsed)

    def getCon(self):
        return self.Type.getCon()

class Bitfield(ConstructClass):
    def str(self, *, map={}):
        # to rename a feld, use map = {"old_name": "new_name"}
        # to filter out a field, use map = {"field_name": False}} (or None or "")
        attrs = []
        for k, v in self.items():
            k = map.get(k, k) # filter or rename field names
            if not k or k.startswith("_"):
                continue
            if v is True:
                attrs.append(k)
            elif v is not False and int(v) != 0:
                attrs.append(str(v))
            if k == "padding" and int(v) != 0:
                attrs.append(f"padding({int(v)})")
        return " ".join(attrs)

    def __str__(self):
        return self.str()

    # Override for a slight performance improvement
    @classmethod
    def _parse(cls, stream, context, path):
        obj = cls.subcon._parse(stream, context, path)
        self = cls.__new__(cls)
        self._apply(obj)
        del self._io

        return self

class StructProperty(Bitfield):
    # bitfield describing class/struct/union/enum properties
    subcon = BitsSwapped(BitStruct(
        # Total, 16 bits
            "packed" / Flag,  # struct is packed
            "ctor" / Flag,    # constructors or destructors present
            "ovlops" / Flag,  #  overload operators present
            "isnested" / Flag, # class is nested
            "cnested" / Flag, # class contains nested types
            "opassign" / Flag, # overloaded assignment (=)
            "opcast" / Flag, # casting methods present
            "fwdref" / Flag, # forward reference (incomplete definition)
            "scoped" / Flag, # scoped definition
            "hasUniqueName" / Flag, # There is a decorated name following the regular name
            "sealed" / Flag, # class cannot be inherited
            "hfa" / Enum(BitsInteger(2), Nil=0, Float=2, Dobule=1, Other=3), # none/float/double/other
            "intrinsics" / Flag, # this class is an intrinsic type (like __m128)
            "mocom" / Enum(BitsInteger(2), Nil=0, Ref=2, Value=1, Interface=3), # none/ref/value/interface
        )
    )

class FunctionAttributies(Bitfield):
    subcon = FixedSized(1,
        BitStruct(
            "cxxreturnudt" / Flag, # C++ style return UDT
            "ctor" / Flag, # constructor
            "ctorvbase" / Flag, # constructor with virtual base
            "padding" / BitsInteger(5),
        )
    )

class ModifierAttributes(Bitfield):
    subcon = FixedSized(2,
        BitsSwapped(BitStruct(
            "const" / Flag, # const
            "volatile" / Flag, # volatile
            "unaligned" / Flag, # unaligned
            Padding(13),
        ))
    )

class FieldAttributes(Bitfield):
    subcon = FixedSized(2,
        BitStruct(
            # Note: Construct's BitsInterger doesn't appear to work well with BitsSwapped.
            #       So instead we reverse the order of fields within each byte
            "noconstruct" / Flag, # class can't be constructed
            "noinherit" / Flag, # class can't be inherited
            "pseudo" / Flag, # doesn't exist, compiler generated function
            "mprop" / Enum(BitsInteger(3),
                vanilla = 0,
                virtual = 1,
                static = 2,
                friend = 3,
                intro = 4, # Implies MTvirtual. The "introduction" of this virtual function
                purevirt = 5,
                pureintro = 6, # likewise, implies MTpurevirt
            ),
            "access" / Enum(BitsInteger(2),
                private=1,
                protected=2,
                public=3
            ),
            "padding" / BitsInteger(6), # padding bits
            "sealed" / Flag, # method can't be overridden
            "compgenx" / Flag, # doesn't exist, compiler generated function
        )
    )

CallingConvention = Enum(Int8ul,
    NearC = 0x00,
    FarC = 0x01,
    NearPascal = 0x02,
    FarPascal = 0x03,
    NearFast = 0x04,
    FarFast = 0x05,
    NearStd = 0x07,
    FarStd = 0x08,
    NearSys = 0x09,
    FarSys = 0x0a,
    ThisCall = 0x0b,
)

TpSwitch = {}

# decorator to assign classes to switch map
def TpRec(type):
    def decorator(cls):
        cls.type = type
        TpSwitch[type] = cls
        return cls
    return decorator

@TpRec(0x0001) # LF_MODIFIER_16t
class LfModifier(TypeLeaf):
    subcon = Struct(
        "Attributes" / ModifierAttributes,
        "Type" / TypeIndex, # Modified types
    )

    def getCon(self):
        return self.Type.Type.con

    def mods(self):
        s = self.Attributes.str()
        if s:
            s += " "
        return s

    def __str__(self):
        return f"{self.mods()}{self.Type.shortstr()}"

    def typestr(self, name=None):
        return f"{self.mods()}{self.Type.typestr(name)}"

    def type_size(self):
        return self.Type.type_size()

    def access(self, prefix, offset, size):
        return self.Type.access(prefix, offset, size)

    def initializer(self, parsed):
        return self.Type.Type.initializer(parsed)

class PointerAttributes(Bitfield):
    subcon = FixedSized(2,
        BitStruct(
            "ptrmode" / Enum(BitsInteger(3),
                Ptr=0,
                Ref=1,
                PMem=2,
                PMFunc=3,
                Reserved=4,
            ),
            "ptrtype" / Enum(BitsInteger(5),
                PtrNear = 0,
                PtrFar = 1,
                PtrHuge = 2,
                PtrBaseSeg = 3,
                PtrBaseVal = 4,
                PtrBaseSegVal = 5,
                PtrBaseAddr = 6,
                PtrBaseSegAddr = 7,
                PtrBaseType = 8,
                PtrBaseSelf = 9,
                PtrNear32 = 10,
                PtrFar32 = 11,
                Ptr64 = 12,
                PtrUnused = 13,
            ),
            Padding(4),
            "isunaligned" / Flag, # unaligned pointer
            "isconst" / Flag, # const pointer
            "isvolatile" / Flag, # volatile pointer
            "isflat32" / Flag, # flat model pointer
        ))

@TpRec(0x0002) # LF_POINTER_16t
class LfPointer(TypeLeaf):
    subcon = Struct(
        "Attributes" / PointerAttributes,
        "Type" / TypeIndex,
    )

    def attributes(self):
        s = ""
        if self.Attributes.ptrtype != "PtrNear32":
            s = f"{self.Attributes.ptrtype}"
        s += self.Attributes.str(map={
            "ptrmode": None,
            "ptrtype": None,
            "isunaligned": 'unaligned',
            "isconst": 'const',
            "isvolatile": 'volatile',
            "isflat32": 'flat32',
        })
        if s:
            s += " "
        return s

    def shortstr(self):
        s = f"{self.Attributes.ptrmode} to: {self.Type.shortstr()}"
        return self.attributes() + s

    def typestr(self, name=None):
        match self.Attributes.ptrmode:
            case "Ptr":
                if isinstance(self.Type.Type, LfProcedure):
                    #breakpoint()
                    # Special case for function pointers
                    fn = self.Type.Type
                    if not name:
                        name = ""
                    s = f"{fn.rvtype.typestr()} (*{name})({', '.join(str(arg.typestr()) for arg in fn.args)})"
                else:
                    if name:
                        name = "*" + name
                        s = f"{self.Type.typestr(name)}"
                    else:
                        s = f"{self.Type.typestr()}*"
            case "Ref":
                if name:
                    #name = "&" + name
                    s = f"{self.Type.typestr()}& {name}"
                else:
                    s = f"{self.Type.typestr(name)}&"
            case _:
                breakpoint()
                s = f"{self.Attributes.ptrmode} to: {self.Type.typestr()}"
        return self.attributes() + s

    def type_size(self):
        assert self.Attributes.ptrtype in ("PtrNear32"), self.Attributes.ptrtype
        return 4

    def access(self, prefix, offset, size):
        # if offset:
        #     match self.Attributes.ptrmode:
        #         case "Ptr":
        #             prefix += "->"
        #         case "Ref":
        #             #prefix += "."
        #             pass
        #         case _:
        #             raise NotImplementedError(f"Access not implemented for {self.Attributes.ptrmode}")
        #     return self.Type.access(prefix, offset, size)
        return Access(size, prefix, self)

    def deref(self, prefix, offset, size):
        match self.Attributes.ptrmode:
            case "Ptr":
                prefix += "->"
            case "Ref":
                prefix += "."
            case _:
                raise NotImplementedError(f"Dereference not implemented for {self.Attributes.ptrmode}")
        return self.Type.access(prefix, offset, size)

@TpRec(0x0003) # LF_ARRAY_16t
class LfArray(TypeLeaf):
    subcon = Struct(
        "Type" / TypeIndex,
        "IndexType" / TypeIndex, # type index of index type
        "Size" / VarInt, # size in bytes
        Const(0, Int8ul), # technically this is a zero-length string for the name
                          # but I don't think arrays can be named
        #"Name" / PascalString(Int8ul, "ascii"),
    )

    #def parsed(self, ctx):
        #assert self.IndexType.value == 17, "Array index type should be uint32_t"

    def parsed(self, ctx):
        try:
            pass
        except AttributeError:
            pass

    def initializer(self, parsed):
        init = self.Type.Type.initializer
        emnts = [init(x) for x in parsed]
        return f"{{{', '.join(emnts)}}}"

    def shortstr(self):
        return self.typestr()

    def typestr(self, name=None):
        element_size = self.Type.Type.type_size()
        count = self.Size.value // element_size

        if name:
            name = f"{name}[{count}]"
            return self.Type.typestr(name)
        return f"{self.Type.typestr()}[{count}]"

    def type_size(self):
        return self.Size.value

    def access(self, prefix, offset, size):
        element_size = self.Type.type_size()
        if isinstance(offset, ScaleExpr):
            index = offset.expr
            var_off = 0
        else:
            index = offset // element_size
            var_off = offset - index * element_size

        array = ArrayAccess(prefix, index, self.Type.Type)
        return array.access(var_off, size)

    def getCon(self):
        element_size = self.Type.Type.type_size()
        element_con = self.Type.Type.getCon()
        if element_size and element_con is not None:
            return Array(self.Size.value // element_size, element_con)



class FrowardRef(TypeLeaf):
    def linkTIs(self, other, tpi):
        TypeLeaf.linkTIs(self, other, tpi)
        if self.properties.fwdref:
            for ty in tpi.byName[self.Name]:
                if ty.__class__ == self.__class__ and not ty.properties.fwdref:
                    self._definition = ty
                    ty.addRef(self)
                    return
            if getattr(self, "Size", None) == 0:
                # Almost certainly an empty struct
                self._definition = None
            else:
                print (f"Failed to resolve forwards ref: {self.Name}")
        else:
            self._definition = None

    def __str__(self):
        try:
           if self._definition:
               return f"(Forwards ref to)\n {self.definition}"
        except AttributeError:
            pass
        return TypeLeaf.__str__(self)

    def shortstr(self):
        prefix = self.__class__.__name__[2:].lower()
        return f"{prefix} {self.Name}"


    def is_fwdref(self):
        return self.properties.fwdref


@TpRec(0x0004) # LF_CLASS_16t
class LfClass(FrowardRef):
    subcon = Struct(
        "count" / Dec(Int16ul), # Number of elements in class
        "fieldList" / TypeIndex, # Type Index of Field descriptor list
        "properties" / StructProperty,
        "derivedList" / TypeIndex, # Type Index of derived class list
        "vshape" / TypeIndex, # Type Index of vshape table
        "Size" / VarInt,
        "Name" / PascalString(Int8ul, "ascii"),
    )

    def type_size(self):
        if self.properties.fwdref:
            try:
                return self._definition.type_size()
            except AttributeError:
                raise Exception(f"Forward reference {self.Name} has no definition")
        return self.Size.value

    def get_class(self):
        if self.properties.fwdref:
            try:
                return self._definition.get_class()
            except AttributeError:
                return None
        try:
            return self._class
        except AttributeError:
            breakpoint()
            return None

    def access(self, prefix, offset, size):
        cls = self.get_class()
        if cls is None:
            return Access(size, f"{prefix}<{self.Name}+0x{offset:02x}:{size}>", self, offset=offset)
        return cls.access(prefix, offset, size)

    def as_code(self):
        cls = getattr(self, '_class', None)
        cls = getattr(self, '_def_class', cls)
        if cls is None:
            try:
                cls = self._definition._class
            except AttributeError:
                return f"// {self.Name} Class implementation not found\n"
        return cls.as_code()


@TpRec(0x0005) # LF_STRUCTURE_16t
class LfStruct(LfClass):
    pass

@TpRec(0x0006) # LF_UNION_16t
class LfUnion(FrowardRef):
    subcon = Struct(
        "count" / Dec(Int16ul), # Number of elements in class
        "fieldList" / TypeIndex, # Type Index of Field descriptor list
        "properties" / StructProperty,
        "Size" / VarInt,
        "Name" / PascalString(Int8ul, "ascii"),
    )

    def type_size(self):
        return self.Size.value

    def access(self, prefix, offset, size):
        # todo: maybe we can guess which field based on offset+size?
        return Access(size, f"{prefix}<{self.Name}+0x{offset:02x}:{size}>", self, offset=offset)


@TpRec(0x0007) # LF_ENUM_16t
class LfEnum(FrowardRef):
    subcon = Struct(
        "count" / Dec(Int16ul), # Number of elements in enum
        "utype" / TypeIndex, # Underlying type
        "fieldList" / TypeIndex, # Type Index of Field descriptor list
        "properties" / StructProperty,
        "Name" / PascalString(Int8ul, "ascii"),
    )

    def type_size(self):
        return self.utype.type_size()

    def as_code(self):
        if self.is_fwdref():
            try:
                return self._definition.as_code()
            except AttributeError:
                return f"// {self.Name} Enum implementation not found\n"
        name = self.Name.split("::")[-1]  # Use the last part of the name, in case of nested enums
        if name == "__unnamed":
            name = "/* __unnamed */"
        access = "public"
        typestr = ""
        if self.utype.value != 0x74: # int32_t
            typestr = f" /* {self.utype.Type.typestr()} */"

        s = f"enum {name}{typestr} {{\n"
        props = self.properties.str(map={"isnested": ''})
        if props:
            s += f"\t// properties: {self.properties}\n"
        for e in self.fieldList.Type.Data:

            if e.attr.access != access:
                s += f"//{e.attr.access}\n"
                access = e.attr.access
            attr = e.attr.str(map={'access': None})
            if attr:
                attr = f" // {attr}"
            s += f"\t{e.Name} = {e.value.value},{attr}\n"
        s += "};\n"
        return s


@TpRec(0x0008) # LF_PROCEDURE_16t
class LfProcedure(TypeLeaf):
    subcon = Struct(
        "rvtype" / TypeIndex, # type index of return value
        "calltype" / CallingConvention, # calling convention (call_t)
        "funcattr" / FunctionAttributies, # attributes
        "parmcount" / Int16ul, # number of parameters
        "arglist" / TypeIndex, # type index of argument list
    )

    def linkTIs(self, other, tpi):
        self.addRef(other)
        self.rvtype.link(self, tpi)
        if self.parmcount:
            self.args = tpi.types[self.arglist.value].args
            assert self.parmcount == len(self.args)
            for arg in self.args:
                arg.link(self, tpi)
        else:
            self.args = []
        del self.arglist
        del self.parmcount

    def shortstr(self):
        s = f"{self.rvtype} ("
        for arg in self.args:
            s += f"{arg}, "
        s += ")"
        return s

    def typestr(self, name=None):
        args = ", ".join(arg.typestr() for arg in self.args)
        if name:
            return f"{self.rvtype.typestr()} (*{name})({args})"
        return f"{self.rvtype.typestr()} ({args})"

    def type_size(self):
        #this seems to be a pointer to a function, not the function itself
        return 4


@TpRec(0x0009) # LF_MFUNCTION_16t
class LfMemberFunction(TypeLeaf):
    subcon = Struct( # struct lfMFunc_16t
        "rvtype" / TypeIndex, # type index of return value
        "classtype" / TypeIndex, # type index of containing class
        "thistype" / TypeIndex, # type index of this pointer (model specific)
        "calltype" / CallingConvention, # calling convention (call_t)
        "funcattr" / FunctionAttributies, # attributes
        "parmcount" / Int16ul, # number of parameters
        "arglist" / TypeIndex, # type index of argument list
        "thisadjust" / Int32sl, # this adjuster (long because pad required anyway)
    )

    def linkTIs(self, other, tpi):
        self.addRef(other)
        self.rvtype.link(self, tpi)
        self.classtype.link(self, tpi)
        self.thistype.link(self, tpi)
        if self.parmcount:
            self.args = tpi.types[self.arglist.value].args
            assert self.parmcount == len(self.args)
            for arg in self.args:
                arg.link(self, tpi)
        else:
            self.args = []
        del self.arglist
        del self.parmcount

    def string(self, name):
        s = f"{self.rvtype} {self.classtype.Type.Name}::{name}("
        for arg in self.args:
            s += f"{arg}, "
        s += ")"
        return s

@TpRec(0x000a) # LF_VTSHAPE
class LfVtShape(TypeLeaf):
    # Virtual Shape table
    subcon = Struct(
        "count" / Int16ul, # Number of elements in class
        # Packed nibbles, 4 bits per entry
        "desc" / Bitwise(Aligned(8,
            Array(this.count,
                Enum(BitsInteger(4),
                    Near=0,
                    Far=1,
                    Thin=2,
                    Outer=3,
                    Meta=4,
                    Near32=5,
                    Far32=6,
                    Unused=7,
                )
            )
        )),
    )

    def shortstr(self):
        return f"VtShape({self.count}) [{', '.join(str(x) for x in self.desc)}]"

@TpRec(0x0012) # LF_VFTPATH_16t
class LfVftPath(TypeLeaf):
    subcon = Struct(
        "count" / Int16ul, # number of bases in path
        "bases" / Array(this.count, TypeIndex),
    )

@TpRec(0x0201) # LF_ARGLIST_16t
class LfArgList(TypeLeaf):
    subcon = Struct(
        "count" / Int16ul, # Number of elements in class
        "args" / Array(this.count, TypeIndex),
    )

class FieldListEntry(TypeLeaf):
    subcon = Aligned(4, Struct(
        "Type" / Int16ul,
        "Data" / Switch(this.Type, TpSwitch,
            #default=HexDump(GreedyBytes)
            default=Error
        )),
    )

@TpRec(0x0204) # LF_FIELDLIST_16t
class LfFieldList(TypeLeaf):
    subcon = Struct(
        "Data" / GreedyRange(FieldListEntry),
    )

    def parsed(self, ctx):
        self.Data = ListContainer([x.Data for x in self.Data])

@TpRec(0x0206) # LF_BITFIELD_16t
class LfBitfield(TypeLeaf):
    subcon = Struct(
        "length" / Int8ul,
        "position" / Int8ul,
        "type" / TypeIndex,
    )

    def type_size(self):
        return self.length

class MethodListEntry(TypeLeaf):
    subcon = Struct(
        "attr" / FieldAttributes,
        "index" / TypeIndex,
        "vbaseoffset" / If(lambda ctx: ctx.attr.mprop in ("intro", "pureintro"),
            Int32ul # offset into virtual function table
        )
    )

@TpRec(0x0207)
class LfMethodList(TypeLeaf):
    subcon = Struct(
        "Data" / GreedyRange(MethodListEntry)
    )

# Records starting with 0x0400 are only used referenced from field lists

@TpRec(0x0400) # LF_BCLASS_16t
class LfBaseClass(TypeLeaf):
    subcon = Struct(
        "index" / TypeIndex, # type index of base class
        "attr" / FieldAttributes,
        "offset" / VarInt, # offset of base within class
    )

@TpRec(0x0401) # LF_VBCLASS_16t
class LfVirtualBaseClass(TypeLeaf):
    subcon = Struct(
        "index" / TypeIndex, # type index of direct virtual base class
        "vbptr" / TypeIndex, # type index of virtual base pointer
        "attr" / FieldAttributes,
        "ptroffset" / VarInt, # virtual base pointer offset from address point
        "vtableoffset" / VarInt, # virtual base offset from vbtable
    )

@TpRec(0x0402) # LF_IVBCLASS_16t
class LfIndirectVirtualBaseClass(TypeLeaf):
    subcon = Struct(
        "index" / TypeIndex, # type index of direct virtual base class
        "vbptr" / TypeIndex, # type index of virtual base pointer
        "attr" / FieldAttributes,
        "ptroffset" / VarInt, # virtual base pointer offset from address point
        "vtableoffset" / VarInt, # virtual base offset from vbtable
    )

@TpRec(0x0403) # LF_ENUMERATE_ST
class LfEnumerate(TypeLeaf):
    subcon = Struct(
        "attr" / FieldAttributes,
        "value" / VarInt, # offset of base within class
        "Name" / PascalString(Int8ul, "ascii"),
    )

@TpRec(0x0406) # LF_MEMBER_16t
class LfMember(TypeLeaf):
    subcon = Struct(
        "index" / TypeIndex,
        "attr" / FieldAttributes,
        "offset" / VarInt, # offset of field within class
        "Name" / PascalString(Int8ul, "ascii"),
    )

@TpRec(0x0407) # LF_STMEMBER_16t
class LfStaticMember(TypeLeaf):
    subcon = Struct(
        "index" / TypeIndex,
        "attr" / FieldAttributes,
        "Name" / PascalString(Int8ul, "ascii"),
    )

@TpRec(0x0408) # LF_METHOD_16t
class LfMethod(TypeLeaf):
    subcon = Struct(
        "count" / Int16ul,
        "methodList" / TypeIndex,
        "Name" / PascalString(Int8ul, "ascii"),
    )

@TpRec(0x0409) # LF_NESTTYPE_16t
class LfNestedType(TypeLeaf):
    subcon = Struct(
        "index" / TypeIndex,
        "Name" / PascalString(Int8ul, "ascii"),
    )

@TpRec(0x040a) # LF_VFUNCTAB_16t
class LfVFuncTab(TypeLeaf):
    subcon = Struct(
        "index" / TypeIndex,
    )

@TpRec(0x040c) # LF_ONEMETHOD_16t
class LfOneMethod(TypeLeaf):
    subcon = Struct(
        "attr" / FieldAttributes,
        "index" / TypeIndex,
        "vbaseoffset" / If(lambda ctx: ctx.attr.mprop in ("intro", "pureintro"),
            Int32ul # offset into virtual function table
        ),
        "Name" / PascalString(Int8ul, "ascii"),
    )


class TypeRecord(ConstructClass):
    subcon = Aligned(4, Struct(
        "Length" / Int16ul,
        "Type" / Int16ul,
        "Data" / FixedSized(this.Length - 2, Switch(this.Type, TpSwitch,
            #default=HexDump(GreedyBytes)
            default=Error
        ))
        )
    )

    def parsed(self, ctx):
        #print(f"TypeRecord: {self.Type:04x} {self.Data}")
        #print(f"{self._io.tell():x}")
        if self.Type not in TpSwitch:
            print(f"Unknown leaf type: {self.Type:04x} {self.Data}")
            breakpoint()



class TypeInfomation(ConstructClass):
    """
        See struct HDR_16t from: https://github.com/microsoft/microsoft-pdb/blob/master/PDB/dbi/tpi.h
    """

    subcon = Struct(
        "Version" / Const(19951122, Int32ul), # version number for impv41
        "MinimumTI" / Int16ul, # lowest TI
        "MaximumTI" / Int16ul, # highest TI + 1
        "ByteCount" / Int32ul, # Total size of Records

        # see parseHashes, doesn't seem to have useful infomation
        "HashValueStream" / Int16ul,
        Padding(2),
        "Records" / Array(this.MaximumTI - this.MinimumTI, TypeRecord)
    )

    def parsed(self, ctx):
        #assert sizeof(self.Records) == self.ByteCount
        import base_types
        self.types = list(base_types.types)

        self.byRecOffset = {}
        byName = defaultdict(list)

        idx = self.MinimumTI
        assert len(self.types) == self.MinimumTI

        for rec in self.Records:
            addr = rec._addr
            rec = rec.Data
            rec._idx = idx
            rec.TI = idx
            idx += 1
            self.types.append(rec)
            self.byRecOffset[addr] = rec

            if hasattr(rec, "Name"):
                byName[rec.Name].append(rec)

        self.byName = dict(byName)

        for ty in self.types:
            if isinstance(ty, TypeLeaf):
                ty.linkTIs(None, self)

    def fromOffset(self, offset):
        try:
            return self.byRecOffset[offset]
        except KeyError:
            return None

    def parseHashes(self, msf):
        if self.HashValueStream == 0:
            return

        numTypes = self.MaximumTI - self.MinimumTI

        stream = msf.getStream(self.HashValueStream)

        # There is one bucket idx (in the range 0 to 4095) per TI
        # presumably the same hash function as used in GSI
        buckets = list(Array(numTypes, Int16ul).parse_stream(stream))

        # This some kind of skip list that allows implementations to quickly find the TI they are looking for
        # It links to the first whole record after each 8KB boundary
        Skip = Struct(
            "TI" / Int16ul,
            "unk" / Int16ul, # might be flags?? Usually in the ranges 0x80-8f or 0xe0-0xef
            "off" / Int32ul
        )
        skiplist = list(GreedyRange(Skip).parse_stream(stream))

        print("\n")

        for o in skiplist:
            print(f"{o.TI:04x} {o.unk:04x} {o.off:08x}")
            print(self.types[o.TI])


