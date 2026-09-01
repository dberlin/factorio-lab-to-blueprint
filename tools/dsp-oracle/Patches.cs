using System;
using System.Collections.Generic;
using UnityEngine;
using HarmonyLib;

namespace FlabOracle
{
    /// <summary>
    /// Observes one MatchInserter call. The prefix snapshots the preview's
    /// connection fields before the game touches them; the postfix snapshots
    /// them after. Nothing in between is computed by us.
    /// </summary>
    [HarmonyPatch(typeof(BuildTool_BlueprintPaste), "MatchInserter")]
    internal static class MatchInserterPatch
    {
        [HarmonyPrefix]
        private static void Prefix(BuildTool_BlueprintPaste __instance, BuildPreview bp)
        {
            try
            {
                if (bp == null)
                {
                    return;
                }

                Oracle.NoteToolPool(__instance != null ? __instance.bpPool : null);

                MatchRecord rec = Oracle.RecordFor(bp);
                rec.BeginFrame(Time.frameCount, Oracle.WantDetail());

                MatchCall call = new MatchCall();
                call.Before = PreviewConnState.From(bp);
                call.OverlapFrom = rec.Overlaps.Count;
                call.OverlapTake = 0;

                Oracle.ActiveTool = __instance;
                Oracle.ActiveCall = call;
                Oracle.ActiveRecord = rec;
            }
            catch (Exception e)
            {
                Oracle.ActiveRecord = null;
                Oracle.Log.LogError("flab2bp oracle MatchInserter prefix failed: " + e);
            }
        }

        [HarmonyPostfix]
        private static void Postfix(BuildPreview bp)
        {
            try
            {
                MatchRecord rec = Oracle.ActiveRecord;
                if (rec != null && bp != null)
                {
                    MatchCall call = Oracle.ActiveCall;
                    call.After = PreviewConnState.From(bp);
                    call.OverlapTake = rec.Overlaps.Count - call.OverlapFrom;
                    rec.Calls.Add(call);
                }
            }
            catch (Exception e)
            {
                Oracle.Log.LogError("flab2bp oracle MatchInserter postfix failed: " + e);
            }
            finally
            {
                Oracle.ActiveRecord = null;
            }
        }
    }

    [HarmonyPatch(typeof(BuildTool_BlueprintPaste), "DeterminePreviewsPrestage")]
    internal static class DeterminePreviewsPrestagePatch
    {
        [HarmonyPostfix]
        private static void Postfix(BuildTool_BlueprintPaste __instance)
        {
            try
            {
                TargetCaptureRuntime.Ensure(__instance);
                TargetCaptureRuntime.Snapshot(__instance, "determine-previews-prestage-postfix");
            }
            catch (Exception e)
            {
                TargetCaptureRuntime.LogFailure("DeterminePreviewsPrestage postfix", e);
            }
        }
    }

    [HarmonyPatch(typeof(BuildTool_BlueprintPaste), "CheckBuildConditionsPrestage")]
    internal static class CheckBuildConditionsPrestagePatch
    {
        [HarmonyPostfix]
        private static void Postfix(BuildTool_BlueprintPaste __instance, bool __result)
        {
            try
            {
                TargetCaptureRuntime.Ensure(__instance);
                TargetCaptureRuntime.RecordPrestage(__instance, __result);
            }
            catch (Exception e)
            {
                TargetCaptureRuntime.LogFailure("CheckBuildConditionsPrestage postfix", e);
            }
        }
    }

    [HarmonyPatch(typeof(BuildTool_BlueprintPaste), "ArrangeOverlapBP")]
    internal static class ArrangeOverlapBPPatch
    {
        [HarmonyPrefix]
        private static void Prefix(BuildTool_BlueprintPaste __instance)
        {
            try
            {
                TargetCaptureRuntime.BeginCycle(__instance);
                TargetCaptureRuntime.Snapshot(__instance, "arrange-overlap-prefix");
            }
            catch (Exception e)
            {
                TargetCaptureRuntime.LogFailure("ArrangeOverlapBP prefix", e);
            }
        }

        [HarmonyPostfix]
        private static void Postfix(BuildTool_BlueprintPaste __instance)
        {
            try { TargetCaptureRuntime.Snapshot(__instance, "arrange-overlap-postfix"); }
            catch (Exception e) { TargetCaptureRuntime.LogFailure("ArrangeOverlapBP postfix", e); }
        }
    }

