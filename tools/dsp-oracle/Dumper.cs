using System;
using System.Collections.Generic;
using System.Globalization;
using UnityEngine;

namespace FlabOracle
{
    /// <summary>
    /// The ambient facts a dump records that do not live on the paste tool.
    /// Passed in rather than read from statics so that <see cref="Dumper.Serialize"/>
    /// has no dependency on BepInEx or on a live Unity player, and can therefore
    /// be exercised outside the game.
    /// </summary>
    internal struct DumpContext
    {
        public bool OverlapPatchApplied;
        public bool OverlapHookEverFired;
        public int UnityFrame;
        public Dictionary<BuildPreview, MatchRecord> Records;
    }

    /// <summary>
    /// Serialises what the game decided. Every value written here was read off a
    /// game object; none of it is derived from a rule this plugin knows.
    /// </summary>
    internal static class Dumper
    {
        internal const string SchemaId = "flab2bp-oracle/1";

        /// <summary>
        /// Renders the current preview set as JSON. Returns null when there is
        /// nothing to render. Pure: reads game state, touches no statics.
        /// </summary>
        internal static string Serialize(
            BuildTool_BlueprintPaste tool,
            string trigger,
            bool? checkResult,
            bool detailed,
            DumpContext ctx)
        {
            if (tool == null)
            {
                return null;
            }

            BuildPreview[] pool = tool.bpPool;
            if (pool == null)
            {
                return null;
            }

            int count = tool.bpCursor;
            if (count > pool.Length)
            {
                count = pool.Length;
            }

            if (count < 0)
            {
                count = 0;
            }

            PlanetFactory factory = tool.factory;
            int frame = ctx.UnityFrame;

            Dictionary<BuildPreview, int> indexOf = new Dictionary<BuildPreview, int>(count);
            for (int i = 0; i < count; i++)
            {
                BuildPreview bp = pool[i];
                if (bp != null && !indexOf.ContainsKey(bp))
                {
                    indexOf[bp] = i;
                }
            }

            SortedDictionary<int, int> conditionCounts = new SortedDictionary<int, int>();
            SortedDictionary<int, PrefabDesc> prefabs = new SortedDictionary<int, PrefabDesc>();

            for (int i = 0; i < count; i++)
            {
                BuildPreview bp = pool[i];
                if (bp == null)
                {
                    continue;
                }

                int cond = (int)bp.condition;
                int have;
                conditionCounts[cond] = conditionCounts.TryGetValue(cond, out have) ? have + 1 : 1;

                if (bp.item != null && bp.desc != null && !prefabs.ContainsKey(bp.item.ID))
                {
                    prefabs[bp.item.ID] = bp.desc;
                }
            }

            JsonWriter w = new JsonWriter();
            w.BeginObject();
            w.Prop("schema", SchemaId);
            w.Prop("trigger", trigger);
            w.Prop("utcTime", DateTime.UtcNow.ToString("o", CultureInfo.InvariantCulture));
            w.Prop("unityFrame", frame);
            w.Prop("toolFrame", tool.frame);
            if (checkResult.HasValue)
            {
                w.Prop("checkBuildConditionsResult", checkResult.Value);
            }
            else
            {
                w.Prop("checkBuildConditionsResult", (string)null);
            }

            w.Prop("colliderDetailRequested", detailed);
            w.Prop("overlapPatchApplied", ctx.OverlapPatchApplied);
            w.Prop("overlapHookEverFired", ctx.OverlapHookEverFired);
            w.Prop("planetId", tool.planet != null ? tool.planet.id : 0);
            w.Prop("blueprintPath", tool.blueprintPath);
            w.Prop("pasteResult", tool.result.ToString());
            w.Prop("cursorValid", tool.cursorValid);
            w.Prop("yaw", tool.yaw);
            w.Prop("anchorType", tool.anchorType);
            w.Prop("bpCursor", tool.bpCursor);
            w.Prop("previewCount", count);

            w.BeginObject("conditionCounts");
            foreach (KeyValuePair<int, int> kv in conditionCounts)
            {
                w.Prop(ConditionName(kv.Key) + " (" + kv.Key.ToString(CultureInfo.InvariantCulture) + ")", kv.Value);
            }

            w.EndObject();

            w.BeginObject("prefabs");
            foreach (KeyValuePair<int, PrefabDesc> kv in prefabs)
            {
                WritePrefab(w, kv.Key, kv.Value);
            }

            w.EndObject();

            w.BeginArray("previews");
            for (int i = 0; i < count; i++)
            {
                WritePreview(w, i, pool[i], indexOf, factory, ctx);
            }

            w.EndArray();
            w.EndObject();

            return w.ToString().TrimStart('\n');
        }

