import mltypes as types
from mltypes import VarType
import llvm_util as lu
import llvm_instructions as inst
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
        cx.funDepth += 1
        name = cx.lamb()
        arg = cx.local()
        retLtype = self.type.result().llvm(cx)
        fsig = '%s %s(%%voidptr %%cl0, %s %s)' % (retLtype, name, self.type.argument().llvm(cx), arg)
        fout = cx.local()
        
        k = (self.var, str(self.var.type.llvm(cx)))
        cx.bindings[k] = (arg, self.var.type.llvm(cx))
        cx.defLocal(self.var)
        exprCode = self.expr.compile(cx, fout)
        # cx.delLocal(self.var)
        # cx.funDepth -= 1
        # cv = []
        # for (var, sltype), (reg, ltype) in cx.bindings.items():
            # assert type(ltype)!=str
            # if var in cx.varDefDepth and cx.varRefDepth[var] > cx.varDefDepth[var]:
                # cx.varRefDepth[var] = cx.funDepth
                # cv.append((var, ltype))
        del cx.bindings[k]
        cv0 = set(self.closedVars())
        cv = [(var, ltype) for (var, sltype), (reg, ltype) in cx.bindings.items() if var in cv0]
        if cv:
            clTypes = list(zip(*cv))[1]
            clType = lu.closureType(clTypes, cx)
            loadClosure = ['%%clPtr = bitcast %%voidptr %%cl0 to %s*' % clType,
                           inst.load(clType, '%clPtr', '%cl')]
            clTypedPtr, clPtr = cx.local(), cx.local() 
            storeClosure = []
            builder = 'undef'
            copiedRegs = set()
            for i, (var, ltype) in enumerate(cv):
                reg = cx.local()
                rBound, _ = cx.bindings[(var, str(ltype))]
                if rBound in copiedRegs: continue
                copiedRegs.add(rBound)
                loadClosure.append('%s = extractvalue %s %%cl, %d' % (rBound, clType, i))
                storeClosure.append('%s = insertvalue %s %s, %s %s, %d' % (
                    reg, clType, builder, ltype, rBound, i))
                builder = reg
            storeClosure += lu.heapCreate(clType, builder, cx, clTypedPtr)
            storeClosure += ['%s = bitcast %s* %s to %%voidptr' % (clPtr, clType, clTypedPtr)]
            
        else:
            loadClosure = storeClosure = []
            clPtr = 'null'
        
        
        fbody = loadClosure + exprCode + [inst.ret(retLtype, fout)]
        cx.lambdaDefinitions.append(lu.formatFunctionDef(fsig, fbody, cx.llvmVersion))
        
        return storeClosure + lu.makeFuncObj(name, self.type, clPtr, cx, out)
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
        # for t in self.var.instantiatedTypes:
            # cx.bindings[t] = [cx.local()]
        self.var.instantiationCode = []
        self.var.instantiationKeys = []
        cx.defLocal(self.var)
        exprCode = self.expr.compile(cx, out)
        instantiationsCode = self.var.instantiationCode
        del self.var.instantiationCode
        for key in self.var.instantiationKeys:
            del cx.bindings[key]
        del self.var.instantiationKeys
        cx.delLocal(self.var)
        return instantiationsCode + exprCode

class Sequence(Expr):
    def __init__(self, x0, x1):
        self.x0 = x0
        self.x1 = x1
        self.type = x1.type
    def children(self):
        return [self.x0, self.x1]
        
class If2(Expr):
    def __init__(self, cond, expr):
        self.cond = cond
        self.expr = expr
        self.type = types.Unit()
    def children(self):
        return [self.cond, self.expr]
        
class If3(Expr):
    def __init__(self, cond, trueExpr, falseExpr):
        self.cond = cond
        self.trueExpr = trueExpr
        self.falseExpr = falseExpr
        self.type = trueExpr.type
    def children(self):
        return [self.cond, self.trueExpr, self.falseExpr]
    def compile(self, cx, out):
        trueBlock, falseBlock, endBlock = cx.label(), cx.label(), cx.label()
        condReg, trueReg, falseReg = cx.local(), cx.local(), cx.local()
        condCode = self.cond.compile(cx, condReg)
        trueCode = self.trueExpr.compile(cx, trueReg)
        falseCode = self.falseExpr.compile(cx, falseReg)
        jumpEnd = 'br label %' + endBlock
        return condCode + \
            ['br i1 %s, label %%%s, label %%%s' % (condReg, trueBlock, falseBlock),
             trueBlock + ':'] + trueCode + [jumpEnd, falseBlock + ':'] + \
            falseCode + [jumpEnd, endBlock + ':', '%s = phi %s [%s, %%%s], [%s, %%%s]' % 
                (out, self.type.llvm(cx), trueReg, trueBlock, falseReg, falseBlock)]
                
