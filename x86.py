from iced_x86 import Decoder, Mnemonic, OpKind, Register



def disassemble(data, addr=0):
    decoder = Decoder(32, data, ip=addr)
    instrs = []
    for instr in decoder:
        instrs.append(instr)
    return instrs