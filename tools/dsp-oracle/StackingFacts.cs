using System;
using System.Collections.Generic;
using System.Globalization;
using System.Reflection;

namespace FlabOracle
{
    /// <summary>
    /// A one-shot dump of everything the game knows about cargo stacking: the
    /// sorter cargo-stacking research table, the sorter component's stack fields,
    /// and the Automatic Piler.
    ///
    /// Same rule as the rest of the plugin: nothing here reimplements a game rule.
    /// Every number is read from <c>LDB</c>, from <c>GameMain.history</c>, from a
    /// live component, or (for the handful of facts the game keeps as IL literals
    /// rather than fields) is quoted with the exact method it was read out of and
    /// flagged <c>"observed": false</c> so the transcriber can see the difference.
    /// Reflection is used wherever the question is "which fields exist", so the
    /// answer is the assembly's, not a guess of ours.
    /// </summary>
    internal static class StackingFacts
    {
        internal const string SchemaId = "flab2bp-stacking/1";

        /// <summary>
        /// UnlockFunctions that <c>GameHistoryData.UnlockTechFunction</c> routes to
        /// a sorter-stacking field. 14 -> inserterStackCountObsolete, 39 ->
        /// inserterStackOutput, 40 -> inserterBidirectional, 41 -> inserterStackInput.
        /// </summary>
        private static readonly int[] StackUnlockFunctions = { 14, 39, 40, 41 };

        /// <summary>Cap on how many live components a single dump enumerates.</summary>
        private const int MaxLiveRows = 256;

        internal static string Serialize(string trigger)
        {
            JsonWriter w = new JsonWriter();
            w.BeginObject();
            w.Prop("schema", SchemaId);
            w.Prop("trigger", trigger);
            w.Prop("utcTime", DateTime.UtcNow.ToString("o", CultureInfo.InvariantCulture));
            w.Prop("gameVersion", ReadGameVersion());
            w.Prop("inGame", GameMain.data != null);

            WriteTechs(w);
            WriteHistory(w);
            WritePrefabs(w);
            WriteBelts(w);
            WriteSorterFacts(w);
            WritePilerFacts(w);
            WriteLive(w);

            w.EndObject();
            return w.ToString();
        }

        private static string ReadGameVersion()
        {
            try
            {
                // GameConfig.gameVersion is the game's own version object.
                return GameConfig.gameVersion.ToString();
            }
            catch (Exception e)
            {
                return "unavailable: " + e.Message;
            }
        }

        // ------------------------------------------------------------------
        // Research
        // ------------------------------------------------------------------

        /// <summary>
        /// Every TechProto that touches sorter stacking, selected by the unlock
        /// function ids the game itself switches on rather than by an English
        /// name, so the selection survives a localisation change. Techs whose
        /// name mentions stacking or the piler are included as well, so a tech
        /// that grants the ability by some other route still shows up.
        /// </summary>
        private static void WriteTechs(JsonWriter w)
        {
            w.BeginArray("techs");
            try
            {
                TechProto[] techs = LDB.techs.dataArray;
                for (int i = 0; i < techs.Length; i++)
                {
                    TechProto t = techs[i];
                    if (t == null || !TechIsInteresting(t))
                    {
                        continue;
                    }

                    w.BeginObject();
                    w.Prop("ID", t.ID);
                    w.Prop("Name", t.Name);
                    w.Prop("translatedName", SafeTranslatedName(t));
                    w.Prop("Level", t.Level);
                    w.Prop("MaxLevel", t.MaxLevel);
                    w.Prop("Published", t.Published);
                    w.Prop("IsObsolete", t.IsObsolete);
                    w.PropIntArray("UnlockFunctions", t.UnlockFunctions);
                    w.PropDoubleArray("UnlockValues", t.UnlockValues);
                    w.PropIntArray("UnlockRecipes", t.UnlockRecipes);
                    w.PropIntArray("PropertyOverrideItems", t.PropertyOverrideItems);
                    w.PropIntArray("PropertyItemCounts", t.PropertyItemCounts);
                    w.PropIntArray("PreTechs", t.PreTechs);
                    w.Prop("HashNeeded", t.HashNeeded);
                    WriteTechState(w, t.ID);
                    w.EndObject();
                }
            }
            catch (Exception e)
            {
                w.BeginObject();
                w.Prop("error", e.ToString());
                w.EndObject();
            }

            w.EndArray();
        }

