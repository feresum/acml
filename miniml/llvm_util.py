from sys import stderr
from collections import ChainMap
import ltypes as lt
import memory as mem


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
        self.destructors = {}
        self.lambdaDefinitions = []
        self.destructorDefinitions = []
        self.s = ChainMap(key_defaultdict())
        self.size_t = size_tMap[bitness]
        self.voidptr = lt.Scalar('%voidptr', self.size_t.size, self.size_t.align)
    def useBuiltin(self, f):
        self.builtins.add(f)
    def getDestructor(self, mtype):
        ltype = str(mtype.llvm(self))
        if ltype in self.destructors:
            return self.destructors[ltype]
        name = self.destructor()
        self.destructors[ltype] = name
        self.useBuiltin('~free')
        dbody = mtype.destructorBody(self)
        destructor = 'define void %s(%s* %%object)\n{\n' % (name, ltype)
        for line in dbody + ['%%ptr = bitcast %s* %%object to %%voidptr' % ltype,
                             'call void @free(%voidptr %ptr)',
                             'ret void']:
            destructor += '\t' + line + '\n'
        destructor += '}\n'
        self.destructorDefinitions.append(destructor)
        return name
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
    def destructor(self):
        self.id += 1
        return '%destroy' + str(self.id)
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
    rctype = mem.rctype(ltype)
    return ['%s = call %%voidptr @malloc(%%size_t %d)' % (p, rctype.size),
            '%s = bitcast %%voidptr %s to %s*' % (out, p, ltype),
            'store %s %s, %s* %s' % (ltype, value, ltype, out)]

def structGEP(addr, ltype, out, *ind):
    s = '%s = getelementpointer inbounds %s,%s* %s, i32 0' % (out, ltype, ltype, addr)
    for i in ind:
        s += ', i32 %d' % i
    return [s]
    
def store(type, value, addr):
    return 'store %s %s, %s* %s' % (type, value, type, addr)

def extractProductElement(mtype, p, ind, cx, out):
    return ['%s = extractvalue %s %s, %d' % (out, mtype.llvm(cx), p, ind)]
    
def getSumTypeSelector(s, cx, out):
    return [load('i1', s, out)]
    
def formatFunctionDef(signature, lines):
    s = 'define ' + signature + '\n{\n'
    for l in lines:
        s += '\t' + l + '\n'
    return s + '}\n'