using System;
using System.Collections.Generic;
using System.Globalization;
using System.IO;
using System.Linq;
using System.Net;
using System.Text;
using System.Text.Json.Nodes;
using System.Threading;
using System.Threading.Tasks;
using StardewValley;
using StardewValley.Characters;
using StardewValley.Menus;

namespace BlindWhaleFarmer
{
    /// <summary>
    /// 给 Python 插件用的轻量 REST 面：GET /state 读状态、POST /command 执行工具、GET /ping。
    /// 只监听 127.0.0.1。状态查询不算“客户端在玩”，不会冻结游戏时间；
    /// 动作执行和 MCP 的 tools/call 走同一条 Tools.Execute 路径。
    /// </summary>
    internal sealed class StateApi
    {
        private readonly ModEntry mod;
        private readonly HttpListener listener = new();
        private System.Threading.CancellationTokenSource cts;
        private long lastActionTicks;

        public int Port { get; }

        public StateApi(ModEntry mod, int port)
        {
            this.mod = mod;
            Port = port;
        }

        public bool IsActive(int idleSeconds)
        {
            long last = Interlocked.Read(ref lastActionTicks);
            return last > 0 && DateTime.UtcNow.Ticks - last < TimeSpan.FromSeconds(Math.Max(10, idleSeconds)).Ticks;
        }

        public void Start()
        {
            listener.Prefixes.Add($"http://127.0.0.1:{Port}/");
            listener.Start();
            cts = new System.Threading.CancellationTokenSource();
            Task.Run(() => AcceptLoop(cts.Token));
        }

        public void Dispose()
        {
            try { cts?.Cancel(); } catch { }
            try { listener.Close(); } catch { }
        }

        private async Task AcceptLoop(System.Threading.CancellationToken ct)
        {
            while (!ct.IsCancellationRequested)
            {
                HttpListenerContext ctx;
                try
                {
                    ctx = await listener.GetContextAsync().ConfigureAwait(false);
                }
                catch
                {
                    if (ct.IsCancellationRequested || !listener.IsListening)
                        return;
                    continue;
                }
                _ = Task.Run(() => Handle(ctx));
            }
        }

