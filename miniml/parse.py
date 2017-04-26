from mlast import *
import tokens, mltypes as types, mlbuiltins as builtins


class ParseException(Exception): pass


def parse(code, cx):
    toks = [tokens.tok(t) for t in tokens.tokenize(code)] + [None]
    p = Parser(toks, cx.s)
    tree = p.expr()
    if p.tl[:1] != [None]:
        raise ParseException()
    if len(p.tl) > 1:
        cx.warn('not all tokens used')
    return tree

class Parser:
    def __init__(self, tokens, subst):
        self.tl = tokens[::-1]
        self.bindings = {}
        self.subst = subst
        self.lambdaTypes = set()

    def bind(self, name, var):
        self.bindings.setdefault(name, []).append(var)
        
    def unbind(self, name):
        self.bindings[name].pop()
        
    def unify(self, ta, tb):
        types.unify_inplace(ta, tb, self.subst)
        
    def expr(self):
        t = self.tl.pop()
        if t == 'fun':
            return self.fun_f()
        if t == 'let':
            return self.let_f()
        self.tl.append(t)
        return self.sequence()

    def fun_f(self):
        argtoken = self.tl.pop()
        var = LambdaVar()
        if argtoken == '(':
            assert(self.tl.pop() == ')')
            pname = '()'
            self.unify(var.type, types.Unit())
        else:
            pname = argtoken.name
        
        self.lambdaTypes.add(var.type)
        # I have no idea what I'm doing
        #ngExtra = {v for v in types.freeVariables(var.type, self.subst) if v not in self.lambdaTypes}
        #self.lambdaTypes |= ngExtra
        attrs = set()
        while self.tl[-1].startswith('@'):
            attrs.add(self.tl.pop()[1:])
        assert(self.tl.pop() == '->')
        self.bind(pname, var)
        x = self.expr()
        self.unbind(pname)
        ret = Lambda(var, x)
        ret.attrs = attrs
        self.lambdaTypes.remove(var.type)
        #self.lambdaTypes -= ngExtra
        return ret
        
    def let_f(self):
        pname = self.tl.pop().name
        assert(self.tl.pop() == '=')
        boundExpr = self.expr()
        var = LetVar(boundExpr)
        assert(self.tl.pop() == 'in')
        self.bind(pname, var)
        x = self.expr()
        self.unbind(pname)
        lb = LetBinding(var, boundExpr, x)
        lb.letName = pname
        return lb
    def sequence(self):
        x = self.ifthen()
        while self.tl[-1] == ';':
            self.unify(x.type, types.Unit())
            self.tl.pop()
            x = Sequence(x, self.ifthen())
        return x
    
    def ifthen(self):
        if self.tl[-1] != 'if':
            return self.product()
        self.tl.pop()
        cond = self.ifthen()
        self.unify(cond.type, types.Bool)
        assert(self.tl.pop() == 'then')
        xTrue = self.ifthen()
        if self.tl[-1] == 'else':
            self.tl.pop()
            xFalse = self.ifthen()
            ret = If3(cond, xTrue, xFalse)
            self.unify(xTrue.type, xFalse.type)
        else:
            ret = If2(cond, xTrue)
            self.unify(xTrue.type, types.Unit())
        return ret

    def product(self):
        x = self.application()
        if self.tl[-1] != ',':
            return x
        self.tl.pop()
        y = self.product()
        dpr(x, y)
        return Product(x, y)

    def application(self):
        x = self.paren()
        while True:
            try:
                x2 = self.paren()
                x = Application(x, x2)
                self.unify(x.function.type, types.Arrow(x.argument.type, x.type))
            except ParseException:
                return x
                
    def paren(self):
        if self.tl[-1] == '(':
            self.tl.pop()
            if self.tl[-1] == ')':
                self.tl.pop()
                return UnitLiteral()
            x = self.expr()
            assert(self.tl.pop() == ')')
            return x
        elif self.tl[-1] in ('<', '>'):
            i = '<>'.find(self.tl.pop())
            x = self.expr()
            assert(self.tl.pop() == '|')
            return SumConstructor(i, x)
        elif self.tl[-1] == 'switch':
            self.tl.pop()
            return self.switch_f()
        elif self.tl[-1] == '_fst':
            self.tl.pop()
            return self.productElement(0)
        elif self.tl[-1] == '_snd':
            self.tl.pop()
            return self.productElement(1)
        
        return self.single()
        
    def productElement(self, side):
        assert(self.tl.pop() == '(')
        x = self.expr()
        assert(self.tl.pop() == ')')
        prod = types.Product(VarType(), VarType())
        self.unify(prod, x.type)
        return ProductProjection(x, side, prod.parms[side])
        
    def switch_f(self):
        assert(self.tl.pop() == '(')
        sumExpr = self.expr()
        assert(self.tl.pop() == ':')
        sumType = types.Sum(types.VarType(), types.VarType())
        self.unify(sumType, sumExpr.type)
        temp = LambdaVar()
        self.lambdaTypes.add(temp.type)
        tempRef = lambda: LambdaBindingRef(temp)
        def case(i):
            f = self.fun_f()
            a = Application(f, SumProjection(tempRef(), i, sumType.parms[i]))
            self.unify(a.function.type, types.Arrow(a.argument.type, a.type))
            return a
        left = case(0)
        assert(self.tl.pop() == '|')
        right = case(1)
        assert(self.tl.pop() == ')')
        self.unify(left.type, right.type)
        out = Application(Lambda(temp, If3(SumSide(tempRef()), right, left)), sumExpr)
        self.unify(out.function.type, types.Arrow(out.argument.type, out.type))
        self.lambdaTypes.remove(temp.type)
        return out
        
    def single(self):
        if self.tl[-1] == 'true':
            self.tl.pop()
            return IntegralLiteral(types.Bool, 1)
        if self.tl[-1] == 'false':
            self.tl.pop()
            return IntegralLiteral(types.Bool, 0)
        if type(self.tl[-1]) is str and self.tl[-1][0] == "'":
            return IntegralLiteral(types.Char, ord(self.tl.pop()[1]))
        if self.tl[-1] == '_builtin':
            self.tl.pop()
            assert(self.tl.pop() == '(')
            name = self.tl.pop().name
            assert(self.tl.pop() == ')')
            return NativeFunction(name, builtins.signature[name])
        if self.tl[-1] == '_error':
            self.tl.pop()
            return ErrorExpr()
        try:
            if type(self.tl[-1]) is str and self.tl[-1].isdigit():
                num = int(self.tl.pop(), 10)
                return IntegralLiteral(types.Int, num)
            name = self.tl[-1].name
        except:
            raise ParseException()
        self.tl.pop()
        var = self.bindings[name][-1]
        if isinstance(var, LetVar):
            ref = LetBindingRef(var, self.subst, self.lambdaTypes)
            ref.letName = name
            return ref
        else:
            return LambdaBindingRef(var)
