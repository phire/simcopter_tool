from construct import *
from constructutils import *

from typing import *
import textwrap

# Some fields used this variable length integer encoding
#   If the 16bit "typeOrVal" value is less than 0x8000, then the value is inlined (This might be limited to 8 bit values)
#   Otherwise, it is treated as a type and a value of that type follows
class VarInt(ConstructClass):
    subcon = Struct(
            "typeOrVal" / Int16ul,
            "value" / Switch(this.typeOrVal,
                {
                    0x8000: Int8sl,  # LF_CHAR
                    0x8001: Int16sl, # LF_SHORT
                    0x8002: Int16ul, # LF_USHORT
                    0x8003: Int32sl, # LF_LONG
                    0x8004: Int32ul, # LF_ULONG
                    0x8009: Int64sl, # LF_QUADWORD
                    0x800a: Int64ul, # LF_UQUADWORD
                },
                default=Computed(this.typeOrVal) # otherwise, value was small enough to be inlined
            )
        )

CVSwitch = {}

# decorator to assign classes to switch map
def CVRec(type):
    def decorator(cls):
        cls.type = type
        CVSwitch[type] = cls
        return cls
    return decorator

@CVRec(0x1) # S_COMPILE
class CompileFlags(ConstructClass):
    subcon = Struct(
        "Machine" / Int8ul,
        "Flags" / BitStruct(
            "Language" / BitsInteger(8),
            "PCode" / Flag,
            "FloatPrecision" / BitsInteger(2),
            "FloatPackage" / BitsInteger(2),
            "AmbientData" / BitsInteger(3),
            "AmbientCode" / BitsInteger(3),
            "Mode32" / Flag,
            Padding(4)
        ),
        "CompilerVersion" / PascalString(Int8ul, "ascii"),
    )

@CVRec(0x3) # S_CONSTANT_16t
class Constant(ConstructClass):
    subcon = Struct(
        "Type" / Int16ul,
        "Value" / VarInt, # cvinfo.h claims this is always a short, but it's actually VarInt
        "Name" / PascalString(Int8ul, "ascii"),
    )

@CVRec(0x4) # S_UDT_16t
class UserDefinedType(ConstructClass):
    subcon = Struct(
        "Type" / Int16ul,
        "Name" / PascalString(Int8ul, "ascii"),
    )

@CVRec(0x6) # S_END
class End(ConstructClass):
    subcon = Struct()

    def __str__(self):
        return "End"

@CVRec(0x9) # S_OBJNAME_ST
class ObjName(ConstructClass):
    subcon = Struct(
        "Sig" / Int32ul, # Usually 0, but sometimes 1 for xmt_obj files
        "Name" / PascalString(Int8ul, "ascii"),
    )

@CVRec(0x200) # S_BPREL32_16t
class BpRelative(ConstructClass):
    subcon = Struct(
        "Offset" / Int32sl,
        "Type" / Int16ul,
        "Name" / PascalString(Int8ul, "ascii"),
    )

def getContrib(sym, program):
    try:
        return sym.contrib
    except AttributeError:
        try:
            section = program.sections[sym.Segment]
        except IndexError:
            raise Exception(f"Segment {sym.Segment} not found for symbol {sym}")

        try:
            contrib = section.contribs[sym.Offset].pop().data
            sym.contribOffset = sym.Offset - contrib.Offset
        except KeyError:
            contrib = program.unknownContribs
            sym.contribOffset = None

        contrib.symbols.append(sym)
        sym.contrib = contrib
        return contrib

class DataSym(ConstructClass):
    subcon = Struct(
            "Offset" / Int32ul,
            "Segment" / Int16ul,
            "Type" / Int16ul,
            "Name" / PascalString(Int8ul, "ascii"),
        )

    def getContrib(self, program):
        return getContrib(self, program)

    def getModuleId(self, program):
        contrib = getContrib(self, program)
        return contrib.ModuleIndex

@CVRec(0x201) # S_LDATA32_16t
class LocalData(DataSym):
    pass

@CVRec(0x202) # S_GDATA32_16t
class GlobalData(DataSym):
    pass

@CVRec(0x203) # S_PUB32_16t
class PublicData(DataSym):
    pass

class ProcSym(ConstructClass):
    subcon = Struct(
        "pParent" / Int32ul,
        "pEnd" / Int32ul,
        "pNext" / Int32ul,
        "Len" / Int32ul,
        "DbgStart" / Int32ul,
        "DbgEnd" / Int32ul,
        "Offset" / Int32ul,
        "Segment" / Int16ul,
        "Type" / Int16ul,
        "Flags" / Int8ul,
        "Name" / PascalString(Int8ul, "ascii"),
    )

    def getContrib(self, program):
        return getContrib(self, program)

    def getModuleId(self, program):
        contrib = getContrib(self, program)
        return contrib.ModuleIndex

