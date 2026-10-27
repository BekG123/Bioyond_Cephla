"""Small, deterministic DSL preview compiler. It never executes generated code.

Version 1 is one machine, a timed loop and ordered independent IF decisions.
The Python output is a decision function, not a hardware driver or scheduler.
"""
import ast
import re


EXAMPLE = '''count = 0

Machine TYPE.Hamilton_MiniLab_Prep:
    FOR every 500 millis:
        count += 1
        check.logs

        IF Machine.has_fault:
            PAUSE = human.review

        IF Machine.parked & no.tips:
            ASK = Role TYPE.Researcher(request=unload)

        IF count >= 120:
            PAUSE = human.review

        IF !Machine.parked OR !no.tips:
            WAIT

agent(MODEL).translate()
agent(MODEL).retranslate()
'''

PREDICATES = {
    'Machine.has_fault': 'has_fault',
    'Machine.parked': 'parked',
    'no.tips': 'no_tips',
    'Machine.door_closed': 'door_closed',
}
ACTIONS = {
    'PAUSE = human.review': {'kind': 'pause', 'target': 'human.review'},
    'ASK = Role TYPE.Researcher(request=unload)':
        {'kind': 'ask', 'role': 'Researcher', 'request': 'unload'},
    'WAIT': {'kind': 'wait'},
}


def parse_condition(text):
    """Parse boolean expressions without eval or arbitrary Python expressions."""
    python = text.replace('&', ' and ').replace(' OR ', ' or ')
    python = re.sub(r'!(?!=)', 'not ', python).strip()
    try:
        node = ast.parse(python, mode='eval').body
    except SyntaxError as error:
        raise ValueError('Invalid IF condition.') from error

    def check(item):
        if ast.unparse(item) in PREDICATES:
            return
        if isinstance(item, ast.BoolOp) and isinstance(item.op, (ast.And, ast.Or)):
            for value in item.values:
                check(value)
            return
        if isinstance(item, ast.UnaryOp) and isinstance(item.op, ast.Not):
            check(item.operand)
            return
        if (isinstance(item, ast.Compare) and isinstance(item.left, ast.Name)
                and item.left.id == 'count' and len(item.ops) == 1
                and isinstance(item.ops[0], (ast.Gt, ast.GtE, ast.Eq, ast.Lt, ast.LtE))
                and isinstance(item.comparators[0], ast.Constant)
                and type(item.comparators[0].value) is int
                and 0 <= item.comparators[0].value <= 1000000):
            return
        raise ValueError('Unsupported condition: ' + ast.unparse(item))

    check(node)
    return node


def condition_python(node):
    class Observations(ast.NodeTransformer):
        def visit_Attribute(self, item):
            name = ast.unparse(item)
            if name in PREDICATES:
                return ast.Subscript(value=ast.Name(id='observation', ctx=ast.Load()),
                    slice=ast.Constant(value=PREDICATES[name]), ctx=ast.Load())
            return self.generic_visit(item)
    return ast.unparse(ast.fix_missing_locations(Observations().visit(node)))


