import abc
import re

# Self-interpretable AST classes
class Expression:
    abc.abstractmethod
    def match(self, text: str) -> bool:
        _ = text
        raise NotImplementedError

class LiteralExpression(Expression):
    def __init__(self, literal: str):
        self.literal = literal
    def match(self, text: str) -> bool:
        return self.literal in text
    def __repr__(self):
        return f'Literal("{self.literal}")'

class NotExpression(Expression):
    def __init__(self, expr: Expression):
        self.expr = expr
    def match(self, text: str) -> bool:
        return not self.expr.match(text)
    def __repr__(self):
        return f"Not({self.expr!r})"

class AndExpression(Expression):
    def __init__(self, left: Expression, right: Expression):
        self.left = left
        self.right = right
    def match(self, text: str) -> bool:
        return self.left.match(text) and self.right.match(text)
    def __repr__(self):
        return f"And({self.left!r}, {self.right!r})"

class OrExpression(Expression):
    def __init__(self, left: Expression, right: Expression):
        self.left = left
        self.right = right
    def match(self, text: str) -> bool:
        return self.left.match(text) or self.right.match(text)
    def __repr__(self):
        return f"Or({self.left!r}, {self.right!r})"

# Tokenizer
TOKEN_REGEX = r'''
    "((?:\\.|[^"\\])*)"   |   # double-quoted literal with escapes
    \bNOT\b               |
    \bAND\b               |
    \bOR\b                |
    \(|\)                 |
    \s+                   |   # whitespace
    .                         # fallback
'''

def tokenize(s):
    for m in re.finditer(TOKEN_REGEX, s, re.VERBOSE | re.IGNORECASE):
        tok = m.group(0)
        if tok.isspace():
            continue
        yield tok

# Recursive descent parser
class Parser:
    def __init__(self, tokens):
        self.tokens = list(tokens)
        self.i = 0

    def peek(self):
        return self.tokens[self.i] if self.i < len(self.tokens) else None

    def consume(self, t=None):
        cur = self.peek()
        if t and cur != t:
            raise ValueError(f"Expected {t}, got {cur}")
        self.i += 1
        return cur

    def parse(self):
        return self.parse_or()

    def parse_or(self):
        node = self.parse_and()
        while self.peek() and self.peek().upper() == "OR":
            self.consume()
            node = OrExpression(node, self.parse_and())
        return node

    def parse_and(self):
        node = self.parse_unary()
        while self.peek() and self.peek().upper() == "AND":
            self.consume()
            node = AndExpression(node, self.parse_unary())
        return node

    def parse_unary(self):
        if self.peek() and self.peek().upper() == "NOT":
            self.consume()
            return NotExpression(self.parse_unary())
        return self.parse_primary()

    def parse_primary(self):
        tok = self.peek()
        if tok == "(":
            self.consume("(")
            node = self.parse_or()
            self.consume(")")
            return node
        if tok.startswith('"'):
            self.consume()
            # extract literal removing escapes
            literal = tok[1:-1].replace(r'\"', '"')
            return LiteralExpression(literal)
        raise ValueError("Invalid token: " + str(tok))


def parse_expression(s: str) -> Expression:
    return Parser(tokenize(s)).parse()

