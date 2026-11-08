using System;
using System.Collections.Generic;
using System.IO;
using System.Linq;
using System.Reflection;
using Microsoft.Xna.Framework;
using StardewModdingAPI;
using StardewValley;
using StardewValley.Menus;

namespace BlindWhaleFarmer
{
    /// <summary>
    /// 在标题界面自动「继续游戏」：等价于真人点「读取存档 → 第一个存档（最近玩的）」。
    /// 这样重启游戏后不用人手点，AI 自己就能接着玩。
    /// </summary>
    internal static class TitleLoader
    {
        private static readonly BindingFlags All = BindingFlags.Public | BindingFlags.NonPublic | BindingFlags.Instance | BindingFlags.Static;
        private static int waitTicks;
        private static int clicks;
        private static string preferred;

        public static string SavesDir
        {
            get
            {
                return Path.Combine(
                    Environment.GetFolderPath(Environment.SpecialFolder.ApplicationData),
                    "StardewValley", "Saves");
            }
        }

        public static string[] Saves()
        {
            var result = new List<string>();
            try
            {
                if (Directory.Exists(SavesDir))
                    result.AddRange(new DirectoryInfo(SavesDir).GetDirectories().Select(d => d.Name));
            }
            catch
            {
            }
            result.Sort(StringComparer.OrdinalIgnoreCase);
            return result.ToArray();
        }

        public static string NewestSaveName()
        {
            try
            {
                if (!Directory.Exists(SavesDir))
                    return null;
                DirectoryInfo newest = new DirectoryInfo(SavesDir)
                    .GetDirectories()
                    .OrderByDescending(dir => dir.LastWriteTimeUtc)
                    .FirstOrDefault();
                return newest?.Name;
            }
            catch
            {
                return null;
            }
        }

        /// <summary>开始自动读档；save 为空时读最近修改的存档。</summary>
        public static string Begin(string save)
        {
            preferred = string.IsNullOrWhiteSpace(save) ? NewestSaveName() : save;
            waitTicks = 0;
            clicks = 0;
            return string.IsNullOrEmpty(preferred) ? "找不到任何存档" : "准备读取：" + preferred;
        }

        /// <summary>每帧由 ModEntry 调用；读到存档或放弃时返回 true。</summary>
        public static bool Tick()
        {
            if (Context.IsWorldReady)
                return true;
            if (string.IsNullOrEmpty(preferred))
                return true;
            if (Game1.activeClickableMenu is not TitleMenu title)
                return false;

            waitTicks++;
            // 等标题按钮/背景加载完
            if (waitTicks < 60)
                return false;
            if (waitTicks > 10800)
            {
                preferred = null;
                return true;
            }

            // 游戏自带「直接读这个存档」入口：debugSaveFileToTry（和真人在标题界面读档等价）
            if (SetDebugSave(title, preferred))
            {
                ClickButton(title, "load");
                return false;
            }

            // 兜底：点「读取存档」，再点第一个存档项
            if (clicks == 0)
            {
                if (ClickButton(title, "load"))
                    clicks = 1;
                return false;
            }
            if (TitleMenu.subMenu is LoadGameMenu load)
            {
                // 存档列表是异步读出来的：读到之前每帧重试，别因为“点了没反应”就放弃
                if (ClickFirstSlot(load))
                    clicks++;
            }
            return false;
        }

        private static bool SetDebugSave(TitleMenu menu, string saveName)
        {
            if (menu == null || string.IsNullOrEmpty(saveName))
                return false;
            try
            {
                var field = typeof(TitleMenu).GetField("debugSaveFileToTry", All);
                if (field == null)
                    return false;
                field.SetValue(menu, saveName);
                return true;
            }
            catch
            {
                return false;
            }
        }

        private static bool ClickButton(TitleMenu menu, string namePart)
        {
            if (menu?.buttons == null)
                return false;
            foreach (ClickableTextureComponent button in menu.buttons)
            {
                if (button == null)
                    continue;
                if ((button.name ?? "").IndexOf(namePart, StringComparison.OrdinalIgnoreCase) < 0)
                    continue;
                Point center = button.bounds.Center;
                menu.receiveLeftClick(center.X, center.Y, true);
                return true;
            }
            return false;
        }

        private static bool ClickFirstSlot(LoadGameMenu load)
        {
            if (load == null)
                return false;
            try
            {
                var slots = load.slotButtons;
                if (slots == null || slots.Count == 0)
                    return false;
                ClickableComponent slot = slots[0];
                Point center = slot.bounds.Center;
                load.receiveLeftClick(center.X, center.Y, true);
                return true;
            }
            catch
            {
                return false;
            }
        }
    }
}
