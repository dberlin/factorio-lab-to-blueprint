using System;
using System.Collections.Generic;
using System.Runtime.CompilerServices;
using UnityEngine;

namespace FlabOracle
{
    internal sealed class TargetCaptureSession
    {
        internal const string SchemaId = "flab2bp-model40-belts/3";
        private const int EventLimit = 128;
        private const int PassQueryLimit = 4096;
        private const int PassAddErrorLimit = 16;
        private const int NonOkSettleFrames = 2;
        private const int MonitorWindowFrames = 1800;
        private readonly BuildTool_BlueprintPaste _tool;
        private readonly BlueprintData _blueprint;
        private readonly BuildPreview[] _pool;
        private readonly string _blueprintPath;
        private readonly BlueprintArea _area;
        private readonly int _areaArraySlot;
        private readonly Group[] _groups;
        private readonly Target[] _targets;
        private readonly List<Event> _events = new List<Event>(32);
        private int _sequence;
        private bool _truncated;
        private bool _sphereHookFired;
        private bool _capsuleHookFired;
        private int _monitorStartFrame = -1;
        private int _monitorLastFrame = -1;
        private bool _nonOkObserved;
        private int _monitorLastChangeFrame = -1;
        private bool _hasMonitorState;
        private readonly MonitorState[] _monitorStates;
        private bool _prestageObserved;
        private bool _lastPrestageResult;
        private int _prestageLastChangeFrame = -1;
        private readonly Dictionary<BuildPreview, PassData> _passData =
            new Dictionary<BuildPreview, PassData>(BuildPreviewReferenceComparer.Instance);
        private readonly Dictionary<BuildPreview, int> _activeSlots =
            new Dictionary<BuildPreview, int>(BuildPreviewReferenceComparer.Instance);
        private readonly List<Query> _passQueries = new List<Query>(64);
        private bool _capturingCheckPass;
        private bool _passQueriesTruncated;

        private TargetCaptureSession(BuildTool_BlueprintPaste tool, BlueprintArea area, int areaArraySlot, Group[] groups)
        {
            _tool = tool;
            _blueprint = tool.blueprint;
            _pool = tool.bpPool;
            _blueprintPath = tool.blueprintPath;
            _area = area;
            _areaArraySlot = areaArraySlot;
            _groups = groups;
            _targets = new Target[groups.Length * 5];
            _monitorStates = new MonitorState[_targets.Length];
            for (int g = 0; g < groups.Length; g++)
            {
                groups[g].Splitter.Tool = tool;
                _targets[g * 5] = groups[g].Splitter;
                for (int t = 0; t < groups[g].Targets.Length; t++)
                {
                    Target target = groups[g].Targets[t];
                    target.Tool = tool;
                    _targets[g * 5 + t + 1] = target;
                }
            }
        }

        internal BuildTool_BlueprintPaste Tool { get { return _tool; } }

        internal bool Matches(BuildTool_BlueprintPaste tool)
        {
            return ReferenceEquals(_tool, tool) &&
                ReferenceEquals(_blueprint, tool != null ? tool.blueprint : null) &&
                ReferenceEquals(_pool, tool != null ? tool.bpPool : null);
        }

        internal static bool TryCreate(BuildTool_BlueprintPaste tool, out TargetCaptureSession capture)
        {
            capture = null;
            if (tool == null || tool.blueprint == null || tool.blueprint.areas == null || tool.blueprint.buildings == null || tool.bpPool == null) return false;
            BlueprintArea matchedArea = null;
            int matchedAreaArraySlot = -1;
            for (int i = 0; i < tool.blueprint.areas.Length; i++)
            {
                BlueprintArea a = tool.blueprint.areas[i];
                if (a != null && a.width == 75 && a.height == 36 && a.areaSegments == 160)
                {
                    if (matchedArea != null) return false;
                    matchedArea = a;
                    matchedAreaArraySlot = i;
                }
            }
            if (matchedArea == null) return false;

            BlueprintBuilding[] buildings = tool.blueprint.buildings;
            Group control;
            Group suspect;
            if (!TryCreateGroup(tool, buildings, matchedArea.index, "control-y2", 2f,
                44.7723007f, 2.00012708f, 45.2276993f, 2.00012708f, out control) ||
                !TryCreateGroup(tool, buildings, matchedArea.index, "suspect-y6", 6f,
                44.7780228f, 6.00012112f, 45.2219772f, 6.00012112f, out suspect))
            {
                return false;
            }
            capture = new TargetCaptureSession(tool, matchedArea, matchedAreaArraySlot, new[] { control, suspect });
            return true;
        }

        internal void ResetCycle()
        {
            _events.Clear();
            _sequence = 0;
            _truncated = false;
            _sphereHookFired = false;
            _capsuleHookFired = false;
            _monitorStartFrame = -1;
            _monitorLastFrame = -1;
            _nonOkObserved = false;
            _monitorLastChangeFrame = -1;
            _hasMonitorState = false;
            _prestageObserved = false;
            _lastPrestageResult = false;
            _prestageLastChangeFrame = -1;
            _passData.Clear();
            _passQueries.Clear();
            _activeSlots.Clear();
            _capturingCheckPass = false;
            _passQueriesTruncated = false;
            for (int i = 0; i < _targets.Length; i++)
            {
                _targets[i].QueryCount = 0;
                _targets[i].AddErrorCount = 0;
            }
        }

