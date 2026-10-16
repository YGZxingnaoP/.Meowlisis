import re
import time


def _name(book):
    return re.sub(r'[\\/:*?"<>|]', "_", str(book or "book"))[:80]


def file_of(ctx, uid, book):
    return ctx.store(_name(book), per_user=uid)


def load_state(ctx, uid, book):
    return file_of(ctx, uid, book).load({})


def save_state(ctx, uid, book, chapter, section, finished=False):
    data = {"uid": uid, "book": book, "chapter": int(chapter), "section": int(section),
            "finished": bool(finished), "updated": time.strftime("%Y-%m-%d %H:%M:%S")}
    file_of(ctx, uid, book).save(data)
    return data
