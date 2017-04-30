import argparse, sys, os.path
from llvm_util import CompileContext
from parse import parse

def stdlib_text():
    path = os.path.join(os.path.dirname(__file__), 'stdlib.miniml')
    with open(path) as libfile:
        return libfile.read()

parser = argparse.ArgumentParser()
parser.add_argument('infile', nargs='?', type=argparse.FileType('r'), default=sys.stdin)
parser.add_argument('-o', '--outfile', type=argparse.FileType('w'), default=sys.stdout)
parser.add_argument('-b', '--bitness', default=64, type=int, choices=[32, 64])
parser.add_argument('-v', '--llvm-version', default='0')
parser.add_argument('--no-stdlib', action='store_false', dest='use_stdlib')

a = parser.parse_args()
llver = tuple(map(int, a.llvm_version.split('.')))
cx = CompileContext(a.bitness, llver)
with a.infile as infile:
    text = a.infile.read()
if a.use_stdlib:
    text = stdlib_text() + text
tree = parse(text, cx)
out = cx.compile(tree)
with a.outfile as outfile:
    outfile.write(out)