        internal void BeginCheckPass()
        {
            _passData.Clear();
            _passQueries.Clear();
            _activeSlots.Clear();
            _passQueriesTruncated = false;
            _capturingCheckPass = true;
            int active = Math.Min(Math.Max(_tool.bpCursor, 0), _pool.Length);
            for (int i = 0; i < active; i++)
            {
                BuildPreview bp = _pool[i];
                if (bp != null && !_activeSlots.ContainsKey(bp)) _activeSlots.Add(bp, i);
            }
        }

        internal bool MonitorFrame(int frame, out string flushReason)
        {
            flushReason = null;
            if (_monitorLastFrame == frame) return false;
            if (_monitorStartFrame < 0) _monitorStartFrame = frame;
            _monitorLastFrame = frame;

            bool currentNonOk = false;
            bool changed = !_hasMonitorState;
            for (int i = 0; i < _targets.Length; i++)
            {
                BuildPreview bp = _targets[i].Preview;
                if (!changed && !_monitorStates[i].Matches(bp)) changed = true;
                if (bp.condition != EBuildCondition.Ok)
                {
                    currentNonOk = true;
                    _nonOkObserved = true;
                }
            }
            if (changed)
            {
                for (int i = 0; i < _targets.Length; i++) _monitorStates[i] = MonitorState.Read(_targets[i].Preview);
                _hasMonitorState = true;
                _monitorLastChangeFrame = frame;
                SnapshotAll("update-monitor-state-change");
            }

            if (_prestageObserved && !_lastPrestageResult &&
                frame - _prestageLastChangeFrame >= NonOkSettleFrames)
            {
                flushReason = "prestage-false-stable";
                return true;
            }
            if (currentNonOk && frame - _monitorLastChangeFrame >= NonOkSettleFrames)
            {
                flushReason = "target-non-ok-stable";
                return true;
            }
            if (frame - _monitorStartFrame >= MonitorWindowFrames)
            {
                flushReason = "monitor-window-expired";
                return true;
            }
            return false;
        }

        internal void RecordPrestageResult(bool result, int frame)
        {
            if (_prestageObserved && _lastPrestageResult == result) return;
            _prestageObserved = true;
            _lastPrestageResult = result;
            _prestageLastChangeFrame = frame;
            SnapshotAll("check-build-conditions-prestage-postfix");
            if (_events.Count > 0) _events[_events.Count - 1].BoolResult = result;
        }

        internal void SnapshotAll(string phase)
        {
            if (!Reserve()) return;
            Event e = NewEvent(phase, null);
            e.States = new PreviewState[_targets.Length];
            for (int i = 0; i < _targets.Length; i++) e.States[i] = PreviewState.Read(_tool, _targets[i].Preview);
            _events.Add(e);
        }

        internal void RecordAddError(BuildPreview bp, EBuildCondition argument)
        {
            if (_capturingCheckPass && bp != null && _activeSlots.ContainsKey(bp))
            {
                PassData data;
                if (!_passData.TryGetValue(bp, out data))
                {
                    data = new PassData();
                    _passData.Add(bp, data);
                }
                data.AddArgument(argument, PassAddErrorLimit);
            }

            Target target = TargetFor(bp);
            if (target == null || !Reserve()) return;
            target.AddErrorCount++;
            Event e = NewEvent("add-error-message", target);
            e.TargetEventOrdinal = target.AddErrorCount;
            e.ArgumentCondition = (int)argument;
            e.ArgumentConditionName = argument.ToString();
            e.State = PreviewState.Read(_tool, bp);
            _events.Add(e);
        }

        internal void RecordSphere(Vector3 center, float radius, Collider[] results, int mask, QueryTriggerInteraction qti, int result)
        {
            _sphereHookFired = true;
            RecordQuery("sphere", center, center, radius, results, mask, qti, result);
        }

        internal void RecordCapsule(Vector3 p0, Vector3 p1, float radius, Collider[] results, int mask, QueryTriggerInteraction qti, int result)
        {
            _capsuleHookFired = true;
            RecordQuery("capsule", p0, p1, radius, results, mask, qti, result);
        }

