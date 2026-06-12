"""Config layer: ekey loading, safe printing, and the core/ path anchor.

Leaf module with no internal dependencies, so any other module can import
`safeprint` (or `_CORE_DIR`) without risking an import cycle.
"""
import os, json, importlib

_CORE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))  # core/ — this file lives in core/llm/

_oldprint = print
def safeprint(*argv):
    try: _oldprint(*argv)
    except OSError: pass
print = safeprint

def _load_ekeys():
    global _ekey_path
    try:
        import ekey; importlib.reload(ekey); _ekey_path = ekey.__file__
        return {k: v for k, v in vars(ekey).items() if not k.startswith('_')}
    except ImportError: pass
    _ekey_path = p = os.path.join(_CORE_DIR, 'ekey.json')
    if not os.path.exists(p): raise Exception('[ERROR] ekey.py or ekey.json not found, please create one from ekey_template.')
    with open(p, encoding='utf-8') as f: return json.load(f)

_ekey_path = _ekey_mtime = None
def reload_ekeys():
    global _ekey_mtime
    try: mt = os.stat(_ekey_path).st_mtime_ns if _ekey_path else -1
    except OSError: mt = -1  # path went away / never created → fall through to _load_ekeys for a clear error
    if mt == _ekey_mtime: return globals().get('ekeys', {}), False
    mk = _load_ekeys(); _ekey_mtime = os.stat(_ekey_path).st_mtime_ns
    print(f'[Info] Load ekeys from {_ekey_path}')
    globals().update(ekeys=mk)
    return mk, True