    [HarmonyPatch(typeof(BuildTool_BlueprintPaste), "ActiveColliders")]
    internal static class ActiveCollidersPatch
    {
        [HarmonyPostfix]
        private static void Postfix(BuildTool_BlueprintPaste __instance, BuildModel model)
        {
            try
            {
                TargetCaptureRuntime.Ensure(__instance);
                TargetCaptureRuntime.Snapshot(__instance, "active-colliders-postfix");
            }
            catch (Exception e)
            {
                TargetCaptureRuntime.LogFailure("ActiveColliders postfix", e);
            }
        }
    }

    [HarmonyPatch(typeof(BuildTool_BlueprintPaste), "AddErrorMessage")]
    internal static class AddErrorMessagePatch
    {
        [HarmonyPrefix]
        private static void Prefix(EBuildCondition _bdCondition, BuildPreview _bp)
        {
            try { TargetCaptureRuntime.RecordAddError(_bp, _bdCondition); }
            catch (Exception e) { TargetCaptureRuntime.LogFailure("AddErrorMessage prefix", e); }
        }
    }

    /// <summary>
    /// The hotkey dump lands here, because this is the only moment at which every
    /// preview's <c>condition</c> is the game's finished verdict for the current
    /// cursor position.
    /// </summary>
    [HarmonyPatch(typeof(BuildTool_BlueprintPaste), "CheckBuildConditions")]
    internal static class CheckBuildConditionsPatch
    {
        [HarmonyPrefix]
        private static void Prefix(BuildTool_BlueprintPaste __instance)
        {
            Oracle.ActiveRecord = null;
            try
            {
                TargetCaptureRuntime.Ensure(__instance);
                TargetCaptureRuntime.EnterCheck(__instance);
            }
            catch (Exception e)
            {
                TargetCaptureRuntime.LogFailure("CheckBuildConditions prefix", e);
            }
        }

        [HarmonyPostfix]
        private static void Postfix(BuildTool_BlueprintPaste __instance, bool __result)
        {
            Oracle.ActiveRecord = null;
            try { TargetCaptureRuntime.ExitCheck(__instance, __result); }
            catch (Exception e) { TargetCaptureRuntime.LogFailure("CheckBuildConditions postfix", e); }
            if (!Oracle.HotkeyPending)
            {
                return;
            }

            Oracle.HotkeyPending = false;
            bool detailed = Oracle.CaptureDetail;
            Oracle.CaptureDetail = Oracle.AlwaysCaptureColliders.Value;

            DumpSink.Dump(__instance, "hotkey", __result, detailed);
        }
    }

    /// <summary>
    /// The commit. Dumped twice so the pre-commit verdicts and the post-commit
    /// objIds are both on record and distinguishable.
    /// </summary>
    [HarmonyPatch(typeof(BuildTool_BlueprintPaste), "CreatePrebuilds")]
    internal static class CreatePrebuildsPatch
    {
        [HarmonyPrefix]
        private static void Prefix(BuildTool_BlueprintPaste __instance)
        {
            try { TargetCaptureRuntime.Commit(__instance); }
            catch (Exception e) { TargetCaptureRuntime.LogFailure("CreatePrebuilds prefix", e); }
            if (Oracle.DumpOnPaste == null || !Oracle.DumpOnPaste.Value)
            {
                return;
            }

            DumpSink.Dump(__instance, "createprebuilds-pre", null, Oracle.WantDetail());
        }

        [HarmonyPostfix]
        private static void Postfix(BuildTool_BlueprintPaste __instance)
        {
            if (Oracle.DumpOnPaste == null || !Oracle.DumpOnPaste.Value)
            {
                return;
            }

            DumpSink.Dump(__instance, "createprebuilds-post", null, Oracle.WantDetail());
        }
    }