        private async Task Handle(HttpListenerContext ctx)
        {
            var req = ctx.Request;
            var resp = ctx.Response;
            try
            {
                string path = (req.Url?.AbsolutePath ?? "/").TrimEnd('/');
                if (path.Length == 0) path = "/";

                if (path == "/ping")
                {
                    await Json(resp, 200, new JsonObject
                    {
                        ["ok"] = true,
                        ["mod"] = "StardewAgent",
                        ["version"] = typeof(StateApi).Assembly.GetName().Version?.ToString(3) ?? "0.7.0",
                        ["mcp"] = mod.Mcp != null,
                        ["save"] = SaveName(),
                    });
                    return;
                }

                if (path == "/screenshot")
                {
                    int before = mod.ScreenshotDone;
                    mod.RequestScreenshot();
                    for (int i = 0; i < 240; i++)
                    {
                        await Task.Delay(16).ConfigureAwait(false);
                        if (mod.ScreenshotDone != before)
                            break;
                    }
                    bool ok = mod.ScreenshotDone != before && string.IsNullOrEmpty(mod.LastScreenshotError);
                    await Json(resp, 200, new JsonObject
                    {
                        ["ok"] = ok,
                        ["path"] = mod.LastScreenshotPath ?? "",
                        ["reason"] = mod.LastScreenshotError ?? "",
                    });
                    return;
                }

                if (path == "/saves")
                {
                    await Json(resp, 200, new JsonObject
                    {
                        ["ok"] = true,
                        ["items"] = new JsonArray(TitleLoader.Saves().Select(s => (JsonNode)JsonValue.Create(s)).ToArray()),
                    });
                    return;
                }

                if (path == "/load" && req.HttpMethod == "POST")
                {
                    string body;
                    using (var rd = new StreamReader(req.InputStream, Encoding.UTF8))
                        body = await rd.ReadToEndAsync();
                    string save = "";
                    try
                    {
                        var payload = JsonNode.Parse(string.IsNullOrWhiteSpace(body) ? "{}" : body) as JsonObject;
                        save = payload?["save"]?.GetValue<string>() ?? "";
                    }
                    catch { }
                    string message = TitleLoader.Begin(save);
                    await Json(resp, 200, new JsonObject { ["ok"] = true, ["message"] = message ?? "" });
                    return;
                }

                if (path == "/farmmap")
                {
                    if (!StardewModdingAPI.Context.IsWorldReady)
                    {
                        await Json(resp, 200, new JsonObject { ["ok"] = false, ["reason"] = "游戏还没进存档" });
                        return;
                    }
                    JsonObject map = null;
                    try
                    {
                        await mod.MainThread.Invoke(() => { map = BuildFarmMap(); return 0; }).ConfigureAwait(false);
                    }
                    catch (Exception ex)
                    {
                        await Json(resp, 500, new JsonObject { ["ok"] = false, ["reason"] = ex.Message });
                        return;
                    }
                    await Json(resp, 200, map ?? new JsonObject { ["ok"] = false });
                    return;
                }

                if (path == "/state")
                {
                    if (!StardewModdingAPI.Context.IsWorldReady)
                    {
                        await Json(resp, 200, new JsonObject { ["ok"] = false, ["ready"] = false, ["reason"] = "游戏还没进存档" });
                        return;
                    }
                    string text = "";
                    JsonObject meta = null;
                    try
                    {
                        await mod.MainThread.Invoke(() =>
                        {
                            text = mod.Observer.Build();
                            meta = BuildMeta();
                            return 0;
                        }).ConfigureAwait(false);
                    }
                    catch (Exception ex)
                    {
                        await Json(resp, 500, new JsonObject { ["ok"] = false, ["reason"] = "读取状态失败：" + ex.Message });
                        return;
                    }
                    await Json(resp, 200, new JsonObject
                    {
                        ["ok"] = true,
                        ["ready"] = true,
                        ["save"] = SaveName(),
                        ["text"] = text ?? "",
                        ["meta"] = meta ?? new JsonObject(),
                    });
                    return;
                }

                if (path == "/cancel")
                {
                    mod.MainThread.CancelCurrent("插件请求取消当前动作");
                    await Json(resp, 200, new JsonObject
                    {
                        ["ok"] = true,
                        ["message"] = "已请求取消当前动作",
                    });
                    return;
                }

                if (path == "/command" && req.HttpMethod == "POST")
                {
                    string body;
                    using (var rd = new StreamReader(req.InputStream, Encoding.UTF8))
                        body = await rd.ReadToEndAsync();
                    JsonObject payload;
                    try
                    {
                        payload = JsonNode.Parse(string.IsNullOrWhiteSpace(body) ? "{}" : body) as JsonObject ?? new JsonObject();
                    }
                    catch (Exception ex)
                    {
                        await Json(resp, 400, new JsonObject { ["ok"] = false, ["reason"] = "bad json: " + ex.Message });
                        return;
                    }
                    string tool = payload["tool"]?.GetValue<string>() ?? payload["name"]?.GetValue<string>();
                    JsonObject args = payload["args"] as JsonObject ?? payload["arguments"] as JsonObject ?? new JsonObject();
                    if (string.IsNullOrWhiteSpace(tool))
                    {
                        await Json(resp, 400, new JsonObject { ["ok"] = false, ["reason"] = "缺少 tool" });
                        return;
                    }
                    Interlocked.Exchange(ref lastActionTicks, DateTime.UtcNow.Ticks);
                    string result = await mod.RunTool(tool, args).ConfigureAwait(false);
                    Interlocked.Exchange(ref lastActionTicks, DateTime.UtcNow.Ticks);
                    bool ok = result != null && result.StartsWith("成功");
                    await Json(resp, 200, new JsonObject
                    {
                        ["ok"] = ok,
                        ["tool"] = tool,
                        ["result"] = result ?? "",
                    });
                    return;
                }

                await Json(resp, 404, new JsonObject { ["ok"] = false, ["reason"] = "not found" });
            }
            catch (Exception ex)
            {
                try { await Json(resp, 500, new JsonObject { ["ok"] = false, ["reason"] = ex.Message }); } catch { }
            }
        }

