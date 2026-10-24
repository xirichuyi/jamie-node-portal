"""Single entry point for node installation, registration and verification."""

import sys
from nodes import cli, manager, instabox


def main():
    args = sys.argv[1:]
    if args and args[0] in ('list', 'advanced'):
        return manager.main(args if args[0] == 'list' else args[1:])
    if args and args[0] == 'instabox':
        sys.argv = [sys.argv[0], *args[1:]]
        return instabox.main()
    return cli.main(args)


if __name__ == '__main__':
    try:
        main()
    except (RuntimeError, ValueError, OSError) as error:
        print('接入未完成：' + str(error))
        raise SystemExit(1) from None