        internal string Serialize(string trigger, bool? checkResult, int frame, bool spherePatchApplied, bool capsulePatchApplied)
        {
            JsonWriter w = new JsonWriter();
            w.BeginObject();
            w.Prop("schema", SchemaId);
            w.Prop("trigger", trigger);
            w.Prop("unityFrame", frame);
            w.Prop("semanticMatch", true);
            w.Prop("semanticMismatchReason", (string)null);
            w.PropNullableInt("monitorStartFrame", _monitorStartFrame >= 0 ? (int?)_monitorStartFrame : null);
            w.PropNullableInt("monitorLastFrame", _monitorLastFrame >= 0 ? (int?)_monitorLastFrame : null);
            w.Prop("nonOkObserved", _nonOkObserved);
            w.PropNullableInt("monitorLastChangeFrame", _monitorLastChangeFrame >= 0 ? (int?)_monitorLastChangeFrame : null);
            w.Prop("prestageObserved", _prestageObserved);
            if (_prestageObserved) w.Prop("lastPrestageResult", _lastPrestageResult); else w.Prop("lastPrestageResult", (string)null);
            w.Prop("toolStage", ReadToolStage());
            w.Prop("bMeetTech", _tool.bMeetTech);
            w.Prop("isAreaValid", _tool.isAreaValid);
            w.Prop("gratBoxCursor", _tool.gratBoxCursor);
            w.Prop("pasteResult", _tool.result.ToString());
            WriteGratBoxConditions(w);
            w.Prop("blueprintPath", _blueprintPath);
            w.Prop("blueprintBuildingCount", _blueprint.buildings.Length);
            w.PropNullableInt("prestageLastChangeFrame", _prestageLastChangeFrame >= 0 ? (int?)_prestageLastChangeFrame : null);
            w.Prop("areaArraySlot", _areaArraySlot);
            w.Prop("areaIndex", _area.index);
            w.Prop("areaWidth", _area.width);
            w.Prop("areaHeight", _area.height);
            w.Prop("areaSegments", _area.areaSegments);
            w.Prop("bpCursor", _tool.bpCursor);
            w.Prop("eventLimit", EventLimit);
            w.Prop("eventsTruncated", _truncated);
            w.Prop("spherePatchApplied", spherePatchApplied);
            w.Prop("capsulePatchApplied", capsulePatchApplied);
            w.Prop("sphereHookFiredWhileTargetActive", _sphereHookFired);
            w.Prop("capsuleHookFiredWhileTargetActive", _capsuleHookFired);
            if (checkResult.HasValue) w.Prop("checkBuildConditionsResult", checkResult.Value); else w.Prop("checkBuildConditionsResult", (string)null);
            w.Prop("passPhysicsQueryLimit", PassQueryLimit);
            w.Prop("passPhysicsQueryCount", _passQueries.Count);
            w.Prop("passPhysicsQueriesTruncated", _passQueriesTruncated);
            WriteNonOkPreviews(w);
            w.BeginArray("groups");
            for (int i = 0; i < _groups.Length; i++) WriteGroup(w, _groups[i]);
            w.EndArray();
            w.BeginArray("events");
            for (int i = 0; i < _events.Count; i++) WriteEvent(w, _events[i]);
            w.EndArray();
            w.EndObject();
            return w.ToString();
        }

        private void RecordQuery(string shape, Vector3 p0, Vector3 p1, float radius, Collider[] results, int mask, QueryTriggerInteraction qti, int result)
        {
            if (mask != 395264 || !Near(radius, 0.23f)) return;
            Query query = null;
            if (_capturingCheckPass)
            {
                if (_passQueries.Count < PassQueryLimit)
                {
                    query = Query.Read(_tool, shape, p0, p1, radius, mask, qti, result, results);
                    _passQueries.Add(query);
                }
                else
                {
                    _passQueriesTruncated = true;
                }
            }
            for (int i = 0; i < _targets.Length; i++)
            {
                Target target = _targets[i];
                if (target.Role == "model40-splitter") continue;
                Vector3 expected = target.Preview.lpos + target.Preview.lpos.normalized * 0.2f;
                float distance = shape == "sphere" ? Vector3.Distance(expected, p0) : SegmentDistance(expected, p0, p1);
                if (distance > 0.025f || !Reserve()) continue;
                target.QueryCount++;
                Event e = NewEvent(shape + "-overlap", target);
                e.TargetEventOrdinal = target.QueryCount;
                e.State = PreviewState.Read(_tool, target.Preview);
                if (query == null) query = Query.Read(_tool, shape, p0, p1, radius, mask, qti, result, results);
                e.Query = query;
                _events.Add(e);
            }
        }

        private bool Reserve()
        {
            if (_events.Count >= EventLimit)
            {
                _events.RemoveAt(0);
                _truncated = true;
            }
            return true;
        }

        private int ReadToolStage()
        {
            return _tool.controller != null ? _tool.controller.cmd.stage : -1;
        }

        private Event NewEvent(string phase, Target target)
        {
            return new Event { Sequence = ++_sequence, Phase = phase, Target = target, ToolStage = ReadToolStage() };
        }
        private Target TargetFor(BuildPreview bp) { for (int i = 0; i < _targets.Length; i++) if (ReferenceEquals(_targets[i].Preview, bp)) return _targets[i]; return null; }
        private static bool Near(float a, float b) { return a == b; }

        private void WriteGratBoxConditions(JsonWriter w)
        {
            w.BeginArray("gratBoxConditions");
            int count = _tool.bpGratBoxConditionArr == null ? 0 :
                Math.Min(_tool.gratBoxCursor, _tool.bpGratBoxConditionArr.Length);
            for (int i = 0; i < count; i++)
            {
                IntVector4 value = _tool.bpGratBoxConditionArr[i];
                w.BeginObject();
                w.Prop("index", i);
                w.Prop("x", value.x);
                w.Prop("y", value.y);
                w.Prop("z", value.z);
                w.Prop("w", value.w);
                w.EndObject();
            }
            w.EndArray();
        }