        private static bool TechIsInteresting(TechProto t)
        {
            int[] funcs = t.UnlockFunctions;
            if (funcs != null)
            {
                for (int i = 0; i < funcs.Length; i++)
                {
                    for (int j = 0; j < StackUnlockFunctions.Length; j++)
                    {
                        if (funcs[i] == StackUnlockFunctions[j])
                        {
                            return true;
                        }
                    }
                }
            }

            return NameMentionsStacking(t.Name) || NameMentionsStacking(SafeTranslatedName(t));
        }

        private static bool NameMentionsStacking(string name)
        {
            if (string.IsNullOrEmpty(name))
            {
                return false;
            }

            return name.IndexOf("stack", StringComparison.OrdinalIgnoreCase) >= 0
                || name.IndexOf("pile", StringComparison.OrdinalIgnoreCase) >= 0;
        }

        /// <summary>The translated name goes through the localisation tables, which
        /// are not guaranteed to be loaded; never let that cost the dump.</summary>
        private static string SafeTranslatedName(Proto p)
        {
            try
            {
                return p.name;
            }
            catch (Exception)
            {
                return null;
            }
        }

        private static void WriteTechState(JsonWriter w, int techId)
        {
            GameHistoryData history = SafeHistory();
            if (history == null || history.techStates == null)
            {
                w.Prop("techState", (string)null);
                return;
            }

            TechState state;
            if (!history.techStates.TryGetValue(techId, out state))
            {
                w.Prop("techState", (string)null);
                return;
            }

            w.BeginObject("techState");
            w.Prop("unlocked", state.unlocked);
            w.Prop("curLevel", state.curLevel);
            w.Prop("maxLevel", state.maxLevel);
            w.Prop("hashUploaded", state.hashUploaded);
            w.Prop("hashNeeded", state.hashNeeded);
            w.EndObject();
        }

        private static GameHistoryData SafeHistory()
        {
            try
            {
                if (GameMain.data == null)
                {
                    return null;
                }

                return GameMain.data.history;
            }
            catch (Exception)
            {
                return null;
            }
        }

        /// <summary>
        /// The live values the research has already produced. These are the fields
        /// UnlockTechFunction writes (cases 14, 39, 40, 41) and the ones
        /// GameData.OnInserterTechChange then copies onto every sorter.
        /// </summary>
        private static void WriteHistory(JsonWriter w)
        {
            GameHistoryData h = SafeHistory();
            if (h == null)
            {
                w.Prop("history", (string)null);
                return;
            }

            w.BeginObject("history");
            w.Prop("inserterStackCountObsolete", h.inserterStackCountObsolete);
            w.Prop("inserterStackInput", h.inserterStackInput);
            w.Prop("inserterStackOutput", h.inserterStackOutput);
            w.Prop("inserterBidirectional", h.inserterBidirectional);
            w.Prop("stationPilerLevel", h.stationPilerLevel);
            w.EndObject();
        }

        // ------------------------------------------------------------------
        // Prefabs
        // ------------------------------------------------------------------

