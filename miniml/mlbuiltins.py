import mltypes as types
import llvm_instructions as inst
import llvm_util as lu

signature = {}
definition = {}

def reg(name, type, code):
    signature[name] = type
    definition[name] = code.strip().replace('UNIT_VALUE', '%Unit undef') + '\n'

reg('char', types.Arrow(types.Int, types.Char), '''
define %Char @char(%voidptr, %Int %code)
{
    %c = trunc %Int %code to %Char
    ret %Char %c
}
''')

reg('char_to_int', types.Arrow(types.Char, types.Int), '''
define %Int @char_to_int(%voidptr, %Char %ch)
{
    %i = zext %Char %ch to %Int
    ret %Int %i
}
''')

reg('ml_putchar', types.Arrow(types.Char, types.Unit()), '''
declare i32 @putchar(i32)
define %Unit @ml_putchar(%voidptr, %Char %c)
{
    %int_c = zext %Char %c to i32
    call i32 @putchar(i32 %int_c)
    ret UNIT_VALUE
}
''')

reg('ml_getchar', types.Arrow(types.Unit(), types.Int), '''
declare i32 @getchar()
define %Int @ml_getchar(%voidptr, %Unit)
{
    %c32 = call i32 @getchar()
    %c64 = sext i32 %c32 to %Int
    ret %Int %c64
}
''')

reg('integer_negate', types.Arrow(types.Int, types.Int),
    lu.formatFunctionDef('%Int @integer_negate(%voidptr, %Int %n)',
        [inst.sub_nsw('%Int', 0, '%n', '%result'),
         inst.ret('%Int', '%result')], 0))

reg('~malloc', None, 'declare %voidptr @malloc(%size_t)')
reg('~free', None, 'declare void @free(%voidptr)')

def regBinaryIntOp(name, instr, type):
    ltype = type.llvm(None)
    mIntpair = types.Product(types.Int, types.Int)
    intpair = mIntpair.llvm(None)
    sig = '%s @%s(%%voidptr, %s %%args)' % (ltype, name, intpair)
    lines = [inst.extractvalue(intpair, '%args', 0, '%x'),
             inst.extractvalue(intpair, '%args', 1, '%y'),
             '%%result = %s %%Int %%x, %%y' % instr,
             inst.ret(ltype, '%result')]
    reg(name, types.Arrow(mIntpair, type), lu.formatFunctionDef(sig, lines, 0))
    
regBinaryIntOp('integer_add', 'add nsw', types.Int)
regBinaryIntOp('integer_less', 'icmp slt', types.Bool)
regBinaryIntOp('integer_equal', 'icmp eq', types.Bool)
regBinaryIntOp('integer_divide', 'sdiv', types.Int)
regBinaryIntOp('integer_remainder', 'srem', types.Int)
regBinaryIntOp('integer_multiply', 'mul nsw', types.Int)