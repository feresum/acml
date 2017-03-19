import re

kw = {'let', 'in', 'fun', 'if', 'then', 'else', 'true', 'false'}

class Identifier:
    def __init__(self, name):
        if name in kw or not name.isalpha():
            raise ValueError()
        self.name = name

def tok(w):
    try: return Identifier(w)
    except ValueError: pass
    return w
    
def tokenize(s):
    return re.findall(r'\w+|[()]|[^\w\s]+', s)