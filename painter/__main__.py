"""python -m painter"""
import sys

from painter.cli.main import main

sys.argv[0] = "painter"
raise SystemExit(main())
