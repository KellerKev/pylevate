"""Tools for the agent template.

calculator: a hand-rolled recursive-descent arithmetic evaluator — no eval().
fetch_url:  fetches a URL and returns truncated text. Browser fetch is
            CORS-bound: only sites that allow cross-origin reads will work.
"""

from pylevate.ai import tool


def tokenize(expr):
    tokens = []
    i = 0
    while i < len(expr):
        ch = expr[i]
        if ch == ' ':
            i += 1
            continue
        if ch in '+-*/()':
            tokens.append(ch)
            i += 1
            continue
        if ch.isdigit() or ch == '.':
            num = ''
            while i < len(expr) and (expr[i].isdigit() or expr[i] == '.'):
                num += expr[i]
                i += 1
            tokens.append(num)
            continue
        raise Exception('Unexpected character: ' + ch)
    return tokens


class Parser:
    def __init__(self, tokens):
        self.tokens = tokens
        self.pos = 0

    def peek(self):
        if self.pos < len(self.tokens):
            return self.tokens[self.pos]
        return None

    def next(self):
        token = self.peek()
        self.pos += 1
        return token

    def parse_expr(self):
        value = self.parse_term()
        while self.peek() == '+' or self.peek() == '-':
            op = self.next()
            rhs = self.parse_term()
            if op == '+':
                value = value + rhs
            else:
                value = value - rhs
        return value

    def parse_term(self):
        value = self.parse_factor()
        while self.peek() == '*' or self.peek() == '/':
            op = self.next()
            rhs = self.parse_factor()
            if op == '*':
                value = value * rhs
            else:
                if rhs == 0:
                    raise Exception('Division by zero')
                value = value / rhs
        return value

    def parse_factor(self):
        token = self.next()
        if token == '(':
            value = self.parse_expr()
            if self.next() != ')':
                raise Exception('Missing closing parenthesis')
            return value
        if token == '-':
            return -self.parse_factor()
        if token is None:
            raise Exception('Unexpected end of expression')
        return parseFloat(token)


def evaluate(expr):
    parser = Parser(tokenize(expr))
    result = parser.parse_expr()
    if parser.peek() is not None:
        raise Exception('Unexpected token: ' + parser.peek())
    return result


def calc_handler(args):
    return str(evaluate(args['expression']))


async def fetch_handler(args):
    response = await fetch(args['url'])
    if not response.ok:
        return 'HTTP ' + str(response.status)
    text = await response.text()
    return text[:2000]


calculator = tool(
    name='calculator',
    description='Evaluate an arithmetic expression with + - * / and parentheses.',
    parameters={
        'type': 'object',
        'properties': {
            'expression': {'type': 'string', 'description': "e.g. '(17*23)+5'"},
        },
        'required': ['expression'],
    },
    handler=lambda args: calc_handler(args),
)

fetch_url = tool(
    name='fetch_url',
    description='Fetch a URL and return the first 2000 characters of the body. '
                'Only works for CORS-permissive sites.',
    parameters={
        'type': 'object',
        'properties': {
            'url': {'type': 'string', 'description': 'Absolute http(s) URL'},
        },
        'required': ['url'],
    },
    handler=lambda args: fetch_handler(args),
)
