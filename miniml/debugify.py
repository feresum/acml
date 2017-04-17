def debugify(p):
    post = []
    out = ['declare i32 @puts([99 x i8]*)']
    for line in p.split('\n'):
        if line.startswith('\t') and not line.startswith('\t;') \
                                 and not line.endswith(':') \
                                 and not 'phi' in line:
            lnum = len(out) + 2
            const = '@debugmessage.%d' % lnum
            post.append('%s = constant [99 x i8] c"%s"' % (const, 
                '%-101s' % (r'Line %d\00' % lnum)))
            out.append('call i32 @puts([99 x i8]* %s)' % const)
        out.append(line)
    return '\n'.join(out + post)

import sys
with open(sys.argv[1], 'r+') as f:
    p = f.read()
    q = debugify(p)
    f.seek(0)
    f.write(q)