"""Small arithmetic language for product templates; no execution of user code."""
import ast
import re
from decimal import Decimal, InvalidOperation, DivisionByZero, localcontext, ROUND_HALF_UP, ROUND_CEILING

class CalculationError(ValueError):pass

def number(value):
    if isinstance(value,bool):raise CalculationError('Ожидается число.')
    try:result=Decimal(str(value).replace(',','.'))
    except (InvalidOperation,ValueError):raise CalculationError('Ожидается число.')
    if not result.is_finite() or abs(result)>Decimal('1000000000000'):raise CalculationError('Число выходит за допустимые пределы.')
    return result

def parse_formula(source,names):
    if not isinstance(source,str) or len(source)>2000:raise CalculationError('Формула должна быть строкой до 2000 символов.')
    source=re.sub(r'/\*.*?\*/','',source,flags=re.S).strip()
    match=re.fullmatch(r'result\s*=\s*(.+?)\s*;?',source,flags=re.S)
    if not match:raise CalculationError('Формула должна иметь вид result = выражение;')
    expression=match[1].rstrip(';').strip()
    try:tree=ast.parse(expression,mode='eval')
    except (SyntaxError,RecursionError):raise CalculationError('Ошибка в записи формулы: проверьте скобки и знаки.')
    nodes=list(ast.walk(tree))
    if len(nodes)>150:raise CalculationError('Формула слишком сложная.')
    for node in nodes:
        if isinstance(node,ast.Attribute):
            if not isinstance(node.value,ast.Name) or node.value.id!='param' or node.attr not in names:raise CalculationError(f'Неизвестная переменная: {ast.get_source_segment(expression,node)}')
        elif isinstance(node,ast.Name):
            if node.id!='param':raise CalculationError(f'Неизвестное имя: {node.id}')
        elif isinstance(node,ast.Constant):
            if isinstance(node.value,bool) or not isinstance(node.value,(int,float)):raise CalculationError('В формуле разрешены только числа.')
            number(ast.get_source_segment(expression,node))
        elif not isinstance(node,(ast.Expression,ast.BinOp,ast.UnaryOp,ast.Add,ast.Sub,ast.Mult,ast.Div,ast.UAdd,ast.USub,ast.Load)):
            raise CalculationError('Разрешены числа, param.переменная, +, -, *, / и скобки.')
    return tree.body,expression

def evaluate(source,params):
    root,expression=parse_formula(source,set(params))
    def visit(node):
        if isinstance(node,ast.Constant):return number(ast.get_source_segment(expression,node))
        if isinstance(node,ast.Attribute):return number(params[node.attr])
        if isinstance(node,ast.UnaryOp):return visit(node.operand)*(1 if isinstance(node.op,ast.UAdd) else -1)
        if isinstance(node,ast.BinOp):
            a,b=visit(node.left),visit(node.right)
            try:
                if isinstance(node.op,ast.Add):return number(a+b)
                if isinstance(node.op,ast.Sub):return number(a-b)
                if isinstance(node.op,ast.Mult):return number(a*b)
                return number(a/b)
            except (DivisionByZero,InvalidOperation,ZeroDivisionError):raise CalculationError('Деление на ноль или недопустимое вычисление.')
        raise CalculationError('В формуле не хватает выражения.')
    with localcontext() as context:
        context.prec=32
        result=visit(root)
    if result<0:raise CalculationError('Рассчитанное количество не может быть отрицательным.')
    return result

def money(value,places=2):return value.quantize(Decimal(1).scaleb(-places),rounding=ROUND_HALF_UP)
def quantity(value,unit,places=2,piece_rounding='up'):
    piece=unit.strip().casefold() in ['штука','штук','шт','шт.']
    return value.quantize(Decimal('1') if piece else Decimal(1).scaleb(-places),rounding=ROUND_CEILING if piece and piece_rounding=='up' else ROUND_HALF_UP)
