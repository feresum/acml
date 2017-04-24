import re

kw = {'let', 'in', 'fun', 'if', 'then', 'else', 'true', 'false', 'switch'}

class Identifier:
    def __init__(self, name):
        if name in kw or not name[0].isalpha():
            raise ValueError()
        self.name = name

def tok(w):
    try: return Identifier(w)
    except ValueError: pass
    return w
    
def tokenize(s):
    return re.findall(r'\w(?:[-\w]*\w)?|[(),<>|:]|\'.\'|[^\w\s]+', s)