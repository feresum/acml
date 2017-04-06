import parse, llvm_util, mltypes as t, ltypes as lt
import pdb, bdb
from llvm_instructions import versionSyntaxReplace


def shouldFailTypeCheck(code):
    cx = llvm_util.CompileContext(64)
    try:
        parse.parse(code, cx)
    except t.TypesNotUnifiable:
        return
    assert False
    
def shouldCompile(code):
    cx = llvm_util.CompileContext(64)
    cx.compile(parse.parse(code, cx))
    
def shouldWork():
    sftc = shouldFailTypeCheck
    sc = shouldCompile
    sc('5, true, false, _builtin(char)')
    sc('<3|')
    sc('>fun x->x|')
    sc('switch(<3| : l -> 9 | r -> 5)')
    sc('if true then 1 else 2')
    sftc('if true then 1 else true')
    sftc('if 1 then 1 else 1')
    sc('let id = fun x->x in (id 3, id true)')
    sftc('(fun id -> (id 3, id true) ) (fun x -> x)')
    sc('let id = (fun x->x) (fun x->x) in (id 3, id true)')
    sftc('fun f -> let g = fun x -> f x in (g 3, g true)')
    #pdb.set_trace()
    sc(''' ( fun f ->
            let r = (fun rr -> fun lol ->
                rr rr (f (_builtin(char) 99) )
            ) in r  r 1234
        )  _builtin(ml_putchar)''')
    sc(''' ( fun f ->
            let r = (fun rr -> fun lol ->
                rr  rr (f (_builtin(char) 99) )
            ) in r  r 1234
        )  _builtin(ml_putchar)''')
    
    
    
try: shouldWork()
except: pdb.post_mortem()


cx = llvm_util.CompileContext(64)

lib = open('stdlib.miniml').read()
p = input()

try:
    ast = parse.parse(lib + p, cx)
    code = cx.compile(ast)
    code = versionSyntaxReplace((3, 6, 2), code)
    print(code)
except:
    pdb.post_mortem()
