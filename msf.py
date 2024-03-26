# Parse Microsoft's Multi-stream format (wrapper for PDB files)
# https://llvm.org/docs/PDB/MsfFile.html


from construct import *
from constructutils import *

import os

class SuperblockSmall(ConstructClass):
    # Small pages version of the MSF superblock, with 16bit page offsets (used until version 7)

    subcon = Struct(
        "FileMagic" / Const(b"Microsoft C/C++ program database 2.00\r\n\032JG\0\0"), # 0x2c bytes
        "BlockSize" / Hex(Int32ul),
        "FreeBlockMapBlock" / Int16ul, # Can only be 1 or 2
        "NumBlocks" / Hex(Int16ul),
        "NumDirectoryBytes" / Hex(Int32ul),
        "Unknown" / Hex(Int32ul),
        "NumDirectoryBlocks" / Computed((this.NumDirectoryBytes + this.BlockSize - 1) // this.BlockSize),
        "BlockMap" / Array(this.NumDirectoryBlocks, Hex(Int16ul)),
    )

    def __str__(self):
         return f"""Superblock:
    BlockSize: {self.BlockSize}
    FreeBlockMapBlock: {self.FreeBlockMapBlock}
    NumBlocks: {self.NumBlocks}
    NumDirectoryBytes: {self.NumDirectoryBytes}
    Unknown: {self.Unknown}
    BlockMap: {self.BlockMap} {self.BlockMap[0] * self.BlockSize:x}
    """

class MsfStream():
    def __init__(self, fd, size, block_size, blocks):
        self.fd = fd
        self.size = size
        self.block_size = block_size
        self.blocks = blocks
        self.pos = 0
        self.do_seek()

    def do_seek(self):
        if self.pos >= self.size:
            self.data = b""
            return

        block_idx = self.pos // self.block_size
        block_offset = self.pos % self.block_size
        block = self.blocks[block_idx]
        self.fd.seek(block * self.block_size)
        self.data = self.fd.read(self.block_size)

        if block_idx == len(self.blocks) - 1:
            self.data = self.data[:self.size % self.block_size]

        if block_offset > 0:
            self.data = self.data[block_offset:]

    def read(self, size=-1):
        if size == -1:
            size = self.size - self.pos

        remaining = size
        data = b""

        while remaining > 0:
            if remaining < len(self.data):
                self.pos += remaining
                data += self.data[:remaining]
                self.data = self.data[remaining:]
                remaining = 0
            else:
                self.pos += len(self.data)
                remaining -= len(self.data)
                data += self.data
                self.do_seek()

            if self.data == b"":
                break

        return data

    def readable(self):
        return True

    def writable(self):
        return False

    def seek(self, n, wherenc=0):
        oldpos = self.pos
        if wherenc == 0:
            self.pos = n
        elif wherenc == 1:
            self.pos += n
        elif wherenc == 2:
            self.pos = self.size + n
        if oldpos != self.pos:
            self.do_seek()

    def seekable(self):
        return True

    def tell(self):
        return self.pos

    def closed(self):
        return False

    def clone(self):
        return MsfStream(self.fd, self.size, self.block_size, self.blocks)

# class SubStream:
#     def __init__(self, stream, offset, size):
#         self.stream = stream
#         self.offset = offset
#         self.size = size
#         self.seek(0)

#     def read(self, size):
#         if self.tell() + size > self.size:
#             size = self.size - self.tell()
#         return self.stream.read(size)

#     def readable(self):
#         return True

#     def writable(self):
#         return False

#     def seek(self, n, wherenc=0):
#         if wherenc == 0:
#             self.stream.seek(self.offset + n)
#         elif wherenc == 2:
#             self.stream.seek(self.offset + self.size + n)

#     def seekable(self):
#         return True

#     def tell(self):
#         return self.stream.tell() - self.offset

#     def closed(self):
#         return False

class MsfFile(ConstructClass):
    subcon = Struct(
        "superblock" / SuperblockSmall,
    )

    def parsed(self, ctx):
        fd = self._stream
        dir_stream = MsfStream(fd, self.superblock.NumDirectoryBytes, self.superblock.BlockSize, self.superblock.BlockMap)
        self.directory = StreamDirectory.parse_stream(dir_stream, blocksize = self.superblock.BlockSize, fd = fd)

    def getStream(self, idx):
        return self.directory.getStream(idx)

    def __len__(self):
        return self.directory.NumStreams

class StreamDirectory(ConstructClass):
    subcon = Struct(
        "NumStreams" / Hex(Int16ul),
        "Reserved" / Hex(Int16ul),
        "StreamSizes" / Array(this.NumStreams, Struct(
            "Size" / Hex(Int32ul),
            "ReservedPtr" / Hex(Int32ul))
        ),
       # "TotalBlocks" / Computed(lambda this: StreamDirectory.countBlocks(this)),
        "StreamBlocks" / GreedyRange(Int16ul)
    )

    def countBlocks(ctx):
        blocksize = ctx._.blocksize
        sizes = [(x.Size + blocksize - 1) // blocksize for x in ctx.StreamSizes]
        return sum(sizes)

    def parsed(self, ctx):
        self.StreamSizes = [x.Size for x in self.StreamSizes]
        self.blocksize = ctx.blocksize
        fd = ctx.fd

        blocks = list(self.StreamBlocks)
        self.Streams = []

        for size in self.StreamSizes:
            count = (size + self.blocksize - 1) // self.blocksize
            stream_blocks = blocks[:count]
            blocks = blocks[count:]
            #print(f"idx: {len(self.Streams):x}, stream size {size}, count {count}, blocks {stream_blocks}")
            self.Streams.append(MsfStream(fd, size, self.blocksize, stream_blocks))

        assert len(blocks) == 0

    def getStream(self, idx):
        return self.Streams[idx]