        private static void WritePrefab(JsonWriter w, int itemId, PrefabDesc desc)
        {
            w.BeginObject(itemId.ToString(CultureInfo.InvariantCulture));
            w.Prop("itemId", itemId);
            w.Prop("itemName", ProtoName(itemId));
            w.Prop("modelIndex", desc.modelIndex);
            w.Prop("subId", desc.subId);
            w.Prop("isInserter", desc.isInserter);
            w.Prop("isBelt", desc.isBelt);
            w.Prop("isSplitter", desc.isSplitter);
            w.Prop("isStorage", desc.isStorage);
            w.Prop("isAssembler", desc.isAssembler);
            w.Prop("multiLevel", desc.multiLevel);
            w.Prop("inserterSTT", desc.inserterSTT);
            w.Prop("inserterDelay", desc.inserterDelay);
            w.Prop("inserterGrade", desc.inserterGrade);
            WritePoses(w, "slotPoses", desc.slotPoses);
            WritePoses(w, "portPoses", desc.portPoses);
            w.EndObject();
        }

        private static void WritePoses(JsonWriter w, string key, Pose[] poses)
        {
            if (poses == null)
            {
                w.Prop(key, (string)null);
                return;
            }

            w.BeginArray(key);
            for (int i = 0; i < poses.Length; i++)
            {
                w.BeginObject();
                w.Prop("index", i);
                w.Prop("position", poses[i].position);
                w.Prop("rotation", poses[i].rotation);
                w.EndObject();
            }

            w.EndArray();
        }

        private static void WritePreview(
            JsonWriter w,
            int index,
            BuildPreview bp,
            Dictionary<BuildPreview, int> indexOf,
            PlanetFactory factory,
            DumpContext ctx)
        {
            w.BeginObject();
            w.Prop("index", index);

            if (bp == null)
            {
                w.Prop("null", true);
                w.EndObject();
                return;
            }

            w.Prop("objId", bp.objId);
            w.Prop("previewIndex", bp.previewIndex);

            if (bp.item != null)
            {
                w.Prop("itemId", bp.item.ID);
                w.Prop("itemName", bp.item.name);
                w.Prop("itemNameKey", bp.item.Name);
            }
            else
            {
                w.Prop("itemId", (string)null);
                w.Prop("itemName", (string)null);
                w.Prop("itemNameKey", (string)null);
            }

            if (bp.desc != null)
            {
                w.Prop("descModelIndex", bp.desc.modelIndex);
                w.Prop("descSubId", bp.desc.subId);
                w.Prop("descIsInserter", bp.desc.isInserter);
                w.Prop("descIsBelt", bp.desc.isBelt);
                w.Prop("descMultiLevel", bp.desc.multiLevel);
            }
            else
            {
                w.Prop("descModelIndex", (string)null);
                w.Prop("descSubId", (string)null);
                w.Prop("descIsInserter", (string)null);
                w.Prop("descIsBelt", (string)null);
                w.Prop("descMultiLevel", (string)null);
            }

            int cond = (int)bp.condition;
            w.Prop("condition", cond);
            w.Prop("conditionName", ConditionName(cond));
            w.Prop("conditionText", SafeConditionText(bp));

            w.Prop("inputObjId", bp.inputObjId);
            w.Prop("inputFromSlot", bp.inputFromSlot);
            w.Prop("inputToSlot", bp.inputToSlot);
            w.Prop("inputOffset", bp.inputOffset);
            w.Prop("outputObjId", bp.outputObjId);
            w.Prop("outputFromSlot", bp.outputFromSlot);
            w.Prop("outputToSlot", bp.outputToSlot);
            w.Prop("outputOffset", bp.outputOffset);

            w.Prop("hasInput", bp.input != null);
            w.Prop("hasOutput", bp.output != null);
            w.PropNullableInt("inputPreviewIndex", LookupIndex(indexOf, bp.input));
            w.PropNullableInt("outputPreviewIndex", LookupIndex(indexOf, bp.output));
            w.Prop("hasCoverBp", bp.coverbp != null);
            w.Prop("hasAddonBp", bp.addonbp != null);

            w.Prop("lpos", bp.lpos);
            w.Prop("lpos2", bp.lpos2);
            w.Prop("lrot", bp.lrot);
            w.Prop("lrot2", bp.lrot2);
            w.Prop("tilt", bp.tilt);

            w.Prop("recipeId", bp.recipeId);
            w.Prop("filterId", bp.filterId);
            w.Prop("paramCount", bp.paramCount);
            w.PropIntArray("parameters", bp.parameters, bp.paramCount);
            w.Prop("coverObjId", bp.coverObjId);
            w.Prop("willRemoveCover", bp.willRemoveCover);
            w.Prop("willReconstructCover", bp.willReconstructCover);
            w.Prop("addonObjId", bp.addonObjId);
            w.Prop("addonAreaIdx", bp.addonAreaIdx);
            w.Prop("isConnNode", bp.isConnNode);
            w.Prop("needModel", bp.needModel);
            w.Prop("bpgpuiModelId", bp.bpgpuiModelId);
            w.Prop("genNearColliderArea2", bp.genNearColliderArea2);
            w.Prop("content", bp.content);

            WriteTarget(w, "inputTarget", bp.inputObjId, factory);
            WriteTarget(w, "outputTarget", bp.outputObjId, factory);

            WriteMatchInserter(w, bp, ctx);

            w.EndObject();
        }

