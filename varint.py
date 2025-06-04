from construct import *
from constructutils import *

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

    def __eq__(self, other):
        return self.value == other

    def __str__(self):
        return f"{self.value}"