        private void WriteNonOkPreviews(JsonWriter w)
        {
            int active = Math.Min(Math.Max(_tool.bpCursor, 0), _pool.Length);
            int count = 0;
            for (int i = 0; i < active; i++)
            {
                BuildPreview bp = _pool[i];
                if (bp != null && bp.condition != EBuildCondition.Ok) count++;
            }
            w.Prop("nonOkPreviewCount", count);
            w.BeginArray("nonOkPreviews");
            for (int i = 0; i < active; i++)
            {
                BuildPreview bp = _pool[i];
                if (bp == null || bp.condition == EBuildCondition.Ok) continue;
                WriteNonOkPreview(w, bp, i);
            }
            w.EndArray();
        }

        private void WriteNonOkPreview(JsonWriter w, BuildPreview bp, int activeSlot)
        {
            int buildingSlot = -1;
            int blueprintGroupOrdinal = -1;
            string mappingSource = null;
            BlueprintBuilding building = null;
            int buildingCount = _blueprint.buildings.Length;
            if (buildingCount > 0)
            {
                int mapped;
                if (bp.bpgpuiModelId > 0)
                {
                    mapped = bp.bpgpuiModelId - 1;
                    mappingSource = "bpgpui-model-id";
                }
                else
                {
                    mapped = activeSlot;
                    mappingSource = "active-pool-order";
                }
                buildingSlot = mapped % buildingCount;
                blueprintGroupOrdinal = mapped / buildingCount;
                if (buildingSlot >= 0 && buildingSlot < buildingCount) building = _blueprint.buildings[buildingSlot];
            }

            w.BeginObject();
            w.Prop("referenceIdentity", RuntimeHelpers.GetHashCode(bp));
            w.Prop("poolSlot", activeSlot);
            w.Prop("activeSlot", activeSlot);
            w.Prop("bpgpuiModelId", bp.bpgpuiModelId);
            w.Prop("mappingSource", mappingSource);
            w.PropNullableInt("blueprintGroupOrdinal", blueprintGroupOrdinal >= 0 ? (int?)blueprintGroupOrdinal : null);
            w.PropNullableInt("blueprintArraySlot", buildingSlot >= 0 ? (int?)buildingSlot : null);
            w.PropNullableInt("blueprintIndexField", building != null ? (int?)building.index : null);
            w.PropNullableInt("blueprintModelIndex", building != null ? (int?)building.modelIndex : null);
            w.PropNullableInt("blueprintItemId", building != null ? (int?)building.itemId : null);
            if (building != null)
            {
                w.Prop("blueprintLocalOffset", new Vector3(building.localOffset_x, building.localOffset_y, building.localOffset_z));
                w.Prop("blueprintYaw", building.yaw);
            }
            else
            {
                w.Prop("blueprintLocalOffset", (string)null);
                w.Prop("blueprintYaw", (string)null);
            }
            w.PropNullableInt("previewItemId", bp.item != null ? (int?)bp.item.ID : null);
            w.Prop("hasDesc", bp.desc != null);
            w.Prop("descModelIndex", bp.desc != null ? bp.desc.modelIndex : -1);
            w.Prop("descSubId", bp.desc != null ? bp.desc.subId : -1);
            w.Prop("descIsInserter", bp.desc != null && bp.desc.isInserter);
            w.Prop("descIsBelt", bp.desc != null && bp.desc.isBelt);
            w.Prop("descIsSplitter", bp.desc != null && bp.desc.isSplitter);
            w.Prop("descIsStorage", bp.desc != null && bp.desc.isStorage);
            w.Prop("descIsAssembler", bp.desc != null && bp.desc.isAssembler);
            w.Prop("descMultiLevel", bp.desc != null && bp.desc.multiLevel);
            w.Prop("descAddonType", bp.desc != null ? bp.desc.addonType.ToString() : null);
            WriteState(w, "state", PreviewState.Read(_tool, bp));

            PassData data;
            bool hasData = _passData.TryGetValue(bp, out data);
            w.Prop("addErrorArgumentsTruncated", hasData && data.ArgumentsTruncated);
            w.BeginArray("addErrorArguments");
            if (hasData)
            {
                for (int i = 0; i < data.Arguments.Count; i++)
                {
                    w.BeginObject();
                    w.Prop("condition", data.Arguments[i].Condition);
                    w.Prop("conditionName", data.Arguments[i].ConditionName);
                    w.EndObject();
                }
            }
            w.EndArray();

            Vector3 expected = bp.lpos + bp.lpos.normalized * 0.2f;
            w.BeginArray("nearbyPhysicsQueries");
            for (int i = 0; i < _passQueries.Count; i++)
            {
                Query query = _passQueries[i];
                float distance = query.Shape == "sphere"
                    ? Vector3.Distance(expected, query.P0)
                    : SegmentDistance(expected, query.P0, query.P1);
                if (distance <= 0.025f) WriteQueryElement(w, query);
            }
            w.EndArray();
            w.EndObject();
        }