        /// <summary>
        /// Every PrefabDesc field whose name mentions pile or stack, discovered by
        /// reflection over the type rather than named by us, written for every item
        /// whose prefab is a sorter or a piler.
        /// </summary>
        private static void WritePrefabs(JsonWriter w)
        {
            FieldInfo[] stackFields = StackNamedFields(typeof(PrefabDesc));

            w.BeginArray("prefabDescStackFieldNames");
            for (int i = 0; i < stackFields.Length; i++)
            {
                w.BeginObject();
                w.Prop("field", stackFields[i].Name);
                w.Prop("type", stackFields[i].FieldType.FullName);
                w.EndObject();
            }

            w.EndArray();

            w.BeginArray("items");
            try
            {
                ItemProto[] items = LDB.items.dataArray;
                for (int i = 0; i < items.Length; i++)
                {
                    ItemProto item = items[i];
                    if (item == null)
                    {
                        continue;
                    }

                    PrefabDesc desc = item.prefabDesc;
                    if (desc == null || (!desc.isInserter && !desc.isPiler))
                    {
                        continue;
                    }

                    w.BeginObject();
                    w.Prop("ID", item.ID);
                    w.Prop("Name", item.Name);
                    w.Prop("translatedName", SafeTranslatedName(item));
                    w.Prop("isInserter", desc.isInserter);
                    w.Prop("isPiler", desc.isPiler);
                    w.Prop("inserterGrade", desc.inserterGrade);
                    w.Prop("inserterSTT", desc.inserterSTT);
                    w.Prop("inserterDelay", desc.inserterDelay);
                    w.BeginObject("stackNamedFields");
                    WriteFieldValues(w, stackFields, desc);
                    w.EndObject();
                    w.EndObject();
                }
            }
            catch (Exception e)
            {
                w.BeginObject();
                w.Prop("error", e.ToString());
                w.EndObject();
            }

            w.EndArray();
        }

        private static FieldInfo[] StackNamedFields(Type type)
        {
            List<FieldInfo> hits = new List<FieldInfo>();
            FieldInfo[] all = type.GetFields(BindingFlags.Public | BindingFlags.Instance);
            for (int i = 0; i < all.Length; i++)
            {
                string name = all[i].Name;
                if (name.IndexOf("stack", StringComparison.OrdinalIgnoreCase) >= 0
                    || name.IndexOf("pile", StringComparison.OrdinalIgnoreCase) >= 0)
                {
                    hits.Add(all[i]);
                }
            }

            return hits.ToArray();
        }

        private static void WriteFieldValues(JsonWriter w, FieldInfo[] fields, object target)
        {
            for (int i = 0; i < fields.Length; i++)
            {
                object value;
                try
                {
                    value = fields[i].GetValue(target);
                }
                catch (Exception e)
                {
                    w.Prop(fields[i].Name, "error: " + e.Message);
                    continue;
                }

                if (value == null)
                {
                    w.Prop(fields[i].Name, (string)null);
                }
                else if (value is bool)
                {
                    w.Prop(fields[i].Name, (bool)value);
                }
                else if (value is int)
                {
                    w.Prop(fields[i].Name, (int)value);
                }
                else if (value is byte)
                {
                    w.Prop(fields[i].Name, (int)(byte)value);
                }
                else if (value is short)
                {
                    w.Prop(fields[i].Name, (int)(short)value);
                }
                else if (value is float)
                {
                    w.Prop(fields[i].Name, (float)value);
                }
                else if (value is double)
                {
                    w.Prop(fields[i].Name, (double)value);
                }
                else
                {
                    w.Prop(fields[i].Name, Convert.ToString(value, CultureInfo.InvariantCulture));
                }
            }
        }

        /// <summary>
        /// Belt tiers, because the piler's rate is a belt rate: PilerComponent
        /// charges by <c>beltSpeed * 1000</c> per tick and spends 10000 per cargo,
        /// so a piler on a belt of speed s moves 60 * s * 1000 / 10000 cargo per
        /// second. The divisor and the multiplier both come from
        /// PilerComponent.InternalUpdate; the speeds come from the game's protos.
        /// </summary>
        private static void WriteBelts(JsonWriter w)
        {
            w.BeginArray("belts");
            try
            {
                byte[] cd = ReadPilerCdTickArray();
                ItemProto[] items = LDB.items.dataArray;
                for (int i = 0; i < items.Length; i++)
                {
                    ItemProto item = items[i];
                    if (item == null || item.prefabDesc == null || !item.prefabDesc.isBelt)
                    {
                        continue;
                    }

                    int speed = item.prefabDesc.beltSpeed;
                    w.BeginObject();
                    w.Prop("ID", item.ID);
                    w.Prop("Name", item.Name);
                    w.Prop("translatedName", SafeTranslatedName(item));
                    w.Prop("beltSpeed", speed);
                    // Not the belt's own reported rate: computed from the piler's constants
                    // (60 ticks/s, 10000 ticks-per-cargo, i.e. kCargoLength 10 * 1000 charge
                    // per tick per belt speed -- see WriteBelts's doc comment). It only
                    // coincides with the belt's own throughput because both derive from the
                    // same beltSpeed.
                    w.Prop("pilerCargoPerSecond", speed * 60000.0 / 10000.0);
                    int clamped = speed > 2 ? 3 : speed;
                    if (cd != null && clamped >= 1 && clamped <= cd.Length)
                    {
                        w.Prop("pilerClampedSpeedIndex", clamped);
                        w.Prop("pilerCacheCdTicks", cd[clamped - 1]);
                    }
                    else
                    {
                        w.Prop("pilerClampedSpeedIndex", clamped);
                        w.Prop("pilerCacheCdTicks", (string)null);
                    }

                    w.EndObject();
                }
            }
            catch (Exception e)
            {
                w.BeginObject();
                w.Prop("error", e.ToString());
                w.EndObject();
            }

            w.EndArray();
        }

