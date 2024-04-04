
from construct import *
from constructutils import *

from codeview import VarInt


class StructProperty(ConstructClass):
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

class FunctionAttributies(ConstructClass):
    subcon = FixedSized(1,
        BitStruct(
            "cxxreturnudt" / Flag, # C++ style return UDT
            "ctor" / Flag, # constructor
            "ctorvbase" / Flag, # constructor with virtual base
            Padding(5),
        )
    )

class ModifierAttributes(ConstructClass):
    subcon = FixedSized(2,
        BitsSwapped(BitStruct(
            "const" / Flag, # const
            "volatile" / Flag, # volatile
            "unaligned" / Flag, # unaligned
            Padding(13),
        ))
    )

class FieldAttributes(ConstructClass):
    subcon = FixedSized(2,
        BitStruct(
            # Note: Construct's BitsInterger doesn't appear to work well with BitsSwapped.
            #       So instead we reverse the order of fields within each byte
            "noconstruct" / Flag, # class can't be constructed
            "noinherit" / Flag, # class can't be inherited
            "pseudo" / Flag, # doesn't exist, compiler generated function
            "mprop" / Enum(BitsInteger(3),
                MTvanilla = 0,
                MTvirtual = 1,
                MTstatic = 2,
                MTfriend = 3,
                MTintro = 4, # Implies MTvirtual. The "introduction" of this virtual function
                MTpurevirt = 5,
                Mtpureintro = 6, # likewise, implies MTpurevirt
            ),
            "access" / Enum(BitsInteger(2),
                Private=2,
                Protected=1,
                Public=3
            ),
            Padding(6),
            "sealed" / Flag, # method can't be overridden
            "compgenx" / Flag, # doesn't exist, compiler generated function
        )
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
class LfModifier(ConstructClass):
    subcon = Struct(
        "Attributes" / ModifierAttributes,
        "Type" / Int16ul, # Modified types
    )


@TpRec(0x0002) # LF_POINTER_16t
class LfPointer(ConstructClass):
    subcon = Struct(
        "Attributes" / FixedSized(2,
            BitsSwapped(BitStruct(
                "ptrtype" / BitsInteger(5),
                "ptrmode" / BitsInteger(3),
                "isflat32" / Flag,
                "isvolatile" / Flag,
                "isconst" / Flag,
                "isunaligned" / Flag,
                Padding(4),
            )
        )),
        "Type" / Int16ul,
    )

@TpRec(0x0003) # LF_ARRAY_16t
class LfArray(ConstructClass):
    subcon = Struct(
        "Count" / Int16ul,
        "Type" / Int16ul,
        "Size" / VarInt,
        Const(0, Int8ul), # technically this is a zero-length string for the name
                          # but I don't think arrays can be named
        #"Name" / PascalString(Int8ul, "ascii"),
    )

ClassOrStruct = Struct(
        "count" / Int16ul, # Number of elements in class
        "fieldList" / Int16ul, # Type Index of Field descriptor list
        "properties" / StructProperty,
        "derivedList" / Int16ul, # Type Index of derived class list
        "vshape" / Int16ul, # Type Index of vshape table
        "Size" / VarInt,
        "Name" / PascalString(Int8ul, "ascii"),
    )

@TpRec(0x0004) # LF_CLASS_16t
class LfClass(ConstructClass):
    subcon = ClassOrStruct

@TpRec(0x0005) # LF_STRUCTURE_16t
class LfStructure(ConstructClass):
    subcon = ClassOrStruct


@TpRec(0x0006) # LF_UNION_16t
class LfUnion(ConstructClass):
    subcon = Struct(
        "count" / Int16ul, # Number of elements in class
        "fieldList" / Int16ul, # Type Index of Field descriptor list
        "properties" / StructProperty,
        "Size" / VarInt,
        "Name" / PascalString(Int8ul, "ascii"),
    )


@TpRec(0x0007) # LF_ENUM_16t
class LfEnum(ConstructClass):
    subcon = Struct(
        "count" / Int16ul, # Number of elements in enum
        "utype" / Int16ul, # Underlying type
        "fieldList" / Int16ul, # Type Index of Field descriptor list
        "properties" / StructProperty,
        "Name" / PascalString(Int8ul, "ascii"),
    )

@TpRec(0x0008) # LF_PROCEDURE_16t
class LfProcedure(ConstructClass):
    subcon = Struct(
        "rvtype" / Int16ul, # type index of return value
        "calltype" / Int8ul, # calling convention (call_t)
        "funcattr" / FunctionAttributies, # attributes
        "parmcount" / Int16ul, # number of parameters
        "arglist" / Int16ul, # type index of argument list
    )

@TpRec(0x0009) # LF_MFUNCTION_16t
class LfMemberFunction(ConstructClass):
    subcon = Struct( # struct lfMFunc_16t
        "rvtype" / Int16ul, # type index of return value
        "classtype" / Int16ul, # type index of containing class
        "thistype" / Int16ul, # type index of this pointer (model specific)
        "calltype" / Int8ul, # calling convention (call_t)
        "funcattr" / FunctionAttributies, # attributes
        "parmcount" / Int16ul, # number of parameters
        "arglist" / Int16ul, # type index of argument list
        "thisadjust" / Int32sl, # this adjuster (long because pad required anyway)
    )

@TpRec(0x000a) # LF_VTSHAPE
class LfVtShape(ConstructClass):
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
        #"desc" / HexDump(GreedyBytes),
    )

@TpRec(0x0012) # LF_VFTPATH_16t
class LfVftPath(ConstructClass):
    subcon = Struct(
        "count" / Int16ul, # number of bases in path
        "bases" / Array(this.count, Int16ul),
    )

