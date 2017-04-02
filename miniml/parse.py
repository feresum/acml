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
        pname = self.tl.pop().name
        var = LambdaVar()
        self.lambdaTypes.add(var.type)
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
        return ret
        
    def let_f(self):
        pname = self.tl.pop().name
        assert(self.tl.pop() == '=')
        boundExpr = self.expr()
        var = LetVar(boundExpr.type)
        assert(self.tl.pop() == 'in')
        self.bind(pname, var)
        x = self.expr()
        self.unbind(pname)
        return LetBinding(var, boundExpr, x)
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
        return Product(x, y)#self.product())

    def application(self):
        x = self.paren()
        while True:
            try:
                x2 = self.paren()
                dpr('arg', types.canonicalStr(x2.type, self.subst))
                x = Application(x, x2)
                dpr('before', types.typeDbgStr(x.function.type, self.subst))
                dpr('befor2', types.canonicalStr(x.function.type, self.subst))
                self.unify(x.function.type, types.Arrow(x.argument.type, x.type))
                dpr('after', types.typeDbgStr(x.function.type, self.subst))
            except ParseException:
                return x
                
    def paren(self):
        if self.tl[-1] == '(':
            self.tl.pop()
            x = self.expr()
            assert(self.tl.pop() == ')')
            return x
        return self.single()
        
    def single(self):
        if self.tl[-1] == 'true':
            self.tl.pop()
            return IntegralLiteral(types.Bool, 1)
        if self.tl[-1] == 'false':
            self.tl.pop()
            return IntegralLiteral(types.Bool, 0)
        if self.tl[-1] == '_builtin':
            self.tl.pop()
            assert(self.tl.pop() == '(')
            name = self.tl.pop().name
            assert(self.tl.pop() == ')')
            return NativeFunction(name, builtins.signature[name])
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
            var.instantiatedTypes.add(ref.type)
            return ref
        else:
            return LambdaBindingRef(var)
    

def test():
    xx = """fun x -> fun x -> x
            let f = ( fun x -> x ) in f
            let f = ( fun x -> x ) in if if f then f else f then f else f
            if ( fun x -> x ) then ( fun y -> y ) """
    for l in xx.split('\n'):
        print(parse(l))