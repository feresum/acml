from collections import ChainMap
from llvm_util import funcPtrType, key_defaultdict
from typeunion import TypeUnion
import ltypes as lt
import memory
from dbg import *



class MLtype:
    def isTypeVariable(self):
        return False
    def isDirectlyRecursive(self, subst): # this function doesn't really work. don't use
        check = [self]
        seen = set()
        while check:
            t = subst[check.pop()]
            if not t.isTypeVariable():
                for p in t.parms:
                    if p is self:
                        # assert(self.isTypeVariable())
                        return True
                    if p not in seen:
                        check.append(p)
                        seen.add(p)
        return False
    def __str__(self):
        return typeDbgStr0(self)
    def __repr__(self):
        return str(self)
    def destructorBody(self, cx):
        return []

class VarType(MLtype):
    count = 0
    def __init__(self):
        VarType.count += 1
        self.id = VarType.count
    def isTypeVariable(self):
        return True
    def llvm(self, cx):
        t = cx.s[self]
        if t is self:
            cx.warn('Expression compiled with generic type')
            t = Unit()
        return t.llvm(cx)
        

def TypeConstructor(numParms):
    class TypeConstructor(MLtype):
        def __init__(self, *parms):
            assert len(parms) == numParms
            self.nParms = numParms
            self.parms = parms
    return TypeConstructor
            
class TypesNotUnifiable(Exception): pass

class Arrow(TypeConstructor(2)):
    def argument(self):
        return self.parms[0]
    def result(self):
        return self.parms[1]
    def llvm(self, cx):
        
        cstr = canonicalStr(self, cx.s)
        if cstr not in cx.funcTypeDeclarations:
            dpr('new type', cstr)
            
            func = cx.func()
            cx.funcTypeDeclarations[cstr] = (func,)
            cx.funcTypeDeclarations[cstr] = (func,
                'type {%s, %s}' % (funcPtrType(self, cx), '%voidptr'))
        return cx.funcTypeDeclarations[cstr][0]
    def register(self, cx):
        cx.funcTypeDeclarations[self] = 'type %s = {%s, %s}' % (
            self.llvm(cx.s), funcPtrType(self, cx), '%voidptr')

class Product(TypeConstructor(2)):
    def llvm(self, cx):
        return lt.Aggregate(p.llvm(cx) for p in self.parms)
    def destructorBody(self, cx):
        o = []
        for i in 0, 1:
            r = cx.local()
            o += lu.extractProductElement(self, '%object', i, cx, r)
            o += memory.unreference(r, self.parms[i], cx)
        return o
    
class Sum(TypeConstructor(2)):
    def llvm(self, cx):
        return lt.Pointer(lt.i1, cx)
    def destructorBody(self, cx):
        pass
    
class Unit(TypeConstructor(0)):
    def llvm(self, cx):
        return lt.Unit

def Integral(bits, ltype):
    class Integral(TypeConstructor(0)):
        def __init__(self):
            super().__init__()
            self.bits = bits
        def llvm(self, cx):
            return ltype
    Integral.__name__ += str(bits)
    return Integral()
    
Int = Integral(64, lt.Int)
Char = Integral(8, lt.Char)
Bool = Integral(1, lt.Bool)
        
def typeDbgStr0(t):
    names = {}
    rec = set()
    i = 0
    def s(t):
        if t in rec:
            return names[t] + '(...)'
        rec.add(t)
        nonlocal i
        i += 1
        var = t.isTypeVariable()
        nam = "'" + str(t.id) if var else type(t).__name__ + str(i)
        nam = names.setdefault(t, nam)
        if not var and t.nParms > 0:
            nam += '(' + ', '.join(map(s, t.parms)) + ')'
        rec.remove(t)
        return nam
    return s(t)
def typeDbgStr0(t):
    names = {}
    i = 0
    def s(t):
        nonlocal i
        i += 1
        var = t.isTypeVariable()
        nam = "'" + str(t.id) if var else type(t).__name__ + str(i)
        nam = names.setdefault(t, nam)
        if not var and t.nParms > 0:
            nam += '(' + ', '.join(map(s, t.parms)) + ')'
        return nam
    return s(t)

def typeDbgStr(t, subst):
    names = {}
    i = 0
    def s(t):
        if t in names:
            return names[t]
        nonlocal i
        isVar = t.isTypeVariable()
        free = isVar and t is subst[t]
        if t.isDirectlyRecursive(subst) or free:
            nonlocal i
            i += 1
            names[t] = "'" + str(i)
            if free: return names[t]
            nam = names[t] + '='
        elif t is not subst[t]:
            return s(subst[t])
        else:
            nam = ''
        t = subst[t]
        nam += type(t).__name__
        if t.nParms > 0:
            nam += '(' + ', '.join(map(s, t.parms)) + ')'
        return nam
    return s(t)
    

