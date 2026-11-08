using System;
using System.Collections.Generic;
using System.Linq;
using Microsoft.Xna.Framework;
using StardewValley;
using StardewValley.Locations;
using StardewValley.Menus;
using StardewValley.Objects;

namespace BlindWhaleFarmer
{
    internal sealed partial class GameActions
    {
        /// <summary>找当前场景里的电视（家具）。</summary>
        private static Furniture FindTv(GameLocation location)
        {
            if (location?.furniture == null)
                return null;
            foreach (var item in location.furniture.OfType<Furniture>())
            {
                if (item == null)
                    continue;
                try
                {
                    if (item.HasContextTag("tv_item"))
                        return item;
                }
                catch { }
                string id = item.QualifiedItemId ?? "";
                if (id == "(F)1466" || id == "(F)1468" || id == "(F)1680" || id == "(F)2326")
                    return item;
                string name = item.Name ?? "";
                if (name.IndexOf("TV", StringComparison.OrdinalIgnoreCase) >= 0
                    || name.IndexOf("电视", StringComparison.Ordinal) >= 0)
                    return item;
            }
            return null;
        }

        /// <summary>
        /// 看电视：走到电视前 → 打开 → 选频道（默认天气预报）→ 看一会儿 → 关掉。
        /// 节目台词收进结果里，Python 侧可以写进当天的日志/记忆。
        /// </summary>
        public IEnumerable<object> WatchTv(string channel)
        {
            channel = string.IsNullOrEmpty(channel) ? "Weather" : channel.Trim();
            if (Blocked(out string why))
            {
                yield return ActionResult.Fail(why);
                yield break;
            }

            if (!(Loc is FarmHouse))
            {
                var go = new Outcome();
                foreach (var s in TravelInner("FarmHouse", go))
                    yield return s;
                if (!go.Ok)
                {
                    yield return ActionResult.Fail("回不了家：" + go.Message);
                    yield break;
                }
            }

            var tv = FindTv(Loc);
            if (tv == null)
            {
                yield return ActionResult.Fail("屋子里没有电视");
                yield break;
            }
            Point tile = new Point((int)tv.TileLocation.X, (int)tv.TileLocation.Y);

            foreach (var s in WaitPlayerFree())
                yield return s;

            // 电视是贴墙家具：用家具占地格找可站的格子，优先正下方
            var stands = new List<Point>();
            int wide = 1, high = 1;
            try
            {
                wide = Math.Max(1, tv.getTilesWide());
                high = Math.Max(1, tv.getTilesHigh());
            }
            catch { }
            for (int dx = 0; dx < wide; dx++)
            {
                for (int dy = 0; dy < high; dy++)
                {
                    var occupied = new Point(tile.X + dx, tile.Y + dy);
                    stands.AddRange(Pathfinder.AdjacentStandTiles(Loc, occupied));
                }
            }
            stands = stands.Distinct().ToList();
            if (stands.Count == 0)
                stands = Pathfinder.NearestStandTiles(Loc, tile, 4);
            if (stands.Count == 0)
            {
                yield return ActionResult.Fail("电视前面站不了人");
                yield break;
            }
            var front = stands.Where(p => p.Y == tile.Y + 1).ToList();
            if (front.Count > 0)
                stands = front;
            var origin = Player.TilePoint;
            stands = stands.OrderBy(p => Math.Abs(p.X - origin.X) + Math.Abs(p.Y - origin.Y)).ToList();

            var walkOutcome = new Outcome();
            foreach (var s in GoToAny(stands, walkOutcome, "电视"))
                yield return s;
            if (!walkOutcome.Ok)
            {
                yield return ActionResult.Fail("走不到电视前：" + walkOutcome.Message);
                yield break;
            }

            Face(tile);
            var tvNow = FindTv(Loc) ?? tv;
            tile = new Point((int)tvNow.TileLocation.X, (int)tvNow.TileLocation.Y);
            bool handled = false;
            try
            {
                handled = Loc.checkAction(new xTile.Dimensions.Location(tile.X, tile.Y), Game1.viewport, Player);
            }
            catch { }
            if (!handled)
            {
                try { handled = tvNow.checkForAction(Player); }
                catch { }
            }
            foreach (var s in WaitTicks(20))
                yield return s;

            // 频道选择：DialogueBox 的 responses 里按 key/文字匹配
            var box = Game1.activeClickableMenu as DialogueBox;
            if (box != null && box.isQuestion && box.responses != null && box.responses.Length > 0)
            {
                int pick = -1;
                string want = channel.ToLowerInvariant();
                for (int i = 0; i < box.responses.Length; i++)
                {
                    string key = (box.responses[i].responseKey ?? "").ToLowerInvariant();
                    string text = (box.responses[i].responseText ?? "").ToLowerInvariant();
                    if (key.Contains(want) || text.Contains(want)
                        || (want.StartsWith("weather") && (key.Contains("weather") || text.Contains("天气")))
                        || (want.StartsWith("fortune") && (key.Contains("fortune") || text.Contains("运势")))
                        || (want.StartsWith("program") && (key.Contains("land") || key.Contains("sauce") || text.Contains("节目"))))
                    {
                        pick = i;
                        break;
                    }
                }
                if (pick < 0)
                    pick = 0;
                try
                {
                    box.selectedResponse = pick;
                    box.receiveLeftClick(Game1.uiViewport.Width / 2, Game1.uiViewport.Height - 40, true);
                }
                catch { }
                foreach (var s in WaitTicks(15))
                    yield return s;
            }

            // 让节目演一会儿，把台词记下来
            string program = "";
            string lastLine = "";
            int lastClick = -1;
            for (int tick = 0; tick < 300; tick++)
            {
                var current = Game1.activeClickableMenu as DialogueBox;
                if (current != null)
                {
                    try
                    {
                        string line = current.getCurrentString() ?? "";
                        if (!string.IsNullOrEmpty(line) && line != lastLine && program.Length < 600)
                        {
                            program += line;
                            lastLine = line;
                        }
                    }
                    catch { }
                    if (current.isQuestion)
                    {
                        try { current.receiveLeftClick(Game1.uiViewport.Width / 2, Game1.uiViewport.Height - 40, true); }
                        catch { }
                    }
                    else if (tick - lastClick > 12)
                    {
                        lastClick = tick;
                        try { current.receiveLeftClick(Game1.uiViewport.Width / 2, Game1.uiViewport.Height - 40, true); }
                        catch { }
                    }
                }
                yield return null;
            }

            try
            {
                if (Game1.activeClickableMenu != null)
                    Game1.exitActiveMenu();
            }
            catch { }

            string summary = string.IsNullOrWhiteSpace(program) ? "看完了电视" : "看完了电视：" + program.Trim();
            yield return ActionResult.Success(summary.Length > 300 ? summary.Substring(0, 300) : summary);
        }
    }
}