        // ------------------------------------------------------------------
        // Sorters
        // ------------------------------------------------------------------

        private static void WriteSorterFacts(JsonWriter w)
        {
            w.BeginObject("sorter");

            w.BeginArray("componentStackFieldNames");
            FieldInfo[] fields = StackNamedFields(typeof(InserterComponent));
            for (int i = 0; i < fields.Length; i++)
            {
                w.BeginObject();
                w.Prop("field", fields[i].Name);
                w.Prop("type", fields[i].FieldType.FullName);
                w.EndObject();
            }

            w.EndArray();

            // Read out of GameData.OnInserterTechChange and FactorySystem.NewInserterComponent,
            // which are the only two places that assign stackInput/stackOutput.
            w.BeginArray("gradeRules");
            WriteGradeRule(w, 3, "inserterStackCountObsolete", "1", false,
                "GameData.OnInserterTechChange: grade == 3 (stackInput = inserterStackCountObsolete, " +
                "stackOutput forced to 1). FactorySystem.NewInserterComponent (FactorySystem.cs:534-554) " +
                "and the upgrade path in PlanetFactory.cs:1822-1845 apply the same values using grade >= 3.");
            WriteGradeRule(w, 4, "inserterStackInput", "inserterStackOutput", true,
                "GameData.OnInserterTechChange: grade == 4 (stackInput = inserterStackInput, stackOutput = " +
                "inserterStackOutput, bidirectional from history). FactorySystem.NewInserterComponent " +
                "(FactorySystem.cs:534-554) and the upgrade path in PlanetFactory.cs:1822-1845 apply the " +
                "same values using grade > 3.");
            WriteGradeRule(w, -1, "1", "1", false,
                "GameData.OnInserterTechChange: every other grade -> stackInput = stackOutput = 1. " +
                "FactorySystem.NewInserterComponent (FactorySystem.cs:534-554) and the upgrade path in " +
                "PlanetFactory.cs:1822-1845 use range comparisons (grade >= 3 / grade > 3) that produce " +
                "the same 1/1 outcome for every grade that exists.");
            w.EndArray();

            w.Prop("stackRateFactor", true);
            w.Prop(
                "stackRateFactorSource",
                "InserterComponent.InternalUpdate: every pick does itemCount += stack (the picked cargo's " +
                "stack byte), and the Inserting stage delivers itemCount items - " +
                "TryInsertItemToBeltWithStackIncreasement(beltId, offset, itemId, stackOutput, ref itemCount, ...) " +
                "onto a belt, or InsertInto(..., itemCount / stackCount, ...) into a building. A carried stack " +
                "of n therefore counts as n items on that one trip.");
            w.Prop("stackRateFactorObserved", false);
            w.Prop("itemsPerCargoDivisor", 4);
            w.Prop(
                "itemsPerCargoDivisorSource",
                "InserterComponent.InternalUpdate, belt-insert branch: stackCount = (itemCount - 1) / 4 + 1. " +
                "The 4 is an IL literal, not a field: one belt cargo never holds more than 4 items.");
            w.Prop("itemsPerCargoDivisorObserved", false);
            w.EndObject();
        }

