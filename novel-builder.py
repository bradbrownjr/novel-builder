#!/usr/bin/env python3
"""Thin wrapper to invoke Novel Builder as a package.

Usage:
    python novel-builder.py [OPTIONS]

This is equivalent to:
    python -m novel_builder [OPTIONS]
"""

from novel_builder.__main__ import main

if __name__ == "__main__":
    main()
