# For now, closures and sum types will use heap pointers; other types by value.
# Storing sum types and nothing else as pointers knocks out recursive types and the inconvenient

# Live references can be on either the stack or the heap
# A stack reference is created when a heap object is allocated, when something containing
#   (possibly multiple) pointers is loaded from the heap, or when a sum/product/function expression
#   is created containing a pointer.
# Passing something as a function argument does not create a new reference.
# A stack reference can stay alive if it is returned as the result of the function; otherwise
#   it is removed after evaluating the expression

import mltypes as types
import ltypes as lt
import llvm_util as lu
import llvm_instructions as inst

class StorageType:
    VALUE = 'by value'
    POINTER = 'by pointer'

def isDirectlyRecursive(mtype, s):
    check = [s[mtype]]
    seen = set(check)
    while check:
        t = check.pop()
        if not t.isTypeVariable():
            for p in t.parms:
                p = s[p]
                if p not in seen:
                    if types.equivalent(mtype, p, s):
                        return True
                    seen.add(p)
                    check.append(p)
    return False

def canonicalStorage(mtype, s):
    mtype = s[mtype]
    if isinstance(mtype, types.Sum):
        return StorageType.POINTER
    return StorageType.VALUE

class Ref:
    def __init__(self, mtype, cx, reg):
        self.mtype = mtype
        self.ltype = mtype.llvm(cx)
        self.reg = reg
    def _increment(self, ptr, cx):
        return []
    def decrement(self, cx):
        return []
        
class RegisterRef(Ref):
    def load(self, cx, out):
        return lu.dup(self.reg, out, self.ltype, cx)

class ClosureRef(Ref):
    def __init__(self, ltype, reg, cltype):
        super().__init__(ltype, reg)
        self.cltype = cltype
    def load(self, cx, out):
        addr = cx.local()
    
def rctype(ltype, cx):
    return lt.Aggregate((cx.size_t, ltype))
def getPtrToRefcount(addr, ptrType, cx, out):
    sizeptr = cx.local()
    return [inst.bitcast(ptrType, '%size_t*', addr, sizeptr),
            inst.linearGEP(sizeptr, '%size_t', out, -1)]

    
def heapRefcountIncrement(addr, ptrType, cx):
    p, count, plus1 = cx.local(), cx.local(), cx.local()
    return getPtrToRefcount(addr, ptrType, cx, p) + [
            inst.load('%size_t', p, count),
            '%s = add nuw %%size_t 1, %s' % (plus1, count),
            inst.store('%size_t', plus1, p)]

def heapRefcountDecrement(refcAddr, destroyCode, cx):
    count, minus1, isZero = cx.local(), cx.local(), cx.local()
    return [
        inst.load('%size_t', refcAddr, count),
        '%s = sub nuw %%size_t %s, 1' % (minus1, count),
        '%s = icmp eq %%size_t 0, %s' % (isZero, minus1)
        ] + lu.ifThenElse(isZero, destroyCode, [inst.store('%size_t', minus1, refcAddr)], cx)


def closureDestructorType(cx):
    return lt.Funcptr('void(%voidptr)', cx)

def destroyClosure(refcAddr, cx): # assuming nonnull
    cdt = closureDestructorType(cx)
    sizep, funcpp, funcp, voidp = cx.local(), cx.local(), cx.local(), cx.local()
    cx.useBuiltin('~free')
    return [inst.linearGEP(refcAddr, '%size_t', sizep, -1),
            inst.bitcast('%size_t*', lt.Pointer(cdt, cx), sizep, funcpp),
            inst.load(cdt, funcpp, funcp),
            inst.bitcast('%size_t*', '%voidptr', sizep, voidp), 
            'call void %s(%%voidptr %s)' % (funcp, voidp)]
            
            