        private static void WriteGradeRule(JsonWriter w, int grade, string stackInput, string stackOutput, bool bidirectional, string source)
        {
            w.BeginObject();
            if (grade >= 0)
            {
                w.Prop("grade", grade);
            }
            else
            {
                w.Prop("grade", (string)null);
            }

            w.Prop("stackInputFrom", stackInput);
            w.Prop("stackOutputFrom", stackOutput);
            w.Prop("bidirectionalFromHistory", bidirectional);
            w.Prop("source", source);
            w.Prop("observed", false);
            w.EndObject();
        }

        // ------------------------------------------------------------------
        // Piler
        // ------------------------------------------------------------------

        private static byte[] ReadPilerCdTickArray()
        {
            try
            {
                FieldInfo f = typeof(PilerComponent).GetField(
                    "cacheCdTickArray",
                    BindingFlags.NonPublic | BindingFlags.Static | BindingFlags.Public);
                if (f == null)
                {
                    return null;
                }

                return f.GetValue(null) as byte[];
            }
            catch (Exception)
            {
                return null;
            }
        }

        private static void WritePilerFacts(JsonWriter w)
        {
            w.BeginObject("piler");

            w.Prop("componentType", typeof(PilerComponent).FullName);
            w.Prop("prefabComponentType", typeof(PilerDesc).FullName);

            // PilerDesc is what PrefabDesc looks for on the prefab
            // (PrefabDesc.ReadPrefab: GetComponentInChildren<PilerDesc>() -> isPiler = true).
            // Reflection says what it carries; if that list is empty, the piler has no
            // per-prefab stack setting at all.
            w.BeginArray("prefabComponentFields");
            FieldInfo[] descFields = typeof(PilerDesc).GetFields(BindingFlags.Public | BindingFlags.Instance | BindingFlags.NonPublic | BindingFlags.DeclaredOnly);
            for (int i = 0; i < descFields.Length; i++)
            {
                w.BeginObject();
                w.Prop("field", descFields[i].Name);
                w.Prop("type", descFields[i].FieldType.FullName);
                w.EndObject();
            }

            w.EndArray();

            w.BeginArray("componentFields");
            FieldInfo[] compFields = typeof(PilerComponent).GetFields(BindingFlags.Public | BindingFlags.Instance);
            for (int i = 0; i < compFields.Length; i++)
            {
                w.BeginObject();
                w.Prop("field", compFields[i].Name);
                w.Prop("type", compFields[i].FieldType.FullName);
                w.EndObject();
            }

            w.EndArray();

            w.BeginArray("stateEnumValues");
            string[] stateNames = Enum.GetNames(typeof(PilerState));
            Array stateValues = Enum.GetValues(typeof(PilerState));
            for (int i = 0; i < stateNames.Length; i++)
            {
                w.BeginObject();
                w.Prop("name", stateNames[i]);
                w.Prop("value", Convert.ToInt32(stateValues.GetValue(i), CultureInfo.InvariantCulture));
                w.EndObject();
            }

            w.EndArray();

            byte[] cd = ReadPilerCdTickArray();
            if (cd == null)
            {
                w.Prop("cacheCdTickArray", (string)null);
            }
            else
            {
                int[] widened = new int[cd.Length];
                for (int i = 0; i < cd.Length; i++)
                {
                    widened[i] = cd[i];
                }

                w.PropIntArray("cacheCdTickArray", widened);
            }

            // The piler's stack setting: there is none. RematchPilerConnection is the
            // only writer that derives Pile/Split from wiring (which connected belt is
            // the output side); CargoTraffic.DisconnectToPiler and PilerComponent.SetEmpty/
            // Import also write pilerState, but only to reset it to None or restore a
            // serialised value, never to derive it from wiring. BuildingParameters has no
            // piler case (its only "piler" mention is StationComponent.pilerCount, a
            // logistics-station field). So the plan's PILER_STACK_PARAMETER is null, and
            // it is null because the setting does not exist, not because we failed to
            // find it.
            w.Prop("stackParameterIndex", (string)null);
            w.Prop(
                "stackParameterSource",
                "None. CargoTraffic.RematchPilerConnection is the only writer that derives Pile/Split from " +
                "wiring: it decides pilerState from which connected belt is the output side. " +
                "CargoTraffic.DisconnectToPiler (CargoTraffic.cs:984,989), PilerComponent.SetEmpty (:44) and " +
                "PilerComponent.Import (:83) also write pilerState, but each resets it to None or restores a " +
                "previously serialised value rather than deriving it from wiring. BuildingParameters mentions " +
                "'piler' only as StationComponent.pilerCount (logistics stations), never for a PilerComponent, " +
                "and PilerComponent.Export serialises no stack setting.");
            w.Prop("hasPerBuildingStackSetting", false);

            w.Prop("maxOutputStack", 4);
            w.Prop(
                "maxOutputStackSource",
                "PilerComponent.InternalUpdate, Pile branch: when the two cached cargos are the same item and " +
                "cacheCargoStack1 + cacheCargoStack2 > 4 it emits AddCargo(item, 4, ...) and keeps the remainder. " +
                "The 4 is an IL literal, not a field.");
            w.Prop("maxOutputStackObserved", false);

            w.Prop("outputStackFromUnstackedInput", 2);
            w.Prop(
                "outputStackFromUnstackedInputSource",
                "PilerComponent.InternalUpdate, Pile branch: it holds at most two cargos (cacheItemId1 newest, " +
                "cacheItemId2 shifted) and emits ONE cargo of stack1 + stack2 (capped at 4) per output. Fed a " +
                "belt of stack-1 cargos, stack1 + stack2 = 1 + 1 = 2, so the emitted cargo's stack is 2.");
            w.Prop("outputStackFromUnstackedInputObserved", false);
            w.Prop("singlePassToMaxStack", false);
            w.Prop(
                "singlePassToMaxStackSource",
                "PilerComponent.InternalUpdate, Pile branch: the same stack1 + stack2 (capped at 4) combine " +
                "means reaching stack 4 from an unstacked (stack-1) belt takes two pilers in series " +
                "(1 -> 2 -> 4). It reaches 4 in one pass only when the input is already stacked 2 or more.");
            w.Prop("singlePassToMaxStackObserved", false);

            w.Prop(
                "throughputRule",
                "The piler has no rate of its own: timeSpend += beltSpeed * 1000 * powerRatio per tick and one " +
                "cargo costs 10000, where beltSpeed is the INPUT belt's speed in Pile state and the OUTPUT " +
                "belt's speed in Split state (PilerComponent.InternalUpdate). At 60 ticks per second and full " +
                "power that is 6 * beltSpeed cargo per second on the timed branch alone. The untimed pick " +
                "branch (PilerComponent.cs:176-187, :265-272) pulls a cargo without spending timeSpend, so the " +
                "piler's actual intake is at least the belt's own cargo rate; only the timed branch alone " +
                "equals it exactly. slowlyBeltSpeed = min(input, output) clamped to 3 selects the animation " +
                "and cooldown row only.");
            w.Prop("throughputEqualsBeltRate", true);
            w.Prop("throughputEqualsBeltRateObserved", false);
            w.Prop("throughputTicksPerCargoNumerator", 10000);
            w.Prop("throughputChargePerTickPerBeltSpeed", 1000);
            w.Prop("ticksPerSecond", 60);

            w.EndObject();
        }

