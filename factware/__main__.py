"""支持 ``python -m factware`` 调用命令行。"""

from factware.cli import main

if __name__ == "__main__":
    raise SystemExit(main())
