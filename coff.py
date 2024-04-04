from construct import *
from construct.debug import Debugger

from constructutils import *


class CoffHeader(ConstructClass):
    subcon = Struct(
        "Magic" / Const(b"PE\0\0"),
        "Machine" / Enum(Int16ul,
            IMAGE_FILE_MACHINE_UNKNOWN=0x0000,
            IMAGE_FILE_MACHINE_ALPHA=0x0184,
            IMAGE_FILE_MACHINE_ALPHA64=0x0284,
            IMAGE_FILE_MACHINE_AM33=0x01d3,
            IMAGE_FILE_MACHINE_AMD64=0x8664,
            IMAGE_FILE_MACHINE_ARM=0x01c0,
            IMAGE_FILE_MACHINE_ARM64=0xaa64,
            IMAGE_FILE_MACHINE_ARMNT=0x01c4,
            IMAGE_FILE_MACHINE_AXP64=0x0284,
            IMAGE_FILE_MACHINE_EBC=0x0ebc,
            IMAGE_FILE_MACHINE_I386=0x014c,
            IMAGE_FILE_MACHINE_IA64=0x0200,
            IMAGE_FILE_MACHINE_LOONGARCH32=0x01a2,
            IMAGE_FILE_MACHINE_LOONGARCH64=0x01a3,
            IMAGE_FILE_MACHINE_M32R=0x9041,
            IMAGE_FILE_MACHINE_MIPS16=0x0266,
            IMAGE_FILE_MACHINE_MIPSFPU=0x0366,
            IMAGE_FILE_MACHINE_MIPSFPU16=0x0466,
            IMAGE_FILE_MACHINE_POWERPC=0x01f0,
            IMAGE_FILE_MACHINE_POWERPCFP=0x01f1,
            IMAGE_FILE_MACHINE_R4000=0x0166,
            IMAGE_FILE_MACHINE_RISCV32=0x5032,
            IMAGE_FILE_MACHINE_RISCV64=0x5064,
            IMAGE_FILE_MACHINE_RISCV128=0x5128,
            IMAGE_FILE_MACHINE_SH3=0x01a2,
            IMAGE_FILE_MACHINE_SH3DSP=0x01a3,
            IMAGE_FILE_MACHINE_SH4=0x01a6,
            IMAGE_FILE_MACHINE_SH5=0x01a8,
            IMAGE_FILE_MACHINE_THUMB=0x01c2,
            IMAGE_FILE_MACHINE_WCEMIPSV2=0x0169,
        ),
        "NumberOfSections" / Int16ul,
        "TimeDateStamp" / Int32ul,
        "PointerToSymbolTable" / Int32ul,
        "NumberOfSymbols" / Int32ul,
        "SizeOfOptionalHeader" / Int16ul,
        "Characteristics" / FlagsEnum(Int16ul,
            IMAGE_FILE_RELOCS_STRIPPED=0x0001,
            IMAGE_FILE_EXECUTABLE_IMAGE=0x0002,
            IMAGE_FILE_LINE_NUMS_STRIPPED=0x0004,
            IMAGE_FILE_LOCAL_SYMS_STRIPPED=0x0008,
            IMAGE_FILE_AGGRESSIVE_WS_TRIM=0x0010,
            IMAGE_FILE_LARGE_ADDRESS_AWARE=0x0020,
            IMAGE_FILE_BYTES_REVERSED_LO=0x0080,
            IMAGE_FILE_32BIT_MACHINE=0x0100,
            IMAGE_FILE_DEBUG_STRIPPED=0x0200,
            IMAGE_FILE_REMOVABLE_RUN_FROM_SWAP=0x0400,
            IMAGE_FILE_NET_RUN_FROM_SWAP=0x0800,
            IMAGE_FILE_SYSTEM=0x1000,
            IMAGE_FILE_DLL=0x2000,
            IMAGE_FILE_UP_SYSTEM_ONLY=0x4000,
            IMAGE_FILE_BYTES_REVERSED_HI=0x8000,
        ),
    )


class MzHeader(ConstructClass):
    subcon = Struct(
        "Magic" / Const(b"MZ"),
        "BytesOnLastPage" / Int16ul,
        "Pages" / Int16ul,
        "Relocations" / Int16ul,
        "HeaderSize" / Int16ul,
        "MinAlloc" / Int16ul,
        "MaxAlloc" / Int16ul,
        "InitialSS" / Int16ul,
        "InitialSP" / Int16ul,
        "Checksum" / Int16ul,
        "InitialIP" / Int16ul,
        "InitialCS" / Int16ul,
        "RelocationTableOffset" / Int16ul,
        "OverlayNumber" / Int16ul,
        "Reserved" / Array(4, Int16ul),
        "OEMID" / Int16ul,
        "OEMInfo" / Int16ul,
        "Reserved2" / Array(10, Int16ul),
        "PeOffset" / Int32ul,
    )

class DataDirectory(ConstructClass):
    subcon = Struct(
        "VirtualAddress" / Int32ul,
        "Size" / Int32ul,
    )

