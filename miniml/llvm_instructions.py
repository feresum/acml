import re

def bitcast(fro, to, value, out):
    return '%s = bitcast %s %s to %s' % (out, fro, value, to)
def extractvalue(type, value, ind, out):
    return '%s = extractvalue %s %s, %d' % (out, type, value, ind)
def ret(type=None, value=None):
    if None is type:
        return 'ret void'
    return 'ret %s %s' % (type, value)
def insertvalue(tOuter, outer, tInner, inner, out, *inds):
    a = '%s = insertvalue %s %s, %s %s' % (out, tOuter, outer, tInner, inner)
    for i in inds:
        a += ', %d' % i
    return a
def sub_nsw(type, x, y, out):
    return '%s = sub nsw %s %s, %s' % (out, type, x, y)
def load(type, ptr, out):
    return '%s = load %s* %s' % (out, type, ptr)
def store(type, value, addr):
    return 'store %s %s, %s* %s' % (type, value, type, addr)
    
    
def versionSyntaxReplace(ver, code):
    # versions are not accurate
    subs = (
        ((3, 9), r'load (.+)\*', r'load \1,\1*'),
    )
    for v, pattern, repl in subs:
        if ver >= v:
            code = re.sub(pattern, repl, code)
    return code
    
def branch(*a):
    if len(a) == 1:
        return 'br label ' + a[0]
    cond, trueLbl, falseLbl = a
    return 'br i1 %s, label %%%s, label%%%s' % (cond, trueLbl, falseLbl)
def label(name):
    return name + ':'
def phi(type, out, *valueLabelPairs):
    return '%s = phi %s ' % (out, type) + ', '.join('[ %s, %%%s ]' % vl for vl in valueLabelPairs)