        private static string SaveName()
        {
            try
            {
                return StardewModdingAPI.Context.IsWorldReady ? (StardewModdingAPI.Constants.SaveFolderName ?? "") : "";
            }
            catch
            {
                return "";
            }
        }

        /// <summary>给插件做结构化判断用的少量字段：时间、体力、金币、背包格子、位置、天气。</summary>
        private JsonObject BuildMeta()
        {
            var me = Game1.player;
            var gm = new JsonObject
            {
                ["year"] = Game1.year,
                ["season"] = Game1.currentSeason ?? "",
                ["day"] = Game1.dayOfMonth,
                ["time"] = Game1.timeOfDay,
                ["raining"] = Game1.isRaining,
                ["snowing"] = Game1.isSnowing,
                ["festival"] = Game1.isFestival(),
                ["day_of_week"] = Game1.shortDayNameFromDayOfSeason(Game1.dayOfMonth),
                ["weather_tomorrow"] = Game1.weatherForTomorrow ?? "",
                ["luck"] = me?.DailyLuck ?? 0.0,
            };
            var player = new JsonObject
            {
                ["name"] = me?.Name ?? "",
                ["location"] = me?.currentLocation?.NameOrUniqueName ?? "",
                ["tile_x"] = me?.TilePoint.X ?? 0,
                ["tile_y"] = me?.TilePoint.Y ?? 0,
                ["energy"] = (int)(me?.Stamina ?? 0),
                ["max_energy"] = (int)(me?.MaxStamina ?? 0),
                ["health"] = me?.health ?? 0,
                ["max_health"] = me?.maxHealth ?? 0,
                ["money"] = me?.Money ?? 0,
                ["inventory_slots"] = me?.MaxItems ?? 36,
                ["used_slots"] = me?.Items?.Count(i => i != null) ?? 0,
                ["has_rod"] = me != null && Util.FindTool<StardewValley.Tools.FishingRod>() >= 0,
                ["skills"] = new JsonObject
                {
                    ["farming"] = me?.FarmingLevel ?? 0,
                    ["mining"] = me?.MiningLevel ?? 0,
                    ["foraging"] = me?.ForagingLevel ?? 0,
                    ["fishing"] = me?.FishingLevel ?? 0,
                    ["combat"] = me?.CombatLevel ?? 0,
                },
                ["professions"] = Professions(),
            };
            var inventory = new JsonArray();
            if (me?.Items != null)
            {
                for (int i = 0; i < me.Items.Count; i++)
                {
                    var item = me.Items[i];
                    if (item == null) continue;
                    inventory.Add(new JsonObject
                    {
                        ["slot"] = i,
                        ["name"] = item.DisplayName ?? item.Name ?? "",
                        ["id"] = item.ItemId ?? "",
                        ["count"] = item.Stack,
                        ["is_tool"] = item is StardewValley.Tool,
                        ["kind"] = item is StardewValley.Tool t ? t.GetType().Name : "",
                        ["category"] = item.Category,
                        ["edible"] = item is StardewValley.Object o ? o.Edibility : 0,
                        ["price"] = SafePrice(item),
                    });
                }
            }
            var farm = new JsonObject();
            try
            {
                var f = Game1.getFarm();
                if (f != null)
                {
                    int crops = 0, ready = 0, thirsty = 0, emptyDirt = 0, debris = 0, trees = 0, grass = 0;
                    foreach (var pair in f.terrainFeatures.Pairs)
                    {
                        if (pair.Value is StardewValley.TerrainFeatures.HoeDirt hd)
                        {
                            if (hd.crop != null && !hd.crop.dead.Value)
                            {
                                crops++;
                                if (hd.readyForHarvest()) ready++;
                                else if (Observer.NeedsWater(hd)) thirsty++;
                            }
                            else if (hd.crop == null)
                            {
                                emptyDirt++;
                            }
                        }
                        else if (pair.Value is StardewValley.TerrainFeatures.Tree) trees++;
                        else if (pair.Value is StardewValley.TerrainFeatures.Grass) grass++;
                    }
                    foreach (var obj in f.objects.Values)
                    {
                        if (obj != null && (obj.IsSpawnedObject || obj.Name == "Weeds" || obj.ParentSheetIndex == 343 || obj.ParentSheetIndex == 450)) debris++;
                    }
                    farm["crops"] = crops;
                    farm["ready"] = ready;
                    farm["thirsty"] = thirsty;
                    farm["empty_dirt"] = emptyDirt;
                    farm["debris"] = debris;
                    farm["trees"] = trees;
                    farm["grass"] = grass;
                    farm["animals"] = f.animals?.Length ?? 0;
                    farm["buildings"] = f.buildings?.Count ?? 0;
                    farm["hay"] = f.piecesOfHay.Value;
                }
            }
            catch { }
            var npcs = new JsonArray();
            var pets = new JsonArray();
            try
            {
                if (Game1.currentLocation?.characters != null)
                {
                    foreach (var npc in Game1.currentLocation.characters)
                    {
                        if (npc == null || npc.IsInvisible)
                            continue;
                        if (npc is Pet)
                        {
                            pets.Add(new JsonObject
                            {
                                ["name"] = npc.Name ?? "",
                                ["display"] = npc.displayName ?? npc.Name ?? "",
                                ["x"] = npc.TilePoint.X,
                                ["y"] = npc.TilePoint.Y,
                                ["location"] = Game1.currentLocation.NameOrUniqueName ?? "",
                            });
                            continue;
                        }
                        bool villager = npc.IsVillager;
                        bool monster = npc is StardewValley.Monsters.Monster;
                        if (!villager && !monster)
                            continue;
                        npcs.Add(new JsonObject
                        {
                            ["name"] = npc.Name ?? "",
                            ["display"] = npc.displayName ?? npc.Name ?? "",
                            ["x"] = npc.TilePoint.X,
                            ["y"] = npc.TilePoint.Y,
                            ["villager"] = villager,
                            ["monster"] = monster,
                        });
                    }
                }
            }
            catch { }

            // 宠物可能在农舍/农场，不在当前地图：扫一遍所有地点，方便主动去找它
            try
            {
                foreach (var loc in Game1.locations)
                {
                    if (loc == null || loc == Game1.currentLocation || loc.characters == null)
                        continue;
                    foreach (var npc in loc.characters)
                    {
                        if (npc is not Pet)
                            continue;
                        pets.Add(new JsonObject
                        {
                            ["name"] = npc.Name ?? "",
                            ["display"] = npc.displayName ?? npc.Name ?? "",
                            ["x"] = npc.TilePoint.X,
                            ["y"] = npc.TilePoint.Y,
                            ["location"] = loc.NameOrUniqueName ?? "",
                        });
                        if (pets.Count >= 8)
                            break;
                    }
                    if (pets.Count >= 8)
                        break;
                }
            }
            catch { }

            var forageables = new JsonArray();
            try
            {
                var loc = Game1.currentLocation;
                if (loc?.objects != null)
                {
                    foreach (var pair in loc.objects.Pairs)
                    {
                        var obj = pair.Value;
                        if (obj == null || !obj.IsSpawnedObject)
                            continue;
                        forageables.Add(new JsonObject
                        {
                            ["name"] = obj.DisplayName ?? obj.Name ?? "",
                            ["x"] = (int)pair.Key.X,
                            ["y"] = (int)pair.Key.Y,
                        });
                        if (forageables.Count >= 20)
                            break;
                    }
                }
            }
            catch { }

            return new JsonObject
            {
                ["game"] = gm,
                ["player"] = player,
                ["inventory"] = inventory,
                ["farm"] = farm,
                ["menu"] = MenuInfo(),
                ["npcs"] = npcs,
                ["pets"] = pets,
                ["forageables"] = forageables,
            };
        }