    /// <summary>
    /// Records the raw PhysX candidate set behind MatchInserter's snap ladder.
    /// The count is the engine's return value; the identity of each collider is
    /// resolved by the game's own PlanetPhysics.GetColliderData. We invent
    /// nothing and we filter nothing.
    ///
    /// Applied manually (see OraclePlugin.TryPatchOverlapSphere) so that a
    /// missing overload or a refused patch degrades to overlapObserved=false
    /// instead of killing plugin load.
    /// </summary>
    internal static class PhysicsPatch
    {
        internal static void OverlapSphereNonAllocPostfix(
            Vector3 __0,
            float __1,
            Collider[] __2,
            int __3,
            QueryTriggerInteraction __4,
            int __result)
        {
            try { TargetCaptureRuntime.RecordSphere(__0, __1, __2, __3, __4, __result); }
            catch (Exception e) { TargetCaptureRuntime.LogFailure("OverlapSphereNonAlloc postfix", e); }
            MatchRecord rec = Oracle.ActiveRecord;
            if (rec == null)
            {
                return;
            }

            Oracle.OverlapHookEverFired = true;

            try
            {
                OverlapObservation obs;
                obs.Center = __0;
                obs.Radius = __1;
                obs.LayerMask = __3;
                obs.ColliderCount = __result;
                obs.ColliderFrom = rec.Colliders.Count;
                obs.ColliderTake = 0;

                if (rec.Detailed && __2 != null && __result > 0)
                {
                    PlanetPhysics physics = null;
                    if (Oracle.ActiveTool != null && Oracle.ActiveTool.planet != null)
                    {
                        physics = Oracle.ActiveTool.planet.physics;
                    }

                    int take = __result;
                    if (take > __2.Length)
                    {
                        take = __2.Length;
                    }

                    for (int i = 0; i < take; i++)
                    {
                        rec.Colliders.Add(Describe(__2[i], physics));
                    }

                    obs.ColliderTake = take;
                }

                rec.Overlaps.Add(obs);
            }
            catch (Exception e)
            {
                Oracle.Log.LogError("flab2bp oracle overlap postfix failed: " + e);
            }
        }

        internal static void OverlapCapsuleNonAllocPostfix(
            Vector3 __0,
            Vector3 __1,
            float __2,
            Collider[] __3,
            int __4,
            QueryTriggerInteraction __5,
            int __result)
        {
            try { TargetCaptureRuntime.RecordCapsule(__0, __1, __2, __3, __4, __5, __result); }
            catch (Exception e) { TargetCaptureRuntime.LogFailure("OverlapCapsuleNonAlloc postfix", e); }
        }

        private static ColliderObservation Describe(Collider col, PlanetPhysics physics)
        {
            ColliderObservation o = new ColliderObservation();
            o.HasColliderData = false;
            o.ObjId = 0;
            o.ObjType = null;
            o.Usage = null;
            o.Shape = null;
            o.Link = 0;
            o.GameObjectLayer = -1;
            o.Name = null;

            if (col == null)
            {
                return o;
            }

            try
            {
                GameObject go = col.gameObject;
                if (go != null)
                {
                    o.Name = go.name;
                    o.GameObjectLayer = go.layer;
                }
            }
            catch (Exception)
            {
                // A destroyed collider is a fact about the frame, not an error.
            }

            if (physics == null)
            {
                return o;
            }

            try
            {
                ColliderData cd;
                if (physics.GetColliderData(col, out cd))
                {
                    o.HasColliderData = true;
                    o.ObjId = cd.objId;
                    o.ObjType = cd.objType.ToString();
                    o.Usage = cd.usage.ToString();
                    o.Shape = cd.shape.ToString();
                    o.Link = cd.link;
                    o.Pos = cd.pos;
                    o.Ext = cd.ext;
                    o.Radius = cd.radius;
                    o.Rot = cd.q;
                }
            }
            catch (Exception e)
            {
                Oracle.Log.LogError("flab2bp oracle GetColliderData failed: " + e);
            }

            return o;
        }
    }

    internal static class TargetCaptureRuntime
    {
        private static TargetCaptureSession _pending;
        private static BlueprintData _completedBlueprint;
        private static BlueprintData _announcedBlueprint;
        private static bool? _checkResult;
        private static readonly HashSet<string> LoggedFailures = new HashSet<string>();

        [ThreadStatic]
        private static TargetCaptureSession _activeCapture;

        internal static void LogFailure(string hook, Exception error)
        {
            _activeCapture = null;
            if (LoggedFailures.Add(hook))
            {
                Oracle.Log.LogError(
                    "flab2bp oracle automatic target capture disabled at " + hook +
                    " for this call (first occurrence only): " + error);
            }
        }

