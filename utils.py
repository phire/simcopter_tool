

def hexdump(s, sep=" "):
    return sep.join(["%02x"%x for x in s])

def hexdump32(s, sep=" "):
    vals = struct.unpack("<%dI" % (len(s)//4), s)
    return sep.join(["%08x"%x for x in vals])

def _ascii(s):
    s2 = ""
    for c in s:
        if c < 0x20 or c > 0x7e:
            s2 += "."
        else:
            s2 += chr(c)
    return s2

def chexdump(s, st=0, abbreviate=True, stride=16, indent="", print_fn=print):
    last = None
    skip = False
    for i in range(0,len(s),stride):
        val = s[i:i+stride]
        if val == last and abbreviate:
            if not skip:
                print_fn(indent+"%08x  *" % (i + st))
                skip = True
        else:
            print_fn(indent+"%08x  %s  |%s|" % (
                i + st,
                "  ".join(hexdump(val[i:i+8], ' ').ljust(23)
                          for i in range(0, stride, 8)),
                _ascii(val).ljust(stride)))
            last = val
            skip = False