        /// <summary>当前界面：类型 / 是否职业选择 / 候选职业 / 对话选项。Python 侧据此决定先处理界面。</summary>
        /// <summary>
        /// 农场宏观记忆图：每 4×4 格压成一个块，块里只记“作物/成熟/待浇/树/草/杂物/空耕地”的数量。
        /// 不是逐格地图，只给模型看大局和变化。
        /// </summary>
        private static JsonObject BuildFarmMap()
        {
            var farm = Game1.getFarm();
            if (farm == null)
                return new JsonObject { ["ok"] = false, ["reason"] = "农场未加载" };
            int width = 80, height = 65;
            try
            {
                width = farm.map.Layers[0].LayerWidth;
                height = farm.map.Layers[0].LayerHeight;
            }
            catch { }
            const int block = 4;
            int cols = (width + block - 1) / block;
            int rows = (height + block - 1) / block;
            var cells = new int[cols * rows, 7];
            int totalCrop = 0, totalReady = 0, totalThirsty = 0, totalTree = 0;
            int totalGrass = 0, totalDebris = 0, totalEmpty = 0;

            void Add(int x, int y, int kind)
            {
                if (x < 0 || y < 0 || x >= cols || y >= rows)
                    return;
                cells[y * cols + x, kind]++;
            }

            try
            {
                foreach (var pair in farm.terrainFeatures.Pairs)
                {
                    int bx = (int)pair.Key.X / block;
                    int by = (int)pair.Key.Y / block;
                    if (pair.Value is StardewValley.TerrainFeatures.HoeDirt hd)
                    {
                        if (hd.crop != null && !hd.crop.dead.Value)
                        {
                            Add(bx, by, 0);
                            totalCrop++;
                            if (hd.readyForHarvest()) { Add(bx, by, 1); totalReady++; }
                            else if (Observer.NeedsWater(hd)) { Add(bx, by, 2); totalThirsty++; }
                        }
                        else if (hd.crop == null)
                        {
                            Add(bx, by, 6);
                            totalEmpty++;
                        }
                    }
                    else if (pair.Value is StardewValley.TerrainFeatures.Tree)
                    {
                        Add(bx, by, 3);
                        totalTree++;
                    }
                    else if (pair.Value is StardewValley.TerrainFeatures.Grass)
                    {
                        Add(bx, by, 4);
                        totalGrass++;
                    }
                }
                foreach (var pair in farm.objects.Pairs)
                {
                    var obj = pair.Value;
                    if (obj == null)
                        continue;
                    bool debris = obj.IsSpawnedObject || obj.Name == "Weeds"
                                  || obj.ParentSheetIndex == 343 || obj.ParentSheetIndex == 450;
                    if (!debris)
                        continue;
                    Add((int)pair.Key.X / block, (int)pair.Key.Y / block, 5);
                    totalDebris++;
                }
            }
            catch { }

            var blocks = new JsonArray();
            for (int y = 0; y < rows; y++)
            {
                for (int x = 0; x < cols; x++)
                {
                    int i = y * cols + x;
                    if (cells[i, 0] == 0 && cells[i, 3] == 0 && cells[i, 4] == 0
                        && cells[i, 5] == 0 && cells[i, 6] == 0)
                        continue;
                    blocks.Add(new JsonObject
                    {
                        ["x"] = x * block,
                        ["y"] = y * block,
                        ["crop"] = cells[i, 0],
                        ["ready"] = cells[i, 1],
                        ["thirsty"] = cells[i, 2],
                        ["tree"] = cells[i, 3],
                        ["grass"] = cells[i, 4],
                        ["debris"] = cells[i, 5],
                        ["empty_dirt"] = cells[i, 6],
                    });
                }
            }

            return new JsonObject
            {
                ["ok"] = true,
                ["day"] = store_day(),
                ["block"] = block,
                ["width"] = width,
                ["height"] = height,
                ["summary"] = new JsonObject
                {
                    ["crops"] = totalCrop,
                    ["ready"] = totalReady,
                    ["thirsty"] = totalThirsty,
                    ["trees"] = totalTree,
                    ["grass"] = totalGrass,
                    ["debris"] = totalDebris,
                    ["empty_dirt"] = totalEmpty,
                },
                ["blocks"] = blocks,
            };
        }

