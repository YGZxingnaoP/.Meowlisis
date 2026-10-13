import argparse
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from func.pipeline.id_signup import IdSignupBridge


class IdentityCli:
    def __init__(self):
        self.bridge = IdSignupBridge()

    def cmd_list(self, args):
        """列出全部用户"""
        users = self.bridge.list_users()
        if not users:
            print("还没有任何用户")
            return 0
        for user in users:
            print(self.bridge.summary(str(user.get("id") or "")))
        return 0

    def cmd_new(self, args):
        """给一个平台账号发编号"""
        uid = self.bridge.ensure(args.platform, args.account, nickname=args.name or "")
        if not uid:
            print("发编号失败：身份表正忙或参数为空")
            return 1
        print(self.bridge.summary(uid))
        return 0

    def cmd_bind(self, args):
        """把一个平台账号绑到某个编号或昵称"""
        user = self.bridge.find(args.key)
        if not user:
            print(f"没找到 {args.key}")
            return 1
        ok, msg, _owner = self.bridge.bind(str(user.get("id")), args.platform, args.account)
        print(self.bridge.summary(str(user.get("id"))) if ok else msg)
        return 0 if ok else 1

    def cmd_unbind(self, args):
        """解绑某个平台的账号"""
        user = self.bridge.find(args.key)
        if not user:
            print(f"没找到 {args.key}")
            return 1
        ok, msg = self.bridge.unbind(str(user.get("id")), args.platform)
        print(self.bridge.summary(str(user.get("id"))) if ok else msg)
        return 0 if ok else 1

    def cmd_nickname(self, args):
        """改昵称"""
        user = self.bridge.find(args.key)
        if not user:
            print(f"没找到 {args.key}")
            return 1
        ok, msg = self.bridge.set_nickname(str(user.get("id")), args.nickname)
        print(self.bridge.summary(str(user.get("id"))) if ok else msg)
        return 0 if ok else 1

    def cmd_show(self, args):
        """按编号昵称或平台账号查身份"""
        if args.platform and args.account:
            uid = self.bridge.resolve(args.platform, args.account)
            print(self.bridge.summary(uid) if uid else f"{args.platform} {args.account} 还没有绑定")
            return 0
        user = self.bridge.find(args.key)
        if not user:
            print(f"没找到 {args.key}")
            return 1
        print(self.bridge.summary(str(user.get("id"))))
        return 0

    def cmd_lookup(self, args):
        """按昵称反查 B站 uid"""
        uid, err = self.bridge.lookup_bili(args.keyword)
        print(uid if uid else err)
        return 0 if uid else 1

    def cmd_merge(self, args):
        """合并用户，默认只预演，加 --apply 才真动手"""
        keys = list(args.keys)
        if not args.apply:
            for line in self.bridge.merge_plan(keys):
                print(line)
            ok, msg = self.bridge.merge_apply(keys, keep=args.keep or "", dry_run=True)
            print(msg)
            return 0 if ok else 1
        ok, msg = self.bridge.merge_apply(keys, keep=args.keep or "", dry_run=False)
        print(msg)
        return 0 if ok else 1


def build_parser():
    """拼命令行参数"""
    parser = argparse.ArgumentParser(prog="identity", description="用户身份表后端命令")
    sub = parser.add_subparsers(dest="action")

    sub.add_parser("list", help="列出全部用户")

    p_new = sub.add_parser("new", help="给平台账号发编号")
    p_new.add_argument("platform")
    p_new.add_argument("account")
    p_new.add_argument("name", nargs="?", default="")

    p_bind = sub.add_parser("bind", help="绑定平台账号")
    p_bind.add_argument("key", help="编号或昵称")
    p_bind.add_argument("platform")
    p_bind.add_argument("account")

    p_unbind = sub.add_parser("unbind", help="解绑平台账号")
    p_unbind.add_argument("key")
    p_unbind.add_argument("platform")

    p_nick = sub.add_parser("nickname", help="改昵称")
    p_nick.add_argument("key")
    p_nick.add_argument("nickname")

    p_show = sub.add_parser("show", help="查身份")
    p_show.add_argument("key", nargs="?", default="")
    p_show.add_argument("--platform", default="")
    p_show.add_argument("--account", default="")

    p_lookup = sub.add_parser("lookup", help="按昵称反查 B站 uid")
    p_lookup.add_argument("keyword")

    p_merge = sub.add_parser("merge", help="合并用户")
    p_merge.add_argument("keys", nargs="+")
    p_merge.add_argument("--keep", default="")
    p_merge.add_argument("--apply", action="store_true")

    return parser


ACTIONS = {
    "list": "cmd_list",
    "new": "cmd_new",
    "bind": "cmd_bind",
    "unbind": "cmd_unbind",
    "nickname": "cmd_nickname",
    "show": "cmd_show",
    "lookup": "cmd_lookup",
    "merge": "cmd_merge",
}


def main():
    """入口：按子命令分发"""
    parser = build_parser()
    args = parser.parse_args()
    cli = IdentityCli()
    if not args.action:
        parser.print_help()
        return 0
    return getattr(cli, ACTIONS[args.action])(args)


if __name__ == "__main__":
    sys.exit(main())
