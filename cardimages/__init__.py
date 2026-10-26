"""Private local mirror of card images for LotR LCG and Arkham Horror LCG.

    from cardimages import open_store
    store = open_store("lotr")            # or "arkham"
    for e in store.resolve_deck("https://ringsdb.com/decklist/view/951"):
        e["faces"][0]["path"], e["qty"], e["card_back"]

Images are for private use - do not redistribute.
"""
from . import arkham, lotr
from .common import DEFAULT_ROOT

GAMES = {"lotr": lotr, "arkham": arkham}


def open_store(game, root=DEFAULT_ROOT):
    return GAMES[game].Store(root)
