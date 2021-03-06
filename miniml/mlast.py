import mltypes as types
from mltypes import VarType
import llvm_util as lu
import llvm_instructions as inst
import memory as mem
from dbg import *

class Expr:
    def __init__(self):
        assert(False)
    def children(self):
        return []
    def reduce(self, f): # f(node, [reduced children])
        rc = [c.reduce(f) for c in self.children()]
        return f(self, rc)
    def dump(self, subst = None, level = 0):
        dpr('  ' * level + type(self).__name__, end=' ')
        if subst:
            dpr(types.typeDbgStr2(self.type, subst))
        else:
            dpr()
        for c in self.children():
            c.dump(subst, level + 1)
    def markDepth(self, d):
        self.depth = d
        for c in self.children():
            c.markDepth(d + 1)
    def toCode(self, tcx):
        return '[toCode unimplemented]'

class Var: pass

class LambdaVar(Var):
    def __init__(self):
        self.type = VarType()

class LetVar(Var):
    def __init__(self, boundExpr):
        self.type = boundExpr.type
        self.boundExpr = boundExpr
        #self.instantiatedTypes = set()


class Lambda(Expr):
    def __init__(self, var, expr):
        self.var = var
        self.expr = expr
        self.type = types.Arrow(var.type, expr.type)
    def children(self):
        return [self.expr]
    def closedVars(self):
        return self.reduce(lambda n, rc: [n.var] if isinstance(n, BindingRef) else sum(rc, []))
    def compile(self, cx, out):
        name = cx.lamb()
        arg = cx.local()
        retLtype = self.type.result().llvm(cx)
        fsig = '%s %s(%%voidptr %%cl0, %s %s)' % (retLtype, name, self.type.argument().llvm(cx), arg)
        fout = cx.local()
        
        k = (self.var, cx.canonicalStr(self.var.type))
        cx.bindings[k] = (arg, self.var.type.llvm(cx))
        cx.bindings2[k] = (lu.reusable(mem.reference  (arg, self.var.type, cx), arg), 
                           lu.reusable(mem.unreference(arg, self.var.type, cx), arg))
        exprCode = self.expr.compile(cx, fout)
        del cx.bindings[k], cx.bindings2[k]
        cv0 = set(self.closedVars())
        cv = [(var, ltype, cstr, reg) for (var, cstr), (reg, ltype) in cx.bindings.items() if var in cv0]
        if cv:
            clTypes = list(zip(*cv))[1]
            clType = lu.closureType(clTypes, cx)
            loadClosure = ['%%clPtr = bitcast %%voidptr %%cl0 to %s*' % clType,
                           inst.load(clType, '%clPtr', '%cl')]
            clTypedPtr, clPtr = cx.local(), cx.local() 
            storeClosure = []
            builder = 'undef'
            copiedRegs = set()
            closureItems = []
            for i, (var, ltype, cstr, rBound) in enumerate(cv):
                reg = cx.local()
                if rBound in copiedRegs: continue
                copiedRegs.add(rBound)
                ref, unref = cx.bindings2[(var, cstr)]
                closureItems.append((ltype, unref, rBound))
                loadClosure.append(inst.extractvalue(clType, '%cl', i, rBound))
                storeClosure.append('%s = insertvalue %s %s, %s %s, %d' % (
                    reg, clType, builder, ltype, rBound, i))
                builder = reg
                storeClosure += ref(cx)
            destruc = cx.closureDestructor()
            storeClosure += mem.createClosure(clType, builder, destruc, cx, clTypedPtr)
            storeClosure += ['%s = bitcast %s* %s to %%voidptr' % (clPtr, clType, clTypedPtr)]
            
            cx.destructorDefinitions.append(mem.closureDestructorDefinition(destruc, clType, closureItems, cx))
            
        else:
            loadClosure = storeClosure = []
            clPtr = 'null'
        
        
        fbody = loadClosure + exprCode + [inst.ret(retLtype, fout)]
        cx.lambdaDefinitions.append(lu.formatFunctionDef(fsig, fbody, cx.llvmVersion))
        
        return storeClosure + lu.makeFuncObj(name, self.type, clPtr, cx, out)
    def toCode(self, tcx):
        arg = tcx.name()
        tcx.bind(self.var, arg)
        ret = 'fun %s -> (%s)' % (arg, self.expr.toCode(tcx))
        tcx.unbind(self.var)
        return ret

