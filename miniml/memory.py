# For now, closures and sum types will use heap pointers; other types by value.
# Storing sum types and nothing else as pointers knocks out recursive types and the inconvenient
#  need for bitcasting at once for easiest implementation.
# When a heap object is created, have refcount be 1, owned by the current stack frame.
# Increment in a function if it intends to return an object.
# Increment when another heap object creates a pointer to the object.
# Decrement refcount when:
#    a scope with ownership ends without returning the object
#    a heap object pointing to it is destroyed

# Live references can be on either the stack or the heap
# 

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
    if isinstance(mtype, types.Sum):
        return StorageType.POINTER
    if isDirectlyRecursive(mtype, s):
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
def getPtrToRefcount(addr, ltype, cx, out):
    sizeptr = cx.local()
    return [inst.bitcast(ltype, '%size_t*', addr, sizeptr),
    '%s = getelementptr %%size_t,%%size_t* %s, %%size_t -1' % (out, sizeptr)]
    
def heapRefcountIncrement(addr, ltype, cx):
    p, count, plus1 = cx.local(), cx.local(), cx.local()
    return [getPtrToRefcount(addr, ltype, cx, p),
            '%s = load %%size_t* %s' % (count, p),
            '%s = add nuw %%size_t 1, %s' % (plus1, count),
            store('%size_t', plus1, p)]

def heapRefcountDecrement(addr, mtype, cx):
    ltype = mtype.llvm(cx)
    rctype = rctype(ltype, cx)
    p, count, minus1, isZero = cx.local(), cx.local(), cx.local(), cx.local()
    destroy, decr, after = cx.label(), cx.label(), cx.label()
    return getPtrToRefcount(addr, ltype, cx, p) + [
        '%s = load %%size_t* %s' % (count, p),
        '%s = sub nuw %%size_t %s, 1' % (minus1, count),
        '%s = icmp eq %%size_t 0, %s' % (isZero, minus1),
        'br i1 %s, label %%%s, label %%%s' % (isZero, destroy, after),
        destroy + ':',
        'call void %s(%s* %s)' % (cx.getDestructor(mtype), rctype, addr),
        'br label %' + after,
        decr + ':',
        store('%size_t', minus1, p),
        'br label %' + after,
        after + ':'
    ]
    
def unreference(v, mtype, cx):
    if canonicalStorage(mtype, cx.s) is StorageType.POINTER:
        return heapRefcountDecrement(v, mtype, cx)
    return []
    
def reference(v, mtype, cx):
    if canonicalStorage(mtype, cx.s) is StorageType.POINTER:
        return heapRefcountIncrement(v, mtype, cx)
    return []