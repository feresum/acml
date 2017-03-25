from sys import stderr
dpr = lambda *a: print(*a, file=stderr)
def dbgEntry(f):
    def ff(*a):
        dpr('Entering', f.__name__)
        ret = f(*a)
        dpr('Exiting', f.__name__)
        return ret
    return ff