@TpRec(0x0201) # LF_ARGLIST_16t
class LfArgList(ConstructClass):
    subcon = Struct(
        "count" / Int16ul, # Number of elements in class
        "args" / Array(this.count, Int16ul),
    )

class FieldListEntry(ConstructClass):
    subcon = Aligned(4, Struct(
        "Type" / Int16ul,
        "Data" / Switch(this.Type, TpSwitch,
            #default=HexDump(GreedyBytes)
            default=Error
        )),
    )

@TpRec(0x0204) # LF_FIELDLIST_16t
class LfFieldList(ConstructClass):
    subcon = Struct(
        "Data" / GreedyRange(FieldListEntry),
    )

@TpRec(0x0206) # LF_BITFIELD_16t
class LfBitfield(ConstructClass):
    subcon = Struct(
        "length" / Int8ul,
        "position" / Int8ul,
        "type" / Int16ul,
    )

class MethodListEntry(ConstructClass):
    subcon = Struct(
        "attr" / FieldAttributes,
        "index" / Int16ul,
        "vbaseoffset" / If(lambda ctx: ctx.attr.mprop in ("MTintro", "MTpureintro"),
            Int32ul # offset into virtual function table
        )
    )

@TpRec(0x0207)
class LfMethodList(ConstructClass):
    subcon = Struct(
        "Data" / GreedyRange(MethodListEntry)
    )

# Records starting with 0x0400 are only used referenced from field lists

@TpRec(0x0400) # LF_BCLASS_16t
class LfBaseClass(ConstructClass):
    subcon = Struct(
        "index" / Int16ul, # type index of base class
        "attr" / FieldAttributes,
        "offset" / VarInt, # offset of base within class
    )

@TpRec(0x0401) # LF_VBCLASS_16t
class LfVirtualBaseClass(ConstructClass):
    subcon = Struct(
        "index" / Int16ul, # type index of direct virtual base class
        "vbptr" / Int16ul, # type index of virtual base pointer
        "attr" / FieldAttributes,
        "ptroffset" / VarInt, # virtual base pointer offset from address point
        "vtableoffset" / VarInt, # virtual base offset from vbtable
    )

@TpRec(0x0402) # LF_IVBCLASS_16t
class LfIndirectVirtualBaseClass(ConstructClass):
    subcon = Struct(
        "index" / Int16ul, # type index of direct virtual base class
        "vbptr" / Int16ul, # type index of virtual base pointer
        "attr" / FieldAttributes,
        "ptroffset" / VarInt, # virtual base pointer offset from address point
        "vtableoffset" / VarInt, # virtual base offset from vbtable
    )

@TpRec(0x0403) # LF_ENUMERATE_ST
class LfEnumerate(ConstructClass):
    subcon = Struct(
        "attr" / FieldAttributes,
        "value" / VarInt, # offset of base within class
        "Name" / PascalString(Int8ul, "ascii"),
    )

@TpRec(0x0406) # LF_MEMBER_16t
class LfMember(ConstructClass):
    subcon = Struct(
        "index" / Int16ul,
        "attr" / FieldAttributes,
        "offset" / VarInt, # offset of field within class
        "Name" / PascalString(Int8ul, "ascii"),
    )

@TpRec(0x0407) # LF_STMEMBER_16t
class LfStaticMember(ConstructClass):
    subcon = Struct(
        "index" / Int16ul,
        "attr" / FieldAttributes,
        "Name" / PascalString(Int8ul, "ascii"),
    )

@TpRec(0x0408) # LF_METHOD_16t
class LfMethod(ConstructClass):
    subcon = Struct(
        "count" / Int16ul,
        "methodList" / Int16ul,
        "Name" / PascalString(Int8ul, "ascii"),
    )

@TpRec(0x0409) # LF_NESTTYPE_16t
class LfNestedType(ConstructClass):
    subcon = Struct(
        "index" / Int16ul,
        "Name" / PascalString(Int8ul, "ascii"),
    )

@TpRec(0x040a) # LF_VFUNCTAB_16t
class LfVFuncTab(ConstructClass):
    subcon = Struct(
        "index" / Int16ul,
    )

@TpRec(0x040c) # LF_ONEMETHOD_16t
class LfOneMethod(ConstructClass):
    subcon = Struct(
        "attr" / FieldAttributes,
        "index" / Int16ul,
        "vbaseoffset" / If(lambda ctx: ctx.attr.mprop in ("MTintro", "MTpureintro"),
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
        "ByteCount" / Int32ul, # Num bytes in following stream

        # TODO: Should we parse this hash value stream?
        #       Appears to be 16bits per record, and is probally the same hash used for the GSI mapping
        #       Probally used to accelerate reverse lookups?
        #       I'm not sure we will find any interesting information there.
        "HashValueStream" / Int16ul,
        Padding(2),
        "Records" / Array(this.MaximumTI - this.MinimumTI, TypeRecord)
    )

    def parsed(self, ctx):
        #print(f"Loaded {len(self.Records)} type records", file=sys.stderr)


        # TODO: Fill in all the built-in types
        self.types = [None] * self.MinimumTI
        self.byRecOffset = {}

        for rec in self.Records:
            #print(f"{rec._addr:04x} {rec}")
            rec.isGlobal = False
            rec.isPublic = False
            self.types += [rec]
            self.byRecOffset[rec._addr] = rec

        #for k, v in self.byRecOffset.items():
            #print(f"{k:x} {v}")

    def fromOffset(self, offset):
        try:
            return self.byRecOffset[offset]
        except KeyError:
            return None