        private static bool TryCreateGroup(
            BuildTool_BlueprintPaste tool,
            BlueprintBuilding[] buildings,
            int areaIndex,
            string semantic,
            float y,
            float feedX,
            float feedY,
            float drawX,
            float drawY,
            out Group group)
        {
            group = null;
            int splitter = Find(buildings, 40, 45f, y, 0f);
            int outerFeed = Find(buildings, 36, 44f, y, 1f);
            int feed = Find(buildings, 36, feedX, feedY, 1.00009131f);
            int draw = Find(buildings, 36, drawX, drawY, 1.00009131f);
            int outerDraw = Find(buildings, 36, 46f, y, 1f);
            if (splitter < 0 || outerFeed < 0 || feed < 0 || draw < 0 || outerDraw < 0) return false;
            if (buildings[splitter].areaIndex != areaIndex || buildings[outerFeed].areaIndex != areaIndex ||
                buildings[feed].areaIndex != areaIndex || buildings[draw].areaIndex != areaIndex ||
                buildings[outerDraw].areaIndex != areaIndex) return false;
            if (!Near(buildings[splitter].yaw, 90f) ||
                !ReferenceEquals(buildings[feed].outputObj, buildings[splitter]) ||
                !ReferenceEquals(buildings[draw].inputObj, buildings[splitter])) return false;

            int[] slots = { outerFeed, feed, draw, outerDraw, splitter };
            BuildPreview[] previews = new BuildPreview[5];
            if (!FindPreviewGroup(tool, slots, previews)) return false;
            Target[] targets =
            {
                new Target(semantic, "outer-feed", outerFeed, buildings[outerFeed], previews[0]),
                new Target(semantic, "splitter-feed", feed, buildings[feed], previews[1]),
                new Target(semantic, "splitter-draw", draw, buildings[draw], previews[2]),
                new Target(semantic, "outer-draw", outerDraw, buildings[outerDraw], previews[3])
            };
            group = new Group(
                semantic,
                new Target(semantic, "model40-splitter", splitter, buildings[splitter], previews[4]),
                targets);
            return true;
        }

        private static int Find(BlueprintBuilding[] bs, short model, float x, float y, float z)
        {
            int found = -1;
            for (int i = 0; i < bs.Length; i++)
            {
                BlueprintBuilding b = bs[i];
                if (b != null && b.modelIndex == model && Near(b.localOffset_x, x) && Near(b.localOffset_y, y) && Near(b.localOffset_z, z))
                { if (found >= 0) return -1; found = i; }
            }
            return found;
        }

        private static bool FindPreviewGroup(BuildTool_BlueprintPaste tool, int[] slots, BuildPreview[] output)
        {
            int n = tool.blueprint.buildings.Length;
            int active = Math.Min(tool.bpCursor, tool.bpPool.Length);
            for (int i = 0; i < active; i++)
            {
                BuildPreview first = tool.bpPool[i];
                if (first == null || first.bpgpuiModelId <= 0 || (first.bpgpuiModelId - 1) % n != slots[0]) continue;
                int group = (first.bpgpuiModelId - 1) / n;
                bool ok = true;
                for (int t = 0; t < slots.Length; t++)
                {
                    output[t] = null;
                    int id = group * n + slots[t] + 1;
                    for (int p = 0; p < active; p++) if (tool.bpPool[p] != null && tool.bpPool[p].bpgpuiModelId == id) { output[t] = tool.bpPool[p]; break; }
                    if (output[t] == null) { ok = false; break; }
                }
                if (ok) return true;
            }
            return false;
        }

        private static float SegmentDistance(Vector3 p, Vector3 a, Vector3 b)
        {
            Vector3 ab = b - a; float d = Vector3.Dot(ab, ab);
            if (d <= 1e-12f) return Vector3.Distance(p, a);
            float t = Mathf.Clamp01(Vector3.Dot(p - a, ab) / d);
            return Vector3.Distance(p, a + ab * t);
        }

        private static int? Slot(BuildTool_BlueprintPaste tool, BuildPreview bp, bool activeOnly)
        {
            if (bp == null || tool == null || tool.bpPool == null) return null;
            int n = activeOnly ? Math.Min(tool.bpCursor, tool.bpPool.Length) : tool.bpPool.Length;
            for (int i = 0; i < n; i++) if (ReferenceEquals(tool.bpPool[i], bp)) return i;
            return null;
        }

        private static void WriteGroup(JsonWriter w, Group group)
        {
            w.BeginObject();
            w.Prop("semantic", group.Semantic);
            WriteTarget(w, "splitter", group.Splitter);
            w.BeginArray("targets");
            for (int i = 0; i < group.Targets.Length; i++)
            {
                w.BeginObject();
                WriteTargetFields(w, group.Targets[i]);
                w.EndObject();
            }
            w.EndArray();
            w.EndObject();
        }

        private static void WriteTarget(JsonWriter w, string key, Target t) { w.BeginObject(key); WriteTargetFields(w, t); w.EndObject(); }
        private static void WriteTargetFields(JsonWriter w, Target t)
        {
            w.Prop("semantic", t.Role); w.Prop("blueprintArraySlot", t.BlueprintSlot); w.Prop("blueprintIndexField", t.Building.index);
            w.Prop("modelIndex", (int)t.Building.modelIndex); w.Prop("itemId", (int)t.Building.itemId);
            w.Prop("localOffset", new Vector3(t.Building.localOffset_x, t.Building.localOffset_y, t.Building.localOffset_z)); w.Prop("yaw", t.Building.yaw);
            WriteState(w, "final", PreviewState.Read(t.Tool, t.Preview));
        }