class BindingRef(Expr):
    def compile(self, cx, out):
        reg, ltype = cx.bindings[self.key(cx)]
        cx.useLocal(self.var)
        return lu.dup(reg, out, ltype, cx)
    def key(self, cx):
        return (self.var, str(self.type.llvm(cx)))
class LetBindingRef(BindingRef):
    def __init__(self, var, subst, nongeneric):
        self.var = var
        self.type = types.duplicate(var.type, subst, nongeneric)
        #var.instantiatedTypes.add(self.type)

    def compile(self, cx, out):
        lt = self.type.llvm(cx)
        k = (self.var, str(lt))
        if k in cx.bindings:
            return super().compile(cx, out)
        cx.useLocal(self.var)
        cx.bindings[k] = (out, lt)
        cx.s = cx.s.new_child()
        types.unify_inplace(self.type, self.var.type, cx.s)
        code = self.var.boundExpr.compile(cx, out)
        cx.s = cx.s.parents
        self.var.instantiationKeys.append(k)
        #dpr('adding %d to %d' % (id(self.key()), id(self.var)))
        self.var.instantiationCode += code
        return []


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
                fptr, '%voidptr', cl, ftype.argument().llvm(cx), argReg)]

class NativeFunction(Expr):
    def __init__(self, name, type):
        self.name = name
        self.type = type
    def compile(self, cx):
        cx.useBuiltin(self.name)
        out = cx.local()
        fpp, dpp = cx.local(), cx.local()
        fpt = lu.funcPtrType(self.type)
        return ['%s = alloca %s' % (out, self.type.llvm()),
                 fpp + ' = ' + lu.functionFuncPtrPtr(out, self.type),
                 'store %s @%s, %s* %s' % (fpt, self.name, fpt, fpp),
                 dpp + ' = ' + lu.functionDataPtrPtr(out, self.type),
                 'store %s null, %s* %s' % (lu.voidptr, lu.voidptr, dpp)]
    def compile(self, cx, out):
        cx.useBuiltin(self.name)
        ltype = self.type.llvm()
        fpt = lu.funcPtrType(self.type)
        return ['%s = alloca %s' % (out, ltype)] + \
            lu.storeField(out, ltype, 0, fpt, cx, '@' + self.name) + \
            lu.storeField(out, ltype, 1, '%voidptr', cx, 'null')
    def compile(self, cx, out):
        cx.useBuiltin(self.name)
        return lu.makeFuncObj('@' + self.name, self.type, 'null', cx, out)

class IntegralLiteral(Expr):
    def __init__(self, type, value):
        self.value = value
        self.type = type
    def compile(self, cx, out):
        return ['%s = add %s 0, %d' % (out, self.type.llvm(cx), self.value)]

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

class SumConstructor(Expr):
    def __init__(self, side, expr):
        self.side = side
        self.expr = expr
        self.type = types.Sum(*(expr.type, VarType())[::(-1)**side])
    def children(self):
        return [self.expr]
    def compile(self, cx, out):
        expr, tagged, ptr = cx.local(), cx.local(), cx.local()
        sideType = lu.sumSideType(self.type, self.side, cx)
        return self.expr.compile(cx, expr) + \
            lu.formAggregate(sideType, cx, tagged, self.side, expr) \
             + lu.heapCreate(sideType, tagged, cx, ptr) + [
            inst.bitcast('%s*' % sideType, self.type.llvm(cx), ptr, out)]
            
        
class SumProjection(Expr):
    def __init__(self, sumExpr, side, type):
        self.type = type
        self.expr = sumExpr
    def children(self):
        return [self.expr]
    def compile(self, cx, out):
        psum, pside = cx.local(), cx.local()
        tp = self.type.llvm(cx)
        return self.expr.compile(cx, psum) + [
            inst.bitcast('i1*', '%s*' % tp, psum, pside),
            inst.load(tp, pside, out)]
            
class SumSide(Expr):
    def __init__(self, sumExpr):
        self.type = types.Bool
        self.expr = sumExpr
    def children(self):
        return [self.expr]
    def compile(self, cx, out):
        sum = cx.local()
        return self.expr.compile(cx, sum) + [inst.load('i1', sum, out)]
        
class UnitLiteral(Expr):
    def __init__(self):
        self.type = types.Unit()
    def compile(self, cx, out):
        return lu.dup('undef', out, '%Unit', cx)
        
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
            inst.extractvalue(self.expr.type.llvm(cx), x, self.side, out)]
            
class ErrorExpr(Expr):
    def __init__(self):
        self.type = VarType()
    def compile(self, cx, out):
        return lu.dup('undef', out, self.type.llvm(cx), cx)