from construct import *
from constructutils import *

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
        Const(0, Int32ul),
        "Name" / PascalString(Int8ul, "ascii"),
    )

@CVRec(0x200) # S_BPREL32_16t
class BpRelative(ConstructClass):
    subcon = Struct(
        "Offset" / Int32ul,
        "Type" / Int16ul,
        "Name" / PascalString(Int8ul, "ascii"),
    )

DataSym = Struct(
        "Offset" / Int32ul,
        "Segment" / Int16ul,
        "Type" / Int16ul,
        "Name" / PascalString(Int8ul, "ascii"),
    )

@CVRec(0x201) # S_LDATA32_16t
class LocalData(ConstructClass):
    subcon = DataSym

@CVRec(0x202) # S_GDATA32_16t
class GlobalData(ConstructClass):
    subcon = DataSym

@CVRec(0x203) # S_PUB32_16t
class PublicData(ConstructClass):
    subcon = DataSym

ProcSym = Struct(
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

@CVRec(0x204) # S_LPROC32_16t
class LocalProcedureStart(ConstructClass):
    subcon = ProcSym

@CVRec(0x205) # S_GPROC32_16t
class GlobalProcedureStart(ConstructClass):
    subcon = ProcSym

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

RefSym = Struct(
        "SucOfName" / Int32ul, # I have no idea what "SUC" is
        "SymbolId" / Int32ul,  # offset into $$Symbols table
        "ModuleId" / Int16ul,  # Module containing actual symbol
        "Fill"    /  Int16ul,  # is this just padding?
    )

RefSym2 = Struct(
        "SucOfName" / Int32ul, # I have no idea what "SUC" is
        "SymbolId" / Int32ul,  # offset into $$Symbols table
        "ModuleId" / Int16ul,  # Module containing actual symbol
        "Name"    /  PascalString(Int8ul, "ascii"),  # Hidden name of frist class memeber
    )

@CVRec(0x0400) # S_PROCREF_ST
class ProcRef(ConstructClass):
    # TODO: The public symbol table contains a corrupted version of this record
    #       It has the type and length of REFSYM, but actually contains a RefSym2, complete
    #       with a name that massivly overruns the reported length.
    #       How do we detect these?
    subcon = RefSym2

@CVRec(0x040a) # LF_VFUNCTAB_16t
class VirtualFunctionTable(ConstructClass):
    subcon = Struct(
        "Type" / Int16ul,
    )

class CodeviewRecord(ConstructClass):
    subcon = Struct(
        "RecordLength" / Int16ul,
        "RecordType" / Int16ul,
        StopIf(lambda ctx: ctx.RecordLength < 2),
        "Data" / FixedSized(this.RecordLength - 2, Switch(this.RecordType, CVSwitch,
            default=HexDump(GreedyBytes)
            #default=Error
        )),
    )

    def parsed(self, ctx):
        pass
        #print(f"Record: {self.RecordLength} {self.RecordType}\n\t{self.Data}")