        internal static void BeginCycle(BuildTool_BlueprintPaste tool)
        {
            _checkResult = null;
            Ensure(tool);
        }

        internal static void Ensure(BuildTool_BlueprintPaste tool)
        {
            if (_pending != null && _pending.Matches(tool))
            {
                _activeCapture = _pending;
                return;
            }
            if (tool == null || ReferenceEquals(_completedBlueprint, tool.blueprint))
            {
                _pending = null;
                _activeCapture = null;
                return;
            }

            TargetCaptureSession next;
            _pending = TargetCaptureSession.TryCreate(tool, out next) ? next : null;
            if (_pending != null) _checkResult = null;
            _activeCapture = _pending;
            Announce(tool);
        }

        private static void Announce(BuildTool_BlueprintPaste tool)
        {
            if (_pending != null && !ReferenceEquals(_announcedBlueprint, tool.blueprint))
            {
                _announcedBlueprint = tool.blueprint;
                Oracle.Log.LogMessage(
                    "flab2bp oracle automatically armed for the canonical model40 control/suspect belt clusters; " +
                    "one bounded target capture will be written automatically after the game's condition pass.");
            }
        }

        internal static void Snapshot(BuildTool_BlueprintPaste tool, string phase)
        {
            if (_pending != null && _pending.Matches(tool))
            {
                _pending.SnapshotAll(phase);
            }
        }

        internal static void EnterCheck(BuildTool_BlueprintPaste tool)
        {
            if (_pending == null || !_pending.Matches(tool))
            {
                return;
            }
            _activeCapture = _pending;
            _pending.SnapshotAll("check-prefix-before-collision-rescue");
        }

        internal static void ExitCheck(BuildTool_BlueprintPaste tool, bool result)
        {
            if (_pending == null || !_pending.Matches(tool))
            {
                return;
            }
            _pending.SnapshotAll("check-postfix-after-propagation");
            _checkResult = result;
            Flush("check-build-conditions-postfix");
        }

        internal static void RecordPrestage(BuildTool_BlueprintPaste tool, bool result)
        {
            if (_pending != null && _pending.Matches(tool))
            {
                _activeCapture = _pending;
                _pending.RecordPrestageResult(result, Time.frameCount);
            }
        }

        internal static void RecordAddError(BuildPreview bp, EBuildCondition condition)
        {
            if (_activeCapture != null && _activeCapture.Matches(_activeCapture.Tool))
            {
                _activeCapture.RecordAddError(bp, condition);
            }
        }

        internal static void RecordSphere(Vector3 center, float radius, Collider[] results, int mask, QueryTriggerInteraction qti, int result)
        {
            if (_activeCapture != null && _activeCapture.Matches(_activeCapture.Tool))
            {
                _activeCapture.RecordSphere(center, radius, results, mask, qti, result);
            }
        }

        internal static void RecordCapsule(Vector3 p0, Vector3 p1, float radius, Collider[] results, int mask, QueryTriggerInteraction qti, int result)
        {
            if (_activeCapture != null && _activeCapture.Matches(_activeCapture.Tool))
            {
                _activeCapture.RecordCapsule(p0, p1, radius, results, mask, qti, result);
            }
        }

        internal static void MonitorUpdate(int frame)
        {
            if (_pending == null)
            {
                return;
            }
            if (!_pending.Matches(_pending.Tool))
            {
                _pending = null;
                _activeCapture = null;
                return;
            }

            _activeCapture = _pending;
            string reason;
            if (_pending.MonitorFrame(frame, out reason))
            {
                Flush(reason);
            }
        }

        internal static void Commit(BuildTool_BlueprintPaste tool)
        {
            if (_pending == null || !_pending.Matches(tool))
            {
                return;
            }
            _pending.SnapshotAll("createprebuilds-prefix");
            Flush("createprebuilds-prefix");
        }

        private static void Flush(string trigger)
        {
            TargetCaptureSession capture = _pending;
            if (capture == null)
            {
                return;
            }
            DumpSink.DumpTargetCapture(capture, trigger, _checkResult);
            _completedBlueprint = capture.Tool.blueprint;
            _pending = null;
            _activeCapture = null;
        }
    }
}
