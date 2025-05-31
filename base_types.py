
def cast_access(ty, prefix, offset, size):
    match size:
        case None:
            return prefix
        case 1:
            access_type = "uint8_t"
        case 2:
            access_type = "uint16_t"
        case 4:
            access_type = "uint32_t"
        case _:
            raise ValueError(f"Cannot access {size} bytes at offset {offset} in {ty.typestr()}")

    if offset == 0:
        return f"reinterpret_cast<{access_type}>({prefix})"
    elif offset + size <= ty.size:
        # TODO: Why would the compiler even generate this in debug mode?
        return f"*reinterpret_cast<{access_type}*>(reinterpret_cast<char*>(&{prefix}) + {offset})"
    else:
        raise ValueError(f"Cannot access {size} bytes at offset {offset} in {ty.typestr()}")


class BaseType:
    def __init__(self):
        self._refs = set()
        self.symbols = []

    def __str__(self):
        try:
            return self.s
        except AttributeError:
            return f"<{self.__class__.__name__}>"

    def shortstr(self):
        return self.__str__()

    def typestr(self, name=None):
        if name:
            return f"{self.shortstr()} {name}"
        else:
            return self.shortstr()

    def addRef(self, ref):
        self._refs.add(ref.TI)

    def type_size(self):
        return self.size

    def access(self, prefix, offset, size):
        if offset == 0 and not size or size == self.size:
            return prefix

        return cast_access(self, prefix, offset, size)

    def is_fwdref(self):
        return False

# Special types

class NoType(BaseType):
    """uncharacterized type (no type)"""
    TI = 0x0000

class AbsoluteSymbol(BaseType):
    """absolute symbol"""
    TI = 0x0001

class Segment(BaseType):
    """segment type"""
    TI = 0x0002

class Void(BaseType):
    TI = 0x0003
    s = "void"

class HRESULT(BaseType):
    """OLE/COM HRESULT"""
    TI = 0x0008
    s = "HRESULT"

class _32PHRESULT(BaseType):
    """OLE/COM HRESULT __ptr32 *"""
    TI = 0x0408
    s = "HRESULT __ptr32 *"

class _64PHRESULT(BaseType):
    """OLE/COM HRESULT __ptr64 *"""
    TI = 0x0608
    s = "HRESULT __ptr64 *"
class PVOID(BaseType):
    """near pointer to void"""
    TI = 0x0103
    s = "void *"
class PFVOID(BaseType):
    """far pointer to void"""
    TI = 0x0203
    s = "void __far *"
class PHVOID(BaseType):
    """huge pointer to void"""
    TI = 0x0303
    s = "void __huge *"
class _32PVOID(BaseType):
    """32 bit pointer to void"""
    TI = 0x0403
    s = "void * __ptr32"
    size = 4

class _32PFVOID(BaseType):
    """16:32 pointer to void"""
    TI = 0x0503
    s = "void __ptr16 * __ptr32"
class _64PVOID(BaseType):
    """64 bit pointer to void"""
    TI = 0x0603
    s = "void * __ptr64"
class CURRENCY(BaseType):
    """BASIC 8 byte currency value"""
    TI = 0x0004
    s = "CURRENCY"
class NBASICSTR(BaseType):
    """Near BASIC string"""
    TI = 0x0005
    s = "BASIC string"
class FBASICSTR(BaseType):
    """Far BASIC string"""
    TI = 0x0006
    s = "BASIC string __far"
class NotTrans(BaseType):
    """type not translated by cvpack"""
    TI = 0x0007
    s = "not translated"
class Bit(BaseType):
    TI = 0x0060
    s = "bit"
class PasChar(BaseType):
    """Pascal CHAR"""
    TI = 0x0061
    s = "CHAR"
class Bool32FF(BaseType):
    """32-bit BOOL where true is 0xffffffff"""
    TI = 0x0062
    s = "BOOL32FF"


def derive_pointers(cls):
    pointers = [
        # ("P", 0x100, "*", "16 bit pointer"),
        # ("PF", 0x200, "far *", "16:16 far pointer"),
        # ("PH", 0x300, "huge *", "16:16 huge pointer"),
        ("P", 0x400, "*", 4, "32 bit pointer"),
        ("PF", 0x500, "far *", 6, "16:32 pointer"),
        ("P64", 0x600, "far __ptr64 *", 8, "64 bit pointer"),
    ]
    for prefix, offset, code, size, comment in pointers:
        class_name = f"{prefix}{cls.__name__}"
        newclass = type(class_name, (cls,),
            {
                "TI": cls.TI + offset,
                "s": f"{cls.s} {code}",
                "size": size,
                "__doc__": f"{comment} to {cls.__doc__}"
            }
        )

        globals()[class_name] = newclass
    return cls

@derive_pointers
class Char(BaseType):
    """8 bit signed"""
    TI = 0x0010
    s = "char"
    size = 1

@derive_pointers
class UChar(BaseType):
    """8 bit unsigned"""
    TI = 0x0020
    s = "unsigned char"
    size = 1

@derive_pointers
class RChar(BaseType):
    """really a char"""
    TI = 0x0070
    s = "char"
    size = 1

@derive_pointers
class WChar(BaseType):
    """wide char"""
    TI = 0x0071
    s = "wchar_t"
    size = 2

