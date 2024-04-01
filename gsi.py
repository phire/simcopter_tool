"""The GSI/PGSI streams contains a serialized version of the linked-list hash table for mapping
   symbol names to their symbol data in the SymbolRecord stream.
   The hash tables also count references.

   I'm guessing everything with zero references was stripped out of the PDB file.

   From tests on copter_d.pdb, it appears a symbol will only appear in GSI or PSGI, never both.

   From what I can tell, the only reason I need to parse this is to know if a symbol is global
   or public (or neither?).
   But I'll need to investigate if the ordering (within buckets) or the reference counts might
   provide some additional scraps of information about the original source code.
"""

from construct import *
from constructutils import *

from codeview import CodeviewRecord

from enum import Enum

class HRFile(ConstructClass):
    # This is the on-disk format for the GSI/PGSI hash tables
    subcon = Struct(
        "offset" / Int32sl, #
        "RefrenceCount" / Int32sl,
    )

class HashEntry:
    def __init__(self, offset, refcount, ty=None):
        self.offset = offset
        self.refcount = refcount
        self.ty = ty

class Gsi(ConstructClass):
    # There is no header for this version of the GSI stream.
    # Instead, there are some number of hashes, followed by exactly 4097 buckets
    # The last bucket is the free list.
    subcon = Struct(
        "hashes" / OffsettedEnd(-4097 * 4, GreedyRange(HRFile)),
        "buckets" / Array(4097, Int32ul),
    )

    def parsed(self, ctx):
        hashes = [HashEntry(x.offset, x.RefrenceCount) for x in self.hashes]
        self.all_hashes = hashes
        self.map = [[]] * 4097

        # Enumerate over the buckets backwards
        for i in reversed(range(4097)):
            bound = self.buckets[i]
            if bound == 0xffffffff:
                continue

            # Bucket offsets are to the in-memory version of HR, which is 12 bytes long:
            #    (PointerToSymbol, ReferenceCount, Next)
            # Where next points to the next entry in the that bucket.
            # So we divide by 12 to get the index of the first entry for each bucket
            idx = bound // 12

            # pop the entries for this bucket off the end of the list
            self.map[i] = hashes[idx-1:]

            hashes = hashes[:idx-1]

        del self.hashes
        del self.buckets

    def apply_visablity(self, visablity, symbols):
        for sym in self.all_hashes:
            rec = symbols.fromOffset(sym.offset - 1)
            if rec:
                rec.visablity = visablity
                rec.refcount = sym.refcount


class PsgiHeader(ConstructClass):

    # struct PSGSIHDR from :
    # https://github.com/microsoft/microsoft-pdb/blob/master/PDB/dbi/gsi.h#L191
    subcon = Struct(
        "HashesBytes" / Int32ul, # Number of bytes for hashes + buckets
        "AddrMapBytes" / Int32ul,
        "nThunks" / Int32ul,
        "sizeofThunk" / Int32ul,
        "ThunkTableSection" / Int32ul,
        "ThunkTableOffset" / Int32ul,
        "SectionCount" / Int32ul,
    )

class Pgsi(ConstructClass):
    # PGSI does have a header, as it also contains the address map
    # The first HashesBytes of the stream (after the 0x1c byte header) can be decoded the same way as GSI

    # I'm not entirely sure what address map is. I think it's just a list of all records in the symbol record stream
    subcon = Struct(
        "header" / PsgiHeader,
        "gsi" / FixedSized(this.header.HashesBytes, Gsi),
        "addrmap" / Array(this.header.AddrMapBytes // 4, Int32ul),
    )

class Visablity(Enum):
    Unknown = 0
    Global = 1
    Public = 2

class Symbols:
    def __init__(self, symbols):
        self.symbols = []
        self.byRecOffset = {}
        self.byAddress = {}

        for i, rec in enumerate(symbols):
            offset = rec._addr

            # Strip the record wrapper
            rec = rec.Data

            rec.index = i
            rec.visablity = Visablity.Unknown
            rec.refcount = 0

            self.symbols.append(rec)
            self.byRecOffset[offset] = rec


    def fromOffset(self, offset):
        try:
            return self.byRecOffset[offset]
        except KeyError:
            return None

    def __getitem__(self, index):
        return self.symbols[index]

    def __len__(self):
        return len(self.symbols)

def LoadSymbols(symbolRecordStream):

    symbols = RepeatUntil(lambda x, lst, ctx: x._io.tell() == symbolRecordStream.size,
            Aligned(4, CodeviewRecord)
        ).parse_stream(symbolRecordStream)



    return Symbols(symbols)