def freeVariables(t, subst):
    seen = {}
    free = []
    def search(t):
        t = subst[t]
        if t in seen: return
        seen.add(t)
        if t.isTypeVariable():
            free.append(t)
        else:
            for u in t.parms:
                search(u)
    return free

# https://inst.eecs.berkeley.edu/~cs164/sp11/lectures/lecture22.pdf  p. 9
def unify(a, b, bind0 = ()): # doesn't work when bind is nonempty!
                             # can return non-idempotent bindings
    dpr('unify:', a, b)
    bind = dict(bind0)
    def unify_r(a, b):
        ua, ub = bind.get(a, a), bind.get(b, b)
        if ua is ub: return
        if ua.isTypeVariable():
            bind[ua] = ub
            return
        bind[ub] = ua
        if ub.isTypeVariable():
            return
        if type(ua) != type(ub) or len(ua.parms) != len(ub.parms):
            raise TypesNotUnifiable()
        for x, y in zip(ua.parms, ub.parms):
            unify_r(x, y)
    unify_r(a, b)
    return bind
    
def unify_nofree(a, b, bind0):
    dpr('unf', a, b, bind0)
    bind = ChainMap({}, bind0)
    def myIsTV(v):
        return v.isTypeVariable() and v in bind0
    def free(v):
        return v.isTypeVariable() and v not in bind0
    def unify_(a, b):
        ua, ub = bind.get(a, a), bind.get(b, b)
        if ua is ub: return True
        if myIsTV(ua):
            bind[ua] = ub
            return True
        if (free(ua) or free(ub)) and (ua in bind or ub in bind):
            return False
        #bind[ub] = ua
        bind[b] = ua
        if myIsTV(ub):
            return True
        if ua.isTypeVariable() and ub.isTypeVariable():
            return True
        if type(ua) != type(ub) or ua.nParms != ub.nParms:
            return False
        return all(unify_(*p) for p in zip(ua.parms, ub.parms))
    return unify_(a, b)


def equivalent(a, b, bind):
    # if len(freeVariables(a, bind)) != len(freeVariables(b, bind)):
        # return False
    bind = ChainMap({}, bind)
    b = duplicate(b, bind)
    u = TypeUnion()
    u.import_dict(bind)
    joinedV = set()
    def unify_(a, b):
        ua, ub = u[a], u[b]
        if ua is ub:
            return True
        if ua.isTypeVariable() ^ ub.isTypeVariable():
            return False
        u.join(ua, ub)
        if ua.isTypeVariable():
            for v in ua, ub:
                if v in joinedV: return False
                joinedV.add(v)
            return True
        if type(ua) != type(ub) or ua.nParms != ub.nParms:
            return False
        return all(map(unify_, ua.parms, ub.parms))
    return unify_(a, b)
        

def unify_inplace(a, b, bind):
    delme = set()
    def unify_r(a, b):
        ua, ub = bind.get(a, a), bind.get(b, b)
        if ua is ub: return
        if ua.isTypeVariable():
            bind[ua] = ub
            return
        bind[ub] = ua
        if ub.isTypeVariable():
            return
        delme.add(ub)
        for x, y in zip(ua.parms, ub.parms):
            unify_r(x, y)
    unify_r(a, b)
    for k in delme:
        del bind[k]
def unify_inplace(a, b, bind): # not really in place anymore...
    dpr('unify', bind)
    dpr('unify', [typeDbgStr0(x) for x in (a,b)])
    bind2 = key_defaultdict()
    def unify_r(a, b):
        ua, ub = bind2[bind[a]], bind2[bind[b]]
        if ua is ub: return
        if ua.isTypeVariable():
            bind2[ua] = ub
            return
        bind2[ub] = ua
        if ub.isTypeVariable():
            return
        if type(ua) != type(ub) or ua.nParms != ub.nParms:
            raise TypesNotUnifiable()
        for x, y in zip(ua.parms, ub.parms):
            unify_r(x, y)
    unify_r(a, b)
    for k, v in bind2.items():
        if k.isTypeVariable():
            bind[k] = v
def unify_inplace(a, b, bind0):
    dpr('unify', bind0)
    dpr('unify', [typeDbgStr0(x) for x in (a,b)])
    bind = ChainMap({}, bind0)
    def unify_r(a, b):
        ua, ub = bind[a], bind[b]
        dpr(ua,ub)
        dpr(bind)
        if ua is ub: return
        if ua.isTypeVariable() and a is ua:
            bind0[ua] = ub
            return
        if ub.isTypeVariable() and b is ub:
            bind0[ub] = ua
            return
        bind[ub] = ua
        if type(ua) != type(ub) or ua.nParms != ub.nParms:
            raise TypesNotUnifiable()
        assert(not(ua.isTypeVariable() or ub.isTypeVariable()))
        for x, y in zip(ua.parms, ub.parms):
            unify_r(x, y)
    unify_r(a, b)
    