        private void WriteEvent(JsonWriter w, Event e)
        {
            w.BeginObject(); w.Prop("sequence", e.Sequence); w.Prop("phase", e.Phase);
            if (e.Target != null) w.Prop("semantic", e.Target.Semantic);
            if (e.TargetEventOrdinal > 0) w.Prop("targetEventOrdinal", e.TargetEventOrdinal);
            if (e.ArgumentCondition.HasValue) { w.Prop("argumentCondition", e.ArgumentCondition.Value); w.Prop("argumentConditionName", e.ArgumentConditionName); }
            w.Prop("toolStage", e.ToolStage);
            if (e.BoolResult.HasValue) w.Prop("boolResult", e.BoolResult.Value);
            if (e.State.HasValue) WriteState(w, "state", e.State.Value);
            if (e.States != null)
            {
                w.BeginArray("targetStates");
                for (int i = 0; i < e.States.Length; i++) { w.BeginObject(); w.Prop("semantic", _targets[i].Semantic); WriteStateFields(w, e.States[i]); w.EndObject(); }
                w.EndArray();
            }
            if (e.Query != null) WriteQuery(w, e.Query);
            w.EndObject();
        }

        private static void WriteState(JsonWriter w, string key, PreviewState s) { w.BeginObject(key); WriteStateFields(w, s); w.EndObject(); }
        private static void WriteStateFields(JsonWriter w, PreviewState s)
        {
            w.Prop("referenceIdentity", s.Identity); w.PropNullableInt("bpPoolSlot", s.PoolSlot); w.PropNullableInt("activeSlot", s.ActiveSlot);
            w.Prop("bpgpuiModelId", s.ModelId); w.Prop("previewIndex", s.PreviewIndex); w.Prop("condition", s.Condition); w.Prop("conditionName", s.ConditionName);
            w.Prop("lpos", s.Lpos); w.Prop("lpos2", s.Lpos2); w.Prop("lrot", s.Lrot); w.Prop("lrot2", s.Lrot2); w.Prop("isBelt", s.IsBelt); w.Prop("isSplitter", s.IsSplitter); w.Prop("multiLevel", s.MultiLevel); w.Prop("addonType", s.AddonType);
            w.Prop("inputObjId", s.InputObjId); w.Prop("inputFromSlot", s.InputFromSlot); w.Prop("inputToSlot", s.InputToSlot); w.Prop("inputOffset", s.InputOffset);
            w.Prop("outputObjId", s.OutputObjId); w.Prop("outputFromSlot", s.OutputFromSlot); w.Prop("outputToSlot", s.OutputToSlot); w.Prop("outputOffset", s.OutputOffset);
            WritePointer(w, "input", s.Input); WritePointer(w, "output", s.Output); WritePointer(w, "coverbp", s.Cover);
        }

        private static void WritePointer(JsonWriter w, string key, PreviewPointer p)
        {
            if (!p.Exists) { w.Prop(key, (string)null); return; }
            w.BeginObject(key); w.Prop("referenceIdentity", p.Identity); w.PropNullableInt("bpPoolSlot", p.PoolSlot); w.PropNullableInt("activeSlot", p.ActiveSlot);
            w.Prop("bpgpuiModelId", p.ModelId); w.Prop("previewIndex", p.PreviewIndex); w.Prop("condition", p.Condition); w.Prop("conditionName", p.ConditionName);
            w.Prop("isBelt", p.IsBelt); w.Prop("isSplitter", p.IsSplitter); w.EndObject();
        }

        private static void WriteQuery(JsonWriter w, Query q)
        {
            w.BeginObject("query");
            WriteQueryFields(w, q);
            w.EndObject();
        }

        private static void WriteQueryElement(JsonWriter w, Query q)
        {
            w.BeginObject();
            WriteQueryFields(w, q);
            w.EndObject();
        }

