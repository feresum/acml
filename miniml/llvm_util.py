from sys import stderr
from collections import ChainMap
import re
import ltypes as lt
import memory as mem
import llvm_instructions as inst


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
    def __init__(self, bitness, llvmVersion=0):
        self.llvmVersion = llvmVersion
        self.id = 0
        self.builtins = set()
        self.bindings = {}
        self.funcTypeDeclarations = {}
        self.destructors = {}
        self.lambdaDefinitions = []
        self.destructorDefinitions = []
        self.freeTypeNums = set()
        self.s = ChainMap(key_defaultdict())
        self.size_t = size_tMap[bitness]
        self.voidptr = lt.Scalar('%voidptr', self.size_t.size, self.size_t.align)
        self.funDepth = 0
        self.varDefDepth = {}
        self.varRefDepth = {}
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
        sig = 'void %s(%s* %%object)' % (name, ltype)
        dbody += ['%%ptr = bitcast %s* %%object to %%voidptr' % ltype,
                  'call void @free(%voidptr %ptr)',
                  'ret void']
        self.destructorDefinitions.append(formatFunctionDef(dbody, self.version))
        return name
    def local(self):
        self.id += 1
        #if self.id==2:import pdb;pdb.set_trace()
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
        expr.markDepth(0)
        compiled = expr.compile(self, self.local()) + [inst.ret()]
        out = initial_typedefs + '%%size_t = type %s\n\n' % self.size_t
        for n in self.freeTypeNums:
            out += '%%free_type_%d = type i1\n' % n
        out += '\n'
        for b in self.builtins:
            out += definition[b]
        for nam, tp in self.funcTypeDeclarations.values():
            out += '\n' + nam + ' = ' + tp
        out += '\n\n'
        for l in self.lambdaDefinitions:
            out += l
        out += '\n' + formatFunctionDef('void @ml_program()', compiled, self.llvmVersion)
        out += '\n' + formatFunctionDef('i32 @main()', ['call void @ml_program()', 'ret i32 0'], self.llvmVersion)
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
    #if out=='%r7':import pdb;pdb.set_trace()
    return ['%s = insertvalue %s undef, %s %s, 0' % (s0, mtype.llvm(cx), fpt, fptr),
            '%s = insertvalue %s %s, %s %s, 1' % (out, mtype.llvm(cx), s0, '%voidptr', closure)]
def funcObjFunction(fobj, mtype, cx, out):
    return ['%s = extractvalue %s %s, 0' % (out, mtype.llvm(cx), fobj)]
def funcObjClosure(fobj, mtype, cx, out):
    return ['%s = extractvalue %s %s, 1' % (out, mtype.llvm(cx), fobj)]
    
def formAggregate(ltype, cx, out, *members):
    assert(len(ltype.members) == len(members))
    r = 'undef'
    code = []
    for i, (t, m) in enumerate(zip(ltype.members, members)):
        r2 = cx.local()
        code.append(inst.insertvalue(ltype, r, t, m, r2, i))
        r = r2
    code += dup(r, out, ltype, cx)
    things = ['%s %s' % p for p in zip(ltype.members, members)]
    prefix = '%s = {' % out
    pretty = ['; ' + l for l in (prefix + (',\n' + ' ' * len(prefix)).join(
        things) + '}').split('\n')]
    return code + pretty
def closureType(ltypes, cx):
    return lt.Aggregate(ltypes)
    

def heapCreate(ltype, value, cx, out):
    voidp, rcp, rcval = cx.local(), cx.local(), cx.local()
    cx.useBuiltin('~malloc')
    rctype = mem.rctype(ltype, cx)
    return formAggregate(rctype, cx, rcval, 1, value) + [
           '%s = call %%voidptr @malloc(%%size_t %d)' % (voidp, rctype.size),
           inst.bitcast('%voidptr', lt.Pointer(rctype, cx), voidp, rcp),
           inst.store(rctype, rcval, rcp),
           inst.structGEP(rcp, rctype, out, 1)]

    
def store(type, value, addr):
    return inst.store(type, value, addr)

def extractProductElement(mtype, p, ind, cx, out):
    return ['%s = extractvalue %s %s, %d' % (out, mtype.llvm(cx), p, ind)]
    
def getSumTypeSelector(s, cx, out):
    return [load('i1', s, out)]
    
def sumSideType(ltype):
    return lt.Aggregate((lt.i1, ltype))
    
def formatFunctionDef(signature, lines, version):
    s = 'define ' + signature + '\n{\n'
    for l in removeNops(inst.versionSyntaxReplace(l, version) for l in lines):
        s += '\t' + l + '\n'
    return s + '}\n'

def conditionalValue(cond, ltype, trueBlock, trueReg, falseBlock, falseReg, cx, out):
    tLbl, tLbl0, fLbl, fLbl0, rejoin = cx.label(), cx.label(), cx.label(), cx.label(), cx.label()
    tReg2, fReg2 = cx.local(), cx.local()
    z = lambda lbl0, lbl1, reg0, reg1, block: [inst.label(lbl0)] + block + [inst.branch(lbl1),
        inst.label(lbl1)] + dup(reg0, reg1, ltype, cx) + [inst.branch(rejoin)]
    return [inst.branch(cond, tLbl0, fLbl0)] + z(tLbl0, tLbl, trueReg, tReg2, trueBlock) \
        + z(fLbl0, fLbl, falseReg, fReg2, falseBlock) + [inst.label(rejoin),
        inst.phi(ltype, out, (tReg2, tLbl), (fReg2, fLbl))]

def removeNops(func):
    return func######################
    lines = iter(func)
    out = []
    rx = r'(\S+)'
    reps = key_defaultdict()
    while True:
        try: line = re.sub(r'(%\S+)', lambda m: reps[m.group(1)], next(lines))
        except StopIteration: return out
        if line.endswith(';nop'):
            l2 = next(lines)
            m2 = re.fullmatch(r'%s = extractvalue \{(.+)\} %s, 0 ;nop' % (rx, rx), l2)
            new, tp, tmp = m2.groups()
            escTp = re.escape(tp)
            m1 = re.fullmatch(r'%s = insertvalue {%s} undef, %s %s, 0 ;nop' % (tmp, escTp, escTp, rx), line)
            orig, = m1.groups()
            reps[new] = orig
        else:
            out.append(line)