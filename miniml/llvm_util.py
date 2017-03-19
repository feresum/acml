from sys import stderr
from collections import ChainMap
import ltypes as lt


unit_value = '%Unit undef'

initial_typedefs = '''\
%voidptr = type i8 *
%Int = type i64
%Char = type i8
%Unit = type i1
%Bool = type i1
'''

class key_defaultdict(dict):
    def __getitem__(self, key):
        try:
            return super().__getitem__(key)
        except KeyError:
            return key
            
class idempotent_dict(key_defaultdict):
    def __setitem__(self, key, value):
        assert(key not in self)
        super().__setitem__(key, value)
        assert(all(v not in self for v in self.values()))
#key_defaultdict = idempotent_dict

size_tMap = {32: lt.i32, 64: lt.i64}

class CompileContext:
    def __init__(self, bitness):
        self.id = 0
        self.builtins = set()
        self.bindings = {}
        self.funcTypeDeclarations = {}
        self.lambdaDefinitions = []
        self.s = ChainMap(key_defaultdict())
        self.size_t = size_tMap[bitness]
        self.voidptr = lt.Scalar('%voidptr', self.size_t.size, self.size_t.align)
    def useBuiltin(self, f):
        self.builtins.add(f)
    def local(self):
        self.id += 1
        return '%r' + str(self.id)
    def label(self):
        self.id += 1
        return 'lbl' + str(self.id)
    def lamb(self):
        self.id += 1
        return '@lambda' + str(self.id)
    def func(self):
        self.id += 1
        return '%func' + str(self.id)
    def compile(self, expr):
        from mlbuiltins import definition
        compiled = expr.compile(self, self.local())
        out = initial_typedefs + '%%size_t = type %s\n\n' % self.size_t
        for b in self.builtins:
            out += definition[b]
        for nam, tp in self.funcTypeDeclarations.values():
            out += '\n' + nam + ' = ' + tp
        out += '\n\n'
        for l in self.lambdaDefinitions:
            out += l
        out += '\ndefine void @ml_program()\n{\n'
        for line in compiled + ['ret void']:
            out += '\t' + line + '\n'
        out += '}\n\ndefine i32 @main()\n{\n\tcall void @ml_program()\n\tret i32 0\n}\n'
        return out
    def warn(self, s):
        print('Warning:', s, file=stderr)

def funcPtrType(arrow, cx):
    return '%s(%s,%s)*' % (arrow.result().llvm(cx), '%voidptr', arrow.argument().llvm(cx))

def addrField(structAddr, structLtype, fieldIndex, out):
    return ['%s = getelementptr inbounds %s* %s, i32 0, i32 %d' % 
        (out, structLtype, structAddr, fieldIndex)] 
def loadField(structAddr, structLtype, fieldIndex, fieldLtype, cx, out):
    addr = cx.local()
    return addrField(structAddr, structLtype, fieldIndex, addr) + [
        '%s = load %s* %s' % (out, structLtype, addr)]
def storeField(structAddr, structLtype, fieldIndex, fieldLtype, cx, value):
    addr = cx.local()
    return addrField(structAddr, structLtype, fieldIndex, addr) + [
        'store %s %s, %s* %s' % (fieldLtype, value, fieldLtype, addr)]

def dup(ra, rb, ltype, cx):
    wat = cx.local()
    return ['%s = insertvalue {%s} undef, %s %s, 0 ;nop' % (wat, ltype, ltype, ra),
            '%s = extractvalue {%s} %s, 0 ;nop' % (rb, ltype, wat)]

# def functionFuncPtrPtr(fObjPtr, arrow):
    # ts = arrow.llvm()
    # return 'getelementptr inbounds %s* %s, i32 0, i32 0' % (ts, fObjPtr)
# def functionDataPtrPtr(fObjPtr, arrow):
    # ts = arrow.llvm()
    # return 'getelementptr inbounds %s* %s, i32 0, i32 1' % (ts, fObjPtr)

def makeFuncObj(fptr, mtype, closure, cx, out):
    fpt = funcPtrType(mtype, cx)
    s0 = cx.local()
    return ['%s = insertvalue %s undef, %s %s, 0' % (s0, mtype.llvm(cx), fpt, fptr),
            '%s = insertvalue %s %s, %s %s, 1' % (out, mtype.llvm(cx), s0, '%voidptr', closure)]
def funcObjFunction(fobj, mtype, cx, out):
    return ['%s = extractvalue %s %s, 0' % (out, mtype.llvm(cx), fobj)]
def funcObjClosure(fobj, mtype, cx, out):
    return ['%s = extractvalue %s %s, 1' % (out, mtype.llvm(cx), fobj)]
    

def closureType(mtypes, cx):
    return lt.Aggregate(t.llvm(cx) for t in mtypes)


def heapCreate(ltype, value, cx, out):
    p = cx.local()
    cx.useBuiltin('~malloc')
    return ['%s = call %%voidptr @malloc(%%size_t %d)' % (p, ltype.size),
            '%s = bitcast %%voidptr %s to %s*' % (out, p, ltype),
            'store %s %s, %s* %s' % (ltype, value, ltype, out)]

class Struct: pass
class StackStruct(Struct):
    def __init__(self, *types):
        self.llvm_types = tuple(t.llvm() for t in types)
    def readField(self, index): pass
    