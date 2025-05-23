
from construct import *
from constructutils import *

from codeview import VarInt
from collections import defaultdict

class TypeLeaf(ConstructClass):
    def linkTIs(self, tpi, history=[]):
        if any(x is self for x in history):
            return
        for k, lf in self.items():
            if k.startswith("_"):
                continue
            if isinstance(lf, TypeIndex):
                lf.link(tpi)
            elif isinstance(lf, ListContainer) or isinstance(lf, list):
                for item in lf:
                    if isinstance(item, TypeLeaf):
                        item.linkTIs(tpi, history + [self])

    def addRef(self, ref):
        try:
            self._refs.append(ref)
        except AttributeError:
            self._refs = [ref]

    def shortstr(self):
        return self.__str__()

    def fullstr(self):
        return self.__str__()


class TypeIndex(ConstructValueClass):
    subcon = Int16ul

    def link(self, tpi):
        self.Type = tpi.types[self.value]
        self.Type.addRef(self)

    def __str__(self):
        ty = getattr(self, "Type", None)
        if ty:
            return f"{ty}"
        if self.value == 0:
            return "Nil"
        return f"TI(0x{self.value:04x})"

    def parsed(self, ctx):
        self.Type = None
        self.ViaForwardsRef = None

    def shortstr(self):
        return self.Type.shortstr()

    def fullstr(self):
        return self.Type.fullstr()

class Bitfield(ConstructClass):
    def __str__(self):
        attrs = []
        for k, v in self.items():
            if k.startswith("_"):
                continue
            if v is True:
                attrs.append(k)
            elif v is not False and int(v) != 0:
                attrs.append(str(v))
        return " ".join(attrs)

class StructProperty(Bitfield):
    # bitfield describing class/struct/union/enum properties
    subcon = FixedSized(2,
        BitsSwapped(BitStruct(
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
        )),
    )

class FunctionAttributies(Bitfield):
    subcon = FixedSized(1,
        BitStruct(
            "cxxreturnudt" / Flag, # C++ style return UDT
            "ctor" / Flag, # constructor
            "ctorvbase" / Flag, # constructor with virtual base
            Padding(5),
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
            Padding(6),
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


@TpRec(0x0002) # LF_POINTER_16t
class LfPointer(TypeLeaf):
    subcon = Struct(
        "Attributes" / FixedSized(2,
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
                "isunaligned" / Flag,
                "isconst" / Flag,
                "isvolatile" / Flag,
                "isflat32" / Flag,
            )
        ),
        "Type" / TypeIndex,
    )

    def __str__(self):
        s = f"{self.Attributes.ptrmode} to: {self.Type.shortstr()}"
        if self.Attributes.ptrtype != "PtrNear32":
            s = f"{self.Attributes.ptrtype} {s}"
        if self.Attributes.isunaligned:
            s = f"unaligned {s}"
        if self.Attributes.isconst:
            s = f"const {s}"
        if self.Attributes.isvolatile:
            s = f"volatile {s}"
        if self.Attributes.isflat32:
            s = f"flat32 {s}"
        return s

@TpRec(0x0003) # LF_ARRAY_16t
class LfArray(TypeLeaf):
    subcon = Struct(
        "Type" / TypeIndex,
        "Count" / Dec(Int16ul),
        "Size" / VarInt,
        Const(0, Int8ul), # technically this is a zero-length string for the name
                          # but I don't think arrays can be named
        #"Name" / PascalString(Int8ul, "ascii"),
    )

class FrowardRef(TypeLeaf):
    def linkTIs(self, tpi):
        TypeLeaf.linkTIs(self, tpi)
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


@TpRec(0x0007) # LF_ENUM_16t
class LfEnum(FrowardRef):
    subcon = Struct(
        "count" / Dec(Int16ul), # Number of elements in enum
        "utype" / TypeIndex, # Underlying type
        "fieldList" / TypeIndex, # Type Index of Field descriptor list
        "properties" / StructProperty,
        "Name" / PascalString(Int8ul, "ascii"),
    )

@TpRec(0x0008) # LF_PROCEDURE_16t
class LfProcedure(TypeLeaf):
    subcon = Struct(
        "rvtype" / TypeIndex, # type index of return value
        "calltype" / CallingConvention, # calling convention (call_t)
        "funcattr" / FunctionAttributies, # attributes
        "parmcount" / Int16ul, # number of parameters
        "arglist" / TypeIndex, # type index of argument list
    )

    def linkTIs(self, tpi):
        self.rvtype.link(tpi)
        if self.parmcount:
            self.args = tpi.types[self.arglist.value].args
            assert self.parmcount == len(self.args)
            for arg in self.args:
                arg.link(tpi)
        del self.arglist
        del self.parmcount


@TpRec(0x0009) # LF_MFUNCTION_16t
class LfMemberFunction(TypeLeaf):
    subcon = Struct( # struct lfMFunc_16t
        "rvtype" / TypeIndex, # type index of return value
        "classtype" / TypeIndex, # type index of containing class
        "_thistype" / TypeIndex, # type index of this pointer (model specific)
        "calltype" / CallingConvention, # calling convention (call_t)
        "funcattr" / FunctionAttributies, # attributes
        "parmcount" / Int16ul, # number of parameters
        "arglist" / TypeIndex, # type index of argument list
        "thisadjust" / Int32sl, # this adjuster (long because pad required anyway)
    )

    def linkTIs(self, tpi):
        self.rvtype.link(tpi)
        self.classtype.link(tpi)
        self._thistype.link(tpi)
        if self.parmcount:
            self.args = tpi.types[self.arglist.value].args
            assert self.parmcount == len(self.args)
            for arg in self.args:
                arg.link(tpi)
        del self.arglist
        del self.parmcount

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

            #exit(0)

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
            idx += 1
            self.types.append(rec)
            self.byRecOffset[addr] = rec

            if hasattr(rec, "Name"):
                byName[rec.Name].append(rec)

        self.byName = dict(byName)

        for ty in self.types:
            if isinstance(ty, TypeLeaf):
                ty.linkTIs(self)

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


