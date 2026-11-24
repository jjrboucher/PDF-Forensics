"""
Fast access to parsed content-stream instructions (build 2026-11-23).

pikepdf.parse_content_stream returns one instruction object per operator.
Unpacking one (``for operands, operator in ops``) builds its operand list
as Python objects every time, even for the many instructions a walk then
ignores. On a 13-page drawing with 2.75 million operators that cost 85 s
per walk on Windows, against 7 s to parse the page, and each page was
walked three or more times. Reading only ``.operator`` (a name) is about
ten times faster; the operands are fetched only for the instructions a
walk acts on. The results are the same instructions in the same order.

Plain ``(operands, operator)`` tuples are accepted too, so callers that
build their own lists (and the tests) keep working.
"""


def op_names(ops):
    """The operator names of ops, in order, as strings."""
    try:
        return [str(ins.operator) for ins in ops]
    except AttributeError:
        return [str(ins.operator) if hasattr(ins, "operator")
                else str(ins[1]) for ins in ops]


def operands_of(ins):
    """The operand list of one instruction."""
    try:
        return ins.operands
    except AttributeError:
        return ins[0]


def named_ops(ops):
    """(names, instructions): ops as a list, with its operator names."""
    if not isinstance(ops, list):
        ops = list(ops)
    return op_names(ops), ops


class _Operands:
    """An instruction's operands, fetched the first time they are used."""
    __slots__ = ("_ins", "_v")

    def __init__(self, ins):
        self._ins = ins
        self._v = None

    def _get(self):
        if self._v is None:
            self._v = operands_of(self._ins)
        return self._v

    def __getitem__(self, k):
        return self._get()[k]

    def __len__(self):
        return len(self._get())

    def __iter__(self):
        return iter(self._get())

    def __bool__(self):
        return len(self._get()) > 0


class OpView:
    """ops as a sequence of (name, operands) pairs, like
    ``[(str(op), operands) for operands, op in ops]`` but with each
    pair's operands fetched only if the caller uses them."""
    __slots__ = ("names", "_ops")

    def __init__(self, ops):
        self.names, self._ops = named_ops(ops)

    def __len__(self):
        return len(self.names)

    def __getitem__(self, i):
        if isinstance(i, slice):
            return [self[j] for j in range(*i.indices(len(self)))]
        return self.names[i], _Operands(self._ops[i])

    def __iter__(self):
        ops = self._ops
        for i, name in enumerate(self.names):
            yield name, _Operands(ops[i])
