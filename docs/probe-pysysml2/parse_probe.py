import sys, antlr4
from antlr4 import InputStream, CommonTokenStream, ParseTreeWalker
from antlr4.error.ErrorListener import ErrorListener
from pysysml2.grammar.distpy.SysML2Lexer import SysML2Lexer
from pysysml2.grammar.distpy.SysML2Parser import SysML2Parser

class L(ErrorListener):
    def __init__(self): self.errs=[]
    def syntaxError(self, recog, sym, line, col, msg, e):
        self.errs.append(f"line {line}:{col} {msg}")

for f in sys.argv[1:]:
    text = open(f, encoding='utf-8').read()
    lex = SysML2Lexer(InputStream(text)); lex.removeErrorListeners()
    l1 = L(); lex.addErrorListener(l1)
    tok = CommonTokenStream(lex); tok.fill()
    p = SysML2Parser(tok); p.removeErrorListeners()
    l2 = L(); p.addErrorListener(l2)
    tree = p.model()
    errs = l1.errs + l2.errs
    print(f"--- {f}: syntax_errors={len(errs)}")
    for e in errs[:6]: print("   ", e)
    print(f"    parse tree: {tree.toStringTree(recog=p)[:200]}")
