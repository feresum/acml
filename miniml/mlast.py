import mltypes as types
from mltypes import VarType
import llvm_util as lu
from dbg import *

class Expr:
    def __init__(self):
        assert(False)
    def children(self):
        return []
    def reduce(self, f): # f(node, [reduced children])
        rc = [c.reduce(f) for c in self.children()]
        return f(self, rc)
    def dump(self, level = 0):
        print('  ' * level + type(self).__name__)
        for c in self.children():
            c.dump(level + 1)

class Var: pass

class LambdaVar(Var):
    def __init__(self):
        self.type = VarType()

class LetVar(Var):
    def __init__(self, type):
        self.type = type
        self.instantiatedTypes = set()

class Lambda(Expr):
    def __init__(self, var, expr):
        self.var = var
        self.expr = expr
        self.type = types.Arrow(var.type, expr.type)
    def children(self):
        return [self.expr]
    def closedVars(self):
        return self.reduce(lambda n, rc: [(n.key(), n.type)] if isinstance(n, BindingRef) else sum(rc, []))
    def compile(self, cx, out):
        name = cx.lamb()
        cv = [(k,t) for (k,t) in self.closedVars() if k in cx.bindings]
        cx.bindings[self.var] = ['%arg']
        retLtype = self.type.result().llvm(cx)
        fdef = 'define %s %s(%%voidptr %%cl0, %s %%arg)\n{' % (retLtype, name,
            self.type.argument().llvm(cx))
        
        
        if cv:
            clTypes = list(zip(*cv))[1]
            clType = lu.closureType(clTypes, cx)
            dpr('clty',clTypes,clType)
            loadClosure = ['%%clPtr = bitcast %%voidptr %%cl0 to %s*' % clType,
                           '%%cl = load %s* %%clPtr' % clType]
            clTypedPtr, clPtr = cx.local(), cx.local() 
            storeClosure = []
            builder = 'undef'
            for i, (key, typ) in enumerate(cv):
                reg = cx.local()
                loadClosure.append('%s = extractvalue %s %%cl, %d' % (reg, clType, i))
                storeClosure.append('%s = insertvalue %s %s, %s %s, %d' % (
                    reg, clType, builder, typ.llvm(cx), cx.bindings[key][-1], i))
                cx.bindings[key].append(reg)
                builder = reg
            storeClosure += lu.heapCreate(clType, builder, cx, clTypedPtr)
            storeClosure += ['%s = bitcast %s* %s to %%voidptr' % (clPtr, clType, clTypedPtr)]
            
        else:
            loadClosure = storeClosure = []
            clPtr = 'null'
        fout = cx.local()
        for line in loadClosure + self.expr.compile(cx, fout):
            fdef += '\n\t' + line
        fdef += '\n\tret %s %s\n}\n' % (retLtype, fout)
        cx.lambdaDefinitions.append(fdef)
        del cx.bindings[self.var]
        for key, _ in cv:
            cx.bindings[key].pop()
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
        code = []
        for t in self.var.instantiatedTypes:
            dpr('idt', id(t), t, types.typeDbgStr(t, cx.s), types.canonicalStr(t, cx.s))
            valueReg = cx.local()
            cx.bindings[t] = [valueReg]
            cx.s = cx.s.new_child()
            types.unify_inplace(t, self.var.type, cx.s)
            code += self.value.compile(cx, valueReg)
            # lt = t.llvm(cx)
            # t.llvm = lambda _: lt # lol
            cx.s = cx.s.parents
        ret = code + self.expr.compile(cx, out)
        for t in self.var.instantiatedTypes:
            del cx.bindings[t]
        return ret

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
        return lu.dup(cx.bindings[self.key()][-1], out, self.type.llvm(cx), cx)
class LetBindingRef(BindingRef):
    def __init__(self, var, subst, nongeneric):
        self.var = var
        self.type = types.duplicate(var.type, subst, nongeneric)
    def key(self):
        return self.type



class LambdaBindingRef(BindingRef):
    def __init__(self, var):
        self.var = var
        self.type = var.type
    def key(self):
        return self.var



class Application(Expr):
    def __init__(self, func, arg):
        self.function = func
        self.argument = arg
        self.type = VarType()
    def children(self):
        return [self.function, self.argument]
    def compile(self, cx, out):
        funcVar, argVar = cx.local(), cx.local()
        funcCode = self.function.compile(cx, funcVar)
        argCode = self.argument.compile(cx, argVar)
        ftype = self.function.type
        fpp, dpp, fp, dp = cx.local(), cx.local(), cx.local(), cx.local()
        fpt = lu.funcPtrType(self.function.type)
        return funcCode + argCode + [
            fpp + ' = ' + lu.functionFuncPtrPtr(funcVar, ftype),
            '%s = load %s* %s' % (fp, fpt, fpp),
            dpp + ' = ' + lu.functionDataPtrPtr(funcVar, ftype),
            '%s = load %s* %s' % (dp, '%voidptr', dpp),
            '%s = call %s %s(%s %s, %s %s)' % (out, ftype.result().llvm(), fp, '%voidptr', dp, ftype.argument().llvm(), argVar)]
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