        private static void WriteQueryFields(JsonWriter w, Query q)
        {
            w.Prop("shape", q.Shape); w.Prop("point0", q.P0); w.Prop("point1", q.P1); w.Prop("center", (q.P0 + q.P1) * 0.5f);
            w.Prop("radius", q.Radius); w.Prop("layerMask", q.Mask); w.Prop("queryTriggerInteraction", q.Qti); w.Prop("returnedCount", q.Returned);
            w.Prop("capturedCount", q.Colliders.Length); w.Prop("collidersTruncated", q.Returned > q.Colliders.Length); w.BeginArray("colliders");
            for (int i = 0; i < q.Colliders.Length; i++)
            {
                ColliderInfo c = q.Colliders[i]; w.BeginObject(); w.Prop("resultIndex", i); w.Prop("isNull", c.IsNull); w.Prop("instanceId", c.InstanceId);
                w.Prop("name", c.Name); w.Prop("gameObjectLayer", c.Layer); w.Prop("boundsCenter", c.BoundsCenter); w.Prop("boundsExtents", c.BoundsExtents);
                w.Prop("transformPosition", c.TransformPosition); w.Prop("transformRotation", c.TransformRotation); w.Prop("hasBuildPreviewModel", c.HasModel); w.Prop("buildPreviewModelIndex", c.ModelIndex);
                if (c.Preview.HasValue) WriteState(w, "buildPreview", c.Preview.Value); else w.Prop("buildPreview", (string)null);
                w.Prop("hasColliderData", c.HasColliderData); w.Prop("colliderDataObjId", c.ObjId); w.Prop("colliderDataObjType", c.ObjType); w.Prop("colliderDataUsage", c.Usage); w.Prop("colliderDataShape", c.ColliderShape); w.EndObject();
            }
            w.EndArray();
        }
        private sealed class BuildPreviewReferenceComparer : IEqualityComparer<BuildPreview>
        {
            internal static readonly BuildPreviewReferenceComparer Instance = new BuildPreviewReferenceComparer();
            public bool Equals(BuildPreview x, BuildPreview y) { return ReferenceEquals(x, y); }
            public int GetHashCode(BuildPreview obj) { return RuntimeHelpers.GetHashCode(obj); }
        }


        private sealed class PassData
        {
            internal readonly List<ConditionArgument> Arguments = new List<ConditionArgument>(2);
            internal bool ArgumentsTruncated;

            internal void AddArgument(EBuildCondition condition, int limit)
            {
                if (Arguments.Count >= limit)
                {
                    ArgumentsTruncated = true;
                    return;
                }
                Arguments.Add(new ConditionArgument((int)condition, condition.ToString()));
            }
        }

        private struct ConditionArgument
        {
            internal int Condition;
            internal string ConditionName;
            internal ConditionArgument(int condition, string conditionName)
            {
                Condition = condition;
                ConditionName = conditionName;
            }
        }

        private sealed class Group
        {
            internal string Semantic;
            internal Target Splitter;
            internal Target[] Targets;
            internal Group(string semantic, Target splitter, Target[] targets)
            {
                Semantic = semantic;
                Splitter = splitter;
                Targets = targets;
            }
        }

        private sealed class Target
        {
            internal string Semantic; internal string Role; internal int BlueprintSlot; internal BlueprintBuilding Building; internal BuildPreview Preview; internal BuildTool_BlueprintPaste Tool;
            internal int QueryCount; internal int AddErrorCount;
            internal Target(string group, string role, int slot, BlueprintBuilding building, BuildPreview preview)
            {
                Semantic = group + "/" + role;
                Role = role;
                BlueprintSlot = slot;
                Building = building;
                Preview = preview;
            }
        }
        private sealed class Event
        {
            internal int Sequence; internal string Phase; internal Target Target; internal int TargetEventOrdinal; internal int ToolStage; internal int? ArgumentCondition; internal string ArgumentConditionName;
            internal bool? BoolResult; internal PreviewState? State; internal PreviewState[] States; internal Query Query;
        }

        private struct MonitorState
        {
            private EBuildCondition _condition;
            private BuildPreview _input;
            private BuildPreview _output;
            private BuildPreview _cover;
            private int _inputObjId, _inputFromSlot, _inputToSlot, _inputOffset;
            private int _outputObjId, _outputFromSlot, _outputToSlot, _outputOffset;

            internal bool Matches(BuildPreview bp)
            {
                return bp != null && _condition == bp.condition &&
                    ReferenceEquals(_input, bp.input) && ReferenceEquals(_output, bp.output) &&
                    ReferenceEquals(_cover, bp.coverbp) &&
                    _inputObjId == bp.inputObjId && _inputFromSlot == bp.inputFromSlot &&
                    _inputToSlot == bp.inputToSlot && _inputOffset == bp.inputOffset &&
                    _outputObjId == bp.outputObjId && _outputFromSlot == bp.outputFromSlot &&
                    _outputToSlot == bp.outputToSlot && _outputOffset == bp.outputOffset;
            }

            internal static MonitorState Read(BuildPreview bp)
            {
                MonitorState s = new MonitorState();
                s._condition = bp.condition;
                s._input = bp.input; s._output = bp.output; s._cover = bp.coverbp;
                s._inputObjId = bp.inputObjId; s._inputFromSlot = bp.inputFromSlot;
                s._inputToSlot = bp.inputToSlot; s._inputOffset = bp.inputOffset;
                s._outputObjId = bp.outputObjId; s._outputFromSlot = bp.outputFromSlot;
                s._outputToSlot = bp.outputToSlot; s._outputOffset = bp.outputOffset;
                return s;
            }
        }