        private static void WriteMatchInserter(JsonWriter w, BuildPreview bp, DumpContext ctx)
        {
            MatchRecord rec;
            if (ctx.Records == null || !ctx.Records.TryGetValue(bp, out rec) || rec.Frame < 0)
            {
                w.Prop("matchInserter", (string)null);
                return;
            }

            w.BeginObject("matchInserter");
            w.Prop("frame", rec.Frame);
            w.Prop("framesStale", ctx.UnityFrame - rec.Frame);
            w.Prop("colliderDetailCaptured", rec.Detailed);
            w.Prop("callCount", rec.Calls.Count);

            w.BeginArray("calls");
            for (int c = 0; c < rec.Calls.Count; c++)
            {
                MatchCall call = rec.Calls[c];
                w.BeginObject();
                w.Prop("call", c);
                WriteConnState(w, "before", call.Before);
                WriteConnState(w, "after", call.After);

                w.BeginArray("overlapQueries");
                for (int i = 0; i < call.OverlapTake; i++)
                {
                    int oat = call.OverlapFrom + i;
                    if (oat < 0 || oat >= rec.Overlaps.Count)
                    {
                        continue;
                    }

                    WriteOverlap(w, rec, rec.Overlaps[oat]);
                }

                w.EndArray();
                w.EndObject();
            }

            w.EndArray();
            w.EndObject();
        }

        private static void WriteOverlap(JsonWriter w, MatchRecord rec, OverlapObservation obs)
        {
            w.BeginObject();
            w.Prop("center", obs.Center);
            w.Prop("radius", obs.Radius);
            w.Prop("layerMask", obs.LayerMask);
            w.Prop("colliderCount", obs.ColliderCount);

            if (obs.ColliderTake > 0)
            {
                w.BeginArray("colliders");
                for (int j = 0; j < obs.ColliderTake; j++)
                {
                    int at = obs.ColliderFrom + j;
                    if (at < 0 || at >= rec.Colliders.Count)
                    {
                        continue;
                    }

                    WriteCollider(w, j, rec.Colliders[at]);
                }

                w.EndArray();
            }
            else
            {
                w.Prop("colliders", (string)null);
            }

            w.EndObject();
        }

        private static void WriteCollider(JsonWriter w, int order, ColliderObservation o)
        {
            w.BeginObject();
            w.Prop("order", order);
            w.Prop("name", o.Name);
            w.Prop("gameObjectLayer", o.GameObjectLayer);
            w.Prop("hasColliderData", o.HasColliderData);
            if (!o.HasColliderData)
            {
                w.EndObject();
                return;
            }

            w.Prop("objId", o.ObjId);
            w.Prop("objType", o.ObjType);
            w.Prop("usage", o.Usage);
            w.Prop("shape", o.Shape);
            w.Prop("link", o.Link);
            w.Prop("pos", o.Pos);
            w.Prop("ext", o.Ext);
            w.Prop("radius", o.Radius);
            w.Prop("rot", o.Rot);
            w.EndObject();
        }