@CVRec(0x204) # S_LPROC32_16t
class LocalProcedureStart(ProcSym):
    pass

@CVRec(0x205) # S_GPROC32_16t
class GlobalProcedureStart(ProcSym):
    pass

@CVRec(0x206) # S_THUNK32
class Thunk(ConstructClass):
    # These are functions imported by dlls
    subcon = Struct(
        "pParent" / Int32ul,
        "pEnd" / Int32ul,
        "pNext" / Int32ul,
        "Offset" / Int32ul,
        "Segment" / Int16ul,
        "Len" / Int16ul,
        "Ordinal" / Int8ul,
        "Name" / PascalString(Int8ul, "ascii"),
        "variant" / HexDump(GreedyBytes)
    )

    def getContrib(self, program):
        return getContrib(self, program)

    def getModuleId(self, program):
        contrib = getContrib(self, program)
        return contrib.ModuleIndex

@CVRec(0x207) # S_BLOCK32
class BlockStart(ConstructClass):
    subcon = Struct(
        "pParent" / Int32ul,
        "pEnd" / Int32ul,
        "Length" / Int32ul,
        "Offset" / Int32ul,
        "Segment" / Int16ul,
        "Name" / PascalString(Int8ul, "ascii"),
    )

@CVRec(0x209) # S_LABEL32_ST
class CodeLabel(ConstructClass):
    subcon = Aligned(4, Struct(
        "Offset" / Int32ul,
        "Segment" / Int16ul,
        "Flags" / Const(0, Int8ul),
        "Name" / PascalString(Int8ul, "ascii"),
    ))


class RefSym(ConstructClass):
    # This doesn't match microsoft's documentation, where RefSym doesn't have a name.
    # Instead, vc++ 4.1 seems to output a corrupted record where the length matches RefSym2,
    # but the name actually exists. This means the length of this record is far too short.
    subcon = Struct(
        "SucOfName" / Int32ul, # I have no idea what "SUC" is, always appears to be zero
        "SymbolOffset" / Int32ul,  # offset into $$Symbols table (I think this is the local symbols of the referenced module)
        "ModuleId" / Int16ul,  # Module containing actual symbol
        "Fill"    /  Int16ul,  # is this just padding?
        "Name"    /  PascalString(Int8ul, "ascii"),  # Hidden name that has been made a first class member
    )

    def getModuleId(self, program):
        return self.ModuleId

@CVRec(0x0400) # S_PROCREF_ST
class ProcRef(RefSym):
    pass

@CVRec(0x0401) # S_DATAREF_ST
class DataRef(RefSym):
    pass

@CVRec(0x0403) # S_LPROCREF_ST
class LocalProcRef(RefSym):
    pass


@CVRec(0x040a) # LF_VFUNCTAB_16t
class VirtualFunctionTable(ConstructClass):
    subcon = Struct(
        "Type" / Int16ul,
    )

class CodeviewRecord(ConstructClass):
    subcon = Aligned(4, Struct(
        "RecordLength" / Int16ul,
        "RecordType" / Int16ul,
        "_length_fixed" / IfThenElse(lambda ctx: ctx.RecordType in (0x400, 0x401, 0x403),
            # This is a hack to fix the length of the RefSym record types
            FocusedSeq("Length",
                "Ref" / Peek(RefSym),
                "Length" / Computed(lambda ctx: len(ctx.Ref.Name) + 13)
            ),
            Computed(this.RecordLength - 2),
        ),
        StopIf(lambda ctx: ctx.RecordLength < 2),
        "Data" / FixedSized(this._length_fixed, Switch(this.RecordType, CVSwitch,
            #default=HexDump(GreedyBytes)
            default=Error
        )),
    ))

    def parsed(self, ctx):
        pass
        #print(f"Record: {self.RecordLength} {self.RecordType:04x}\n\t{self.Data}")

def split_list(lst, pred):
    for i, item in enumerate(lst):
        if pred(item):
            return lst[:i], lst[i+1:]
    return [], lst


def toTree(records: List[CodeviewRecord]):
    tree = []

    while len(records) > 0:
        #print("Records:", len(records))
        #print(records)
        record = records.pop(0).Data
        #pEnd = 0
        try:
            pEnd = record.pEnd
        except:
            # This record has no children
            tree.append(record)
            continue

        children, records = split_list(records, lambda x: x._addr == pEnd)
        #print("Children:", len(children))
        record._children = toTree(children)
        tree.append(record)

    return tree


def printTree(tree, indent=0):
    for node in tree:
        print(textwrap.indent(f"{node}", " " * indent * 4))

        try:
            children = node._children
        except:
            continue

        printTree(children, indent + 1)