def unify_inplace(a, b, bind):
    delme = set()
    def unify_r(a, b):
        ua, ub = bind.get(a, a), bind.get(b, b)
        if ua is ub: return
        if ua.isTypeVariable() and a is ua:
            bind[ua] = ub
            return
        bind[ub] = ua
        if ub.isTypeVariable() and b is ub:
            return
        assert(not(a.isTypeVariable() or b.isTypeVariable()))
        delme.add(ub)
        for x, y in zip(ua.parms, ub.parms):
            unify_r(x, y)
    unify_r(a, b)
    for k in delme:
        del bind[k]
        
def unify_hack(a, b, bind):
    F = TypeConstructor(len(bind) + 1)
    return unify(F(a, *bind.keys()), F(b, *bind.values()))
    
def unify_inplace(a, b, bind):
    u = unify_hack(a, b, bind)
    dpr('bind', bind)
    dpr('u', u)
    # for k, v in u.items():
        # if k.isTypeVariable() and k not in bind:
            # while v.isTypeVariable() and v in u:
                # v = u[v]
            # dpr(k,v)
            # bind[k] = v
    bind.clear()
    for k, v in u.items():
        if k.isTypeVariable():
            while v.isTypeVariable() and v in u:
                v = u[v]
            bind[k] = v
def unify_inplace(a, b, bind0):
    bind1 = {}
    bind = ChainMap(bind1, bind0)
    def do_bind(x, y):
        for k, v in list(bind.items()):
            if v == x:
                bind1[k] = y
        bind1[x] = y
    def unify_r(a, b):
        ua, ub = bind[a], bind[b]
        if ua is ub:
            return
        if ua.isTypeVariable():
            do_bind(ua, ub)
        elif ub.isTypeVariable():
            do_bind(ub, ua)
        elif type(ua) != type(ub) or ua.nParms != ub.nParms:
            raise TypesNotUnifiable()
        else:
            if any(k.isTypeVariable() and bind[k] == ua for k in bind.keys()):
                do_bind(ua, ub)
            else:
                do_bind(ub, ua)
            for x, y in zip(ua.parms, ub.parms):
                unify_r(x, y)
    for k, v in bind1.items():
        if k.isTypeVariable():
            bind0[k] = v
def unify_inplace(a, b, bind):
    tu = TypeUnion()
    tu.import_dict(bind)
    def unify_(a, b):
        ua, ub = tu[a], tu[b]
        if ua is ub:
            return
        tu.join(ua, ub)
        if ua.isTypeVariable() or ub.isTypeVariable():
            return
        if type(ua) != type(ub) or ua.nParms != ub.nParms:
            raise TypesNotUnifiable()
        for x, y in zip(ua.parms, ub.parms):
            unify_(x, y)
    unify_(a, b)
    for t in tu:
        dpr(t, tu[t])
        if t.isTypeVariable():
            bind[t] = tu[t]
            
            
def unifyN(*a):
    b = {}
    for t in a[1:]:
        b = unify(a[0], t, b)
    return b
    
def unifiable(a, b):
    try: unify(a, b)
    except TypesNotUnifiable: return False
    else: return True
    
    
def test():
    a, b, c, d = VarType(), VarType(), VarType(), VarType()
    for tl in (
                (Arrow(a, MLint()), Arrow(List(b), b)),
                (Arrow(a, List(c)), Arrow(b, a)),
                (a, Product(b, a)),
                (Sum(a, Unit()), b, Sum(Product(c, b), d)),
                (a, Arrow(b, Arrow(c, a))), 
            ):
        print(' U '.join(map(str, tl)))
        for k,v in unifyN(*tl).items():
            if k.isTypeVariable():
                print(k, '-->', v)
        print()
    
#test()

from copy import copy
def duplicate(t, subst): # replace free vars with new ones
    typeDbgStr0(t)
    r = {}
    def d(t):
        t = subst[t]
        if t in r:
            return r[t]
        if t.isTypeVariable():
            v = VarType()
            r[t] = v
            return v
        t2 = copy(t)
        r[t] = t2
        t2.parms = list(map(d, t2.parms))
        return t2
    typeDbgStr0(d(t))
    return d(t)
    
def duplicate(t, subst, nongeneric=set()):
    tv = {}
    def d(t):
        if t.isTypeVariable():
            if t in nongeneric:
                return t
            if t not in tv:
                tv[t] = VarType()
                if subst[t] != t:
                    subst[tv[t]] = d(subst[t])
            return tv[t]
        t2 = copy(t)
        t2.parms = list(map(d, t2.parms))
        return t2
    return d(t)


def canonicalStr(t, subst):
    numbering = {}
    def cstr(t):
        t = subst[t]
        for u in numbering:
            if equivalent(t, u, subst):
                return numbering[u]
        numbering[t] = "'" + str(len(numbering))
        if t.isTypeVariable():
            return numbering[t]
        name = numbering[t] + type(t).__name__
        if t.nParms > 0:
            name += '(' + ', '.join(map(cstr, t.parms)) + ')'
        return name
    return cstr(t)