        private static void WriteConnState(JsonWriter w, string key, PreviewConnState s)
        {
            w.BeginObject(key);
            w.Prop("condition", s.Condition);
            w.Prop("conditionName", ConditionName(s.Condition));
            w.Prop("inputObjId", s.InputObjId);
            w.Prop("inputFromSlot", s.InputFromSlot);
            w.Prop("inputToSlot", s.InputToSlot);
            w.Prop("inputOffset", s.InputOffset);
            w.Prop("outputObjId", s.OutputObjId);
            w.Prop("outputFromSlot", s.OutputFromSlot);
            w.Prop("outputToSlot", s.OutputToSlot);
            w.Prop("outputOffset", s.OutputOffset);
            w.Prop("hasInput", s.HasInput);
            w.Prop("hasOutput", s.HasOutput);
            w.Prop("lpos", s.Lpos);
            w.Prop("lpos2", s.Lpos2);
            w.Prop("lrot", s.Lrot);
            w.Prop("lrot2", s.Lrot2);
            w.EndObject();
        }

        private static void WriteTarget(JsonWriter w, string key, int objId, PlanetFactory factory)
        {
            if (objId == 0)
            {
                w.Prop(key, (string)null);
                return;
            }

            w.BeginObject(key);
            w.Prop("objId", objId);

            if (objId > 0)
            {
                w.Prop("kind", "entity");
                if (factory != null && factory.entityPool != null &&
                    objId < factory.entityCursor && objId < factory.entityPool.Length)
                {
                    EntityData e = factory.entityPool[objId];
                    w.Prop("resolved", true);
                    w.Prop("id", e.id);
                    w.Prop("protoId", e.protoId);
                    w.Prop("protoName", ProtoName(e.protoId));
                    w.Prop("modelIndex", e.modelIndex);
                    w.Prop("pos", e.pos);
                    w.Prop("rot", e.rot);
                    w.Prop("tilt", e.tilt);
                    w.Prop("beltId", e.beltId);
                    w.Prop("inserterId", e.inserterId);
                }
                else
                {
                    w.Prop("resolved", false);
                }
            }
            else
            {
                int pid = -objId;
                w.Prop("kind", "prebuild");
                if (factory != null && factory.prebuildPool != null &&
                    pid < factory.prebuildCursor && pid < factory.prebuildPool.Length)
                {
                    PrebuildData p = factory.prebuildPool[pid];
                    w.Prop("resolved", true);
                    w.Prop("id", p.id);
                    w.Prop("protoId", p.protoId);
                    w.Prop("protoName", ProtoName(p.protoId));
                    w.Prop("modelIndex", p.modelIndex);
                    w.Prop("pos", p.pos);
                    w.Prop("rot", p.rot);
                    w.Prop("pos2", p.pos2);
                    w.Prop("rot2", p.rot2);
                    w.Prop("tilt", p.tilt);
                    w.Prop("pickOffset", p.pickOffset);
                    w.Prop("insertOffset", p.insertOffset);
                    w.Prop("isDestroyed", p.isDestroyed);
                }
                else
                {
                    w.Prop("resolved", false);
                }
            }

            w.EndObject();
        }

        private static int? LookupIndex(Dictionary<BuildPreview, int> indexOf, BuildPreview bp)
        {
            if (bp == null)
            {
                return null;
            }

            int at;
            if (indexOf.TryGetValue(bp, out at))
            {
                return at;
            }

            return null;
        }

        private static string ConditionName(int condition)
        {
            try
            {
                string name = Enum.GetName(typeof(EBuildCondition), condition);
                if (!string.IsNullOrEmpty(name))
                {
                    return name;
                }
            }
            catch (Exception)
            {
                // fall through
            }

            return "Unknown(" + condition.ToString(CultureInfo.InvariantCulture) + ")";
        }

        private static string SafeConditionText(BuildPreview bp)
        {
            try
            {
                return bp.conditionText;
            }
            catch (Exception)
            {
                return null;
            }
        }

        private static string ProtoName(int protoId)
        {
            if (protoId == 0)
            {
                return null;
            }

            try
            {
                ItemProto proto = LDB.items.Select(protoId);
                if (proto != null)
                {
                    return proto.name;
                }
            }
            catch (Exception)
            {
                // fall through
            }

            return null;
        }
    }
}
