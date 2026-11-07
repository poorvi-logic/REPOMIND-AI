# Sample repository for RepoMind AI

A small Python project used to demonstrate RepoMind AI. It contains:

- Top-level modules (`main.py`, `payment.py`, `utils.py`) and a package-style set of modules that import each other.
- A module-level import cycle (`orders` ↔ `notifications`) and a function-level import that closes a second cycle.
- Classes, methods, properties, async functions, decorators, nested functions and dataclasses.
- Deliberate review patterns so the risk engine has findings to show: a bare `except`, a swallowed `ValueError`,
  an f-string SQL statement, `subprocess.run(..., shell=True)`, `yaml.load` without a safe loader, a hardcoded demo token,
  and a branch-heavy function.

The code is for demonstration only. RepoMind AI parses it with Python's `ast` module and never imports or executes it.
