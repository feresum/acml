class TypeUnion(dict):
    def _get(self, k):
        return super().__getitem__(k)
    def _set(self, k, v):
        super().__setitem__(k, v)
    def representative(self, k):
        while type(self._get(k)) is not int:
            k = self._get(k)
        return k
    def size(self, x):
        return self._get(self[x])
    def compress(self, start, rep):
        while start is not rep:
            tmp = self._get(start)
            self._set(start, rep)
            start = tmp
    def __getitem__(self, key):
        if key not in self:
            return key
        rep = self.representative(key)
        self.compress(key, rep)
        return rep
    def join(self, a, b):
        for x in a, b:
            if x not in self:
                self._set(x, 1)
        ar, br = self.representative(a), self.representative(b)
        if ar is br: return
        av, bv = a.isTypeVariable(), b.isTypeVariable()
        az, bz = self._get(ar), self._get(br)
        if bz > az if av == bv else av:
            self._set(ar, br)
            self._set(br, az + bz)
        else:
            self._set(br, ar)
            self._set(ar, az + bz)
    def import_dict(self, d):
        for k, v in d.items():
            self.join(k, v)
    def __setitem__(*a):
        raise Exception("Don't do that")