class LetBinding(Expr):
    def __init__(self, var, value, expr):
        self.var = var
        self.value = value
        self.expr = expr
        self.type = expr.type
    def children(self):
        return [self.value, self.expr]
    def compile(self, cx, out):
        # TODO - actually compile this correctly
        # current implementation will duplicate side effects
        # (and not do them at all if there are 0 instantiations!)
        self.var.instantiationCode = []
        self.var.instantiationKeys = []
        exprCode = self.expr.compile(cx, out)
        instantiationsCode = self.var.instantiationCode
        unrefCode = []
        del self.var.instantiationCode
        for key in self.var.instantiationKeys:
            unrefCode += cx.bindings2[key][1](cx)
            del cx.bindings[key], cx.bindings2[key]
        del self.var.instantiationKeys
        return instantiationsCode + exprCode + unrefCode
    def toCode(self, tcx):
        v = tcx.name()
        boundCode = self.value.toCode(tcx)
        tcx.bind(self.var, v)
        ret = 'let %s = (%s) in (%s)' % (v, boundCode, self.expr.toCode(tcx))
        tcx.unbind(self.var)
        return ret

class Sequence(Expr):
    def __init__(self, x0, x1):
        self.x0 = x0
        self.x1 = x1
        self.type = x1.type
    def children(self):
        return [self.x0, self.x1]
    def compile(self, cx, out):
        return self.x0.compile(cx, cx.local()) + self.x1.compile(cx, out)
    def toCode(self, tcx):
        return '(%s); (%s)' % (self.x0.toCode(tcx), self.x1.toCode(tcx))
        
class If2(Expr):
    def __init__(self, cond, expr):
        self.cond = cond
        self.expr = expr
        self.type = types.Unit()
    def children(self):
        return [self.cond, self.expr]
    def compile(self, cx, out):
        condReg = cx.local()
        return self.cond.compile(cx, condReg) + \
        lu.ifThen(condReg, self.expr.compile(cx, cx.local()), cx) + \
        lu.dup('undef', out, '%Unit', cx)
    def toCode(self, tcx):
        return 'if (%s) then (%s)' % (self.cond.toCode(tcx), self.expr.toCode(tcx))
        
class If3(Expr):
    def __init__(self, cond, trueExpr, falseExpr):
        self.cond = cond
        self.trueExpr = trueExpr
        self.falseExpr = falseExpr
        self.type = trueExpr.type
    def children(self):
        return [self.cond, self.trueExpr, self.falseExpr]
    def compile(self, cx, out):
        condReg, trueReg, falseReg = cx.local(), cx.local(), cx.local()
        return self.cond.compile(cx, condReg) + lu.conditionalValue(condReg, self.type.llvm(cx), 
            self.trueExpr.compile(cx, trueReg), trueReg, self.falseExpr.compile(cx, falseReg), 
            falseReg, cx, out)
    def toCode(self, tcx):
        return 'if (%s) then (%s) else (%s)' % (
            self.cond.toCode(tcx), self.trueExpr.toCode(tcx), self.falseExpr.toCode(tcx))

class BindingRef(Expr):
    def compile(self, cx, out):
        k = self.key(cx)
        reg, ltype = cx.bindings[k]
        ref, unref = cx.bindings2[k]
        return ref(cx) + lu.dup(reg, out, ltype, cx)
    def key(self, cx):
        return (self.var, cx.canonicalStr(self.type))
    def toCode(self, tcx):
        return tcx.nameOf(self.var)