        // ------------------------------------------------------------------
        // Live components, as a cross-check on the static facts
        // ------------------------------------------------------------------

        private static void WriteLive(JsonWriter w)
        {
            GameData data = GameMain.data;
            if (data == null || data.factories == null)
            {
                w.Prop("live", (string)null);
                return;
            }

            w.BeginObject("live");
            int factoryCount = data.factoryCount;
            if (factoryCount > data.factories.Length)
            {
                factoryCount = data.factories.Length;
            }

            w.Prop("factoryCount", factoryCount);

            int maxCargoStack = 0;
            int cargoCount = 0;
            int pilerRows = 0;
            int inserterRows = 0;

            w.BeginArray("pilers");
            for (int f = 0; f < factoryCount; f++)
            {
                PlanetFactory factory = data.factories[f];
                if (factory == null || factory.cargoTraffic == null)
                {
                    continue;
                }

                CargoTraffic traffic = factory.cargoTraffic;
                if (traffic.pilerPool != null)
                {
                    int cursor = Math.Min(traffic.pilerCursor, traffic.pilerPool.Length);
                    for (int i = 1; i < cursor && pilerRows < MaxLiveRows; i++)
                    {
                        if (traffic.pilerPool[i].id != i)
                        {
                            continue;
                        }

                        pilerRows++;
                        PilerComponent p = traffic.pilerPool[i];
                        w.BeginObject();
                        w.Prop("factoryIndex", f);
                        w.Prop("id", p.id);
                        w.Prop("entityId", p.entityId);
                        w.Prop("pilerState", p.pilerState.ToString());
                        w.Prop("inputBeltId", p.inputBeltId);
                        w.Prop("outputBeltId", p.outputBeltId);
                        w.Prop("inputBeltSpeed", BeltSpeed(traffic, p.inputBeltId));
                        w.Prop("outputBeltSpeed", BeltSpeed(traffic, p.outputBeltId));
                        w.Prop("slowlyBeltSpeed", p.slowlyBeltSpeed);
                        w.Prop("timeSpend", p.timeSpend);
                        w.Prop("cacheItemId1", p.cacheItemId1);
                        w.Prop("cacheCargoStack1", p.cacheCargoStack1);
                        w.Prop("cacheItemId2", p.cacheItemId2);
                        w.Prop("cacheCargoStack2", p.cacheCargoStack2);
                        w.Prop("cacheCdTick", p.cacheCdTick);
                        w.EndObject();
                    }
                }

                // The biggest stack byte actually riding a belt right now. If the user
                // has a piler chain running this is the empirical check on maxOutputStack.
                if (traffic.container != null && traffic.container.cargoPool != null)
                {
                    Cargo[] pool = traffic.container.cargoPool;
                    int cursor = Math.Min(traffic.container.cursor, pool.Length);
                    for (int i = 0; i < cursor; i++)
                    {
                        if (pool[i].item == 0)
                        {
                            continue;
                        }

                        cargoCount++;
                        if (pool[i].stack > maxCargoStack)
                        {
                            maxCargoStack = pool[i].stack;
                        }
                    }
                }
            }

            w.EndArray();

            w.BeginArray("sorters");
            for (int f = 0; f < factoryCount; f++)
            {
                PlanetFactory factory = data.factories[f];
                if (factory == null || factory.factorySystem == null || factory.factorySystem.inserterPool == null)
                {
                    continue;
                }

                FactorySystem system = factory.factorySystem;
                int cursor = Math.Min(system.inserterCursor, system.inserterPool.Length);
                for (int i = 1; i < cursor && inserterRows < MaxLiveRows; i++)
                {
                    if (system.inserterPool[i].id != i)
                    {
                        continue;
                    }

                    inserterRows++;
                    InserterComponent s = system.inserterPool[i];
                    w.BeginObject();
                    w.Prop("factoryIndex", f);
                    w.Prop("id", s.id);
                    w.Prop("entityId", s.entityId);
                    w.Prop("grade", s.grade);
                    w.Prop("canStack", s.canStack);
                    w.Prop("stackInput", s.stackInput);
                    w.Prop("stackOutput", s.stackOutput);
                    w.Prop("bidirectional", s.bidirectional);
                    w.Prop("stt", s.stt);
                    w.Prop("delay", s.delay);
                    w.Prop("itemId", s.itemId);
                    w.Prop("stackCount", s.stackCount);
                    w.Prop("itemCount", s.itemCount);
                    w.EndObject();
                }
            }

            w.EndArray();

            w.Prop("pilerRowsWritten", pilerRows);
            w.Prop("sorterRowsWritten", inserterRows);
            w.Prop("maxLiveRowsPerKind", MaxLiveRows);
            w.Prop("cargoOnBeltsScanned", cargoCount);
            w.Prop("maxCargoStackObserved", maxCargoStack);
            w.EndObject();
        }

        private static int BeltSpeed(CargoTraffic traffic, int beltId)
        {
            if (beltId <= 0 || traffic.beltPool == null || beltId >= traffic.beltPool.Length)
            {
                return 0;
            }

            return traffic.beltPool[beltId].speed;
        }
    }
}