def closureDestructorDefinition(name, clType, items, cx):
    sig = 'void %s(%%voidptr %%cl)' % name
    clTypeFull = closureTypeFull(clType, cx)
    body = []
    for i, (ltype, unrefCode, reg) in enumerate(items):
        unrefCode = unrefCode(cx)
        if unrefCode:
            body += [inst.extractvalue(clType, '%stuff', i, reg)] + unrefCode
    if body:
        body = [inst.bitcast('%voidptr', lt.Pointer(clTypeFull, cx), '%cl', '%p'),
               inst.structGEP('%p', clTypeFull, '%stuffP', 2),
               inst.load(clType, '%stuffP', '%stuff')] + body
    body += ['call void @free(%voidptr %cl)',
             inst.ret()]
    return lu.formatFunctionDef(sig, body, cx.llvmVersion)

def closureTypeFull(cltype, cx):
    return lt.Aggregate((closureDestructorType(cx), cx.size_t, cltype))
def createClosure(clType, clStuff, destructor, cx, out):
    t = closureTypeFull(clType, cx)
    voidp, rcp, rcval = cx.local(), cx.local(), cx.local()
    cx.useBuiltin('~malloc')
    return lu.formAggregate(t, cx, rcval, destructor, 1, clStuff) + [
           '%s = call %%voidptr @malloc(%%size_t %d)' % (voidp, t.size),
           inst.bitcast('%voidptr', lt.Pointer(t, cx), voidp, rcp),
           inst.store(t, rcval, rcp),
           inst.structGEP(rcp, t, out, 2)]

def nullChecked(p, ltype, code, cx):
    cond = cx.local()
    nonnull, end = cx.label(), cx.label()
    return [inst.icmp('eq', ltype, p, 'null', cond),
            inst.branch(cond, end, nonnull),
            inst.label(nonnull)] + code + [
            inst.branch(end),
            inst.label(end)]
    

def unreference(v, mtype, cx):
    mtype = cx.s[mtype]
    if canonicalStorage(mtype, cx.s) is StorageType.POINTER:
        sizep, refc = cx.local(), cx.local()
        return [inst.bitcast('i1*', '%size_t*', v, sizep),
                inst.linearGEP(sizep, '%size_t', refc, -1)] + \
            heapRefcountDecrement(refc,
                ['call void %s(i1* %s)' % (cx.getDestructor(mtype), v)], cx)
    elif isinstance(mtype, types.Product):
        code = []
        for i in 0, 1:
            r = cx.local()
            refcode = unreference(r, mtype.parms[i], cx)
            if refcode:
                code += lu.extractProductElement(mtype, v, i, cx, r)
                code += refcode
        return code
    elif isinstance(mtype, types.Arrow):
        r, prefc = cx.local(), cx.local()
        return lu.funcObjClosure(v, mtype, cx, r) + nullChecked(r, cx.voidptr,
            getPtrToRefcount(r, cx.voidptr, cx, prefc) +
            heapRefcountDecrement(prefc, destroyClosure(prefc, cx), cx), cx)
    return []
    


def reference(v, mtype, cx):
    mtype = cx.s[mtype]
    if canonicalStorage(mtype, cx.s) is StorageType.POINTER:
        return heapRefcountIncrement(v, mtype.llvm(cx), cx)
    elif isinstance(mtype, types.Product):
        code = []
        for i in 0, 1:
            r = cx.local()
            refcode = reference(r, mtype.parms[i], cx)
            if refcode:
                code += lu.extractProductElement(mtype, v, i, cx, r)
                code += refcode
        return code
    elif isinstance(mtype, types.Arrow):
        r = cx.local()
        return lu.funcObjClosure(v, mtype, cx, r) + nullChecked(r, cx.voidptr,
               heapRefcountIncrement(r, cx.voidptr, cx), cx)
    return []

def sumDestructorBody(mtype, cx):
    mtype = cx.s[mtype]
    sel = cx.local()
    def destroySide(i):
        lt_i = mtype.parms[i].llvm(cx)
        sst = lu.sumSideType(lt_i)
        r, sp, mp = cx.local(), cx.local(), cx.local()
        unrefCode = unreference(r, mtype.parms[i], cx)
        if not unrefCode: return []
        return [inst.bitcast('i1*', lt.Pointer(sst, cx), '%object', sp),
                inst.structGEP(sp, sst, mp, 1),
                inst.load(lt_i, mp, r)] + unrefCode
            
    return lu.getSumTypeSelector('%object', cx, sel) + \
           lu.ifThenElse(sel, destroySide(1), destroySide(0), cx)