class LetBindingRef(BindingRef):
    def __init__(self, var, subst, nongeneric):
        self.var = var
        self.type = types.duplicate_tu(var.type, subst, nongeneric)

    def compile(self, cx, out):
        lt = self.type.llvm(cx)
        k = (self.var, cx.canonicalStr(self.type))
        if k in cx.bindings:
            return super().compile(cx, out)
        cx.bindings[k] = (out, lt)
        ref = mem.reference(out, self.type, cx)
        cx.bindings2[k] = (lu.reusable(ref, out), lu.reusable(mem.unreference(out, self.type, cx), out))
        cx.pushTypeContext(self.type, self.var.type)
        code = self.var.boundExpr.compile(cx, out)
        cx.popTypeContext()
        self.var.instantiationKeys.append(k)
        self.var.instantiationCode += code
        if hasattr(self, 'letName'):
            self.var.instantiationCode.append('; let %s = %s' % (self.letName, out))
        return ref


class LambdaBindingRef(BindingRef):
    def __init__(self, var):
        self.var = var
        self.type = var.type




class Application(Expr):
    def __init__(self, func, arg):
        self.function = func
        self.argument = arg
        self.type = VarType()
    def children(self):
        return [self.function, self.argument]
    def compile(self, cx, out):
        funcReg, argReg = cx.local(), cx.local()
        funcCode = self.function.compile(cx, funcReg)
        argCode = self.argument.compile(cx, argReg)
        fptr, cl = cx.local(), cx.local()
        ftype = cx.s[self.function.type]
        return funcCode + argCode + \
            lu.funcObjFunction(funcReg, ftype, cx, fptr) + \
            lu.funcObjClosure(funcReg, ftype, cx, cl) + \
            ['%s = call %s %s(%s %s, %s %s)' % (out, ftype.result().llvm(cx), 
                fptr, '%voidptr', cl, ftype.argument().llvm(cx), argReg)] + \
            mem.unreference(funcReg, self.function.type, cx) + \
            mem.unreference(argReg, self.argument.type, cx)
    def toCode(self, tcx):
        return '(%s) (%s)' % (self.function.toCode(tcx), self.argument.toCode(tcx))

class NativeFunction(Expr):
    def __init__(self, name, type):
        self.name = name
        self.type = type
    def compile(self, cx, out):
        cx.useBuiltin(self.name)
        return lu.makeFuncObj('@' + self.name, self.type, 'null', cx, out)

class IntegralLiteral(Expr):
    def __init__(self, type, value):
        self.value = value
        self.type = type
    def compile(self, cx, out):
        return ['%s = add %s 0, %d' % (out, self.type.llvm(cx), self.value)]
    def toCode(self, tcx):
        return {types.Bool: 'true' if self.value else 'false',
                types.Char: "'%c'" % (self.value & 255),
                types.Int: '%d' % self.value}[self.type]

class Product(Expr):
    def __init__(self, fst, snd):
        self.fst = fst
        self.snd = snd
        self.type = types.Product(fst.type, snd.type)
    def children(self):
        return [self.fst, self.snd]
    def compile(self, cx, out):
        ltype = self.type.llvm(cx)
        fst, snd, r = cx.local(), cx.local(), cx.local()
        return self.fst.compile(cx, fst) + self.snd.compile(cx, snd) + [
            inst.insertvalue(ltype, 'undef', self.fst.type.llvm(cx), fst, r, 0),
            inst.insertvalue(ltype, r, self.snd.type.llvm(cx), snd, out, 1) + ';prod']
    def toCode(self, tcx):
        return '(%s), (%s)' % (self.fst.toCode(tcx), self.snd.toCode(tcx))

class SumConstructor(Expr):
    def __init__(self, side, expr):
        self.side = side
        self.expr = expr
        self.type = types.Sum(*(expr.type, VarType())[::(-1)**side])
    def children(self):
        return [self.expr]
    def compile(self, cx, out):
        expr, tagged, ptr = cx.local(), cx.local(), cx.local()
        sideType = lu.sumSideType(cx.s[self.type].parms[self.side].llvm(cx))
        return self.expr.compile(cx, expr) + \
            lu.formAggregate(sideType, cx, tagged, self.side, expr) \
             + lu.heapCreate(sideType, tagged, cx, ptr) + [
            inst.bitcast('%s*' % sideType, self.type.llvm(cx), ptr, out)]
    def toCode(self, tcx):
        return '<>'[self.side] + self.expr.toCode(tcx) + '|'