        private static string store_day()
        {
            try
            {
                return string.Format("{0:0000}_{1}_{2:00}", Game1.year, Game1.currentSeason, Game1.dayOfMonth);
            }
            catch
            {
                return "";
            }
        }

        private static JsonObject MenuInfo()
        {
            var result = new JsonObject { ["type"] = "", ["is_profession_chooser"] = false };
            try
            {
                var menu = Game1.activeClickableMenu;
                if (menu == null && !Game1.dialogueUp)
                    return result;
                if (Game1.dialogueUp && menu == null)
                {
                    result["type"] = "Dialogue";
                    return result;
                }
                result["type"] = menu.GetType().Name;
                if (menu is LevelUpMenu lvl)
                {
                    result["is_profession_chooser"] = lvl.isProfessionChooser;
                    var choices = new JsonArray();
                    var ids = new List<int>();
                    try
                    {
                        var field = typeof(LevelUpMenu).GetField("professionsToChoose",
                            System.Reflection.BindingFlags.Public | System.Reflection.BindingFlags.NonPublic
                            | System.Reflection.BindingFlags.Instance);
                        if (field?.GetValue(menu) is List<int> found)
                            ids = found;
                    }
                    catch { }
                    if (ids != null)
                    {
                        foreach (var id in ids)
                        {
                            string name = "";
                            string desc = "";
                            try
                            {
                                // 不同版本方法名不一样，统一走反射，拿不到就留空。
                                var titleMethod = typeof(LevelUpMenu).GetMethod("getProfessionTitleFromNumber",
                                    System.Reflection.BindingFlags.Public | System.Reflection.BindingFlags.NonPublic
                                    | System.Reflection.BindingFlags.Static);
                                if (titleMethod != null)
                                    name = titleMethod.Invoke(null, new object[] { id }) as string ?? "";
                                var descMethod = typeof(LevelUpMenu).GetMethod("getProfessionDescription",
                                    System.Reflection.BindingFlags.Public | System.Reflection.BindingFlags.NonPublic
                                    | System.Reflection.BindingFlags.Static);
                                if (descMethod != null && descMethod.Invoke(null, new object[] { id }) is string[] lines)
                                    desc = string.Join(" ", lines);
                            }
                            catch { }
                            choices.Add(new JsonObject
                            {
                                ["id"] = id,
                                ["name"] = name,
                                ["desc"] = desc,
                            });
                        }
                    }
                    result["choices"] = choices;
                }
                else if (menu is DialogueBox box)
                {
                    result["type"] = "Dialogue";
                    try
                    {
                        result["text"] = box.getCurrentString() ?? "";
                        var options = new JsonArray();
                        if (box.responses != null)
                        {
                            foreach (var response in box.responses)
                            {
                                if (response != null && !string.IsNullOrEmpty(response.responseText))
                                    options.Add(response.responseText);
                            }
                        }
                        result["options"] = options;
                        result["is_question"] = box.isQuestion;
                    }
                    catch { }
                }
                else if (menu is ShippingMenu)
                {
                    result["type"] = "ShippingMenu";
                }
            }
            catch
            {
            }
            return result;
        }

        private static int SafePrice(Item item)
        {
            try { return Math.Max(0, item.salePrice()); } catch { return 0; }
        }

        private static JsonArray Professions()
        {
            var result = new JsonArray();
            try
            {
                var set = Game1.player?.professions;
                if (set != null)
                {
                    foreach (var id in set)
                        result.Add(JsonValue.Create(id.ToString()));
                }
            }
            catch { }
            return result;
        }

        private static async Task Json(HttpListenerResponse resp, int status, JsonObject body)
        {
            byte[] bytes = Encoding.UTF8.GetBytes(body.ToJsonString());
            resp.StatusCode = status;
            resp.ContentType = "application/json; charset=utf-8";
            resp.ContentLength64 = bytes.Length;
            resp.Headers["Cache-Control"] = "no-store";
            await resp.OutputStream.WriteAsync(bytes, 0, bytes.Length);
            resp.Close();
        }
    }
}