@derive_pointers
class Char16(BaseType):
    """16-bit unicode char"""
    TI = 0x007a
    s = "char16_t"
    size = 2

@derive_pointers
class Char32(BaseType):
    """32-bit unicode char"""
    TI = 0x007b
    s = "char32_t"
    size = 4

@derive_pointers
class Int1(BaseType):
    """8 bit signed int"""
    TI = 0x0068
    s = "int8_t"
    size = 1

@derive_pointers
class UInt1(BaseType):
    """8 bit unsigned int"""
    TI = 0x0069
    s = "uint8_t"
    size = 1

@derive_pointers
class Short(BaseType):
    """16 bit signed"""
    TI = 0x0011
    s = "short"
    size = 2

@derive_pointers
class UShort(BaseType):
    """16 bit unsigned"""
    TI = 0x0021
    s = "unsigned short"
    size = 2

@derive_pointers
class Int2(BaseType):
    """16 bit signed int"""
    TI = 0x0072
    s = "int16_t"
    size = 2

@derive_pointers
class UInt2(BaseType):
    """16 bit unsigned int"""
    TI = 0x0073
    s = "uint16_t"
    size = 2

@derive_pointers
class Long(BaseType):
    """32 bit signed"""
    TI = 0x0012
    s = "long"
    size = 4

@derive_pointers
class ULong(BaseType):
    """32 bit unsigned"""
    TI = 0x0022
    s = "unsigned long"
    size = 4

@derive_pointers
class Int4(BaseType):
    """32 bit signed int"""
    TI = 0x0074
    s = "int32_t"
    size = 4

@derive_pointers
class UInt4(BaseType):
    """32 bit unsigned int"""
    TI = 0x0075
    s = "uint32_t"
    size = 4

@derive_pointers
class Quad(BaseType):
    """64 bit signed"""
    TI = 0x0013
    s = "quad"
    size = 8

@derive_pointers
class UQuad(BaseType):
    """64 bit unsigned"""
    TI = 0x0023
    s = "unsigned quad"
    size = 8

@derive_pointers
class Int8(BaseType):
    """64 bit signed int"""
    TI = 0x0076
    s = "int64_t"
    size = 8

@derive_pointers
class UInt8(BaseType):
    """64 bit unsigned int"""
    TI = 0x0077
    s = "uint64_t"
    size = 8

@derive_pointers
class Oct(BaseType):
    """128 bit signed"""
    TI = 0x0014
    s = "octet"
    size = 16

@derive_pointers
class UOct(BaseType):
    """128 bit unsigned"""
    TI = 0x0024
    s = "unsigned octet"
    size = 16

@derive_pointers
class Int16(BaseType):
    """128 bit signed int"""
    TI = 0x0078
    s = "int128_t"
    size = 16

@derive_pointers
class UInt16(BaseType):
    """128 bit unsigned int"""
    TI = 0x0079
    s = "uint128_t"
    size = 16

@derive_pointers
class Real32(BaseType):
    """32 bit real"""
    TI = 0x0040
    s = "float"
    size = 4

@derive_pointers
class Real64(BaseType):
    """64 bit real"""
    TI = 0x0041
    s = "double"
    size = 8

@derive_pointers
class Real80(BaseType):
    """80 bit real"""
    TI = 0x0042
    s = "long double"
    size = 10  # 80 bits, but stored in 10 bytes

@derive_pointers
class CPLX32(BaseType):
    """32 bit complex"""
    TI = 0x0050
    s = "complex float"

@derive_pointers
class CPLX64(BaseType):
    """64 bit complex"""
    TI = 0x0051
    s = "complex double"

@derive_pointers
class CPLX80(BaseType):
    """80 bit complex"""
    TI = 0x0052
    s = "complex long double"

#  boolean types

@derive_pointers
class Bool8(BaseType):
    """8 bit boolean"""
    TI = 0x0030
    s = "bool"
    size = 1

@derive_pointers
class Bool16(BaseType):
    """16 bit boolean"""
    TI = 0x007e
    s = "bool16_t"
    size = 2

@derive_pointers
class Bool32(BaseType):
    """32 bit boolean"""
    TI = 0x007f
    s = "bool32_t"
    size = 4

@derive_pointers
class Bool64(BaseType):
    """64 bit boolean"""
    TI = 0x0080
    s = "bool64_t"

class NCVPtr(BaseType):
    """CV Internal type for created near pointers"""
    TI = 0x01f0

class FCVPtr(BaseType):
    """CV Internal type for created far pointers"""
    TI = 0x02f0

class HCVPtr(BaseType):
    """CV Internal type for created huge pointers"""
    TI = 0x03f0

class N32CVFPtr(BaseType):
    """CV Internal type for created near 32-bit pointers"""
    TI = 0x04f0

class F32CVFPtr(BaseType):
    """CV Internal type for created far 16:16 pointers"""
    TI = 0x05f0

class N64CVFPtr(BaseType):
    """CV Internal type for created near 64-bit pointers"""
    TI = 0x06f0

from inspect import isclass

types = [None] * 0x1000
for v in list(globals().values()):
    if isclass(v) and issubclass(v, BaseType) and v is not BaseType:
        types[v.TI] = v()