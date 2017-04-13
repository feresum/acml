import re

class Instruction:
    def __init__(self, formats, *args):
        self.formats = formats
        self.args = args
    def string(self, version):
        if version==0: version=(0,)
        for ver, str in reversed(self.formats):
            if ver==0 or version >= ver:
                return str.format(*self.args)
        assert(False)

def bitcast(fro, to, value, out):
    return '%s = bitcast %s %s to %s' % (out, fro, value, to)
def extractvalue(type, value, ind, out):
    return '%s = extractvalue %s %s, %d' % (out, type, value, ind)
def ret(type=None, value=None):
    if None is type:
        return 'ret void'
    return 'ret %s %s' % (type, value)
def insertvalue(tOuter, outer, tInner, inner, out, *inds):
    if type(out)==list:import pdb;pdb.set_trace()
    a = '%s = insertvalue %s %s, %s %s' % (out, tOuter, outer, tInner, inner)
    for i in inds:
        a += ', %d' % i
    return a
def sub_nsw(type, x, y, out):
    return '%s = sub nsw %s %s, %s' % (out, type, x, y)
def load(type, ptr, out):
    return Instruction(((0, '{0} = load {1}* {2}'),
                   ((3, 9), '{0} = load {1},{1}* {2}')), out, type, ptr) 
    
def store(type, value, addr):
    return 'store %s %s, %s* %s' % (type, value, type, addr)

def structGEP(addr, ltype, out, *ind):
    return Instruction(((0, '{0} = getelementptr inbounds {1}* {2}, {3}'),
                   ((3, 7), '{0} = getelementptr inbounds {1},{1}* {2}, {3}')),
                 out, ltype, addr, ', '.join('i32 %d' % i for i in (0,) + ind))

def versionSyntaxReplace(inst, ver):
    # versions are not accurate
    return inst if isinstance(inst, str) else inst.string(ver)

def branch(*a):
    if len(a) == 1:
        return 'br label ' + a[0]
    cond, trueLbl, falseLbl = a
    return 'br i1 %s, label %%%s, label%%%s' % (cond, trueLbl, falseLbl)
def label(name):
    return name + ':'
def phi(type, out, *valueLabelPairs):
    return '%s = phi %s ' % (out, type) + ', '.join('[ %s, %%%s ]' % vl for vl in valueLabelPairs)