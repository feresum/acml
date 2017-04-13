from sys import stderr
dpr = lambda *a, **k: print(*a, file=stderr, **k)
def dbgEntry(f):
    def ff(*a):
        dpr('Entering', f.__name__)
        ret = f(*a)
        dpr('Exiting', f.__name__)
        return ret
    return ff