        private struct PreviewState
        {
            internal int Identity, ModelId, PreviewIndex, Condition; internal int? PoolSlot, ActiveSlot; internal string ConditionName, AddonType;
            internal Vector3 Lpos, Lpos2; internal Quaternion Lrot, Lrot2; internal bool IsBelt, IsSplitter, MultiLevel;
            internal int InputObjId, InputFromSlot, InputToSlot, InputOffset, OutputObjId, OutputFromSlot, OutputToSlot, OutputOffset;
            internal PreviewPointer Input, Output, Cover;
            internal static PreviewState Read(BuildTool_BlueprintPaste tool, BuildPreview bp)
            {
                PreviewState s = new PreviewState(); if (bp == null) return s;
                s.Identity = RuntimeHelpers.GetHashCode(bp); s.PoolSlot = Slot(tool, bp, false); s.ActiveSlot = Slot(tool, bp, true); s.ModelId = bp.bpgpuiModelId; s.PreviewIndex = bp.previewIndex;
                s.Condition = (int)bp.condition; s.ConditionName = bp.condition.ToString(); s.Lpos = bp.lpos; s.Lpos2 = bp.lpos2; s.Lrot = bp.lrot; s.Lrot2 = bp.lrot2;
                s.IsBelt = bp.desc != null && bp.desc.isBelt; s.IsSplitter = bp.desc != null && bp.desc.isSplitter; s.MultiLevel = bp.desc != null && bp.desc.multiLevel; s.AddonType = bp.desc != null ? bp.desc.addonType.ToString() : null;
                s.InputObjId = bp.inputObjId; s.InputFromSlot = bp.inputFromSlot; s.InputToSlot = bp.inputToSlot; s.InputOffset = bp.inputOffset;
                s.OutputObjId = bp.outputObjId; s.OutputFromSlot = bp.outputFromSlot; s.OutputToSlot = bp.outputToSlot; s.OutputOffset = bp.outputOffset;
                s.Input = PreviewPointer.Read(tool, bp.input); s.Output = PreviewPointer.Read(tool, bp.output); s.Cover = PreviewPointer.Read(tool, bp.coverbp); return s;
            }
        }

        private struct PreviewPointer
        {
            internal bool Exists, IsBelt, IsSplitter; internal int Identity, ModelId, PreviewIndex, Condition; internal int? PoolSlot, ActiveSlot; internal string ConditionName;
            internal static PreviewPointer Read(BuildTool_BlueprintPaste tool, BuildPreview bp)
            {
                PreviewPointer p = new PreviewPointer(); if (bp == null) return p; p.Exists = true; p.Identity = RuntimeHelpers.GetHashCode(bp); p.PoolSlot = Slot(tool, bp, false); p.ActiveSlot = Slot(tool, bp, true);
                p.ModelId = bp.bpgpuiModelId; p.PreviewIndex = bp.previewIndex; p.Condition = (int)bp.condition; p.ConditionName = bp.condition.ToString(); p.IsBelt = bp.desc != null && bp.desc.isBelt; p.IsSplitter = bp.desc != null && bp.desc.isSplitter; return p;
            }
        }

        private sealed class Query
        {
            internal string Shape, Qti; internal Vector3 P0, P1; internal float Radius; internal int Mask, Returned; internal ColliderInfo[] Colliders;
            internal static Query Read(BuildTool_BlueprintPaste tool, string shape, Vector3 p0, Vector3 p1, float radius, int mask, QueryTriggerInteraction qti, int returned, Collider[] results)
            {
                Query q = new Query { Shape = shape, P0 = p0, P1 = p1, Radius = radius, Mask = mask, Qti = qti.ToString(), Returned = returned };
                int n = results == null ? 0 : Math.Min(Math.Max(returned, 0), results.Length); q.Colliders = new ColliderInfo[n];
                for (int i = 0; i < n; i++) q.Colliders[i] = ColliderInfo.Read(tool, results[i]); return q;
            }
        }

        private struct ColliderInfo
        {
            internal bool IsNull, HasModel, HasColliderData; internal int InstanceId, Layer, ModelIndex, ObjId; internal string Name, ObjType, Usage, ColliderShape;
            internal Vector3 BoundsCenter, BoundsExtents, TransformPosition; internal Quaternion TransformRotation; internal PreviewState? Preview;
            internal static ColliderInfo Read(BuildTool_BlueprintPaste tool, Collider col)
            {
                ColliderInfo c = new ColliderInfo { Layer = -1, ModelIndex = -1 }; if (col == null) { c.IsNull = true; return c; }
                try { c.InstanceId = col.GetInstanceID(); c.BoundsCenter = col.bounds.center; c.BoundsExtents = col.bounds.extents; GameObject go = col.gameObject; if (go != null) { c.Name = go.name; c.Layer = go.layer; } Transform tr = col.transform; if (tr != null) { c.TransformPosition = tr.position; c.TransformRotation = tr.rotation; } BuildPreviewModel m = col.GetComponent<BuildPreviewModel>(); if (m != null) { c.HasModel = true; c.ModelIndex = m.index; if (m.buildPreview != null) c.Preview = PreviewState.Read(tool, m.buildPreview); } } catch (Exception) { }
                try { PlanetPhysics physics = tool != null && tool.planet != null ? tool.planet.physics : null; ColliderData d; if (physics != null && physics.GetColliderData(col, out d)) { c.HasColliderData = true; c.ObjId = d.objId; c.ObjType = d.objType.ToString(); c.Usage = d.usage.ToString(); c.ColliderShape = d.shape.ToString(); } } catch (Exception) { }
                return c;
            }
        }
    }
}
