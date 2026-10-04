#!/usr/bin/env python3
"""
agent.py — Terminal agent (thin entrypoint).

The implementation lives in the `arkad` package. See
`arkad/main.py` for the REPL entry point.
"""


if __name__ == "__main__":
    from arkad.cli import main

    main()
