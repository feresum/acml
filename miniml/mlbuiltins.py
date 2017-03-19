import mltypes as types

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

reg('mlputchar', types.Arrow(types.Char, types.Unit()), '''
declare i32 @putchar(i32)
define %Unit @mlputchar(%voidptr, %Char %c)
{
    %int_c = zext %Char %c to i32
    call i32 @putchar(i32 %int_c)
    ret UNIT_VALUE
}
''')

reg('~malloc', None, 'declare %voidptr @malloc(%size_t)')