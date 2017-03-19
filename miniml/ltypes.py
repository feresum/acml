from copy import copy
from dbg import *

def align(size, align):
    return (size + (align - 1)) & -align

class Ltype:
    def __str__(self):
        return self.name

class Scalar(Ltype):
    def __init__(self, name, size, align):
        self.name = name
        self.size = size
        self.align = align
class Funcptr(Ltype):
    def __init__(self, name, cx):
        self.name = name
        self.size = cx.voidptr.size
        self.align = cx.voidptr.align
class Aggregate(Ltype):
    def __init__(self, members):
        self.members = tuple(members)
        assert self.members
        size = 0
        self.align = 1
        for m in self.members:
            size = align(size, m.align) + m.size
            self.align = max(self.align, m.align)
        self.size = align(size, self.align)
        self.name = '{' + ','.join(m.name for m in self.members) + '}'

class Union(Ltype):
    def __init__(self, members):
        self.members = tuple(members)
        self.align = max(m.align for m in self.members)
        self.size = align(max(m.size for m in self.members), self.align)
        self.buf = Aggregate(self, self.size / self.align * [typeWithAlign[self.align]])
        self.name = self.buf.name

i1 = Scalar('i1', 1, 1)
i8 = Scalar('i8', 1, 1)
i32 = Scalar('i32', 4, 4)
i64 = Scalar('i64', 8, 8)
typeWithAlign = {1:i8, 4:i32, 8:i64}

def alias(lt, name):
    t = copy(lt)
    t.name = name
    return t
Unit = alias(i1, '%Unit')
Bool = alias(i1, '%Bool')
Char = alias(i8, '%Char')
Int = alias(i64, '%Int')
