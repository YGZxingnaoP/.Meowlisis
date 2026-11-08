using System;
using System.Collections.Generic;
using System.Linq;
using Microsoft.Xna.Framework;
using StardewValley;
using StardewValley.Menus;

namespace BlindWhaleFarmer
{
    internal sealed partial class GameActions
    {
        private static readonly string[] ShopKeepers =
        {
            "Pierre", "Willy", "Robin", "Clint", "Marnie", "Gus", "Sandy", "Krobus",
            "Marlon", "Dwarf", "Harvey", "Wizard", "Gunther",
        };

        /// <summary>
        /// 走到柜台前、对着柜台按动作键，走游戏自己的开店逻辑。
        /// 不用 Utility.TryOpenShopMenu 直接变出商店（用户明确禁止）。
        /// </summary>
        public IEnumerable<object> OpenShop(string shopId)
        {
            if (string.IsNullOrWhiteSpace(shopId) && !ShopByLocation.TryGetValue(Loc.Name, out shopId))
            {
                yield return ActionResult.Fail("这里没有商店（皮埃尔的店在 SeedShop，铁匠在 Blacksmith，木匠在 ScienceHouse，威利在 FishShop）");
                yield break;
            }
            if (Blocked(out string why))
            {
                yield return ActionResult.Fail(why);
                yield break;
            }
            if (Game1.activeClickableMenu is ShopMenu)
            {
                yield return ActionResult.Success("商店已经开着：\n" + observer.DescribeMenu());
                yield break;
            }

            // 1) 店主面前的柜台：店主 + 方向 = 柜台，再往外一格 = 顾客站位
            var pairs = new List<KeyValuePair<Point, Point>>();
            NPC keeper = Loc.characters?
                .OfType<NPC>()
                .FirstOrDefault(n => n.Name != null && ShopKeepers.Any(k => string.Equals(k, n.Name, StringComparison.OrdinalIgnoreCase)));
            if (keeper != null)
            {
                Point keeperTile = keeper.TilePoint;
                foreach (Point dir in Pathfinder.Dirs)
                {
                    var counter = new Point(keeperTile.X + dir.X, keeperTile.Y + dir.Y);
                    var stand = new Point(keeperTile.X + 2 * dir.X, keeperTile.Y + 2 * dir.Y);
                    if (!Loc.isTileOnMap(counter.X, counter.Y) || !Loc.isTileOnMap(stand.X, stand.Y))
                        continue;
                    string action = Loc.doesTileHaveProperty(counter.X, counter.Y, "Action", "Buildings")
                                    ?? Loc.doesTileHaveProperty(counter.X, counter.Y, "Action", "Back");
                    if (string.IsNullOrEmpty(action))
                        continue;
                    if (action.StartsWith("Door", StringComparison.OrdinalIgnoreCase)
                        || action.StartsWith("Warp", StringComparison.OrdinalIgnoreCase)
                        || action.StartsWith("LockedDoorWarp", StringComparison.OrdinalIgnoreCase))
                        continue;
                    if (!Pathfinder.IsPassable(Loc, stand.X, stand.Y) || Pathfinder.IsTouchWarp(Loc, stand.X, stand.Y))
                        continue;
                    pairs.Add(new KeyValuePair<Point, Point>(stand, counter));
                }
            }

            // 2) 兜底：地图上带 Shop 的柜台格 + 四周能站的地方
            if (pairs.Count == 0)
            {
                int w = Pathfinder.MapWidth(Loc), h = Pathfinder.MapHeight(Loc);
                for (int x = 0; x < w && pairs.Count == 0; x++)
                {
                    for (int y = 0; y < h && pairs.Count == 0; y++)
                    {
                        string action = Loc.doesTileHaveProperty(x, y, "Action", "Buildings")
                                        ?? Loc.doesTileHaveProperty(x, y, "Action", "Back");
                        if (string.IsNullOrEmpty(action) || action.IndexOf("Shop", StringComparison.OrdinalIgnoreCase) < 0)
                            continue;
                        var counter = new Point(x, y);
                        foreach (var stand in Pathfinder.AdjacentStandTiles(Loc, counter))
                            pairs.Add(new KeyValuePair<Point, Point>(stand, counter));
                    }
                }
            }

            if (pairs.Count == 0)
            {
                yield return ActionResult.Fail("没找到店主柜台（店主可能不在店里）");
                yield break;
            }

            Point origin = Player.TilePoint;
            var best = pairs
                .OrderBy(pair => Math.Abs(pair.Key.X - origin.X) + Math.Abs(pair.Key.Y - origin.Y))
                .First();
            Point counterTile = best.Value;
            var o = new Outcome();
            foreach (var s in GoToAny(new List<Point> { best.Key }, o, "柜台前"))
                yield return s;
            if (!o.Ok)
            {
                yield return ActionResult.Fail("走不到柜台前：" + o.Message);
                yield break;
            }

            Face(counterTile);
            bool opened = false;
            try
            {
                opened = Loc.checkAction(new xTile.Dimensions.Location(counterTile.X, counterTile.Y),
                    Game1.viewport, Player);
            }
            catch { }
            foreach (var s in WaitTicks(30))
                yield return s;

            if (Game1.activeClickableMenu is ShopMenu)
                yield return ActionResult.Success("已走到柜台并打开商店：\n" + observer.DescribeMenu());
            else if (Game1.activeClickableMenu is DialogueBox box)
                yield return ActionResult.Fail("柜台有反应但没开店：" + box.getCurrentString());
            else
                yield return ActionResult.Fail(opened
                    ? "点了柜台但商店没开（可能不在营业时间）"
                    : "柜台没反应（可能站错了格子）");
        }
    }
}