class RegisterRef(Expr):
    def __init__(self, reg, type):
        self.reg = reg
        self.type = type
    def compile(self, cx, out):
        return lu.dup(self.reg, out, self.type.llvm(cx), cx)

class Switch(Expr):
    def __init__(self, sumExpr, leftFun, rightFun):
        self.sumExpr = sumExpr
        self.leftFun = leftFun
        self.rightFun = rightFun
        self.type = leftFun.expr.type
    def children(self):
        return [self.sumExpr, self.leftFun, self.rightFun]
    def compile(self, cx, out):
        sum, sel = cx.local(), cx.local()
        sumref = lambda: RegisterRef(sum, self.sumExpr.type)
        def case(i, fn):
            a = Application(fn, SumProjection(sumref(), i, fn.var.type))
            a.type = self.type
            return a
        return self.sumExpr.compile(cx, sum) + lu.getSumTypeSelector(sum, cx, sel) + \
            If3(RegisterRef(sel, types.Bool), case(1, self.rightFun),
                case(0, self.leftFun)).compile(cx, out)
    def toCode(self, tcx):
        return 'switch(%s: %s | %s)' % (self.sumExpr.toCode(tcx),
            self.leftFun.toCode(tcx)[4:], self.rightFun.toCode(tcx)[4:])
        
class SumProjection(Expr):
    def __init__(self, sumExpr, side, type):
        self.type = type
        self.expr = sumExpr
        self.side = side
    def children(self):
        return [self.expr]
    def compile(self, cx, out):
        psum, pside, p = cx.local(), cx.local(), cx.local()
        tp = self.type.llvm(cx)
        sst = lu.sumSideType(tp)
        return self.expr.compile(cx, psum) + [
            inst.bitcast('i1*', '%s*' % sst, psum, pside),
            inst.structGEP(pside, sst, p, 1),
            inst.load(tp, p, out)] + mem.reference(out, self.type, cx) + \
            mem.unreference(psum, self.expr.type, cx)
            
class SumSide(Expr):
    def __init__(self, sumExpr):
        self.type = types.Bool
        self.expr = sumExpr
    def children(self):
        return [self.expr]
    def compile(self, cx, out):
        sum = cx.local()
        return self.expr.compile(cx, sum) + [inst.load('i1', sum, out)] \
            + mem.unreference(sum, self.expr.type, cx)
        
class UnitLiteral(Expr):
    def __init__(self):
        self.type = types.Unit()
    def compile(self, cx, out):
        return lu.dup('undef', out, '%Unit', cx)
    def toCode(self, tcx):
        return '()'
        
class ProductProjection(Expr):
    def __init__(self, productExpr, side, type):
        self.type = type
        self.expr = productExpr
        self.side = side
    def children(self):
        return [self.expr]
    def compile(self, cx, out):
        x = cx.local()
        return self.expr.compile(cx, x) + [
            inst.extractvalue(self.expr.type.llvm(cx), x, self.side, out)
            ] + mem.reference(out, self.type, cx) + mem.unreference(x, self.expr.type, cx)
            
class ErrorExpr(Expr):
    def __init__(self):
        self.type = VarType()
    def compile(self, cx, out):
        return lu.dup('undef', out, self.type.llvm(cx), cx)

class StringLiteral(Expr):
    def __init__(self, string, unify):
        self.type = VarType()
        unify(self.type, types.Sum(types.Product(types.Char, self.type), types.Unit()))
        for c in string:
            assert(ord(c) < 256)
        self.string = string
    def compile(self, cx, out):
        node = SumConstructor(1, UnitLiteral())
        node.type = self.type
        for c in self.string[::-1]:
            node = SumConstructor(0, Product(IntegralLiteral(types.Char, ord(c)), node))
            node.type = self.type
        return node.compile(cx, out)
    def toCode(self, tcx):
        return '"' + self.string.replace('"', '""') + '"'

class TextCodeContext:
    def __init__(self):
        self.n = 0
        self.bindings = {}
    def name(self):
        self.n += 1
        return 'v' + str(self.n)
    def bind(self, var, name):
        self.bindings[var] = name
    def unbind(self, var):
        del self.bindings[var]
    def nameOf(self, var):
        return self.bindings[var]

