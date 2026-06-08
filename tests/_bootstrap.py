"""Shared test bootstrap: put core/ on sys.path and expose a generator driver."""
import os, sys
sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), '..', 'core'))

def drive(gen):
    """Run a generator to exhaustion. Returns (list_of_yields, return_value)."""
    out = []
    try:
        while True: out.append(next(gen))
    except StopIteration as e:
        return out, e.value