def compile_dsl(source):
    if not isinstance(source, str) or len(source) > 16000:
        raise ValueError('DSL must be text of at most 16,000 characters.')
    if '\t' in source:
        raise ValueError('Use four spaces for indentation, not tabs.')
    if ';' in source:
        raise ValueError('Semicolons are not part of DSL v1.')
    lines = [(n, s.rstrip()) for n, s in enumerate(source.splitlines(), 1)
             if s.strip() and not s.lstrip().startswith('#')]
    if len(lines) < 8:
        raise ValueError('Expected count, machine, timed loop, checks and IF blocks.')
    header = [s for _, s in lines[:5]]
    machine = re.fullmatch(r'Machine TYPE\.([A-Za-z][A-Za-z0-9_]*):', header[1])
    interval = re.fullmatch(r'    FOR every ([1-9][0-9]*) millis:', header[2])
    if (header[0] != 'count = 0' or not machine or not interval
            or header[3:] != ['        count += 1', '        check.logs']):
        raise ValueError('Use the v1 header shown in the example, with four-space indentation.')
    millis = int(interval[1])
    if not 50 <= millis <= 60000:
        raise ValueError('Check interval must be 50–60,000 milliseconds.')
    body = lines[5:]
    markers = ['agent(MODEL).translate()', 'agent(MODEL).retranslate()']
    if [s for _, s in body[-2:]] == markers:
        body = body[:-2]
    if not body or len(body) % 2:
        raise ValueError('Each IF requires one indented decision: PAUSE, ASK, or WAIT.')
    decisions = []
    for index in range(0, len(body), 2):
        line_no, line = body[index]
        match = re.fullmatch(r'        IF (.+):', line)
        action_line = body[index + 1][1]
        if not match or not action_line.startswith('            ') or action_line[12:] not in ACTIONS:
            raise ValueError(f'Line {line_no}: expected an IF with one supported decision indented four spaces further.')
        condition = condition_python(parse_condition(match[1]))
        decisions.append((condition, ACTIONS[action_line[12:]]))
    python = [
        '# Generated DSL v1 decision preview. This file is not deployed or executed.',
        '# Caller supplies one fresh snapshot per scheduled tick.',
        '# Caller persists count and suspends scheduling on ask/pause.',
        '# Missing or stale observations must be rejected by the caller.',
        f'MACHINE = {machine[1]!r}', f'CHECK_INTERVAL_MS = {millis}', '',
        'def decide(observation, count):', '    count += 1',
    ]
    for condition, action in decisions:
        python.extend([f'    if {condition}:', f'        return {action!r}, count'])
    python.append("    return {'kind': 'wait'}, count")
    output = '\n'.join(python) + '\n'
    ast.parse(output)
    return dict(python=output, machine=machine[1], interval_ms=millis,
                roundtrip_dsl=decompile_python(output), executable=False,
                note='Preview only. check.logs requires a fresh structured observation; it does not read arbitrary log text. '
                     'First matching decision ends the tick. ASK/PAUSE suspend the workflow. '
                     'Count is a check budget, not an elapsed-time guarantee. No runtime or hardware deployment is attached.')


def decompile_python(source):
    """Read the generated Python AST, not an embedded copy of the original DSL."""
    tree = ast.parse(source)
    if len(tree.body) != 3 or not isinstance(tree.body[2], ast.FunctionDef):
        raise ValueError('Only generated v1 Python can be retransated.')
    machine, interval = [ast.literal_eval(item.value) for item in tree.body[:2]]
    out = ['count = 0', '', f'Machine TYPE.{machine}:',
           f'    FOR every {interval} millis:', '        count += 1', '        check.logs']
    reverse = {value: key for key, value in PREDICATES.items()}

    def expression(node):
        if isinstance(node, ast.Subscript) and isinstance(node.value, ast.Name) and node.value.id == 'observation':
            return reverse[ast.literal_eval(node.slice)]
        if isinstance(node, ast.UnaryOp) and isinstance(node.op, ast.Not):
            value = expression(node.operand)
            return '!(' + value + ')' if isinstance(node.operand, ast.BoolOp) else '!' + value
        if isinstance(node, ast.BoolOp):
            op = ' & ' if isinstance(node.op, ast.And) else ' OR '
            return op.join('(' + expression(v) + ')' if isinstance(v, ast.BoolOp) else expression(v) for v in node.values)
        if isinstance(node, ast.Compare):
            return ast.unparse(node)
        raise ValueError('Unsupported generated expression.')

    for node in tree.body[2].body[1:-1]:
        action = ast.literal_eval(node.body[0].value.elts[0])
        label = next(k for k, v in ACTIONS.items() if v == action)
        out.extend(['', '        IF ' + expression(node.test) + ':', '            ' + label])
    return '\n'.join(out + ['', 'agent(MODEL).translate()', 'agent(MODEL).retranslate()', ''])
