class TypeUnion(dict):
    def _get(self, k):
        return super().__getitem__(k)
    def representative(self, k):
        while type(self._get(k)) is not int:
            k = self._get(k)
        return k
    def size(self, x):
        return self._get(self[x])
    def compress(self, start, rep):
        while start is not rep:
            #start, self[start] = self._get(start), rep
            tmp = self._get(start)
            self[start] = rep
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
                self[x] = 1
        ar, br = self.representative(a), self.representative(b)
        if ar is br: return
        av, bv = a.isTypeVariable(), b.isTypeVariable()
        az, bz = self._get(ar), self._get(br)
        if bz > az if av == bv else av:
            self[ar] = br
            self[br] = az + bz
        else:
            self[br] = ar
            self[ar] = az + bz
    def import_dict(self, d):
        for k, v in d.items():
            self.join(k, v)
        