class OptionalHeader(ConstructClass):
    # This "optional" header is required for .exe files and dlls. Not required for object files.
    subcon = Struct(
        "Magic" / Enum(Int16ul,
            IMAGE_NT_OPTIONAL_HDR32_MAGIC=0x10b,
            IMAGE_NT_OPTIONAL_HDR64_MAGIC=0x20b,
        ),
        "MajorLinkerVersion" / Int8ul,
        "MinorLinkerVersion" / Int8ul,
        "SizeOfCode" / Int32ul,
        "SizeOfInitializedData" / Int32ul,
        "SizeOfUninitializedData" / Int32ul,
        "AddressOfEntryPoint" / Int32ul,
        "BaseOfCode" / Int32ul,
        "BaseOfData" / If(this.Magic == "IMAGE_NT_OPTIONAL_HDR32_MAGIC", Int32ul),
        "ImageBase" / IfThenElse(this.Magic == "IMAGE_NT_OPTIONAL_HDR32_MAGIC", Int32ul, Int64ul),
        "SectionAlignment" / Int32ul,
        "FileAlignment" / Int32ul,
        "MajorOperatingSystemVersion" / Int16ul,
        "MinorOperatingSystemVersion" / Int16ul,
        "MajorImageVersion" / Int16ul,
        "MinorImageVersion" / Int16ul,
        "MajorSubsystemVersion" / Int16ul,
        "MinorSubsystemVersion" / Int16ul,
        "Win32VersionValue" / Int32ul,
        "SizeOfImage" / Int32ul,
        "SizeOfHeaders" / Int32ul,
        "CheckSum" / Int32ul,
        "Subsystem" / Enum(Int16ul, IMAGE_SUBSYSTEM_WINDOWS_GUI=2),
        "DllCharacteristics" / FlagsEnum(Int16ul,
            IMAGE_DLLCHARACTERISTICS_DYNAMIC_BASE=0x0040,
            IMAGE_DLLCHARACTERISTICS_NX_COMPAT=0x0100,
            IMAGE_DLLCHARACTERISTICS_NO_SEH=0x0400,
            IMAGE_DLLCHARACTERISTICS_TERMINAL_SERVER_AWARE=0x8000,
        ),
        "SizeOfStackReserve" / IfThenElse(this.Magic == "IMAGE_NT_OPTIONAL_HDR32_MAGIC", Int32ul, Int64ul),
        "SizeOfStackCommit" / IfThenElse(this.Magic == "IMAGE_NT_OPTIONAL_HDR32_MAGIC", Int32ul, Int64ul),
        "SizeOfHeapReserve" / IfThenElse(this.Magic == "IMAGE_NT_OPTIONAL_HDR32_MAGIC", Int32ul, Int64ul),
        "SizeOfHeapCommit" / IfThenElse(this.Magic == "IMAGE_NT_OPTIONAL_HDR32_MAGIC", Int32ul, Int64ul),
        "LoaderFlags" / Const(0, Int32ul), # Reserved, must be 0
        "NumberOfRvaAndSizes" / Int32ul,
        "DataDirectory" / Array(this.NumberOfRvaAndSizes, DataDirectory),
    )

class Section(ConstructClass):
    subcon = Struct(
        "Name" / PaddedString(8, "ascii"),
        "VirtualSize" / Int32ul,
        "VirtualAddress" / Int32ul,
        "SizeOfRawData" / Int32ul,
        "PointerToRawData" / Int32ul,
        "PointerToRelocations" / Int32ul,
        "PointerToLinenumbers" / Int32ul,
        "NumberOfRelocations" / Int16ul,
        "NumberOfLinenumbers" / Int16ul,
        "Characteristics" / Int32ul,
        "Data" / Pointer(this.PointerToRawData, Bytes(this.SizeOfRawData)),
    )

    def parsed(self, ctx):
        if self.VirtualSize > self.SizeOfRawData:
            self.Data += b"\0" * (self.VirtualSize - self.SizeOfRawData)
        elif self.VirtualSize < self.SizeOfRawData:
            garbage = self.Data[self.VirtualSize:]
            assert all(x == 0 for x in garbage)

            self.Data = self.Data[:self.VirtualSize]


class WindowsExe(ConstructClass):
    subcon = Struct(
        "Dos" / MzHeader,
        "Coff" / Pointer(this.Dos.PeOffset, CoffHeader),
        "_optional_offset" / Computed(this.Dos.PeOffset + CoffHeader.sizeof()),
        "Optional" / Pointer(this._optional_offset,
            FixedSized(this.Coff.SizeOfOptionalHeader,
                OptionalHeader
            ),
        ),
        "_section_offset" / Computed(this._optional_offset + this.Coff.SizeOfOptionalHeader),
        "Sections" / Pointer(this._section_offset,
            Array(this.Coff.NumberOfSections, Section),
        ),
    )

def Executable(filename):
    with open(filename, "rb") as f:
        return WindowsExe.parse_stream(f)

if __name__ == "__main__":
    exe_file = "../debug_build_beta/COPTER_D.EXE"

    exe = Executable(exe_file)
    print(exe)