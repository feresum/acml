from sys import stderr
from collections import ChainMap
from typeunion import TypeUnion
import re
import ltypes as lt
import memory as mem
import llvm_instructions as inst
import mltypes as types
from dbg import *


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

size_tMap = {32: lt.i32, 64: lt.i64}

class CompileContext:
    def __init__(self, bitness, llvmVersion=(0,)):
        self.llvmVersion = llvmVersion
        self.id = 0
        self.builtins = set()
        self.bindings = {}
        self.bindings2 = {} # sadness
        self.funcTypeDeclarations = {}
        self.destructors = {}
        self.lambdaDefinitions = []
        self.destructorDefinitions = []
        self.freeTypeNums = set()
        self.s = TypeUnion()
        self.cstrCache = ChainMap()
        self.size_t = size_tMap[bitness]
        self.voidptr = lt.Scalar('%voidptr', self.size_t.size, self.size_t.align)
        self.typeUnionStack = []
    def useBuiltin(self, f):
        self.builtins.add(f)
    def getDestructor(self, mtype): # for sum types
        smtype = self.canonicalStr(mtype)
        if smtype in self.destructors:
            return self.destructors[smtype]
        name = self.destructor()
        self.destructors[smtype] = name
        self.useBuiltin('~free')
        dbody = ['; ' + smtype] + mem.sumDestructorBody(mtype, self)
        sig = 'void %s(%s %%object)' % (name, mtype.llvm(self))
        dbody += mem.getPtrToRefcount('%object', 'i1*', self, '%prefc') + [
                  inst.bitcast('%size_t*', '%voidptr', '%prefc', '%pvoid'),
                 'call void @free(%voidptr %pvoid)',
                  inst.ret()]
        self.destructorDefinitions.append(formatFunctionDef(sig, dbody, self.llvmVersion))
        return name
    def pushTypeContext(self, ta, tb):
        old = self.s
        self.s = TypeUnion()
        self.s.update(old)
        self.typeUnionStack.append(old)
        self.cstrCache = self.cstrCache.new_child()
        types.unify_inplace_tu(ta, tb, self.s)
    def popTypeContext(self):
        self.s = self.typeUnionStack.pop()
        self.cstrCache = self.cstrCache.parents
    def canonicalStr(self, t):
        try: return self.cstrCache[t]
        except KeyError: pass
        self.cstrCache[t] = s = types.canonicalStr(t, self.s)
        return s
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
        return '@destroy' + str(self.id)
    def closureDestructor(self):
        self.id += 1
        return '@destroyClosure' + str(self.id)
    def compile(self, expr):
        from mlbuiltins import definition
        expr.markDepth(0)
        xreg = self.local()
        compiled = expr.compile(self, xreg) + mem.unreference(xreg, expr.type, self) + [inst.ret()]
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
        out += '\n'
        for d in self.destructorDefinitions:
            out += d
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

def makeFuncObj(fptr, mtype, closure, cx, out):
    fpt = funcPtrType(mtype, cx)
    s0 = cx.local()
    return ['%s = insertvalue %s undef, %s %s, 0' % (s0, mtype.llvm(cx), fpt, fptr),
            '%s = insertvalue %s %s, %s %s, 1' % (out, mtype.llvm(cx), s0, '%voidptr', closure)]
def funcObjFunction(fobj, mtype, cx, out):
    return [inst.extractvalue(mtype.llvm(cx), fobj, 0, out)]
def funcObjClosure(fobj, mtype, cx, out):
    return [inst.extractvalue(mtype.llvm(cx), fobj, 1, out)]
    
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
    return [inst.extractvalue(mtype.llvm(cx), p, ind, out)]
    
def getSumTypeSelector(s, cx, out):
    return [inst.load('i1', s, out)]
    
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

def ifThenElse(cond, trueBlock, falseBlock, cx):
    tLbl, fLbl, rejoin = cx.label(), cx.label(), cx.label()
    return [inst.branch(cond, tLbl, fLbl),
            inst.label(tLbl)] + trueBlock + [
            inst.branch(rejoin),
            inst.label(fLbl)] + falseBlock + [
            inst.branch(rejoin),
            inst.label(rejoin)]

def ifThen(cond, trueBlock, cx):
    tLbl, rejoin = cx.label(), cx.label()
    return [inst.branch(cond, tLbl, rejoin),
            inst.label(tLbl)] + trueBlock + [
            inst.branch(rejoin),
            inst.label(rejoin)]
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
            
def reusable(code, constReg):
    def generate(cx):
        rmap = {constReg: constReg}
        def replace(s):
            s = s.group(0)
            if s in rmap:
                return rmap[s]
            s2 = cx.local() if s[1] == 'r' else cx.label()
            rmap[s] = s2
            return s2
        def subs(s):
            return re.sub(r'(%r|lbl)\d+', replace, s)
        out = []
        for ln in code:
            if isinstance(ln, str):
                out.append(subs(ln))
            else:
                args = [subs(a) if type(a) is str else a for a in ln.args]
                out.append(inst.Instruction(ln.formats, *args))
        return out
    return generate
                