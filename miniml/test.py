
import parse, llvm_util, mltypes as t, ltypes as lt

# a1=t.VarType()
# class U(t.TypeConstructor(1)): pass
# s = {a1: U(a1)}
# s=llvm_util.key_defaultdict(s)

# t.canonicalStr(a1, s)


cx = llvm_util.CompileContext(64)


a,b,c,d=[t.VarType()for _ in 'hhhh']
# s=llvm_util.key_defaultdict()
# s=dict()
# s[a]=t.Arrow(a,b)
# s[c]=t.Arrow(c,d)
# #t.unify(a,c,s)


class F(t.TypeConstructor(3)): pass
class G(t.TypeConstructor(2)): pass

x = F(G(c, d), a, c)
y = F(G(a, b), G(a, b), G(c, d))
t.unify(x, y)



id1 = t.Arrow(a, a)
id2 = t.Arrow(b, b)
s = llvm_util.key_defaultdict()
s[b] = id1

#print(t.canonicalStr(id2, s))

print(cx.compile(parse.parse(input(), cx)))

